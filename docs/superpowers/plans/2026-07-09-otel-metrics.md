# OTel Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add custom OpenTelemetry metrics to the Python agent and Next.js frontend, dual-emitted to a vendor-neutral OTLP endpoint and Sentry's Application Metrics.

**Architecture:** A thin facade in each service records every metric once, fanning out to (a) OTel `Meter` instruments exported via a periodic OTLP-HTTP reader and (b) Sentry's native metrics API. Both sinks are independently env-gated and fully guarded so a metrics failure never breaks a request or agent run.

**Tech Stack:** Python `opentelemetry-sdk` metrics + `opentelemetry-exporter-otlp-proto-http` + `sentry-sdk`; Node `@opentelemetry/sdk-metrics` + `@opentelemetry/exporter-metrics-otlp-http` + `@sentry/nextjs`. Tests: pytest (agent) and vitest (Next.js).

## Global Constraints

- `job_id` MUST NEVER appear as a metric attribute (unbounded cardinality). A test enforces this.
- `ticker` IS included as an attribute on every metric (explicit design choice).
- Python `sentry-sdk[opentelemetry]` floor is raised to **`>=2.44.0`** (Application Metrics support).
- OTLP metrics export is gated exactly like the existing OTLP *trace* path: active only when `DD_API_KEY` is set, `DD_TRACE_ENABLED` is not `"false"`, `DD_EXPORTER == "otlp"`, and `DD_OTLP_ENDPOINT` is set.
- Sentry metrics mirror is active only when the service's Sentry DSN is set (`SENTRY_DSN_AGENT` for the agent, `SENTRY_DSN_NEXTJS` for Next.js).
- Every metric emit and every init path is wrapped so exceptions are swallowed; unconfigured → no-op.
- Metric instrument names, types, and tags come from this table (verbatim):

  | Metric | Type | Service | Tags |
  |---|---|---|---|
  | `jobs.submitted` | counter | Next.js | `outcome`, `ticker` |
  | `jobs.completed` | counter | agent | `final_status`, `ticker` |
  | `agent.run.duration_ms` | histogram | agent | `final_status`, `ticker` |
  | `llm.tokens_in` | histogram | agent | `model`, `api`, `ticker` |
  | `llm.tokens_out` | histogram | agent | `model`, `api`, `ticker` |
  | `llm.calls` | counter | agent | `model`, `api`, `outcome`, `ticker` |
  | `llm.empty_response` | counter | agent | `model`, `api`, `ticker` |
  | `llm.web_search.used` | counter | agent | `api`, `ticker` |
  | `agent.http.requests` | counter | agent | `host`, `status_code`, `ticker` |
  | `agent.http.duration_ms` | histogram | agent | `host`, `ticker` |

---

### Task 1: Python metrics module (`agent/lib/metrics.py`)

**Files:**
- Create: `agent/lib/metrics.py`
- Create: `agent/tests/test_metrics.py`
- Modify: `agent/requirements.txt` (bump `sentry-sdk`)

**Interfaces:**
- Produces (imported by later tasks):
  - `init_metrics(resource, extra_readers: list | None = None) -> None`
  - `flush_metrics(timeout_s: float = 5.0) -> None`
  - `set_current_ticker(ticker: str) -> None`
  - `record_job_completed(final_status: str, ticker: str) -> None`
  - `record_agent_run_duration(final_status: str, ticker: str, duration_ms: float) -> None`
  - `record_llm_tokens(model: str, api: str, tokens_in: int, tokens_out: int, ticker: str) -> None`
  - `record_llm_call(model: str, api: str, outcome: str, ticker: str) -> None`
  - `record_llm_empty_response(model: str, api: str, ticker: str) -> None`
  - `record_llm_web_search(api: str, ticker: str) -> None`
  - `record_http_request(host: str, status_code: int, duration_ms: float, ticker: str) -> None`
  - `build_httpx_client()` -> `httpx.Client` with request/response event hooks
- Consumes: nothing (leaf module)

- [ ] **Step 1: Bump the Sentry SDK floor**

In `agent/requirements.txt`, change the line:

```
sentry-sdk[opentelemetry]>=2.15.0
```

to:

```
sentry-sdk[opentelemetry]>=2.44.0
```

Then install:

Run: `cd agent && pip install -r requirements.txt`
Expected: installs/upgrades `sentry-sdk` to >=2.44.0 with no errors.

- [ ] **Step 2: Write the failing tests**

Create `agent/tests/test_metrics.py`:

```python
import importlib
import httpx
import pytest
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.metrics.export import InMemoryMetricReader


def _fresh(reader=None):
    """Reload the module for a clean global state, init with an in-memory reader."""
    import lib.metrics as m
    importlib.reload(m)
    m.init_metrics(Resource.create({"service.name": "test"}),
                   extra_readers=[reader] if reader else None)
    return m


def _find_points(reader, name):
    data = reader.get_metrics_data()
    points = []
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                if metric.name == name:
                    points.extend(metric.data.data_points)
    return points


def test_no_op_when_unconfigured():
    import lib.metrics as m
    importlib.reload(m)
    m.init_metrics(Resource.create({"service.name": "test"}))  # no readers
    # Emitting without a reader must not raise.
    m.record_job_completed("complete", "AAPL")
    m.flush_metrics(timeout_s=1.0)


def test_job_completed_counter_records_attrs():
    reader = InMemoryMetricReader()
    m = _fresh(reader)
    m.record_job_completed("complete", "AAPL")
    points = _find_points(reader, "jobs.completed")
    assert len(points) == 1
    assert points[0].value == 1
    assert points[0].attributes["final_status"] == "complete"
    assert points[0].attributes["ticker"] == "AAPL"


def test_llm_tokens_histograms():
    reader = InMemoryMetricReader()
    m = _fresh(reader)
    m.record_llm_tokens("gpt-4.1-mini", "responses", 100, 40, "MSFT")
    tin = _find_points(reader, "llm.tokens_in")
    tout = _find_points(reader, "llm.tokens_out")
    assert tin[0].sum == 100 and tin[0].attributes["model"] == "gpt-4.1-mini"
    assert tout[0].sum == 40 and tout[0].attributes["api"] == "responses"


def test_no_metric_carries_job_id():
    """Global constraint: job_id must never be a metric attribute."""
    reader = InMemoryMetricReader()
    m = _fresh(reader)
    m.set_current_ticker("AAPL")
    m.record_job_completed("complete", "AAPL")
    m.record_agent_run_duration("complete", "AAPL", 1234.0)
    m.record_llm_tokens("gpt-4.1-mini", "responses", 10, 5, "AAPL")
    m.record_llm_call("gpt-4.1-mini", "responses", "ok", "AAPL")
    m.record_llm_empty_response("gpt-4.1-mini", "responses", "AAPL")
    m.record_llm_web_search("responses", "AAPL")
    m.record_http_request("api.openai.com", 200, 12.5, "AAPL")
    data = reader.get_metrics_data()
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                for pt in metric.data.data_points:
                    assert "job_id" not in pt.attributes, metric.name


def test_http_hook_records_request(monkeypatch):
    reader = InMemoryMetricReader()
    m = _fresh(reader)
    m.set_current_ticker("AAPL")
    # Drive the response hook directly with a real httpx.Response + request.
    request = httpx.Request("GET", "https://api.openai.com/v1/responses")
    m._on_request(request)  # stamps start time
    response = httpx.Response(200, request=request)
    m._on_response(response)
    points = _find_points(reader, "agent.http.requests")
    assert points[0].value == 1
    assert points[0].attributes["host"] == "api.openai.com"
    assert points[0].attributes["status_code"] == 200
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd agent && python -m pytest tests/test_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.metrics'`.

- [ ] **Step 4: Implement `agent/lib/metrics.py`**

Create `agent/lib/metrics.py`:

```python
"""Metrics facade: records each metric once into an OTel Meter (exported via a
periodic OTLP reader) and mirrors it to Sentry's native metrics API. Every path
is guarded so a metrics failure never propagates. No-ops when unconfigured.

job_id is intentionally never used as an attribute (unbounded cardinality)."""
import os
import time
from contextvars import ContextVar

_meter = None
_meter_provider = None
_instruments: dict = {}
_sentry_metrics_enabled = False
_current_ticker: ContextVar[str] = ContextVar("current_ticker", default="unknown")
_http_starts: dict = {}


def _metrics_endpoint(traces_endpoint: str) -> str:
    """Derive the OTLP metrics URL from the OTLP traces URL. Explicit override
    via DD_OTLP_METRICS_ENDPOINT wins."""
    override = os.environ.get("DD_OTLP_METRICS_ENDPOINT")
    if override:
        return override
    if traces_endpoint.endswith("/v1/traces"):
        return traces_endpoint[: -len("/v1/traces")] + "/v1/metrics"
    return traces_endpoint


def init_metrics(resource, extra_readers=None) -> None:
    """Build a MeterProvider with an OTLP metric reader when configured, plus any
    extra_readers (used by tests). Idempotent + safe when nothing is configured."""
    global _meter, _meter_provider, _instruments, _sentry_metrics_enabled
    if _meter is not None:
        return
    from opentelemetry import metrics as ot_metrics
    from opentelemetry.sdk.metrics import MeterProvider

    readers = list(extra_readers or [])

    dd_key = os.environ.get("DD_API_KEY")
    dd_disabled = os.environ.get("DD_TRACE_ENABLED", "").strip().lower() == "false"
    dd_exporter = (os.environ.get("DD_EXPORTER") or "agent").strip().lower()
    otlp_endpoint = os.environ.get("DD_OTLP_ENDPOINT")
    if dd_key and not dd_disabled and dd_exporter == "otlp" and otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        readers.append(PeriodicExportingMetricReader(OTLPMetricExporter(
            endpoint=_metrics_endpoint(otlp_endpoint),
            headers={"DD-API-KEY": dd_key},
        )))

    _meter_provider = MeterProvider(resource=resource, metric_readers=readers)
    try:
        ot_metrics.set_meter_provider(_meter_provider)
    except Exception:
        pass
    _meter = _meter_provider.get_meter("stock-agent")

    _instruments = {
        "jobs_completed": _meter.create_counter("jobs.completed"),
        "agent_run_duration_ms": _meter.create_histogram("agent.run.duration_ms", unit="ms"),
        "llm_tokens_in": _meter.create_histogram("llm.tokens_in"),
        "llm_tokens_out": _meter.create_histogram("llm.tokens_out"),
        "llm_calls": _meter.create_counter("llm.calls"),
        "llm_empty_response": _meter.create_counter("llm.empty_response"),
        "llm_web_search_used": _meter.create_counter("llm.web_search.used"),
        "http_requests": _meter.create_counter("agent.http.requests"),
        "http_duration_ms": _meter.create_histogram("agent.http.duration_ms", unit="ms"),
    }

    _sentry_metrics_enabled = bool(os.environ.get("SENTRY_DSN_AGENT"))


def set_current_ticker(ticker: str) -> None:
    _current_ticker.set(ticker or "unknown")


def flush_metrics(timeout_s: float = 5.0) -> None:
    if _meter_provider is None:
        return
    try:
        _meter_provider.force_flush(timeout_millis=int(timeout_s * 1000))
    except Exception:
        pass


# --- Sentry mirror (guarded; resilient to SDK API differences) ---
def _sentry_incr(key, value, tags):
    if not _sentry_metrics_enabled:
        return
    try:
        import sentry_sdk
        m = getattr(sentry_sdk, "metrics", None)
        if m and hasattr(m, "incr"):
            m.incr(key, value, tags=tags)
    except Exception:
        pass


def _sentry_dist(key, value, tags):
    if not _sentry_metrics_enabled:
        return
    try:
        import sentry_sdk
        m = getattr(sentry_sdk, "metrics", None)
        if m and hasattr(m, "distribution"):
            m.distribution(key, value, tags=tags)
    except Exception:
        pass


def _add(instr_key, value, attrs):
    if _meter is None:
        return
    try:
        instr = _instruments.get(instr_key)
        if instr is not None:
            instr.add(value, attrs)
    except Exception:
        pass


def _hist(instr_key, value, attrs):
    if _meter is None:
        return
    try:
        instr = _instruments.get(instr_key)
        if instr is not None:
            instr.record(value, attrs)
    except Exception:
        pass


# --- Public emit functions ---
def record_job_completed(final_status: str, ticker: str) -> None:
    attrs = {"final_status": final_status, "ticker": ticker}
    _add("jobs_completed", 1, attrs)
    _sentry_incr("jobs.completed", 1, attrs)


def record_agent_run_duration(final_status: str, ticker: str, duration_ms: float) -> None:
    attrs = {"final_status": final_status, "ticker": ticker}
    _hist("agent_run_duration_ms", duration_ms, attrs)
    _sentry_dist("agent.run.duration_ms", duration_ms, attrs)


def record_llm_tokens(model: str, api: str, tokens_in: int, tokens_out: int, ticker: str) -> None:
    attrs = {"model": model, "api": api, "ticker": ticker}
    _hist("llm_tokens_in", tokens_in, attrs)
    _hist("llm_tokens_out", tokens_out, attrs)
    _sentry_dist("llm.tokens_in", tokens_in, attrs)
    _sentry_dist("llm.tokens_out", tokens_out, attrs)


def record_llm_call(model: str, api: str, outcome: str, ticker: str) -> None:
    attrs = {"model": model, "api": api, "outcome": outcome, "ticker": ticker}
    _add("llm_calls", 1, attrs)
    _sentry_incr("llm.calls", 1, attrs)


def record_llm_empty_response(model: str, api: str, ticker: str) -> None:
    attrs = {"model": model, "api": api, "ticker": ticker}
    _add("llm_empty_response", 1, attrs)
    _sentry_incr("llm.empty_response", 1, attrs)


def record_llm_web_search(api: str, ticker: str) -> None:
    attrs = {"api": api, "ticker": ticker}
    _add("llm_web_search_used", 1, attrs)
    _sentry_incr("llm.web_search.used", 1, attrs)


def record_http_request(host: str, status_code: int, duration_ms: float, ticker: str) -> None:
    count_attrs = {"host": host, "status_code": status_code, "ticker": ticker}
    dur_attrs = {"host": host, "ticker": ticker}
    _add("http_requests", 1, count_attrs)
    _hist("http_duration_ms", duration_ms, dur_attrs)
    _sentry_incr("agent.http.requests", 1, count_attrs)
    _sentry_dist("agent.http.duration_ms", duration_ms, dur_attrs)


# --- httpx event hooks + instrumented client factory ---
def _on_request(request) -> None:
    _http_starts[id(request)] = time.monotonic()


def _on_response(response) -> None:
    start = _http_starts.pop(id(response.request), None)
    dur_ms = (time.monotonic() - start) * 1000 if start is not None else 0.0
    try:
        host = response.request.url.host
    except Exception:
        host = "unknown"
    record_http_request(host=host, status_code=response.status_code,
                        duration_ms=dur_ms, ticker=_current_ticker.get())


def build_httpx_client():
    """An httpx.Client whose event hooks emit agent.http.* metrics. Pass to the
    OpenAI client so all outbound OpenAI HTTP calls are measured."""
    import httpx
    return httpx.Client(event_hooks={"request": [_on_request], "response": [_on_response]})
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd agent && python -m pytest tests/test_metrics.py -v`
Expected: PASS (all tests).

- [ ] **Step 6: Commit**

```bash
git add agent/lib/metrics.py agent/tests/test_metrics.py agent/requirements.txt
git commit -m "feat(agent): add OTel+Sentry metrics facade module"
```

---

### Task 2: Wire metrics into agent observability lifecycle

**Files:**
- Modify: `agent/lib/observability.py` (call `init_metrics` in `init_observability`, `flush_metrics` in `flush_observability`)
- Modify: `agent/tests/test_observability.py` (assert meter initialized + flush safe)

**Interfaces:**
- Consumes: `lib.metrics.init_metrics`, `lib.metrics.flush_metrics` (Task 1)
- Produces: no new public symbols

- [ ] **Step 1: Write the failing test**

Add to `agent/tests/test_observability.py`:

```python
def test_init_sets_up_metrics(monkeypatch):
    monkeypatch.setenv("JOB_ID", "job-metrics")
    import importlib, lib.observability as o, lib.metrics as mtr
    importlib.reload(mtr)
    importlib.reload(o)
    o.init_observability(job_id="job-metrics")
    assert mtr._meter is not None
    o.flush_observability(timeout_s=1.0)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd agent && python -m pytest tests/test_observability.py::test_init_sets_up_metrics -v`
Expected: FAIL — `mtr._meter` is `None` (metrics not wired yet).

- [ ] **Step 3: Wire `init_metrics` into `init_observability`**

In `agent/lib/observability.py`, immediately after the block that sets the tracer provider (after `trace.set_tracer_provider(provider)`, currently line 30), add:

```python
    # Metrics: share the same Resource; OTLP metric export is gated identically
    # to the OTLP trace path (see lib/metrics.init_metrics).
    from lib.metrics import init_metrics
    init_metrics(resource)
```

- [ ] **Step 4: Wire `flush_metrics` into `flush_observability`**

In `agent/lib/observability.py`, inside `flush_observability`, immediately after the `tp = trace.get_tracer_provider()` shutdown block (after its `except Exception: pass`, currently around line 114), add:

```python
    try:
        from lib.metrics import flush_metrics
        flush_metrics(timeout_s=timeout_s)
    except Exception:
        pass
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd agent && python -m pytest tests/test_observability.py -v`
Expected: PASS (new test + all existing observability tests).

- [ ] **Step 6: Commit**

```bash
git add agent/lib/observability.py agent/tests/test_observability.py
git commit -m "feat(agent): init and flush metrics in observability lifecycle"
```

---

### Task 3: Instrument the agent run (`jobs.completed`, `agent.run.duration_ms`)

**Files:**
- Modify: `agent/agent.py`
- Modify: `agent/tests/test_agent.py`

**Interfaces:**
- Consumes: `lib.metrics.record_job_completed`, `lib.metrics.record_agent_run_duration` (Task 1)

- [ ] **Step 1: Write the failing test**

Add to `agent/tests/test_agent.py` (imports at top of file as needed):

```python
def test_agent_records_completion_metrics(monkeypatch):
    monkeypatch.setenv("JOB_ID", "job-x")
    import importlib, agent as agent_module, lib.metrics as mtr
    importlib.reload(mtr)
    calls = {}
    monkeypatch.setattr(mtr, "record_job_completed",
                        lambda final_status, ticker: calls.setdefault("completed", (final_status, ticker)))
    monkeypatch.setattr(mtr, "record_agent_run_duration",
                        lambda final_status, ticker, duration_ms: calls.setdefault("duration", (final_status, ticker)))
    monkeypatch.setattr(agent_module, "get_job", lambda job_id: {"ticker": "AAPL", "status": "pending", "sandbox_id": None})
    monkeypatch.setattr(agent_module, "mark_running", lambda job_id: None)
    monkeypatch.setattr(agent_module, "mark_complete", lambda job_id, recommendation, result: None)
    monkeypatch.setattr(agent_module, "run_analysis", lambda ticker: {"recommendation": "buy"})
    monkeypatch.setattr(agent_module, "self_delete", lambda sandbox_id=None: None)

    agent_module.JOB_ID = "job-x"
    agent_module.main()
    assert calls["completed"] == ("complete", "AAPL")
    assert calls["duration"][0] == "complete"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd agent && python -m pytest tests/test_agent.py::test_agent_records_completion_metrics -v`
Expected: FAIL — `KeyError: 'completed'` (metrics not emitted yet).

- [ ] **Step 3: Instrument `agent/agent.py`**

At the top of `agent/agent.py`, add `import time` (after `import os`) and import the metrics helpers by adding to the existing `lib.metrics` usage — insert this import after the existing `from lib.llm import run_analysis` line:

```python
from lib.metrics import record_job_completed, record_agent_run_duration
```

Then change the `with tracer.start_as_current_span("agent.run") as span:` block. Add a start timestamp and emit metrics in the success and failure branches. The updated block (lines 20-38 region) becomes:

```python
    _start = time.monotonic()
    with tracer.start_as_current_span("agent.run") as span:
        span.set_attribute("job_id", JOB_ID)
        job = None
        try:
            job = get_job(JOB_ID)
            if job is None or job["status"] != "pending":
                print(f"job {JOB_ID} not pending (status={job and job['status']}); exiting", file=sys.stderr)
                return
            span.set_attribute("ticker", job["ticker"])

            mark_running(JOB_ID)
            result = run_analysis(ticker=job["ticker"])
            mark_complete(JOB_ID, recommendation=result["recommendation"], result=result)
            span.set_attribute("final_status", "complete")
            record_job_completed("complete", job["ticker"])
            record_agent_run_duration("complete", job["ticker"], (time.monotonic() - _start) * 1000)
        except Exception as e:
            record_error(span, e)
            mark_failed(JOB_ID, error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
            span.set_attribute("final_status", "failed")
            _ticker = job["ticker"] if job else "unknown"
            record_job_completed("failed", _ticker)
            record_agent_run_duration("failed", _ticker, (time.monotonic() - _start) * 1000)
            raise
        finally:
            flush_observability()
            try:
                # Prefer the sandbox_id from the job row (written by NextJS after dt.create).
                # Fall back to the env var inside self_delete() for any custom setup.
                sandbox_id = (job["sandbox_id"] if job and "sandbox_id" in job else None)
                self_delete(sandbox_id=sandbox_id)
            except Exception:
                pass
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd agent && python -m pytest tests/test_agent.py -v`
Expected: PASS (new test + existing agent tests).

- [ ] **Step 5: Commit**

```bash
git add agent/agent.py agent/tests/test_agent.py
git commit -m "feat(agent): emit jobs.completed and agent.run.duration_ms metrics"
```

---

### Task 4: Instrument LLM calls + outbound HTTP (`agent/lib/llm.py`)

**Files:**
- Modify: `agent/lib/llm.py`
- Modify: `agent/tests/test_llm.py`

**Interfaces:**
- Consumes: `lib.metrics.set_current_ticker`, `record_llm_tokens`, `record_llm_call`, `record_llm_empty_response`, `record_llm_web_search`, `build_httpx_client` (Task 1)

- [ ] **Step 1: Write the failing test**

Add to `agent/tests/test_llm.py`:

```python
def test_analyze_emits_llm_metrics(monkeypatch):
    import importlib, lib.metrics as mtr, lib.llm as llm
    importlib.reload(mtr)
    seen = {"tokens": [], "calls": [], "web_search": []}
    monkeypatch.setattr(mtr, "record_llm_tokens",
                        lambda model, api, tokens_in, tokens_out, ticker: seen["tokens"].append((model, api, tokens_in, tokens_out, ticker)))
    monkeypatch.setattr(mtr, "record_llm_call",
                        lambda model, api, outcome, ticker: seen["calls"].append((model, api, outcome, ticker)))
    monkeypatch.setattr(mtr, "record_llm_web_search",
                        lambda api, ticker: seen["web_search"].append((api, ticker)))
    importlib.reload(llm)

    valid = '{"recommendation":"buy","summary":"s","signals":[]}'

    class FakeResponses:
        def create(self, **kw):
            class R:
                output_text = valid
                status = "completed"
                class usage:  # noqa: N801
                    input_tokens = 100
                    output_tokens = 40
            return R()

    class FakeClient:
        responses = FakeResponses()

    client = llm.OpenAIClient.__new__(llm.OpenAIClient)
    client._client = FakeClient()
    client._model = "gpt-4.1-mini"
    client._use_responses_api = True

    client.analyze("AAPL")
    assert seen["tokens"] == [("gpt-4.1-mini", "responses", 100, 40, "AAPL")]
    assert seen["calls"] == [("gpt-4.1-mini", "responses", "ok", "AAPL")]
    assert seen["web_search"] == [("responses", "AAPL")]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd agent && python -m pytest tests/test_llm.py::test_analyze_emits_llm_metrics -v`
Expected: FAIL — `AttributeError`/no metrics recorded (functions not called yet).

- [ ] **Step 3: Import metrics and pass an instrumented httpx client**

In `agent/lib/llm.py`, add after `from .prompts import SYSTEM_PROMPT, user_prompt` (line 10):

```python
from . import metrics
```

In `OpenAIClient.__init__`, change the client construction to pass the instrumented http client:

```python
        self._client = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.environ.get("OPENAI_API_URL") or None,
            http_client=metrics.build_httpx_client(),
        )
```

- [ ] **Step 4: Emit LLM metrics inside `analyze`**

Replace the body of `analyze` (lines 107-143) with the instrumented version:

```python
    def analyze(self, ticker: str) -> Analysis:
        metrics.set_current_ticker(ticker)
        tracer = trace.get_tracer("stock-agent")
        api = "responses" if self._use_responses_api else "chat.completions"
        with tracer.start_as_current_span("llm.analyze") as span:
            span.set_attribute("model", self._model)
            span.set_attribute("api", api)
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt(ticker)},
            ]
            try:
                if self._use_responses_api:
                    metrics.record_llm_web_search(api, ticker)
                    resp = self._client.responses.create(
                        model=self._model,
                        input=messages,
                        tools=[{"type": "web_search"}],
                    )
                    text = resp.output_text
                    finish_reason = getattr(resp, "status", None)
                    usage = getattr(resp, "usage", None)
                    tin = getattr(usage, "input_tokens", 0) if usage else 0
                    tout = getattr(usage, "output_tokens", 0) if usage else 0
                else:
                    resp = self._client.chat.completions.create(
                        model=self._model,
                        messages=messages,
                    )
                    choice = resp.choices[0]
                    text = choice.message.content
                    finish_reason = choice.finish_reason
                    usage = getattr(resp, "usage", None)
                    tin = getattr(usage, "prompt_tokens", 0) if usage else 0
                    tout = getattr(usage, "completion_tokens", 0) if usage else 0

                span.set_attribute("tokens_in", tin)
                span.set_attribute("tokens_out", tout)
                metrics.record_llm_tokens(self._model, api, tin, tout, ticker)
                _require_nonempty(text, api=api, finish_reason=finish_reason, span=span,
                                  model=self._model, ticker=ticker)
                result = parse_response(text)
                metrics.record_llm_call(self._model, api, "ok", ticker)
                return result
            except Exception:
                metrics.record_llm_call(self._model, api, "error", ticker)
                raise
```

- [ ] **Step 5: Emit the empty-response metric**

Change `_require_nonempty` (lines 64-80) to accept `model`/`ticker` and emit the metric. New signature and body:

```python
def _require_nonempty(text: str | None, *, api: str, finish_reason: str | None, span,
                      model: str, ticker: str) -> None:
    """Log a warning + record a span event + metric + raise EmptyLLMResponseError
    if the model returned no content. tenacity catches EmptyLLMResponseError and retries."""
    if text and text.strip():
        return
    span.add_event("llm.empty_response", {
        "api": api,
        "finish_reason": finish_reason or "unknown",
        "text_is_none": text is None,
    })
    metrics.record_llm_empty_response(model, api, ticker)
    logger.warning(
        "LLM returned empty response (api=%s, finish_reason=%s, text_is_none=%s); retrying",
        api, finish_reason, text is None,
    )
    raise EmptyLLMResponseError(
        f"empty content (api={api}, finish_reason={finish_reason!r}, text_is_none={text is None})"
    )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd agent && python -m pytest tests/test_llm.py -v`
Expected: PASS (new test + existing llm tests — the existing tests exercise the same `analyze` path and must still pass).

- [ ] **Step 7: Commit**

```bash
git add agent/lib/llm.py agent/tests/test_llm.py
git commit -m "feat(agent): emit llm.* and agent.http.* metrics"
```

---

### Task 5: Node metrics module (`lib/observability/metrics.ts`)

**Files:**
- Create: `lib/observability/metrics.ts`
- Create: `tests/observability.metrics.test.ts`
- Modify: `package.json` (add metrics SDK + OTLP metrics exporter)

**Interfaces:**
- Produces:
  - `initMetrics(opts?: { readers?: MetricReader[] }): void`
  - `jobsSubmitted(outcome: string, ticker: string): void`
  - `buildJobAttrs(outcome: string, ticker: string): Record<string, string>`
  - `forceFlushMetrics(): Promise<void>`
- Consumes: nothing

- [ ] **Step 1: Install the Node metrics dependencies**

Run: `npm install @opentelemetry/sdk-metrics @opentelemetry/exporter-metrics-otlp-http`
Expected: both packages added to `package.json` dependencies; `npm install` completes with no errors.

- [ ] **Step 2: Write the failing tests**

Create `tests/observability.metrics.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";

const incr = vi.fn();
vi.mock("@sentry/nextjs", () => ({ metrics: { increment: incr, distribution: vi.fn() } }));

import { initMetrics, jobsSubmitted, buildJobAttrs } from "@/lib/observability/metrics";

describe("node metrics facade", () => {
  beforeEach(() => vi.clearAllMocks());

  it("buildJobAttrs includes outcome and ticker but never job_id", () => {
    const attrs = buildJobAttrs("accepted", "AAPL");
    expect(attrs).toEqual({ outcome: "accepted", ticker: "AAPL" });
    expect("job_id" in attrs).toBe(false);
  });

  it("jobsSubmitted does not throw before/after init", () => {
    expect(() => jobsSubmitted("rejected", "AAPL")).not.toThrow();
    initMetrics();
    expect(() => jobsSubmitted("accepted", "AAPL")).not.toThrow();
  });
});
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `npx vitest run tests/observability.metrics.test.ts`
Expected: FAIL — cannot resolve `@/lib/observability/metrics`.

- [ ] **Step 4: Implement `lib/observability/metrics.ts`**

Create `lib/observability/metrics.ts`:

```typescript
import { MeterProvider, PeriodicExportingMetricReader, type MetricReader } from "@opentelemetry/sdk-metrics";
import { metrics as otelMetrics, type Counter } from "@opentelemetry/api";

let provider: MeterProvider | undefined;
let jobsSubmittedCounter: Counter | undefined;
let sentryEnabled = false;

function metricsEndpoint(tracesEndpoint: string): string {
  const override = process.env.DD_OTLP_METRICS_ENDPOINT;
  if (override) return override;
  if (tracesEndpoint.endsWith("/v1/traces")) {
    return tracesEndpoint.slice(0, -"/v1/traces".length) + "/v1/metrics";
  }
  return tracesEndpoint;
}

export function buildJobAttrs(outcome: string, ticker: string): Record<string, string> {
  return { outcome, ticker };
}

export function initMetrics(opts?: { readers?: MetricReader[] }): void {
  if (provider) return;
  const readers: MetricReader[] = [...(opts?.readers ?? [])];

  const ddKey = process.env.DD_API_KEY;
  const ddDisabled = (process.env.DD_TRACE_ENABLED ?? "").trim().toLowerCase() === "false";
  const ddExporter = (process.env.DD_EXPORTER ?? "agent").trim().toLowerCase();
  const otlpEndpoint = process.env.DD_OTLP_ENDPOINT;
  if (ddKey && !ddDisabled && ddExporter === "otlp" && otlpEndpoint) {
    // Lazy require keeps the OTLP exporter out of edge/browser bundles.
    const { OTLPMetricExporter } = require("@opentelemetry/exporter-metrics-otlp-http");
    readers.push(new PeriodicExportingMetricReader({
      exporter: new OTLPMetricExporter({
        url: metricsEndpoint(otlpEndpoint),
        headers: { "DD-API-KEY": ddKey },
      }),
    }));
  }

  provider = new MeterProvider({ readers });
  otelMetrics.setGlobalMeterProvider(provider);
  const meter = provider.getMeter("stock-agent-frontend");
  jobsSubmittedCounter = meter.createCounter("jobs.submitted");
  sentryEnabled = !!process.env.SENTRY_DSN_NEXTJS;
}

function sentryIncr(key: string, value: number, tags: Record<string, string>): void {
  if (!sentryEnabled) return;
  try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const Sentry = require("@sentry/nextjs");
    Sentry?.metrics?.increment?.(key, value, { tags });
  } catch {
    /* metrics must never break a request */
  }
}

export function jobsSubmitted(outcome: string, ticker: string): void {
  const attrs = buildJobAttrs(outcome, ticker);
  try {
    jobsSubmittedCounter?.add(1, attrs);
  } catch {
    /* no-op */
  }
  sentryIncr("jobs.submitted", 1, attrs);
}

export async function forceFlushMetrics(): Promise<void> {
  try {
    await provider?.forceFlush();
  } catch {
    /* no-op */
  }
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `npx vitest run tests/observability.metrics.test.ts`
Expected: PASS (both tests).

- [ ] **Step 6: Commit**

```bash
git add lib/observability/metrics.ts tests/observability.metrics.test.ts package.json package-lock.json
git commit -m "feat(web): add Node OTel+Sentry metrics facade"
```

---

### Task 6: Wire Node metrics into init + the jobs route

**Files:**
- Modify: `lib/observability/otel.ts` (call `initMetrics`)
- Modify: `app/api/jobs/route.ts` (emit `jobs.submitted`)
- Modify: `tests/api.jobs.test.ts` (assert emission)

**Interfaces:**
- Consumes: `initMetrics`, `jobsSubmitted` (Task 5)

- [ ] **Step 1: Write the failing test**

Add to `tests/api.jobs.test.ts` — add the mock near the other `vi.mock` calls at the top:

```typescript
vi.mock("@/lib/observability/metrics", () => ({
  jobsSubmitted: vi.fn(),
}));
```

Then add, inside `describe("POST /api/jobs", ...)`:

```typescript
  it("emits jobs.submitted on accept and reject", async () => {
    const { jobsSubmitted } = await import("@/lib/observability/metrics");
    await POST(req({ ticker: "AAPL" }));
    await POST(req({ ticker: "" }));
    expect(jobsSubmitted).toHaveBeenCalledWith("accepted", "AAPL");
    expect(jobsSubmitted).toHaveBeenCalledWith("rejected", "unknown");
  });
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run tests/api.jobs.test.ts`
Expected: FAIL — `jobsSubmitted` was not called (route not instrumented yet).

- [ ] **Step 3: Emit `jobs.submitted` in the route**

In `app/api/jobs/route.ts`, add to the imports:

```typescript
import { jobsSubmitted } from "@/lib/observability/metrics";
```

In the reject branch (the `catch` after `Body.parse`), add the emit right after `addAttrs(span, { outcome: "rejected" });`:

```typescript
      jobsSubmitted("rejected", "unknown");
```

In the accept branch, add the emit right after `addAttrs(span, { sandbox_id: sandboxId, outcome: "accepted" });`:

```typescript
      jobsSubmitted("accepted", parsed.ticker);
```

- [ ] **Step 4: Call `initMetrics` at OTel startup**

In `lib/observability/otel.ts`, add to the imports:

```typescript
import { initMetrics } from "./metrics";
```

Inside `initOtel()`, after `sdk.start();`, add:

```typescript
  initMetrics();
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `npx vitest run tests/api.jobs.test.ts tests/observability.metrics.test.ts`
Expected: PASS (all tests).

- [ ] **Step 6: Commit**

```bash
git add app/api/jobs/route.ts lib/observability/otel.ts tests/api.jobs.test.ts
git commit -m "feat(web): emit jobs.submitted metric from POST /api/jobs"
```

---

### Task 7: Documentation + full-suite verification

**Files:**
- Modify: `.env.example`
- Modify: `OTEL.md`

**Interfaces:** none (docs + verification only)

- [ ] **Step 1: Document env vars in `.env.example`**

In the Observability section of `.env.example` (around lines 67-89), add:

```
# --- Metrics ---
# Custom OTel metrics are dual-emitted:
#   * OTLP: exported alongside traces when DD_EXPORTER=otlp and DD_OTLP_ENDPOINT
#     is set (metrics URL derived from the traces URL, or override below).
#   * Sentry: auto-on when the service's Sentry DSN is set.
# DD_OTLP_METRICS_ENDPOINT=   # optional; defaults to <DD_OTLP_ENDPOINT>/v1/metrics
```

- [ ] **Step 2: Update `OTEL.md` metrics section**

In `OTEL.md`, change the at-a-glance table row for Metrics from:

```
| Metrics  | ❌ Not implemented  | —                   | OTel metrics SDK is not even a dependency        |
```

to:

```
| Metrics  | ✅ Implemented      | Sentry + Datadog    | Dual-emit facade (OTLP + Sentry Application Metrics) |
```

Then replace the "## Metrics" section body ("**Not implemented.** ...") with:

```markdown
Custom metrics are dual-emitted through a facade in each service: OTel `Meter`
instruments exported via a periodic OTLP-HTTP reader (gated like the OTLP trace
path) **and** Sentry's Application Metrics API (auto-on with the service DSN).
`job_id` is never a metric tag; `ticker` is tagged on all metrics.

| Metric | Type | Service | Tags |
|---|---|---|---|
| `jobs.submitted` | counter | Next.js | `outcome`, `ticker` |
| `jobs.completed` | counter | agent | `final_status`, `ticker` |
| `agent.run.duration_ms` | histogram | agent | `final_status`, `ticker` |
| `llm.tokens_in` / `llm.tokens_out` | histogram | agent | `model`, `api`, `ticker` |
| `llm.calls` | counter | agent | `model`, `api`, `outcome`, `ticker` |
| `llm.empty_response` | counter | agent | `model`, `api`, `ticker` |
| `llm.web_search.used` | counter | agent | `api`, `ticker` |
| `agent.http.requests` | counter | agent | `host`, `status_code`, `ticker` |
| `agent.http.duration_ms` | histogram | agent | `host`, `ticker` |

Facade modules: `lib/observability/metrics.ts` (Next.js), `agent/lib/metrics.py` (agent).
```

- [ ] **Step 3: Run the full Python test suite**

Run: `cd agent && python -m pytest -q`
Expected: PASS (all tests, including the new metrics/agent/llm tests).

- [ ] **Step 4: Run the full Node test suite**

Run: `npm run test`
Expected: PASS (all vitest suites).

- [ ] **Step 5: Commit**

```bash
git add .env.example OTEL.md
git commit -m "docs: document metrics in OTEL.md and .env.example"
```

---

## Self-Review

**Spec coverage:**
- Dual-emit facade (OTLP + Sentry) → Task 1 (Python), Task 5 (Node). ✓
- All 10 metrics in the inventory → Task 1 instruments + Tasks 3/4/6 emit sites. ✓
- OTLP gating identical to trace path → Task 1 `init_metrics` / Task 5 `initMetrics`. ✓
- Sentry DSN gating → Task 1 `_sentry_metrics_enabled` / Task 5 `sentryEnabled`. ✓
- `sentry-sdk>=2.44.0` bump → Task 1 Step 1. ✓
- `job_id` never tagged → Task 1 `test_no_metric_carries_job_id`, Task 5 `buildJobAttrs` test. ✓
- `ticker` tagged everywhere → all emit functions include it. ✓
- Flush before shutdown → Task 2 (`flush_metrics` in `flush_observability`); Node `forceFlushMetrics` exposed (Task 5). ✓
- web_search + outbound HTTP metrics → Task 4. ✓
- Docs (`.env.example`, `OTEL.md`) → Task 7. ✓
- yfinance explicitly out of scope → not in any task. ✓

**Placeholder scan:** No TBD/TODO/"handle errors appropriately"; every code step shows complete code. ✓

**Type consistency:** `init_metrics(resource, extra_readers=None)`, `flush_metrics(timeout_s)`, `set_current_ticker`, and all `record_*` signatures are defined in Task 1 and consumed with matching arguments in Tasks 2-4. Node `initMetrics`/`jobsSubmitted`/`buildJobAttrs`/`forceFlushMetrics` defined in Task 5, consumed with matching signatures in Task 6. `_require_nonempty` gains `model`/`ticker` kwargs (Task 4 Step 5) and every caller (Task 4 Step 4) passes them. ✓
