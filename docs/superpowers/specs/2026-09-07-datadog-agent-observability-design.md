# Design: Datadog Agent (LLM) Observability + Next.js OTel init fix

**Date:** 2026-09-07
**Status:** Approved (design), pending implementation plan
**Scope:** Agent (`agent/`) gets Datadog's [Agent Observability](https://www.datadoghq.com/products/ai/agent-observability/)
product wired onto its existing LLM/tool-use loop, via the native `ddtrace.llmobs`
SDK. Plus a small, unrelated-but-adjacent fix: Next.js currently never initializes
its OTel SDK.

## Background

`OTEL.md` documents a working base OTel setup: traces, metrics, and logs flow from
both the Next.js frontend and the Python agent to Sentry and Datadog in parallel
(see `2026-07-09-unify-observability-transport-design.md` for the agent-side
transport unification). That base layer is out of scope for changes here except
for one fix (below).

What's missing is Datadog's dedicated **Agent Observability** product — a
separate surface from generic APM, purpose-built for visualizing multi-step
LLM/tool-using agents: a proper execution tree (workflow → agent → llm/tool
spans), prompt/completion inspection, token/cost tracking, and (later,
out of scope here) evaluations. Today the agent's tool-use loop
(`agent/lib/agent_loop.py`) is flattened into a single OTel span
(`llm.analyze`), with tool calls visible only as span *events*
(`agent/lib/tools.py`'s `_observed_tool`), not their own spans.

### Base-setup fix (found during review)

`lib/observability/otel.ts` exports `initOtel()` (Node OTel SDK +
`getNodeAutoInstrumentations()`), but nothing calls it — `instrumentation.ts`
only calls `initDatadogIfEnabled()`. This is already flagged as a known gap in a
WIP worktree's comment (`.worktrees/one-notifications/lib/notify/trigger.ts:19-24`).
Net effect: Next.js gets HTTP/DB auto-instrumentation only through whatever
`dd-trace` and `@sentry/nextjs` independently patch; the vendor-neutral OTel
auto-instrumentation layer is dead code. Fixed here since it's a one-line call
directly adjacent to this work.

## Goals

- Native `ddtrace.llmobs` instrumentation of the Python agent's LLM/tool-use
  loop, structured as a real execution tree in Datadog's dedicated LLM
  Observability UI.
- Full prompt/completion capture (no redaction) — the data involved is ticker/
  financial snapshot content, not user PII.
- Runs **alongside** existing OTel spans, not instead of them — this is an
  additional signal for the dedicated UI, not a replacement for the unified
  OTel/Sentry/Datadog-APM pipeline.
- Its own kill switch (`DD_LLMOBS_ENABLED`), independent of `DD_TRACE_ENABLED`,
  since it's the one signal that ships full prompt text.
- Fix the dead `initOtel()` call in Next.js.

## Non-goals

- Evaluations (built-in or custom quality/faithfulness scoring) — later addition
  once real traces are visible in the UI.
- Any LLM Observability instrumentation on the Next.js side — it makes no LLM
  calls itself.
- Broader base-OTel rework — the transport layer from the prior unification
  design is untouched except for the `initOtel()` call fix.

## Span tree

Mapped onto the existing call structure (`agent/agent.py` → `agent/lib/llm.py`
→ `agent/lib/agent_loop.py` → `agent/lib/tools.py`):

```
workflow: agent.run                     (job_id, ticker, final_status)
  agent: llm.analyze tool-use loop      (one per run_agent_loop() call)
    llm: iteration 1 (model call)       (model, full input, output, tokens_in/out)
    tool: get_financials                (input args, output/error)
    llm: iteration 2 (model call)
    tool: get_valuation
    llm: iteration 3 (final answer, no more tool calls)
```

- `agent.run` → `LLMObs.workflow()`, tagged `job_id`, `ticker`, `final_status`.
- The tool-use loop → `LLMObs.agent()`, one span per `run_agent_loop()` call.
- Each iteration's actual model call → `LLMObs.llm()` — model name, full input
  messages (system + user prompt, including the fetched snapshot), output text,
  `tokens_in`/`tokens_out` (already computed via `agent_loop._usage()`).
- Each tool call (`get_financials`, `get_valuation`, `get_earnings`, and the
  hosted `web_search` tool) → `LLMObs.tool()`, wrapping the existing
  `_observed_tool` dispatch in `tools.py` — input args, output or error.
- `LLMObs.annotate()` sets input/output/metadata on each span; no duplication of
  what the existing OTel spans/attributes already track (those stay as-is).
- `session_id = job_id` on the workflow span — one analysis job is one session
  (no multi-turn conversation to group).

## Configuration

- New env var `DD_LLMOBS_ENABLED` — defaults to on when `DD_API_KEY` is set;
  `"false"` disables just this signal (same pattern as `DD_TRACE_ENABLED`).
- `init_llmobs()` (new, `agent/lib/llmobs.py`) is called from
  `init_observability()` in `agent/lib/observability.py`, gated on
  `DD_API_KEY` set and `DD_LLMOBS_ENABLED != "false"`.
- Agentless mode (`LLMObs.enable(ml_app="stock-agent", agentless_enabled=True,
  api_key=..., site=DD_SITE)`) — Daytona sandboxes have no local Datadog Agent,
  consistent with the existing OTLP-agentless default for traces/metrics/logs.
- `ddtrace>=2.13.0` is already a dependency (`agent/requirements.txt`); confirm
  during implementation that this version includes `ddtrace.llmobs` — bump the
  pin if not.
- `agent.py`'s `EXPECTED_ENV_VARS` (env-presence boot log) gets `DD_LLMOBS_ENABLED`
  added.
- `lib/daytona.ts`'s `spawnAnalysisSandbox` env block gets
  `...forwardIfSet("DD_LLMOBS_ENABLED")` added next to the existing
  `forwardIfSet("DD_TRACE_ENABLED")` / `forwardIfSet("DD_EXPORTER")` lines.
- `flush_observability()` gets an `LLMObs.flush()` call in its shutdown sequence,
  alongside the existing `ddtrace.tracer.shutdown()` call — critical since the
  sandbox self-deletes immediately after.

## Next.js fix

`instrumentation.ts`'s `register()` calls `initOtel()` alongside
`initDatadogIfEnabled()` on the `nodejs` runtime, so the auto-instrumentation
layer that's been dead code actually activates.

## Error handling

- `init_llmobs()` degrades gracefully: if `ddtrace.llmobs` import fails or
  `LLMObs.enable()` raises, log and continue — telemetry must never break an
  agent run (consistent with every other exporter in `observability.py`, all of
  which are try/except-guarded).
- Tool/LLM span helpers wrap the existing `_observed_tool` and `run_agent_loop`
  call sites without changing their control flow or return values — a
  span-annotation failure can't affect the tool-use loop or the final thesis.

## Testing (TDD)

- `agent/tests/`: `init_llmobs()` no-ops when `DD_API_KEY` / `DD_LLMOBS_ENABLED`
  are unset; no-ops (doesn't raise) if `ddtrace.llmobs` is unavailable.
- Span-tree shape: with LLMObs enabled, a workflow span, an agent span, and per-
  iteration llm/tool spans are created in the expected parent/child relationship
  (using `ddtrace.llmobs`'s test/mock utilities).
- `flush_observability()` calls `LLMObs.flush()` when LLMObs was enabled.
- No new frontend tests needed — this is backend-only instrumentation. The
  `initOtel()` fix gets a small check that `register()` calls it on the nodejs
  runtime (extending the existing `instrumentation.ts` coverage if any exists,
  otherwise a minimal new test).

## Out of scope (later)

- Evaluations (faithfulness/quality scoring of the generated thesis against the
  financial snapshot).
- OTel GenAI semantic-convention attributes (`gen_ai.*`) on the existing OTel
  spans — considered as an option, deferred; native LLMObs already covers the
  dedicated-UI use case this pass is for.

## Risks

- Two parallel instrumentation layers (OTel spans + LLMObs spans) around the
  same call sites means some duplicated bookkeeping in `llm.py`/`agent_loop.py`/
  `tools.py`. Mitigated by keeping `LLMObs.annotate()` calls additive/thin —
  they read data already computed for the OTel spans rather than recomputing it.
- Agentless LLMObs export adds another outbound call per job from an ephemeral
  Daytona sandbox; guarded by the same fire-and-forget/flush-before-shutdown
  discipline as the existing OTLP/Sentry/ddtrace flushes.
- Full prompt/completion capture means financial snapshot data and model output
  land in Datadog; acceptable per this design's data-capture decision, but worth
  flagging if the snapshot content scope ever expands to include anything more
  sensitive.
