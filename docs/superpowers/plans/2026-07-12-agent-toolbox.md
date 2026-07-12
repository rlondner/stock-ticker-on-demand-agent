# Custom Data Toolbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Register three yfinance-backed function tools (`get_financials`, `get_valuation`, `get_earnings`) into the agentic thesis loop, each with per-call ok/failed logs + a trace span event.

**Architecture:** A new `agent/lib/tools.py` holds the raw tools + a `_observed_tool` wrapper (uniform guard + observability) + `build_toolset()` returning `(schemas, registry)` that drops into `run_agent_loop`. `llm.py` passes `web_search` + the schemas + the registry.

**Tech Stack:** Python, yfinance 1.5.1, OpenTelemetry, OpenAI Responses API. Tests: pytest with yfinance mocked (no network).

## Global Constraints

- `tools.py` imports only `yfinance`, `opentelemetry.trace`, and `.observability.emit_log` — NO import of `agent_loop` or `llm` (decoupled).
- Every tool goes through `_observed_tool(name, fn)`: it emits `tool.<name>.ok` (info) / `tool.<name>.failed` (warn) via `emit_log`, adds a span event `tool.<name>` with `{"outcome": "ok"|"error"}` (+ `error` on failure) to `trace.get_current_span()`, and NEVER lets an exception reach the loop (a failure returns `{"error": <reason>}`). A raw fn that returns a dict containing an `"error"` key is treated as a failure too.
- Each raw tool takes `args: dict` with a `"ticker"` and returns a compact dict or `{"error": <reason>}`; never raises for missing data.
- Curated output sizes: financials = last 3 fiscal years; earnings = up to 4 recent quarters.
- `get_financials` keys: `fiscal_years, revenue, net_income, gross_margin_pct, operating_margin_pct, revenue_growth_pct`. `get_valuation` keys: `trailing_pe, forward_pe, price_to_sales, ev_to_ebitda, peg_ratio, price_to_book`. `get_earnings` keys: `next_earnings_date, recent_quarters` (each quarter `{date, eps_estimate, eps_actual, surprise_pct}`).
- `build_toolset()` returns exactly 3 function schemas (names `get_financials`/`get_valuation`/`get_earnings`, each with a `ticker` string param) and a registry whose keys equal the schema names.
- Wiring: responses path passes `tools=[{"type":"web_search"}, *schemas]` + `function_registry=registry`; `chat.completions` fallback unchanged.
- Grounding logic (`_grounding` in llm.py) is NOT changed.
- Agent tests use the venv: `agent/.venv/bin/python -m pytest ...` (system `pip` unavailable).

---

### Task 1: `_observed_tool` wrapper (`agent/lib/tools.py`)

**Files:**
- Create: `agent/lib/tools.py`
- Create: `agent/tests/test_tools.py`

**Interfaces:**
- Produces: `_observed_tool(name: str, fn: Callable[[dict], dict]) -> Callable[[dict], dict]`.

- [ ] **Step 1: Write the failing tests**

Create `agent/tests/test_tools.py`:

```python
from unittest.mock import MagicMock, patch
import lib.tools as tools


def _spy(monkeypatch):
    logs = []
    monkeypatch.setattr(tools, "emit_log",
                        lambda level, msg, **kw: logs.append((level, msg, kw)))
    span = MagicMock()
    monkeypatch.setattr(tools.trace, "get_current_span", lambda: span)
    return logs, span


def test_observed_tool_ok(monkeypatch):
    logs, span = _spy(monkeypatch)
    run = tools._observed_tool("get_x", lambda args: {"value": args["ticker"]})
    out = run({"ticker": "AAPL"})
    assert out == {"value": "AAPL"}
    assert ("info", "tool.get_x.ok", {"ticker": "AAPL"}) in logs
    span.add_event.assert_any_call("tool.get_x", {"outcome": "ok"})


def test_observed_tool_swallows_exception(monkeypatch):
    logs, span = _spy(monkeypatch)
    def boom(args):
        raise RuntimeError("nope")
    run = tools._observed_tool("get_x", boom)
    out = run({"ticker": "AAPL"})
    assert "error" in out and "nope" in out["error"]
    assert any(m == "tool.get_x.failed" and lvl == "warn" for lvl, m, _ in logs)
    ev = span.add_event.call_args_list[-1]
    assert ev.args[0] == "tool.get_x" and ev.args[1]["outcome"] == "error"


def test_observed_tool_treats_error_dict_as_failure(monkeypatch):
    logs, span = _spy(monkeypatch)
    run = tools._observed_tool("get_x", lambda args: {"error": "no data"})
    out = run({"ticker": "AAPL"})
    assert out == {"error": "no data"}
    assert any(m == "tool.get_x.failed" for _, m, _ in logs)
    span.add_event.assert_any_call("tool.get_x", {"outcome": "error", "error": "no data"})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd agent && .venv/bin/python -m pytest tests/test_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.tools'`.

- [ ] **Step 3: Implement the module header + `_observed_tool`**

Create `agent/lib/tools.py`:

```python
"""Custom function tools the agentic thesis loop can call for precise, on-demand
structured data (yfinance-backed). Decoupled from agent_loop and llm. Every tool
is wrapped by _observed_tool so it can never crash the loop and every call is
visible in logs + on the current trace span."""
import yfinance
from opentelemetry import trace

from .observability import emit_log


def _observed_tool(name, fn):
    """Wrap a raw tool(args)->dict with uniform guarding + observability.
    Emits tool.<name>.ok / .failed logs and an outcome span event on every call.
    A raised exception OR a returned {'error': ...} counts as a failure; a tool
    can never crash the loop (a failure returns {'error': ...})."""
    def _run(args):
        args = args or {}
        ticker = args.get("ticker")
        span = trace.get_current_span()
        try:
            result = fn(args)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            emit_log("warn", f"tool.{name}.failed", ticker=ticker, reason=reason)
            span.add_event(f"tool.{name}", {"outcome": "error", "error": reason})
            return {"error": reason}
        if isinstance(result, dict) and "error" in result:
            emit_log("warn", f"tool.{name}.failed", ticker=ticker, reason=str(result["error"]))
            span.add_event(f"tool.{name}", {"outcome": "error", "error": str(result["error"])})
            return result
        emit_log("info", f"tool.{name}.ok", ticker=ticker)
        span.add_event(f"tool.{name}", {"outcome": "ok"})
        return result

    return _run
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd agent && .venv/bin/python -m pytest tests/test_tools.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add agent/lib/tools.py agent/tests/test_tools.py
git commit -m "feat(agent): add _observed_tool wrapper (guard + ok/failed logs + span events)"
```

---

### Task 2: The three tools + `build_toolset` (`agent/lib/tools.py`)

**Files:**
- Modify: `agent/lib/tools.py`
- Modify: `agent/tests/test_tools.py`

**Interfaces:**
- Consumes: `_observed_tool` (Task 1).
- Produces: `build_toolset() -> tuple[list[dict], dict[str, Callable[[dict], dict]]]`; raw `_get_financials`/`_get_valuation`/`_get_earnings(args) -> dict`.

- [ ] **Step 1: Write the failing tests**

Add to `agent/tests/test_tools.py`:

```python
def _fake_ticker(**attrs):
    t = MagicMock()
    for k, v in attrs.items():
        setattr(t, k, v)
    return t


def _frame(empty=False, to_dict=None, records=None):
    df = MagicMock()
    df.empty = empty
    if to_dict is not None:
        df.to_dict.return_value = to_dict
    if records is not None:
        df.reset_index.return_value.to_dict.return_value = records
    return df


def test_get_financials_curates_three_years():
    income = _frame(to_dict={
        "2025-12-31": {"Total Revenue": 1000, "Net Income": 100, "Gross Profit": 600, "Operating Income": 200},
        "2024-12-31": {"Total Revenue": 900, "Net Income": 80, "Gross Profit": 520, "Operating Income": 150},
    })
    with patch.object(tools, "yfinance") as yf:
        yf.Ticker.return_value = _fake_ticker(income_stmt=income)
        out = tools._get_financials({"ticker": "MDB"})
    assert out["fiscal_years"] == ["2025", "2024"]
    assert out["revenue"] == [1000.0, 900.0]
    assert out["gross_margin_pct"] == [60.0, round(520 / 900 * 100, 1)]
    # YoY growth for the most-recent year vs the prior: (1000-900)/900*100
    assert out["revenue_growth_pct"][0] == round((1000 - 900) / 900 * 100, 1)


def test_get_financials_empty_returns_error():
    with patch.object(tools, "yfinance") as yf:
        yf.Ticker.return_value = _fake_ticker(income_stmt=_frame(empty=True))
        assert tools._get_financials({"ticker": "X"}) == {"error": "no financials"}


def test_get_valuation_maps_info_fields():
    info = {
        "trailingPE": 30.1, "forwardPE": 25.0, "priceToSalesTrailing12Months": 12.4,
        "enterpriseToEbitda": 40.0, "trailingPegRatio": 1.8, "priceToBook": 15.0,
    }
    with patch.object(tools, "yfinance") as yf:
        yf.Ticker.return_value = _fake_ticker(info=info)
        out = tools._get_valuation({"ticker": "MDB"})
    assert out == {
        "trailing_pe": 30.1, "forward_pe": 25.0, "price_to_sales": 12.4,
        "ev_to_ebitda": 40.0, "peg_ratio": 1.8, "price_to_book": 15.0,
    }


def test_get_valuation_all_missing_returns_error():
    with patch.object(tools, "yfinance") as yf:
        yf.Ticker.return_value = _fake_ticker(info={"foo": "bar"})
        assert tools._get_valuation({"ticker": "X"}) == {"error": "no valuation data"}


def test_get_earnings_next_date_and_recent_quarters():
    records = [
        {"Earnings Date": "2026-04-30", "EPS Estimate": 1.5, "Reported EPS": None, "Surprise(%)": None},
        {"Earnings Date": "2026-01-30", "EPS Estimate": 1.2, "Reported EPS": 1.3, "Surprise(%)": 8.3},
        {"Earnings Date": "2025-10-30", "EPS Estimate": 1.0, "Reported EPS": 0.9, "Surprise(%)": -10.0},
    ]
    with patch.object(tools, "yfinance") as yf:
        yf.Ticker.return_value = _fake_ticker(earnings_dates=_frame(records=records))
        out = tools._get_earnings({"ticker": "MDB"})
    assert out["next_earnings_date"] == "2026-04-30"
    assert out["recent_quarters"][0] == {
        "date": "2026-01-30", "eps_estimate": 1.2, "eps_actual": 1.3, "surprise_pct": 8.3,
    }
    assert len(out["recent_quarters"]) == 2


def test_build_toolset_returns_schemas_and_matching_registry():
    schemas, registry = tools.build_toolset()
    names = [s["name"] for s in schemas]
    assert names == ["get_financials", "get_valuation", "get_earnings"]
    for s in schemas:
        assert s["type"] == "function"
        assert s["parameters"]["properties"]["ticker"]["type"] == "string"
        assert s["parameters"]["required"] == ["ticker"]
    assert set(registry.keys()) == set(names)
    assert all(callable(fn) for fn in registry.values())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd agent && .venv/bin/python -m pytest tests/test_tools.py -k "financials or valuation or earnings or build_toolset" -v`
Expected: FAIL — `AttributeError: module 'lib.tools' has no attribute '_get_financials'` etc.

- [ ] **Step 3: Add the numeric helper + the three raw tools**

Append to `agent/lib/tools.py`:

```python
_FINANCIAL_YEARS = 3
_EARNINGS_QUARTERS = 4


def _num(v):
    """Coerce to float, or None if missing/NaN."""
    try:
        f = float(v)
        return None if f != f else f  # NaN
    except (TypeError, ValueError):
        return None


def _get_financials(args):
    df = yfinance.Ticker(args.get("ticker")).income_stmt
    if df is None or getattr(df, "empty", True):
        return {"error": "no financials"}
    data = df.to_dict()  # {period: {line_item: value}}
    cols = list(data.keys())[:_FINANCIAL_YEARS]
    if not cols:
        return {"error": "no financials"}
    fiscal_years, revenue, net_income, gross_margin, op_margin = [], [], [], [], []
    for col in cols:
        row = data[col]
        rev = _num(row.get("Total Revenue"))
        gp = _num(row.get("Gross Profit"))
        oi = _num(row.get("Operating Income"))
        fiscal_years.append(str(col)[:4])
        revenue.append(rev)
        net_income.append(_num(row.get("Net Income")))
        gross_margin.append(round(gp / rev * 100, 1) if rev and gp is not None else None)
        op_margin.append(round(oi / rev * 100, 1) if rev and oi is not None else None)
    growth = []
    for i in range(len(revenue)):
        prev = revenue[i + 1] if i + 1 < len(revenue) else None
        cur = revenue[i]
        growth.append(round((cur - prev) / prev * 100, 1) if (prev and cur is not None) else None)
    return {
        "fiscal_years": fiscal_years,
        "revenue": revenue,
        "net_income": net_income,
        "gross_margin_pct": gross_margin,
        "operating_margin_pct": op_margin,
        "revenue_growth_pct": growth,
    }


def _get_valuation(args):
    info = yfinance.Ticker(args.get("ticker")).info or {}
    if not info:
        return {"error": "no valuation data"}
    out = {
        "trailing_pe": _num(info.get("trailingPE")),
        "forward_pe": _num(info.get("forwardPE")),
        "price_to_sales": _num(info.get("priceToSalesTrailing12Months")),
        "ev_to_ebitda": _num(info.get("enterpriseToEbitda")),
        "peg_ratio": _num(info.get("trailingPegRatio")) if info.get("trailingPegRatio") is not None else _num(info.get("pegRatio")),
        "price_to_book": _num(info.get("priceToBook")),
    }
    if all(v is None for v in out.values()):
        return {"error": "no valuation data"}
    return out


def _earnings_date(rec):
    for k in ("Earnings Date", "index", "Date"):
        if k in rec:
            return str(rec[k])[:10]
    return None


def _get_earnings(args):
    df = yfinance.Ticker(args.get("ticker")).earnings_dates
    if df is None or getattr(df, "empty", True):
        return {"error": "no earnings data"}
    records = df.reset_index().to_dict("records")
    next_date, recent = None, []
    for rec in records:
        actual = _num(rec.get("Reported EPS"))
        if actual is None:
            if next_date is None:
                next_date = _earnings_date(rec)
        elif len(recent) < _EARNINGS_QUARTERS:
            recent.append({
                "date": _earnings_date(rec),
                "eps_estimate": _num(rec.get("EPS Estimate")),
                "eps_actual": actual,
                "surprise_pct": _num(rec.get("Surprise(%)")),
            })
    if not recent and next_date is None:
        return {"error": "no earnings data"}
    return {"next_earnings_date": next_date, "recent_quarters": recent}
```

- [ ] **Step 4: Add the schemas + `build_toolset`**

Append to `agent/lib/tools.py`:

```python
def _schema(name, description):
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": {"ticker": {"type": "string", "description": "US-listed ticker symbol"}},
            "required": ["ticker"],
        },
    }


_TOOLS = (
    ("get_financials", _get_financials,
     "Last 3 fiscal years of revenue, net income, gross/operating margins, and YoY revenue growth for a ticker."),
    ("get_valuation", _get_valuation,
     "Valuation multiples (trailing/forward P/E, P/S, EV/EBITDA, PEG, P/B) for a ticker."),
    ("get_earnings", _get_earnings,
     "Next scheduled earnings date and recent quarterly EPS estimate vs actual (surprise %) for a ticker."),
)


def build_toolset():
    """Return (schemas, registry) to drop into run_agent_loop: the Responses-API
    function-tool schemas and a name->callable registry of observed tools."""
    schemas = [_schema(name, desc) for name, _fn, desc in _TOOLS]
    registry = {name: _observed_tool(name, fn) for name, fn, _desc in _TOOLS}
    return schemas, registry
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd agent && .venv/bin/python -m pytest tests/test_tools.py -v`
Expected: PASS (all tool + build_toolset tests + the Task 1 wrapper tests).

- [ ] **Step 6: Commit**

```bash
git add agent/lib/tools.py agent/tests/test_tools.py
git commit -m "feat(agent): add get_financials/get_valuation/get_earnings tools + build_toolset"
```

---

### Task 3: Wire the toolset into `analyze` + prompt + verification

**Files:**
- Modify: `agent/lib/llm.py`
- Modify: `agent/lib/prompts.py`
- Modify: `agent/tests/test_llm.py`
- Modify: `agent/tests/test_prompts.py`

**Interfaces:**
- Consumes: `build_toolset` (Task 2).

- [ ] **Step 1: Write the failing tests**

Add to `agent/tests/test_llm.py` (reuses the `_THESIS_JSON` fixture already in the file):

```python
def test_analyze_passes_data_tools_and_web_search(monkeypatch):
    import importlib, lib.metrics as mtr, lib.llm as llm
    importlib.reload(mtr)
    monkeypatch.setattr(mtr, "record_llm_tokens", lambda *a, **k: None)
    monkeypatch.setattr(mtr, "record_llm_call", lambda *a, **k: None)
    importlib.reload(llm)

    from types import SimpleNamespace
    captured = {}

    class _WS:
        def create(self, **kw):
            captured["tools"] = kw.get("tools")
            return SimpleNamespace(output=[], output_text=_THESIS_JSON,
                                   usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    client = llm.OpenAIClient.__new__(llm.OpenAIClient)
    client._client = SimpleNamespace(responses=_WS())
    client._model = "gpt-4.1-mini"
    client._use_responses_api = True
    client.analyze("AAPL")

    tools = captured["tools"] or []
    assert {"type": "web_search"} in tools
    names = {t.get("name") for t in tools if isinstance(t, dict)}
    assert {"get_financials", "get_valuation", "get_earnings"} <= names
```

Add to `agent/tests/test_prompts.py`:

```python
def test_system_prompt_names_the_data_tools():
    for name in ("get_financials", "get_valuation", "get_earnings"):
        assert name in SYSTEM_PROMPT
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd agent && .venv/bin/python -m pytest tests/test_llm.py::test_analyze_passes_data_tools_and_web_search tests/test_prompts.py::test_system_prompt_names_the_data_tools -v`
Expected: FAIL — only `web_search` is passed (no function schemas); the prompt doesn't name the tools.

- [ ] **Step 3: Wire `build_toolset` into `analyze`**

In `agent/lib/llm.py`, add to the imports (next to `from .agent_loop import run_agent_loop`):

```python
from .tools import build_toolset
```

In `analyze` (responses path), replace the `run_agent_loop(...)` call:

```python
                    loop = run_agent_loop(
                        _create, messages, tools=[{"type": "web_search"}],
                        function_registry={}, max_iters=MAX_ITERS, timeout_s=LOOP_TIMEOUT_S,
                    )
```

with:

```python
                    _schemas, _registry = build_toolset()
                    loop = run_agent_loop(
                        _create, messages, tools=[{"type": "web_search"}, *_schemas],
                        function_registry=_registry, max_iters=MAX_ITERS, timeout_s=LOOP_TIMEOUT_S,
                    )
```

- [ ] **Step 4: Name the tools in the prompt**

In `agent/lib/prompts.py`, in `SYSTEM_PROMPT`, add this sentence to the paragraph that already mentions `web_search` (right after the web_search sentence, before the "Output ONLY a JSON object" line):

```
You may also call the tools get_financials, get_valuation, and get_earnings to
pull precise structured numbers for a ticker; use web_search for qualitative
research (news, catalysts, management commentary).
```

- [ ] **Step 5: Run the targeted + full agent suite**

Run: `cd agent && .venv/bin/python -m pytest tests/test_llm.py tests/test_prompts.py tests/test_tools.py -v`
Expected: PASS (new wiring/prompt tests + all existing).

Run: `cd agent && .venv/bin/python -m pytest -q`
Expected: PASS (full agent suite; DB tests skip without `NEON_DATABASE_URL`).

- [ ] **Step 6: Commit**

```bash
git add agent/lib/llm.py agent/lib/prompts.py agent/tests/test_llm.py agent/tests/test_prompts.py
git commit -m "feat(agent): wire the data toolbox into the thesis loop + prompt"
```

---

## Self-Review

**Spec coverage:**
- `tools.py` decoupled (only yfinance/trace/emit_log imports) → Task 1 Step 3 header. ✓
- `_observed_tool` guard + ok/failed logs + span events; exception AND `{"error"}` → failure → Task 1. ✓
- Three tools with the exact output keys, curated sizes (3 years / 4 quarters), `{"error"}` on empty → Task 2 Step 3. ✓
- `build_toolset()` → 3 function schemas (ticker param) + matching registry → Task 2 Step 4 + test. ✓
- Wiring: `tools=[web_search, *schemas]` + `function_registry=registry`; fallback unchanged → Task 3 Step 3. ✓
- Prompt names the three tools → Task 3 Step 4. ✓
- Grounding NOT changed → not touched in any task. ✓
- Per-tool visibility (logs + trace events) → Task 1 (the mechanism) applied to all tools via `build_toolset` (Task 2). ✓
- Out of scope (peers, metrics, frontend) → not in any task. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; schema `description`s are concrete strings. ✓

**Type consistency:** `_observed_tool(name, fn) -> callable` defined Task 1, used by `build_toolset` (Task 2). `build_toolset() -> (schemas, registry)` defined Task 2, consumed in Task 3 Step 3 with matching unpacking (`_schemas, _registry`). Raw tool names (`_get_financials`/`_get_valuation`/`_get_earnings`) and the schema/registry names (`get_financials`/`get_valuation`/`get_earnings`) are consistent between Task 2's `_TOOLS` table, its tests, and Task 3's wiring/prompt assertions. Output-dict keys match between the tool code and the Task 2 tests. ✓
