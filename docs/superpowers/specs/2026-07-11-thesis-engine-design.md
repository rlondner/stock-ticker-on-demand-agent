# Design: Agentic thesis engine (sub-project 1 of the LLM re-architecture)

**Date:** 2026-07-11
**Status:** Approved (design), pending implementation plan
**Scope:** Agent (`agent/`) only. Replace the flat `Analysis` (narrated
yfinance facts) with a tool-using agentic loop that produces a **cited
bull/bear investment thesis**, using `web_search` as the first live tool.

## Background & motivation

yfinance now supplies the structured numbers (price, fundamentals, 52-week
range) and the analyst-recommendation distribution. The LLM step
(`llm.analyze`) currently just narrates those facts into a buy/hold/sell + a
few "signals" — low differentiated value, and it deliberately has **no web
access** today.

This re-architecture moves the LLM to what it's uniquely good at: qualitative,
forward-looking, multi-source synthesis with judgment. The agent becomes a
tool-using **equity research analyst** that produces a balanced, cited
**bull/bear thesis** grounded in both the yfinance snapshot (numbers) and live
web research (news, catalysts, risks).

This spec is **sub-project 1** of a decomposed effort (agreed during
brainstorming):

| # | Sub-project | This spec? |
|---|---|---|
| 1 | Thesis engine: agentic loop + tool framework + `Thesis` schema, with `web_search` as the first live tool | **YES** |
| 2 | Custom data toolbox (`get_financials`, `get_peers`, `get_earnings`, valuation calc) | later |
| 3 | Frontend rendering of the cited bull/bear/risks thesis | later |
| 4 | Agentic observability (per-tool + loop metrics; re-add web_search usage metric) | later |

Sub-project 1 deliberately reverses the earlier "no web access" decision and
shifts the agent from a single few-second call to a slower, costlier multi-turn
loop — so **iteration/time/token budgets are first-class requirements**.

## Output schema (`agent/lib/llm.py`)

Replaces `Analysis`/`Signal`:

```python
class ThesisPoint(BaseModel):
    claim: str
    evidence: str
    source_url: str | None = None   # a real web_search URL; None for claims grounded in the snapshot

class Thesis(BaseModel):
    recommendation: str = Field(pattern="^(buy|hold|sell)$")
    confidence: str = Field(pattern="^(low|medium|high)$")
    summary: str
    bull_case: list[ThesisPoint]   # 2–4 points
    bear_case: list[ThesisPoint]   # 2–4 points
    key_risks: list[ThesisPoint]   # 1–3 points
    grounding: str = Field(pattern="^(researched|limited|snapshot_only)$")
```

Point-count ranges (2–4 / 2–4 / 1–3) are requested in the prompt and treated as
soft guidance; parsing does not hard-fail on count, only on schema/type.

## Agentic loop + tool framework (`agent/lib/agent_loop.py`, new)

A small, generic ReAct-style loop over the OpenAI **Responses API**, decoupled
from the thesis specifics so sub-project 2 can register real tools:

- **Tool registry:** name → `{ "schema": <JSON tool schema>, "run": callable }`
  for custom function tools. `web_search` is a **hosted** tool (declared as
  `{"type": "web_search"}`) that the Responses API executes server-side; it is
  NOT dispatched by us.
- **Loop:** call `responses.create(model, input=conversation, tools=tools)`. If
  the response contains custom function-tool calls, run each via the registry,
  append the tool outputs to `conversation`, and iterate. Stop when the model
  returns a final message (parsed as the `Thesis` JSON) or when a budget cap is
  hit.
- **Budgets (first-class):** `MAX_ITERS` (default 6) and an overall wall-clock
  timeout (default 90s). On reaching either, the loop makes one final
  no-tools request for the thesis (or parses the best output it has) — it never
  loops unbounded. The existing per-call tenacity retry (RateLimit/5xx/empty)
  is preserved for transient API errors.
- **Sub-project-1 tools:** only `web_search` is wired live. The custom-tool
  dispatch path is fully built and unit-tested with a **fake tool**; no real
  custom tools are registered yet (that's sub-project 2).

## Grounding & robustness (decision: always produce, flag grounding)

- `grounding = "researched"` when web_search ran and at least one real
  `source_url` is present; `"limited"` when tools ran but yielded little/no
  citable evidence; `"snapshot_only"` when no tools ran.
- **Non-Responses-API endpoints** (`OPENAI_USE_RESPONSES_API=false`, e.g.
  Ollama/vLLM): fall back to a tool-less `chat.completions` call that produces a
  snapshot-only thesis with `grounding="snapshot_only"`.
- A job is **never failed** for research limits — the engine always returns a
  valid `Thesis`. (Genuine API errors after retries still fail the job, as
  today.)

## Wiring

- `run_analysis(ticker)`: `snapshot = fetch_snapshot(ticker)`;
  `thesis = run_thesis(ticker, snapshot)`; returns
  `{ **thesis.model_dump(), "snapshot": snapshot.model_dump() if snapshot else None }`.
- `agent.py` still calls `mark_complete(recommendation=result["recommendation"], result=result)`
  — `recommendation` now comes from the thesis. No `agent.py` change needed.
- **Prompt** (`agent/lib/prompts.py`): a new system prompt casting the model as
  an equity research analyst — snapshot facts are ground truth for numbers; use
  `web_search` for recent news/catalysts/risks; produce a balanced bull/bear
  thesis + key risks; every qualitative claim must cite a real `source_url`;
  numeric claims grounded in the snapshot use `source_url: null`; output JSON
  only. `user_prompt` continues to inject the snapshot facts (unchanged format).

## Known interim transition (accepted)

This drops `result.signals` in favor of the thesis fields. Consequences until
sub-project 3 (frontend) lands:

- `StockHeader` (reads `recommendation` + `summary`) — **unaffected**.
- `RawLLMResponse` (dumps the whole `result`) — shows the full thesis JSON.
- `KeyInsights` (reads `result.signals`) — **renders empty** until sub-project 3
  repurposes it for bull/bear/risks.

Recommendation: sequence the frontend sub-project (3) immediately after this one
to close the gap.

## Observability (minimal here)

Keep the existing `llm.analyze` span and `record_llm_duration`/`record_llm_call`
metrics (duration measured over the whole loop). Add span attributes
`iterations`, `tools_used` (list/count), and `grounding`. Rich per-tool and
per-loop metrics — and re-adding a `web_search.used` metric — are **sub-project
4**, out of scope here.

## Error handling

- Every tool `run` is guarded; a tool failure returns an error payload to the
  model (so it can adapt), never crashes the loop.
- Budget/timeout → finalize a thesis, never raise for that reason.
- JSON parse of the final message reuses the existing fence-stripping +
  `pydantic` validation pattern (`parse_response`, generalized to `Thesis`).
- The engine returns a valid `Thesis` on every non-API-error path.

## Testing (TDD; OpenAI SDK mocked, no network)

- `Thesis`/`ThesisPoint` parse + validation (valid JSON → model; bad
  recommendation/confidence/grounding enum → error; markdown-fenced JSON
  stripped).
- Loop with a fake OpenAI client:
  - web_search path: a single `responses.create` returning valid thesis JSON →
    parsed, `grounding="researched"`.
  - **custom-tool dispatch:** a fake response emitting a function-tool call →
    the registry `run` is invoked → its output is appended → the next response
    returns the final thesis (proves the framework end-to-end).
  - budget cap: a fake client that keeps emitting tool calls → the loop stops at
    `MAX_ITERS` and still returns a valid thesis.
  - fallback: `OPENAI_USE_RESPONSES_API=false` → `chat.completions` path →
    thesis with `grounding="snapshot_only"`.
- Existing `llm`/`agent`/`prompts` tests updated for the `Analysis`→`Thesis`
  change where they assert the old shape.

## Out of scope (later sub-projects)

- Custom data tools and their implementations (sub-project 2).
- Frontend rendering of the thesis (sub-project 3).
- Per-tool / loop metrics and the `web_search.used` metric (sub-project 4).
- Structured-output (`json_schema` response_format) enforcement — prompt +
  parse is sufficient for now; can harden later.

## Risks

- **Cost & latency:** multi-turn + web_search is materially slower and costlier
  than one call. Mitigated by `MAX_ITERS`/timeout budgets and the fact that the
  agent already runs async in a self-deleting sandbox.
- **Citation fidelity:** we cannot fully verify that a cited `source_url` is
  real/relevant; web_search returns real results the model cites, but the model
  could still fabricate a URL. Accepted limitation for sub-project 1; a
  URL-sanity check can be added later.
- **Responses-API dependency:** the researched path requires the Responses API
  + hosted web_search; the `chat.completions` fallback keeps non-OpenAI
  endpoints working (snapshot-only).
