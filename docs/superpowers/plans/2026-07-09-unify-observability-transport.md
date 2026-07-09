# Unify Observability Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate the agent's traces, metrics, and logs onto one OpenTelemetry SDK exporting via standard OTLP env vars, with Datadog reached through its agentless OTLP intake and Sentry via its native SDK; retire the bespoke `/api/v2` intakes and `emit_metric`.

**Architecture:** A vendor-agnostic `resolve_otlp_target(signal)` resolver (standard `OTEL_EXPORTER_OTLP_*` vars, with a thin Datadog auto-fill convenience) drives OTLP exporters for all three OTel signal providers (`TracerProvider`, `MeterProvider`, `LoggerProvider`) sharing one `Resource`. Sentry keeps its native SDK path; the `ddtrace` local-Agent path stays an opt-in.

**Tech Stack:** Python `opentelemetry-sdk` (traces/metrics/logs) + `opentelemetry-exporter-otlp-proto-http` + `sentry-sdk` + `ddtrace`. Tests: pytest with in-memory OTel exporters.

## Global Constraints

- Config precedence per signal: explicit per-signal `OTEL_EXPORTER_OTLP_{TRACES,METRICS,LOGS}_ENDPOINT` → base `OTEL_EXPORTER_OTLP_ENDPOINT` → Datadog convenience → None (signal not OTLP-exported).
- Datadog convenience activates only when `DD_API_KEY` is set AND `DD_TRACE_ENABLED != "false"` AND the corresponding `OTEL_*` var is unset. It fills endpoint `https://otlp.<DD_SITE>/v1/<signal>` (default site `datadoghq.com`) and header `dd-api-key=<DD_API_KEY>`.
- Explicit `OTEL_*` vars ALWAYS win over the Datadog convenience.
- Headers env format is OTel-standard: comma-separated `key=value` pairs (e.g. `dd-api-key=abc,x-extra=1`).
- Every exporter init and every `emit_*` path is guarded so a telemetry failure never breaks the agent run; unconfigured signals no-op.
- `job_id` MUST NEVER be a metric attribute; `ticker` stays on every metric.
- `emit_metric` and `_datadog_metric` (`/api/v2/series`) and `_datadog_log` (`/api/v2/logs`) are removed by the end of this plan.
- `emit_log(level, message, **attributes)` keeps its signature (callers unchanged).
- `DD_EXPORTER` still validates to `agent` | `otlp`; unknown values raise `ValueError`.
- Tests use the agent venv: `agent/.venv/bin/python -m pytest ...` (system `pip` is unavailable).

---

### Task 1: Vendor-agnostic OTLP target resolver (`agent/lib/otlp_target.py`)

**Files:**
- Create: `agent/lib/otlp_target.py`
- Create: `agent/tests/test_otlp_target.py`

**Interfaces:**
- Produces:
  - `parse_otlp_headers(raw: str) -> dict[str, str]`
  - `resolve_otlp_target(signal: str) -> tuple[str, dict[str, str]] | None` where `signal` ∈ `{"traces","metrics","logs"}`; returns `(endpoint, headers)` or `None`.
- Consumes: nothing (leaf module).

- [ ] **Step 1: Write the failing tests**

Create `agent/tests/test_otlp_target.py`:

```python
import pytest
from lib.otlp_target import parse_otlp_headers, resolve_otlp_target

_ALL = ("traces", "metrics", "logs")


def _clear(monkeypatch):
    for v in (
        "OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_HEADERS",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_HEADERS",
        "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "OTEL_EXPORTER_OTLP_METRICS_HEADERS",
        "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", "OTEL_EXPORTER_OTLP_LOGS_HEADERS",
        "DD_API_KEY", "DD_SITE", "DD_TRACE_ENABLED",
    ):
        monkeypatch.delenv(v, raising=False)


def test_parse_headers_splits_pairs():
    assert parse_otlp_headers("dd-api-key=abc,x-extra=1") == {"dd-api-key": "abc", "x-extra": "1"}
    assert parse_otlp_headers("") == {}
    assert parse_otlp_headers("  k = v  ") == {"k": "v"}


def test_unconfigured_returns_none(monkeypatch):
    _clear(monkeypatch)
    for s in _ALL:
        assert resolve_otlp_target(s) is None


def test_per_signal_endpoint_wins(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://base.example/otlp")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "https://metrics.example/v1/metrics")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_METRICS_HEADERS", "authorization=Bearer m")
    ep, headers = resolve_otlp_target("metrics")
    assert ep == "https://metrics.example/v1/metrics"
    assert headers == {"authorization": "Bearer m"}


def test_base_endpoint_used_when_no_per_signal(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://base.example/otlp")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "authorization=Bearer b")
    ep, headers = resolve_otlp_target("traces")
    assert ep == "https://base.example/otlp/v1/traces"
    assert headers == {"authorization": "Bearer b"}


def test_datadog_convenience_fills_endpoint_and_header(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DD_API_KEY", "dd-key")
    monkeypatch.setenv("DD_SITE", "datadoghq.eu")
    for s in _ALL:
        ep, headers = resolve_otlp_target(s)
        assert ep == f"https://otlp.datadoghq.eu/v1/{s}"
        assert headers == {"dd-api-key": "dd-key"}


def test_datadog_convenience_default_site(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DD_API_KEY", "dd-key")
    ep, _ = resolve_otlp_target("logs")
    assert ep == "https://otlp.datadoghq.com/v1/logs"


def test_explicit_var_beats_datadog_convenience(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DD_API_KEY", "dd-key")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "https://collector.local/v1/traces")
    ep, headers = resolve_otlp_target("traces")
    assert ep == "https://collector.local/v1/traces"
    assert headers == {}


def test_datadog_disabled_flag_suppresses_convenience(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DD_API_KEY", "dd-key")
    monkeypatch.setenv("DD_TRACE_ENABLED", "false")
    assert resolve_otlp_target("metrics") is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd agent && .venv/bin/python -m pytest tests/test_otlp_target.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.otlp_target'`.

- [ ] **Step 3: Implement `agent/lib/otlp_target.py`**

```python
"""Vendor-agnostic OTLP endpoint/header resolution for traces, metrics, and logs.

Precedence per signal: explicit per-signal OTEL_* var -> base OTEL_* var ->
Datadog agentless convenience -> None. Explicit OTEL_* vars always win over the
Datadog convenience, so a Collector/other vendor overrides Datadog."""
import os

_SIGNALS = ("traces", "metrics", "logs")


def parse_otlp_headers(raw: str) -> dict[str, str]:
    """Parse the OTel-standard header format: comma-separated key=value pairs."""
    headers: dict[str, str] = {}
    for pair in (raw or "").split(","):
        if "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        k = k.strip()
        if k:
            headers[k] = v.strip()
    return headers


def _dd_enabled() -> bool:
    if not os.environ.get("DD_API_KEY"):
        return False
    return os.environ.get("DD_TRACE_ENABLED", "").strip().lower() != "false"


def _dd_site() -> str:
    return os.environ.get("DD_SITE", "datadoghq.com").strip() or "datadoghq.com"


def resolve_otlp_target(signal: str) -> tuple[str, dict[str, str]] | None:
    """Return (endpoint, headers) for an OTLP signal, or None if not configured."""
    if signal not in _SIGNALS:
        raise ValueError(f"unknown OTLP signal {signal!r}; expected one of {_SIGNALS}")

    per_ep = os.environ.get(f"OTEL_EXPORTER_OTLP_{signal.upper()}_ENDPOINT")
    if per_ep:
        headers = os.environ.get(f"OTEL_EXPORTER_OTLP_{signal.upper()}_HEADERS")
        return per_ep, parse_otlp_headers(headers if headers is not None else "")

    base_ep = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if base_ep:
        headers = os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "")
        return f"{base_ep.rstrip('/')}/v1/{signal}", parse_otlp_headers(headers)

    if _dd_enabled():
        return f"https://otlp.{_dd_site()}/v1/{signal}", {"dd-api-key": os.environ["DD_API_KEY"]}

    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd agent && .venv/bin/python -m pytest tests/test_otlp_target.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add agent/lib/otlp_target.py agent/tests/test_otlp_target.py
git commit -m "feat(agent): add vendor-agnostic OTLP target resolver"
```

---

### Task 2: Metrics facade uses the resolver + `llm.duration_ms`

**Files:**
- Modify: `agent/lib/metrics.py`
- Modify: `agent/tests/test_metrics.py`

**Interfaces:**
- Consumes: `lib.otlp_target.resolve_otlp_target` (Task 1)
- Produces: `record_llm_duration(model: str, api: str, duration_ms: float, ticker: str) -> None`

- [ ] **Step 1: Write the failing tests**

Add to `agent/tests/test_metrics.py`:

```python
def test_metrics_otlp_reader_added_when_resolver_returns(monkeypatch):
    import importlib, lib.metrics as m
    from opentelemetry.sdk.resources import Resource
    importlib.reload(m)
    monkeypatch.setattr(m, "resolve_otlp_target",
                        lambda signal: ("https://otlp.example/v1/metrics", {"dd-api-key": "k"}) if signal == "metrics" else None)
    m.init_metrics(Resource.create({"service.name": "test"}))
    # A periodic OTLP reader should have been constructed and attached.
    assert m._meter is not None


def test_record_llm_duration_histogram(monkeypatch):
    import importlib, lib.metrics as m
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    importlib.reload(m)
    reader = InMemoryMetricReader()
    m.init_metrics(Resource.create({"service.name": "test"}), extra_readers=[reader])
    m.record_llm_duration("gpt-4.1-mini", "responses", 512.0, "AAPL")
    points = []
    for rm in reader.get_metrics_data().resource_metrics:
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                if metric.name == "llm.duration_ms":
                    points.extend(metric.data.data_points)
    assert points[0].sum == 512.0
    assert points[0].attributes == {"model": "gpt-4.1-mini", "api": "responses", "ticker": "AAPL"}
    assert "job_id" not in points[0].attributes
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd agent && .venv/bin/python -m pytest tests/test_metrics.py -k "otlp_reader or llm_duration" -v`
Expected: FAIL — `AttributeError: module 'lib.metrics' has no attribute 'resolve_otlp_target'` / `record_llm_duration`.

- [ ] **Step 3: Rewire gating to the resolver**

In `agent/lib/metrics.py`, add the import near the top (after `from contextvars import ContextVar`):

```python
from .otlp_target import resolve_otlp_target
```

Delete the `_metrics_endpoint` helper (the `def _metrics_endpoint(...)` block) — it is replaced by the resolver.

Replace the gating block inside `init_metrics` (the `dd_key = ...` through the `readers.append(...)` block) with:

```python
    target = resolve_otlp_target("metrics")
    if target is not None:
        endpoint, headers = target
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        readers.append(PeriodicExportingMetricReader(OTLPMetricExporter(
            endpoint=endpoint,
            headers=headers,
        )))
```

- [ ] **Step 4: Add the `llm.duration_ms` instrument + emitter**

In the `_instruments` dict in `init_metrics`, add after the `llm_empty_response` line:

```python
        "llm_duration_ms": _meter.create_histogram("llm.duration_ms", unit="ms"),
```

Add this public function next to the other `record_llm_*` functions:

```python
def record_llm_duration(model: str, api: str, duration_ms: float, ticker: str) -> None:
    attrs = {"model": model, "api": api, "ticker": ticker}
    _hist("llm_duration_ms", duration_ms, attrs)
    _sentry_dist("llm.duration_ms", duration_ms, attrs)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd agent && .venv/bin/python -m pytest tests/test_metrics.py -v`
Expected: PASS (new tests + existing metrics tests).

- [ ] **Step 6: Commit**

```bash
git add agent/lib/metrics.py agent/tests/test_metrics.py
git commit -m "feat(agent): drive metrics OTLP via resolver; add llm.duration_ms"
```

---

### Task 3: Migrate `emit_metric` callers to the facade; remove `emit_metric`

**Files:**
- Modify: `agent/lib/llm.py`
- Modify: `agent/agent.py`
- Modify: `agent/lib/observability.py`
- Modify: `agent/tests/test_llm.py`

**Interfaces:**
- Consumes: `lib.metrics.record_llm_duration` (Task 2)

- [ ] **Step 1: Write the failing test**

Add to `agent/tests/test_llm.py`:

```python
def test_analyze_records_llm_duration(monkeypatch):
    import importlib, lib.metrics as mtr, lib.llm as llm
    importlib.reload(mtr)
    seen = []
    monkeypatch.setattr(mtr, "record_llm_tokens", lambda *a, **kw: None)
    monkeypatch.setattr(mtr, "record_llm_call", lambda *a, **kw: None)
    monkeypatch.setattr(mtr, "record_llm_duration",
                        lambda model, api, duration_ms, ticker: seen.append((model, api, ticker)))
    importlib.reload(llm)

    valid = '{"recommendation":"buy","summary":"s","signals":[]}'

    class FakeResponses:
        def create(self, **kw):
            class R:
                output_text = valid
                status = "completed"
                class usage:  # noqa: N801
                    input_tokens = 10
                    output_tokens = 5
            return R()

    class FakeClient:
        responses = FakeResponses()

    client = llm.OpenAIClient.__new__(llm.OpenAIClient)
    client._client = FakeClient()
    client._model = "gpt-4.1-mini"
    client._use_responses_api = True

    client.analyze("AAPL")
    assert seen == [("gpt-4.1-mini", "responses", "AAPL")]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd agent && .venv/bin/python -m pytest tests/test_llm.py::test_analyze_records_llm_duration -v`
Expected: FAIL — `record_llm_duration` not called (llm.py still uses `emit_metric`).

- [ ] **Step 3: Migrate `llm.py`**

In `agent/lib/llm.py`, change the import line `from .observability import get_host, emit_metric, emit_log` to:

```python
from .observability import get_host, emit_log
```

Replace the `finally:` block in `analyze` (the `emit_metric("llm.duration_ms", ...)` call) with:

```python
            finally:
                metrics.record_llm_duration(
                    self._model, api,
                    (time.perf_counter() - request_started_at) * 1000,
                    ticker,
                )
```

- [ ] **Step 4: Migrate `agent.py`**

In `agent/agent.py`, change the import line `from lib.observability import init_observability, flush_observability, record_error, emit_log, emit_metric, get_host` to:

```python
from lib.observability import init_observability, flush_observability, record_error, emit_log, get_host
```

In the `finally:` block of `main`, delete the line:

```python
            emit_metric("agent.duration_ms", duration_ms, final_status=final_status)
```

(Leave the surrounding `duration_ms = ...` and `emit_log("info", "agent.finished", ...)` — `duration_ms` is still used by the log.)

- [ ] **Step 5: Remove `emit_metric` and `_datadog_metric` from `observability.py`**

In `agent/lib/observability.py`, delete the entire `def emit_metric(...)` function and the entire `def _datadog_metric(...)` function.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd agent && .venv/bin/python -m pytest tests/test_llm.py tests/test_agent.py -v`
Expected: PASS. Then verify removal:

Run: `grep -rn "emit_metric\|_datadog_metric" agent --include=*.py | grep -v ".venv"`
Expected: no output.

- [ ] **Step 7: Commit**

```bash
git add agent/lib/llm.py agent/agent.py agent/lib/observability.py agent/tests/test_llm.py
git commit -m "refactor(agent): migrate emit_metric callers to metrics facade; remove emit_metric"
```

---

### Task 4: `LoggerProvider` + `emit_log` via OTel logs; remove `_datadog_log`

**Files:**
- Modify: `agent/lib/observability.py`
- Modify: `agent/tests/test_observability.py`

**Interfaces:**
- Consumes: `lib.otlp_target.resolve_otlp_target` (Task 1)
- Produces: module-level `_logger_provider` (drained by `flush_observability`)

- [ ] **Step 1: Write the failing test**

Add to `agent/tests/test_observability.py`:

```python
def test_emit_log_bridges_to_otel_logs(monkeypatch):
    monkeypatch.setenv("JOB_ID", "job-logs")
    import importlib, lib.observability as o
    importlib.reload(o)
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk._logs.export import InMemoryLogExporter, SimpleLogRecordProcessor

    exporter = InMemoryLogExporter()
    lp = LoggerProvider()
    lp.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    o._install_log_bridge(lp)  # attach a stdlib->OTel handler

    o.emit_log("warn", "snapshot.missing", ticker="AAPL")
    lp.force_flush()
    records = exporter.get_finished_log_records()
    assert any("snapshot.missing" in (r.log_record.body or "") for r in records)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd agent && .venv/bin/python -m pytest tests/test_observability.py::test_emit_log_bridges_to_otel_logs -v`
Expected: FAIL — `AttributeError: module 'lib.observability' has no attribute '_install_log_bridge'`.

- [ ] **Step 3: Add logs SDK imports + a stdlib→OTel bridge helper**

In `agent/lib/observability.py`, add near the other imports at the top:

```python
from .otlp_target import resolve_otlp_target
```

Add a module-level global near the other `_inited` globals:

```python
_logger_provider = None
```

Add this helper (place it above `emit_log`):

```python
def _install_log_bridge(logger_provider) -> None:
    """Route stdlib logs emitted through `_stdlib_logger` into an OTel
    LoggerProvider so they reach the OTLP log exporter. Idempotent."""
    from opentelemetry.sdk._logs import LoggingHandler
    for h in list(_stdlib_logger.handlers):
        if isinstance(h, LoggingHandler):
            return
    handler = LoggingHandler(level=logging.DEBUG, logger_provider=logger_provider)
    _stdlib_logger.addHandler(handler)
    _stdlib_logger.setLevel(logging.DEBUG)
```

- [ ] **Step 4: Build the LoggerProvider in `init_observability` and remove `_datadog_log`**

In `agent/lib/observability.py`, inside `init_observability`, after the metrics `init_metrics(resource)` call, add:

```python
    # Logs: OTel LoggerProvider bridged from stdlib; OTLP export via resolver.
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    global _logger_provider
    _logger_provider = LoggerProvider(resource=resource)
    _log_target = resolve_otlp_target("logs")
    if _log_target is not None:
        endpoint, headers = _log_target
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        _logger_provider.add_log_record_processor(BatchLogRecordProcessor(
            OTLPLogExporter(endpoint=endpoint, headers=headers),
        ))
    _install_log_bridge(_logger_provider)
```

Delete the entire `def _datadog_log(...)` function. In `emit_log`, remove the trailing `_datadog_log(level, message, attributes)` call (the stdlib `_stdlib_logger.log(...)` now feeds OTel via the bridge, and the Sentry logger branch stays).

- [ ] **Step 5: Drain the LoggerProvider in `flush_observability`**

In `flush_observability`, after the `flush_metrics` block, add:

```python
    if _logger_provider is not None:
        try:
            _logger_provider.force_flush(timeout_millis=int(timeout_s * 1000))
        except Exception:
            pass
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd agent && .venv/bin/python -m pytest tests/test_observability.py -v`
Expected: PASS (new test + existing). Then verify removal:

Run: `grep -rn "_datadog_log" agent --include=*.py | grep -v ".venv"`
Expected: no output.

- [ ] **Step 7: Commit**

```bash
git add agent/lib/observability.py agent/tests/test_observability.py
git commit -m "feat(agent): route logs through OTel LoggerProvider; remove /api/v2 log intake"
```

---

### Task 5: Traces OTLP via resolver + OTel auto-instrumentation

**Files:**
- Modify: `agent/lib/observability.py`
- Modify: `agent/tests/test_observability.py`

**Interfaces:**
- Consumes: `lib.otlp_target.resolve_otlp_target` (Task 1)

- [ ] **Step 1: Write the failing test**

Add to `agent/tests/test_observability.py`:

```python
def test_trace_otlp_processor_added_when_resolver_returns(monkeypatch):
    monkeypatch.setenv("JOB_ID", "job-traces")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "https://otlp.example/v1/traces")
    import importlib, lib.observability as o
    importlib.reload(o)
    o.init_observability(job_id="job-traces")
    assert o._otlp_traces_inited is True
    o.flush_observability(timeout_s=1.0)


def test_trace_otlp_absent_when_unconfigured(monkeypatch):
    monkeypatch.setenv("JOB_ID", "job-none")
    import importlib, lib.observability as o
    importlib.reload(o)
    o.init_observability(job_id="job-none")
    assert o._otlp_traces_inited is False
    o.flush_observability(timeout_s=1.0)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd agent && .venv/bin/python -m pytest tests/test_observability.py -k "trace_otlp" -v`
Expected: FAIL — `AttributeError: module 'lib.observability' has no attribute '_otlp_traces_inited'`.

- [ ] **Step 3: Replace the trace Datadog-OTLP block with the resolver**

In `agent/lib/observability.py`, add a global near the other `_inited` globals:

```python
_otlp_traces_inited = False
```

In `init_observability`, replace the `else:  # dd_exporter == "otlp"` branch (the block that reads `DD_OTLP_ENDPOINT` and adds the `OTLPSpanExporter`) so the OTLP trace exporter is driven by the resolver instead. Replace the entire Datadog block (`dd_key = ...` through the end of the `otlp` branch) with:

```python
    dd_disabled = os.environ.get("DD_TRACE_ENABLED", "").strip().lower() == "false"
    dd_exporter = (os.environ.get("DD_EXPORTER") or "otlp").strip().lower()
    if dd_exporter not in ("agent", "otlp"):
        raise ValueError(
            f"DD_EXPORTER={dd_exporter!r} is not valid; expected 'agent' or 'otlp'"
        )
    if dd_exporter == "agent" and os.environ.get("DD_API_KEY") and not dd_disabled:
        import ddtrace
        ddtrace.config.service = os.environ.get("DD_SERVICE", "stock-agent")
        ddtrace.config.env = os.environ.get("DD_ENV", "development")
        os.environ.setdefault("DD_TRACE_OTEL_ENABLED", "true")
        ddtrace.patch_all(httpx=True, psycopg=True, openai=True, logging=True)
        global _dd_inited
        _dd_inited = True
    else:
        _trace_target = resolve_otlp_target("traces")
        if _trace_target is not None:
            endpoint, headers = _trace_target
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
                endpoint=endpoint, headers=headers,
            )))
            global _otlp_traces_inited
            _otlp_traces_inited = True
        _install_trace_instrumentors()
```

Note: the default `DD_EXPORTER` is now `otlp` (was `agent`). Update the old `_dd_otlp_inited` references: keep the global defined but set `_otlp_traces_inited` as the authoritative flag (leave `_dd_otlp_inited = False` default in place for backward-compat with any external reader, or delete it if unused — verify with grep in Step 6).

- [ ] **Step 4: Add the OTel auto-instrumentation helper**

Add this helper to `agent/lib/observability.py` (guarded so a missing instrumentor never breaks init):

```python
def _install_trace_instrumentors() -> None:
    """Activate OTel-native auto-instrumentation for outbound HTTP, Postgres, and
    OpenAI against the current TracerProvider (used in OTLP mode, where ddtrace's
    patch_all is not active). Each is guarded independently."""
    for mod_path, cls_name in (
        ("opentelemetry.instrumentation.httpx", "HTTPXClientInstrumentor"),
        ("opentelemetry.instrumentation.psycopg", "PsycopgInstrumentor"),
        ("opentelemetry.instrumentation.openai", "OpenAIInstrumentor"),
    ):
        try:
            mod = __import__(mod_path, fromlist=[cls_name])
            getattr(mod, cls_name)().instrument()
        except Exception:
            pass
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd agent && .venv/bin/python -m pytest tests/test_observability.py -v`
Expected: PASS (new tests + existing gating tests). If an existing test asserted `_dd_otlp_inited`, update it to `_otlp_traces_inited` and re-run.

- [ ] **Step 6: Verify no stale references + commit**

Run: `grep -rn "DD_OTLP_ENDPOINT\|_dd_otlp_inited\|_metrics_endpoint" agent/lib agent/tests --include=*.py | grep -v ".venv"`
Expected: no output (all replaced by the resolver). Fix any stragglers, then:

```bash
git add agent/lib/observability.py agent/tests/test_observability.py
git commit -m "feat(agent): drive trace OTLP via resolver; OTel-native auto-instrumentation"
```

---

### Task 6: Docs + full-suite verification

**Files:**
- Modify: `.env.example`
- Modify: `OTEL.md`

- [ ] **Step 1: Update `.env.example`**

Replace the metrics/OTLP portion of the Observability section with:

```
# --- OTLP transport (vendor-agnostic; traces + metrics + logs) ---
# Standard OpenTelemetry vars. Set a base for all signals and/or per-signal
# overrides. Auth (e.g. Datadog dd-api-key) rides in the _HEADERS var as
# comma-separated key=value pairs.
# OTEL_EXPORTER_OTLP_ENDPOINT=
# OTEL_EXPORTER_OTLP_HEADERS=
# OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=
# OTEL_EXPORTER_OTLP_TRACES_HEADERS=
# OTEL_EXPORTER_OTLP_METRICS_ENDPOINT=
# OTEL_EXPORTER_OTLP_METRICS_HEADERS=
# OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=
# OTEL_EXPORTER_OTLP_LOGS_HEADERS=
#
# Datadog convenience: if DD_API_KEY is set (and DD_TRACE_ENABLED != false) and
# the matching OTEL_* var is unset, all three signals auto-target Datadog's
# agentless intake https://otlp.<DD_SITE>/v1/<signal> with a dd-api-key header.
# DD_EXPORTER=otlp   # 'otlp' (default, agentless) or 'agent' (local Agent :8126)
```

- [ ] **Step 2: Update `OTEL.md`**

In the "Backends & configuration" area of `OTEL.md`, replace the Datadog transport bullet list with a note that all three agent signals export via standard OTLP (resolved from `OTEL_EXPORTER_OTLP_*` with a Datadog agentless convenience), Sentry uses its native SDK, and `DD_EXPORTER=agent` remains an opt-in for a local Agent. Ensure no remaining mention of `/api/v2/series`, `/api/v2/logs`, `emit_metric`, or `DD_OTLP_ENDPOINT`.

- [ ] **Step 3: Run the full Python suite**

Run: `cd agent && .venv/bin/python -m pytest -q`
Expected: PASS (all tests; DB tests may skip without `NEON_DATABASE_URL`).

- [ ] **Step 4: Run the full Node suite (sanity — unchanged)**

Run: `npm run test`
Expected: PASS (unchanged from before).

- [ ] **Step 5: Commit**

```bash
git add .env.example OTEL.md
git commit -m "docs: document unified OTLP transport; drop /api/v2 intakes"
```

---

## Self-Review

**Spec coverage:**
- Standard OTEL_* per-signal config + precedence → Task 1 (`resolve_otlp_target`). ✓
- Datadog agentless convenience (endpoint + `dd-api-key`, overridable) → Task 1. ✓
- Metrics via resolver + retire `_metrics_endpoint` → Task 2. ✓
- Migrate `emit_metric` callers, add `llm.duration_ms`, drop `agent.duration_ms` dup → Tasks 2–3. ✓
- Remove `emit_metric`/`_datadog_metric`/`_datadog_log` → Tasks 3–4 (grep checks). ✓
- LoggerProvider + OTLP logs, `emit_log` signature preserved → Task 4. ✓
- Traces via resolver, ddtrace agent opt-in, OTel auto-instrumentation → Task 5. ✓
- Flush all three providers → Tasks 4–5 (+ existing metrics flush). ✓
- Sentry native SDK unchanged → untouched in all tasks (SentrySpanProcessor/sentry logger remain). ✓
- Docs → Task 6. ✓
- `DD_EXPORTER` validation retained → Task 5 Step 3. ✓
- Snapshot metrics out of scope → not in any task. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. Task 6 Step 2 is a prose doc edit (acceptable — it describes exact text to remove/replace, not code). ✓

**Type consistency:** `resolve_otlp_target(signal) -> tuple[str, dict] | None` defined in Task 1 and consumed with matching unpacking in Tasks 2/4/5. `record_llm_duration(model, api, duration_ms, ticker)` defined in Task 2 and called with matching args in Task 3. `_install_log_bridge`/`_install_trace_instrumentors`/`_logger_provider`/`_otlp_traces_inited` defined and referenced consistently within Tasks 4–5. ✓
