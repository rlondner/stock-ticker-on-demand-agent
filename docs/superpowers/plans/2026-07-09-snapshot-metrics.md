# Snapshot Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Instrument `fetch_snapshot` (the yfinance market-data fetch) with five custom metrics via the unified metrics facade.

**Architecture:** Add four emit functions (five instruments) to `agent/lib/metrics.py`, then emit them from `agent/lib/finance.py::fetch_snapshot` — which gets a monotonic timer and, on success, iterates a key-field list. `_fetch_snapshot_once` changes its return to `(snapshot, backfilled)` so all emission lives in the orchestrator.

**Tech Stack:** Python `opentelemetry-sdk` metrics + `sentry-sdk` (via the existing facade). Tests: pytest with `InMemoryMetricReader` and mocked `yfinance`.

## Global Constraints

- All snapshot metrics are `ticker`-tagged; `job_id` is NEVER a metric attribute (a test enforces this).
- Metric names/types/tags (verbatim):
  | Metric | Type | Tags |
  |---|---|---|
  | `agent.snapshot.fetch` | counter | `outcome`, `ticker` |
  | `agent.snapshot.fetch.duration_ms` | histogram (ms) | `outcome`, `ticker` |
  | `agent.snapshot.backfilled` | counter | `ticker` |
  | `agent.snapshot.field_missing` | counter | `field`, `ticker` |
  | `agent.snapshot.completeness` | histogram | `ticker` |
- `outcome` ∈ `{"success","missing","error"}` matching `fetch_snapshot`'s three branches.
- Duration is measured over the whole `fetch_snapshot` call (including retries).
- Key fields (exactly these 12, in this order): `company_name, sector, industry, close, previous_close, market_cap, fifty_two_week_high, fifty_two_week_low, average_volume, analyst_recommendation, analyst_opinion_count, business_summary`.
- `field_missing` + `completeness` emit ONLY on `outcome == "success"`.
- Every emit path is guarded by the facade (no-op when unconfigured); snapshot metrics must never break `fetch_snapshot` (its "never raises / returns None on total failure" contract is preserved).
- `fetch_snapshot`'s public return type stays `Snapshot | None`. Only `_fetch_snapshot_once` (private) changes to return a tuple.
- Tests use the agent venv: `agent/.venv/bin/python -m pytest ...` (system `pip` unavailable).

---

### Task 1: Metrics facade — snapshot instruments + emit functions

**Files:**
- Modify: `agent/lib/metrics.py`
- Modify: `agent/tests/test_metrics.py`

**Interfaces:**
- Produces:
  - `record_snapshot_fetch(outcome: str, ticker: str, duration_ms: float) -> None`
  - `record_snapshot_backfilled(ticker: str) -> None`
  - `record_snapshot_field_missing(field: str, ticker: str) -> None`
  - `record_snapshot_completeness(populated: int, ticker: str) -> None`
- Consumes: existing `_add`, `_hist`, `_sentry_incr`, `_sentry_dist` helpers in `metrics.py`.

- [ ] **Step 1: Write the failing tests**

Add to `agent/tests/test_metrics.py`:

```python
def _snapshot_points(reader, name):
    out = []
    for rm in reader.get_metrics_data().resource_metrics:
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                if metric.name == name:
                    out.extend(metric.data.data_points)
    return out


def test_record_snapshot_fetch_emits_counter_and_duration():
    import importlib, lib.metrics as m
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    importlib.reload(m)
    reader = InMemoryMetricReader()
    m.init_metrics(Resource.create({"service.name": "test"}), extra_readers=[reader])
    m.record_snapshot_fetch("success", "AAPL", 250.0)
    c = _snapshot_points(reader, "agent.snapshot.fetch")
    d = _snapshot_points(reader, "agent.snapshot.fetch.duration_ms")
    assert c[0].value == 1
    assert c[0].attributes == {"outcome": "success", "ticker": "AAPL"}
    assert d[0].sum == 250.0
    assert d[0].attributes == {"outcome": "success", "ticker": "AAPL"}


def test_record_snapshot_backfilled_field_missing_completeness():
    import importlib, lib.metrics as m
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    importlib.reload(m)
    reader = InMemoryMetricReader()
    m.init_metrics(Resource.create({"service.name": "test"}), extra_readers=[reader])
    m.record_snapshot_backfilled("AAPL")
    m.record_snapshot_field_missing("market_cap", "AAPL")
    m.record_snapshot_completeness(11, "AAPL")
    assert _snapshot_points(reader, "agent.snapshot.backfilled")[0].attributes == {"ticker": "AAPL"}
    fm = _snapshot_points(reader, "agent.snapshot.field_missing")[0]
    assert fm.value == 1 and fm.attributes == {"field": "market_cap", "ticker": "AAPL"}
    comp = _snapshot_points(reader, "agent.snapshot.completeness")[0]
    assert comp.sum == 11 and comp.attributes == {"ticker": "AAPL"}


def test_snapshot_metrics_never_carry_job_id():
    import importlib, lib.metrics as m
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    importlib.reload(m)
    reader = InMemoryMetricReader()
    m.init_metrics(Resource.create({"service.name": "test"}), extra_readers=[reader])
    m.record_snapshot_fetch("success", "AAPL", 1.0)
    m.record_snapshot_backfilled("AAPL")
    m.record_snapshot_field_missing("close", "AAPL")
    m.record_snapshot_completeness(5, "AAPL")
    for rm in reader.get_metrics_data().resource_metrics:
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                for pt in metric.data.data_points:
                    assert "job_id" not in pt.attributes, metric.name
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd agent && .venv/bin/python -m pytest tests/test_metrics.py -k snapshot -v`
Expected: FAIL — `AttributeError: module 'lib.metrics' has no attribute 'record_snapshot_fetch'`.

- [ ] **Step 3: Add the five instruments**

In `agent/lib/metrics.py`, in the `_instruments` dict inside `init_metrics` (after the `http_duration_ms` line), add:

```python
        "snapshot_fetch": _meter.create_counter("agent.snapshot.fetch"),
        "snapshot_fetch_duration_ms": _meter.create_histogram("agent.snapshot.fetch.duration_ms", unit="ms"),
        "snapshot_backfilled": _meter.create_counter("agent.snapshot.backfilled"),
        "snapshot_field_missing": _meter.create_counter("agent.snapshot.field_missing"),
        "snapshot_completeness": _meter.create_histogram("agent.snapshot.completeness"),
```

- [ ] **Step 4: Add the four emit functions**

In `agent/lib/metrics.py`, add after `record_http_request` (near the other `record_*` functions):

```python
def record_snapshot_fetch(outcome: str, ticker: str, duration_ms: float) -> None:
    attrs = {"outcome": outcome, "ticker": ticker}
    _add("snapshot_fetch", 1, attrs)
    _hist("snapshot_fetch_duration_ms", duration_ms, attrs)
    _sentry_incr("agent.snapshot.fetch", 1, attrs)
    _sentry_dist("agent.snapshot.fetch.duration_ms", duration_ms, attrs)


def record_snapshot_backfilled(ticker: str) -> None:
    attrs = {"ticker": ticker}
    _add("snapshot_backfilled", 1, attrs)
    _sentry_incr("agent.snapshot.backfilled", 1, attrs)


def record_snapshot_field_missing(field: str, ticker: str) -> None:
    attrs = {"field": field, "ticker": ticker}
    _add("snapshot_field_missing", 1, attrs)
    _sentry_incr("agent.snapshot.field_missing", 1, attrs)


def record_snapshot_completeness(populated: int, ticker: str) -> None:
    attrs = {"ticker": ticker}
    _hist("snapshot_completeness", populated, attrs)
    _sentry_dist("agent.snapshot.completeness", populated, attrs)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd agent && .venv/bin/python -m pytest tests/test_metrics.py -v`
Expected: PASS (new snapshot tests + all existing metrics tests).

- [ ] **Step 6: Commit**

```bash
git add agent/lib/metrics.py agent/tests/test_metrics.py
git commit -m "feat(agent): add snapshot.* metric instruments and emitters"
```

---

### Task 2: Instrument `fetch_snapshot`

**Files:**
- Modify: `agent/lib/finance.py`
- Modify: `agent/tests/test_finance.py`

**Interfaces:**
- Consumes: `metrics.record_snapshot_fetch/backfilled/field_missing/completeness` (Task 1).
- Produces: `_fetch_snapshot_once(ticker) -> tuple[Snapshot | None, bool]` (private; second element is `backfilled`).

- [ ] **Step 1: Write the failing tests**

Add to `agent/tests/test_finance.py`:

```python
def _spy_snapshot_metrics(monkeypatch):
    """Patch the four snapshot emitters on the metrics module and capture calls."""
    from lib import metrics
    calls = {"fetch": [], "backfilled": [], "field_missing": [], "completeness": []}
    monkeypatch.setattr(metrics, "record_snapshot_fetch",
                        lambda outcome, ticker, duration_ms: calls["fetch"].append((outcome, ticker)))
    monkeypatch.setattr(metrics, "record_snapshot_backfilled",
                        lambda ticker: calls["backfilled"].append(ticker))
    monkeypatch.setattr(metrics, "record_snapshot_field_missing",
                        lambda field, ticker: calls["field_missing"].append(field))
    monkeypatch.setattr(metrics, "record_snapshot_completeness",
                        lambda populated, ticker: calls["completeness"].append(populated))
    return calls


def test_fetch_snapshot_emits_success_metrics(monkeypatch):
    from lib import finance
    calls = _spy_snapshot_metrics(monkeypatch)
    fake_ticker = MagicMock()
    fake_ticker.info = dict(_HAPPY_INFO)
    with patch.object(finance, "yfinance") as yf:
        yf.Ticker.return_value = fake_ticker
        finance.fetch_snapshot("MDB")
    assert calls["fetch"] == [("success", "MDB")]
    assert calls["backfilled"] == []          # regularMarketPrice present → no fallback
    assert calls["field_missing"] == []       # _HAPPY_INFO fills all 12 key fields
    assert calls["completeness"] == [12]


def test_fetch_snapshot_emits_backfilled_on_history_fallback(monkeypatch):
    from lib import finance
    calls = _spy_snapshot_metrics(monkeypatch)
    info_without_prices = {k: v for k, v in _HAPPY_INFO.items() if not k.startswith("regularMarket")}
    fake_ticker = MagicMock()
    fake_ticker.info = info_without_prices
    history_df = MagicMock()
    history_df.empty = False
    close_col = MagicMock()
    close_col.iloc = [None, None, None, 346.44, 342.15]
    history_df.__getitem__.return_value = close_col
    fake_ticker.history.return_value = history_df
    with patch.object(finance, "yfinance") as yf:
        yf.Ticker.return_value = fake_ticker
        finance.fetch_snapshot("MDB")
    assert calls["fetch"] == [("success", "MDB")]
    assert calls["backfilled"] == ["MDB"]


def test_fetch_snapshot_emits_field_missing_and_completeness_for_partial(monkeypatch):
    from lib import finance
    calls = _spy_snapshot_metrics(monkeypatch)
    minimal_info = {"longName": "Some Co.", "sector": "Utilities", "currency": "USD"}
    fake_ticker = MagicMock()
    fake_ticker.info = minimal_info
    empty_history = MagicMock()
    empty_history.empty = True
    fake_ticker.history.return_value = empty_history
    with patch.object(finance, "yfinance") as yf:
        yf.Ticker.return_value = fake_ticker
        finance.fetch_snapshot("SOMECO")
    assert calls["fetch"] == [("success", "SOMECO")]
    # Only company_name + sector populated → 10 missing, completeness 2.
    assert set(calls["field_missing"]) == {
        "industry", "close", "previous_close", "market_cap",
        "fifty_two_week_high", "fifty_two_week_low", "average_volume",
        "analyst_recommendation", "analyst_opinion_count", "business_summary",
    }
    assert calls["completeness"] == [2]


def test_fetch_snapshot_emits_error_outcome_on_exception(monkeypatch):
    from lib import finance
    calls = _spy_snapshot_metrics(monkeypatch)
    with patch.object(finance, "yfinance") as yf:
        yf.Ticker.side_effect = RuntimeError("yahoo says no")
        assert finance.fetch_snapshot("MDB") is None
    assert calls["fetch"] == [("error", "MDB")]
    assert calls["backfilled"] == [] and calls["completeness"] == []


def test_fetch_snapshot_emits_missing_outcome_on_empty_info(monkeypatch):
    from lib import finance
    calls = _spy_snapshot_metrics(monkeypatch)
    fake_ticker = MagicMock()
    fake_ticker.info = {}
    with patch.object(finance, "yfinance") as yf:
        yf.Ticker.return_value = fake_ticker
        assert finance.fetch_snapshot("XXXX") is None
    assert calls["fetch"] == [("missing", "XXXX")]
    assert calls["completeness"] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd agent && .venv/bin/python -m pytest tests/test_finance.py -k "emits" -v`
Expected: FAIL — the spies are never called (no metric emission in `finance.py` yet).

- [ ] **Step 3: Add imports + key-field list to `finance.py`**

In `agent/lib/finance.py`, change the top imports. The current imports are:

```python
from datetime import datetime, timezone
from pydantic import BaseModel
import yfinance

from opentelemetry import trace
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .observability import emit_log
```

Add `import time` and `from . import metrics`, and a module-level key-field tuple after the imports:

```python
import time
from datetime import datetime, timezone
from pydantic import BaseModel
import yfinance

from opentelemetry import trace
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .observability import emit_log
from . import metrics

# The nullable yfinance-sourced fields used for the field-completeness metrics.
# currency/as_of are always set and change_pct is derived, so they are excluded.
_SNAPSHOT_KEY_FIELDS = (
    "company_name", "sector", "industry", "close", "previous_close", "market_cap",
    "fifty_two_week_high", "fifty_two_week_low", "average_volume",
    "analyst_recommendation", "analyst_opinion_count", "business_summary",
)
```

- [ ] **Step 4: Change `_fetch_snapshot_once` to return `(snapshot, backfilled)`**

Replace the body of `_fetch_snapshot_once` (currently returns `Snapshot | None`) with:

```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def _fetch_snapshot_once(ticker: str) -> tuple[Snapshot | None, bool]:
    t = yfinance.Ticker(ticker)
    info = t.info or {}
    if not info:
        return None, False
    snap = _snapshot_from_info(info)
    backfilled = False
    if snap.close is None or snap.previous_close is None:
        close, previous = _backfill_from_history(t)
        if snap.close is None and close is not None:
            snap = snap.model_copy(update={"close": close})
            backfilled = True
        if snap.previous_close is None and previous is not None:
            snap = snap.model_copy(update={"previous_close": previous})
            backfilled = True
        snap = snap.model_copy(update={"change_pct": _derive_change_pct(snap.close, snap.previous_close)})
    return snap, backfilled
```

(This preserves the resulting snapshot exactly: when the fallback value is also `None`, the field stays `None` as before — the only change is tracking whether the fallback actually supplied a value.)

- [ ] **Step 5: Instrument `fetch_snapshot`**

Replace `fetch_snapshot` with:

```python
def fetch_snapshot(ticker: str) -> Snapshot | None:
    """Best-effort ticker snapshot. Never raises. Returns None on total failure."""
    span = trace.get_current_span()
    start = time.monotonic()
    try:
        snap, backfilled = _fetch_snapshot_once(ticker)
    except Exception as exc:
        _annotate_span_failure(span, ticker)
        emit_log(
            "warn",
            "snapshot.missing",
            ticker=ticker,
            reason="exception",
            exception_type=type(exc).__name__,
        )
        metrics.record_snapshot_fetch("error", ticker, (time.monotonic() - start) * 1000)
        return None
    duration_ms = (time.monotonic() - start) * 1000
    if snap is None:
        _annotate_span_failure(span, ticker)
        emit_log("warn", "snapshot.missing", ticker=ticker, reason="empty_info")
        metrics.record_snapshot_fetch("missing", ticker, duration_ms)
        return None
    _annotate_span_success(span, ticker, snap)
    metrics.record_snapshot_fetch("success", ticker, duration_ms)
    if backfilled:
        metrics.record_snapshot_backfilled(ticker)
    populated = 0
    for field in _SNAPSHOT_KEY_FIELDS:
        if getattr(snap, field) is None:
            metrics.record_snapshot_field_missing(field, ticker)
        else:
            populated += 1
    metrics.record_snapshot_completeness(populated, ticker)
    return snap
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd agent && .venv/bin/python -m pytest tests/test_finance.py -v`
Expected: PASS — the new `emits` tests plus ALL existing `finance` tests (they call `fetch_snapshot`, whose public `Snapshot | None` return is unchanged).

- [ ] **Step 7: Commit**

```bash
git add agent/lib/finance.py agent/tests/test_finance.py
git commit -m "feat(agent): emit snapshot.* metrics from fetch_snapshot"
```

---

### Task 3: Docs + full-suite verification

**Files:**
- Modify: `OTEL.md`

- [ ] **Step 1: Add the snapshot metrics to `OTEL.md`**

In the metrics inventory table in `OTEL.md` (the `## Metrics` section), add these rows after the `agent.http.duration_ms` row:

```
| `agent.snapshot.fetch` | counter | agent | `outcome`, `ticker` |
| `agent.snapshot.fetch.duration_ms` | histogram | agent | `outcome`, `ticker` |
| `agent.snapshot.backfilled` | counter | agent | `ticker` |
| `agent.snapshot.field_missing` | counter | agent | `field`, `ticker` |
| `agent.snapshot.completeness` | histogram | agent | `ticker` |
```

- [ ] **Step 2: Run the full Python suite**

Run: `cd agent && .venv/bin/python -m pytest -q`
Expected: PASS (all tests; DB tests may skip without `NEON_DATABASE_URL`).

- [ ] **Step 3: Run the full Node suite (sanity — unchanged)**

Run: `npm run test`
Expected: PASS (unchanged; this plan touches no Node code).

- [ ] **Step 4: Commit**

```bash
git add OTEL.md
git commit -m "docs: document snapshot.* metrics in OTEL.md"
```

---

## Self-Review

**Spec coverage:**
- Five metrics with exact names/types/tags → Task 1 instruments + emitters; Task 3 docs. ✓
- `outcome` success/missing/error on the three branches → Task 2 Step 5. ✓
- Duration over whole call incl. retries → Task 2 `start = time.monotonic()` before `_fetch_snapshot_once` (which owns the tenacity retry). ✓
- `backfilled` via `_fetch_snapshot_once` tuple return; emission centralized in `fetch_snapshot` → Task 2 Steps 4–5. ✓
- field_missing + completeness on success only, over the 12 key fields → Task 2 Step 5 loop. ✓
- `job_id` never a tag → Task 1 `test_snapshot_metrics_never_carry_job_id`. ✓
- `ticker` on every metric → all emitters include it. ✓
- Guarded / never breaks fetch → uses the existing guarded facade; `fetch_snapshot` public contract unchanged (existing tests still pass, Task 2 Step 6). ✓
- Out of scope (traces/logs kept, no Node change) → span annotations + `emit_log` preserved in Task 2 Step 5; Task 3 Node run is sanity-only. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✓

**Type consistency:** `record_snapshot_fetch(outcome, ticker, duration_ms)`, `record_snapshot_backfilled(ticker)`, `record_snapshot_field_missing(field, ticker)`, `record_snapshot_completeness(populated, ticker)` defined in Task 1 and called with matching args in Task 2. `_fetch_snapshot_once -> tuple[Snapshot | None, bool]` defined in Task 2 Step 4 and unpacked as `snap, backfilled` in Step 5. `_SNAPSHOT_KEY_FIELDS` defined in Step 3, iterated in Step 5. ✓
