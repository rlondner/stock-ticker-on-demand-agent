# Design: Custom data toolbox (sub-project 2 of the LLM re-architecture)

**Date:** 2026-07-12
**Status:** Approved (design), pending implementation plan
**Scope:** Agent (`agent/`) only. Give the agentic thesis loop three custom,
yfinance-backed function tools it can call mid-reasoning, with per-tool
success/failure visibility in logs and traces.

## Background

Sub-project 1 built a generic Responses-API tool loop (`agent/lib/agent_loop.py`)
with a `function_registry` for custom tools — currently empty; only the hosted
`web_search` tool is wired. The model produces a cited bull/bear `Thesis`
grounded in the injected yfinance snapshot + web research.

This sub-project registers real function tools so the model can pull **precise,
on-demand structured data** (financial statements, valuation multiples, earnings
history) mid-loop instead of relying on web_search for numbers. Peers are
excluded: yfinance has no reliable comparables API (web_search covers qualitative
comparison). Per-tool count/latency **metrics** stay in sub-project 4; this
sub-project adds success/failure **visibility** (logs + trace events).

## New module `agent/lib/tools.py`

Decoupled from `agent_loop` (generic) and `llm`. Provides:

- `build_toolset() -> tuple[list[dict], dict[str, Callable[[dict], dict]]]` —
  returns the JSON tool **schemas** (for the Responses API `tools` param) and a
  **registry** (`name -> callable`) to pass into `run_agent_loop`.
- `_observed_tool(name, fn) -> Callable[[dict], dict]` — wraps a raw tool with
  uniform guarding + observability (see below). The registry holds wrapped
  callables.

Each raw tool takes `args: dict` (with a `"ticker"` string the model supplies)
and returns a compact JSON-serialisable dict, or `{"error": <reason>}` when data
is missing.

### Per-tool observability (`_observed_tool`)

For every tool call, on both success and failure:

- **Structured log** via `emit_log` — `tool.<name>.ok` (info, with `ticker` + a
  small result summary such as row/quarter counts) or `tool.<name>.failed`
  (warn, with `ticker` + `reason`). These fan out to stdout, Sentry Logs, and
  Datadog logs through the unified transport.
- **Trace event** on the current span (`trace.get_current_span()`) —
  `span.add_event("tool.<name>", {"outcome": "ok"|"error", ...})`, so each call
  is visible inline on the `llm.analyze` trace in Sentry/Datadog Trace Explorer.

`_observed_tool` treats three cases as **error** (failed log + error event +
returns `{"error": …}`): the raw fn raises, the raw fn returns a dict containing
an `"error"` key, or (defensively) any unexpected exception. Otherwise it's
**ok**. This centralises the guard so a tool can never crash the loop and every
tool is observed identically.

## The three tools (curated + compact to bound loop token cost)

All accessors verified against the installed **yfinance 1.5.1**.

1. **`get_financials(ticker)`** — from `Ticker.income_stmt` (annual): the last **3
   fiscal years** of `revenue`, `net_income`, `gross_margin_pct`,
   `operating_margin_pct`, and YoY `revenue_growth_pct`, plus the `fiscal_years`
   labels. Empty/missing statement → `{"error": "no financials"}`.
2. **`get_valuation(ticker)`** — from `Ticker.info`: `trailing_pe`, `forward_pe`,
   `price_to_sales`, `ev_to_ebitda`, `peg_ratio`, `price_to_book` (null where a
   field is absent). Empty `info` → `{"error": "no valuation data"}`.
3. **`get_earnings(ticker)`** — from `Ticker.earnings_dates` (+ `Ticker.calendar`
   for the next date): `next_earnings_date` and up to the last **4 quarters** of
   `{date, eps_estimate, eps_actual, surprise_pct}`. Empty → `{"error": "no
   earnings data"}`.

Each returns only a few years/quarters/fields so the tool output fed back into
the loop stays small.

### Tool schemas

Each schema is a Responses-API function tool:
```json
{
  "type": "function",
  "name": "get_financials",
  "description": "<one line: what it returns and when to use it>",
  "parameters": {
    "type": "object",
    "properties": { "ticker": { "type": "string", "description": "US-listed ticker symbol" } },
    "required": ["ticker"]
  }
}
```
The `description` guides the model on when to call each tool.

## Wiring (`agent/lib/llm.py`, responses path only)

Replace the responses-path `tools=[{"type": "web_search"}], function_registry={}`
with the toolset:
```python
schemas, registry = build_toolset()
loop = run_agent_loop(
    _create, messages,
    tools=[{"type": "web_search"}, *schemas],
    function_registry=registry,
    max_iters=MAX_ITERS, timeout_s=LOOP_TIMEOUT_S,
)
```
The `chat.completions` fallback stays tool-less and snapshot-only (unchanged).

## Prompt (`agent/lib/prompts.py`)

Add one line to `SYSTEM_PROMPT`: the model may call `get_financials`,
`get_valuation`, and `get_earnings` for precise structured numbers, and
`web_search` for qualitative research. (No schema/output-shape change; the
`Thesis` schema and the rest of the prompt are unchanged.)

## Grounding — unchanged, still correct

`_grounding` (llm.py) keys `"researched"` off a real `source_url`, which only
`web_search` produces. A tools-only run (e.g. `get_financials`, no web citation)
therefore correctly yields `"limited"`; no tools → `"snapshot_only"`. Custom
tools populate `tools_used` but cannot spoof `"researched"`. No change here; any
richer per-tool signal belongs to sub-project 4.

## Error handling

- `_observed_tool` guarantees no tool exception reaches the loop; a failure
  returns `{"error": …}` (the loop feeds that back to the model, which can adapt).
- Each raw tool guards its yfinance access and returns `{"error": …}` on empty
  data rather than raising.
- The agent run never fails because a tool failed — the loop and the
  always-produce-a-Thesis contract (sub-project 1) are preserved.

## Testing (TDD; yfinance mocked, no network)

- **Each raw tool:** happy path (mocked `income_stmt`/`info`/`earnings_dates` →
  curated dict with the expected keys/values); empty/missing → `{"error": …}`;
  yfinance raising → the wrapped tool returns `{"error": …}` (guarded).
- **`_observed_tool`:** an ok result emits `tool.<name>.ok` + an `outcome=ok`
  span event; a raised or `{"error"}` result emits `tool.<name>.failed` + an
  `outcome=error` span event (assert via a fake span from
  `trace.get_current_span()`, mirroring the `finance.py` span tests).
- **`build_toolset()`:** returns 3 valid function schemas (each with a `ticker`
  param) and a registry whose keys exactly match the schema names.
- **Wiring:** `analyze` (responses path) passes `web_search` + the 3 schemas and
  the registry into `run_agent_loop` — extend the existing captured-`tools`
  test.
- **Prompt:** `SYSTEM_PROMPT` names the three tools.

## Out of scope

- **Peers** (no reliable yfinance comparables source).
- **Per-tool count/latency metrics** and re-adding a `web_search.used` metric
  (sub-project 4).
- **Frontend** — the `Thesis`/`result` shape is unchanged; the tools only improve
  the thesis content, so no UI change.

## Risks

- yfinance statement/earnings DataFrame shapes vary by version; the tools are
  written against 1.5.1 and fully guarded, so a shape change degrades a tool to
  `{"error": …}` (logged + trace-evented) rather than breaking the run. The plan
  verifies exact row labels/columns against the installed version.
- More tools let the model take more loop turns → more cost/latency; bounded by
  the existing `MAX_ITERS`/timeout budgets from sub-project 1.
