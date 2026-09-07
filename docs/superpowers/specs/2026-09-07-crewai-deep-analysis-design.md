# CrewAI Deep-Analysis Tier — Design

**Date:** 2026-09-07
**Status:** approved, pending implementation plan

## 1. Motivation

The current agent produces a single-shot thesis via one OpenAI Responses-API call
(`agent/lib/llm.py:OpenAIClient.analyze`), with three custom yfinance tools
(`agent/lib/tools.py`) and the hosted `web_search` tool. The README explicitly lists
"multi-step agent loops (planner → researcher → analyst)" as out of scope.

This design adds a second, richer analysis path built on CrewAI, You.com's
Search/News APIs, and Daytona code-execution — wired to the existing (currently
inert) `DepthSelector` UI — without touching or regressing the existing fast/cheap
single-call path.

## 2. Scope

**In scope:**
- A 4-agent CrewAI crew (Researcher, Fundamentals Analyst, Risk Analyst, Portfolio
  Manager) that produces a richer thesis for the `deep` and `full` depth tiers.
- You.com Search/News API tools for the Researcher and Risk Analyst.
- A Daytona code-execution tool for the Fundamentals Analyst to compute custom
  ratios/derived metrics beyond what `get_financials`/`get_valuation` return.
- Wiring the existing `DepthSelector` component through `submitAnalysis` → `/api/jobs`
  → the Daytona sandbox env → `agent.py`'s dispatch.
- A `depth` column on the `jobs` table and an extended (superset) result schema.
- Env-driven timeout/auto-delete budgets per depth tier.

**Out of scope (future work):**
- One (withone.ai) auth/notifications integration — separate spec.
- A distinct code path for `full` beyond larger per-agent time budgets (it reuses the
  same crew as `deep` in this iteration).
- Streaming intermediate agent output to the UI as the crew runs.
- Per-agent LLM model overrides (all four agents share one `LLM` instance/model).

## 3. Architecture & data flow

```
LaunchForm (depth: quick|deep|full)
   │
   ▼
POST /api/jobs { ticker, depth }
   │  insert jobs row (depth column, default 'quick')
   ▼
spawnAnalysisSandbox(jobId, depth, span)
   │  env: DEPTH=<depth>, ...existing vars, YOUDOTCOM_API_KEY (forwarded)
   │  autoDeleteInterval scaled by depth (env-driven, see §6)
   ▼
agent.py main()
   │  if DEPTH in (deep, full): run_crew_analysis(ticker)   ← NEW (agent/lib/crew.py)
   │  else:                     run_analysis(ticker)         ← unchanged (quick)
   ▼
mark_complete(job_id, recommendation, result)   ← same DB write path, richer result JSON
   ▼
self_delete()
   ▼
Browser polls /api/status/[id] → same UI, investment-thesis.tsx renders new optional sections
```

`run_crew_analysis(ticker)` is a new sibling module to `agent/lib/llm.py`, not a
modification of `agent_loop.py`/`llm.py`. `run_analysis` (quick tier) is untouched.
`agent.py` gains only a 3-line branch on `DEPTH`.

## 4. Schema & API changes

### DB migration (`db/migrations/0002_add_depth.sql`)

```sql
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS depth TEXT NOT NULL DEFAULT 'quick'
  CHECK (depth IN ('quick','deep','full'));
```

Mirrored in `lib/db/schema.ts`:
- `depth: text("depth").notNull().default("quick")` on the `jobs` table.
- `export type Depth = "quick" | "deep" | "full";`

### API (`app/api/jobs/route.ts`)

- `Body` (zod) extended: `depth: z.enum(["quick","deep","full"]).default("quick")`.
- `db.insert(jobs).values({ ticker, depth })`.
- `spawnAgent(jobId, depth, span)` → `spawnAnalysisSandbox` sets `DEPTH` in the sandbox
  env and computes `autoDeleteInterval` from the env-driven map (§6).

### Frontend wiring

- `DepthSelector` (`components/analyze/depth-selector.tsx`) becomes a controlled
  component: `value`/`onChange` props instead of local `useState`, lifted into
  `LaunchForm`.
- `SubmitParams`/`submitAnalysis` (`lib/analyze/submit-analysis.ts`) gain a `depth`
  field, included in the `/api/jobs` POST body.
- `SerializedJob` (`lib/job/types.ts`) gains `depth: Depth` and the new optional
  result fields below.

### Result schema extension

Same `ThesisPoint[]` shape as `bull_case`/`bear_case`/`key_risks`, added as new
**optional** fields on both `SerializedJob.result` (TS) and `Thesis` (`agent/lib/llm.py`,
pydantic):

```ts
researcher_findings?: ThesisPoint[];
fundamentals_analysis?: ThesisPoint[];
risk_analysis?: ThesisPoint[];
```

Populated only when `depth !== "quick"`. Absent/undefined for quick-tier jobs and for
all pre-existing rows — no backfill needed since `result` is `jsonb` and the frontend
treats a missing key as "don't render this section." `investment-thesis.tsx` renders
these with one generic sub-component reused for `bull_case`/`bear_case`/`key_risks`
and the three new sections, differing only in heading/icon.

## 5. Crew composition & tools (`agent/lib/crew.py`)

**Process:** sequential — Researcher → Fundamentals Analyst → Risk Analyst →
Portfolio Manager. Each task's output feeds the next as context; the PM's task is
last and produces the final synthesis. Sequential (not hierarchical) because the
pipeline is fixed — no need for a manager LLM to dynamically delegate — which keeps
cost, latency, and debugging surface down for a hackathon build.

| Agent | Role | Tools | Output field |
|---|---|---|---|
| Researcher | Recent news, catalysts, management commentary | `youdotcom_search`, `youdotcom_news` | `researcher_findings: ThesisPoint[]` |
| Fundamentals Analyst | Quantitative analysis | `get_financials`, `get_valuation`, `get_earnings` (reused from `tools.py`, bound to ticker) + `run_python_snippet` (Daytona code-exec) | `fundamentals_analysis: ThesisPoint[]` |
| Risk Analyst | Downside catalysts, competitive/regulatory risk | `youdotcom_search`, `youdotcom_news`, `get_earnings` | `risk_analysis: ThesisPoint[]` |
| Portfolio Manager | Synthesizes everything into the final call | none — reasons over prior agents' outputs + snapshot facts | `recommendation`, `confidence`, `summary`, `bull_case`, `bear_case`, `key_risks` |

All tasks' combined outputs assemble into one dict matching the extended `Thesis`
model, validated the same way `parse_thesis` validates today's single-call output.
Each agent's system prompt requires the same `{"claim","evidence","source_url"}`
shape used today — same discipline, just per-section.

### You.com tool (`agent/lib/youdotcom.py`)

Two thin functions, `search` and `news`, calling You.com's Search/News APIs with
`YOUDOTCOM_API_KEY` (local `.env` only — never committed, never logged). Wrapped in
the same `_observed_tool`-style pattern as `tools.py` (never raises; a failure
becomes `{"error": ...}`; uniform `tool.<name>.ok/.failed` logs + span events) so the
crew's tools get identical observability guarantees to the existing ones.

### Daytona code-exec tool (`run_python_snippet`)

Uses the Daytona Python SDK (the sandbox already has `DAYTONA_API_KEY` forwarded for
`self_delete`) to run a short pandas/python snippet against the *same* sandbox the
agent is already running in (via Daytona's code-execution API, not a nested
sandbox) — e.g. deriving a custom ratio or a simple DCF from the numbers
`get_financials`/`get_valuation` already returned. Same `_observed_tool` wrapping: a
failing or timing-out snippet returns `{"error": ...}`, never crashes the crew.

### LLM configuration

CrewAI's `LLM` class (wraps litellm) reads `OPENAI_API_KEY`/`OPENAI_MODEL`/
`OPENAI_API_URL` the same way `OpenAIClient` does today, preserving the
"point at any OpenAI-compatible endpoint" story for the crew path. One shared `LLM`
instance across all four agents — no per-agent model overrides.

## 6. Timeouts, error handling, observability

### Timeouts (env-driven)

NextJS side (`.env.example`, read in `lib/daytona.ts`), replacing the current
hardcoded `autoDeleteInterval=600`:

```
DAYTONA_AUTO_DELETE_QUICK_S=600
DAYTONA_AUTO_DELETE_DEEP_S=900
DAYTONA_AUTO_DELETE_FULL_S=1500
```

Agent side (`.env.example`, read in `agent/lib/crew.py`, same
`os.environ.get(..., default)` style as `AGENT_MAX_ITERS`/`AGENT_LOOP_TIMEOUT_S`):

```
CREW_MAX_EXECUTION_S_DEEP=780
CREW_MAX_EXECUTION_S_FULL=1380
```

**Invariant:** `CREW_MAX_EXECUTION_S_<TIER>` must stay comfortably under
`DAYTONA_AUTO_DELETE_<TIER>_S` so the crew finishes and writes its result before the
sandbox's auto-delete fires. `run_crew_analysis` divides the per-tier total across
the four agents' `max_execution_time`. If a per-agent budget is exhausted, that
agent returns its best-effort partial output (empty `findings` list at worst)
rather than blocking the pipeline — same philosophy as `run_agent_loop`'s existing
"budget exhausted → force a final answer," applied per-agent instead of per-loop.
(Exact CrewAI API surface for `max_execution_time` is verified during
implementation — version-dependent detail, not a design risk.)

### Error handling

`run_crew_analysis(ticker)` matches `run_analysis(ticker)`'s contract exactly: same
return shape, raises on total failure. `agent.py`'s existing `try/except` →
`mark_failed(job_id, error=...)` handles crew failures identically to today's
failures with no changes to that path — only the `DEPTH` dispatch is new. Any
individual tool failure (You.com, Daytona code-exec, yfinance) is swallowed by
`_observed_tool` and fed back to that agent as `{"error": ...}`.

### Observability

One parent span per crew run (`crew.run`, analogous to `llm.analyze`), with one
child span per agent (`crew.agent.researcher`, `crew.agent.fundamentals`,
`crew.agent.risk`, `crew.agent.pm`), each carrying `tools_used`, `tokens_in/out`
attributes — same pattern as `llm.analyze` today, times four. `metrics.py` gains
`record_crew_run_duration` and `record_crew_agent_tokens`, following existing
naming conventions. Existing dashboards/queries against `llm.response.*` attributes
are untouched since those only exist on the quick-tier span.

## 7. Testing plan

**Python:**
- `test_crew.py` (new) — mocks CrewAI's `Agent`/`Task`/`Crew.kickoff` (same style as
  mocking `OpenAI` in `test_llm.py`): sequential task wiring, extended-schema output
  assembly, per-agent failure → `{"error": ...}` without crashing the run, env-driven
  timeout values applied.
- `test_youdotcom.py` (new) — mocks `httpx`; verifies the never-raises /
  ok-failed-log guarantees.
- `test_tools.py` extended — Daytona code-exec tool with a mocked Daytona SDK client.

**NextJS:**
- `tests/api.jobs.test.ts` extended — `depth` field default + validation.
- `tests/daytona.test.ts` extended — env-driven `autoDeleteInterval` map.
- `tests/components/submit-analysis.test.ts` extended — `depth` in POST body.
- `tests/components/depth-selector.test.ts` (new) — now-controlled component.

**Manual/e2e:**
- `scripts/smoke.sh` gains an optional `$2` depth arg; run once per tier against a
  real ticker before the demo to confirm timing stays under the
  `DAYTONA_AUTO_DELETE_*_S` budget.

## 8. Out of scope (explicit)

- One (withone.ai) auth/notifications — future spec.
- A `full`-specific code path beyond larger time budgets.
- Streaming intermediate agent output to the UI.
- Per-agent LLM model overrides.
