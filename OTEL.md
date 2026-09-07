# Observability (OpenTelemetry → Sentry & Datadog)

This project is instrumented with OpenTelemetry across two services, exporting
**traces** (and trace-correlated logs) to **both Sentry and Datadog in parallel**.
All exporters are gated on environment variables and silently no-op when unset.

- **Next.js frontend** (Node.js runtime) — OTel SDK + `@sentry/nextjs` + `dd-trace`
- **Python agent** (sandbox worker) — OTel SDK + `sentry-sdk[opentelemetry]` + `ddtrace`

A W3C `traceparent` is injected by Next.js and extracted by the Python agent, so a
single distributed trace spans **frontend → agent**.

## At a glance

| Signal   | Status              | Backends            | Notes                                            |
|----------|---------------------|---------------------|--------------------------------------------------|
| Traces   | ✅ Fully tracked    | Sentry + Datadog    | 5 manual spans + broad auto-instrumentation      |
| Logs     | ⚠️ Minimal          | Sentry + Datadog    | Correlated to traces, not a dedicated log pipeline |
| Metrics  | ✅ Implemented      | Sentry + Datadog    | OTLP export (all signals unified) + Sentry Application Metrics |

## Dependencies

### Next.js / Node.js (`package.json`)
- `@opentelemetry/api` 1.9.1
- `@opentelemetry/auto-instrumentations-node` 0.77.0
- `@opentelemetry/core` 2.7.1
- `@opentelemetry/resources` 2.8.0
- `@opentelemetry/sdk-node` 0.219.0
- `@opentelemetry/semantic-conventions` 1.41.1
- `@opentelemetry/sdk-trace-base` 2.7.1 (devDependency)
- `@sentry/nextjs` 10.59.0
- `dd-trace` 5.109.0

### Python agent (`agent/requirements.txt`)
- `opentelemetry-api>=1.27.0`
- `opentelemetry-sdk>=1.27.0`
- `opentelemetry-instrumentation-httpx>=0.48b0`
- `opentelemetry-instrumentation-psycopg>=0.48b0`
- `opentelemetry-instrumentation-openai>=0.30.0`
- `opentelemetry-instrumentation-logging>=0.48b0`
- `opentelemetry-exporter-otlp-proto-http>=1.27.0`
- `sentry-sdk[opentelemetry]>=2.44.0`
- `ddtrace>=2.13.0`

## Traces

### Next.js — manual spans
Created via the `traced(name, attrs, fn)` helper in `lib/observability/api.ts`.

| Span             | Route                      | Attributes                                              |
|------------------|----------------------------|---------------------------------------------------------|
| `api.jobs.post`  | `POST /api/jobs`           | `route`, `job_id`, `ticker`, `sandbox_id`, `outcome` (`accepted`/`rejected`) |
| `api.status.get` | `GET /api/status/[jobId]`  | `job_id`, `status`, `outcome` (`not_found`)             |
| `api.cleanup.post` | `POST /api/cleanup`      | `swept` (count)                                         |

Errors are recorded via `recordError(span, e)` → `span.recordException(e)` + ERROR status.

### Next.js — auto-instrumentation
`@opentelemetry/auto-instrumentations-node` covers incoming HTTP server spans,
database queries, and other standard Node.js instrumentations.

### Python agent — manual spans
Tracer: `trace.get_tracer("stock-agent")` (setup in `agent/lib/observability.py`).

| Span          | File                | Attributes / events                                            |
|---------------|---------------------|----------------------------------------------------------------|
| `agent.run`   | `agent/agent.py`    | `job_id`, `ticker`, `final_status` (`complete`/`failed`)       |
| `llm.analyze` | `agent/lib/llm.py`  | `model`, `api`, `tokens_in`, `tokens_out`, `llm.iterations`, `llm.tools_used`, `llm.response.recommendation`, `llm.response.confidence`, `llm.response.grounding` |

### Python agent — auto-instrumentation
`httpx` (HTTP), `psycopg` (Neon DB), `openai` (LLM calls), and `logging`.

> Note: values like `tokens_in`, `tokens_out`, and `swept` are span **attributes**,
> not metric instruments — query them via trace search, not as time-series metrics.

## Logs

- **Python agent**: standard `logging` module, auto-linked to traces via
  `opentelemetry-instrumentation-logging` and Datadog's `patch_all(logging=True)`
  log injection. Sentry captures logs alongside spans. Few explicit log calls
  (e.g. `logger.warning("LLM returned empty response...")` in `agent/lib/llm.py`).
  Subprocess mode also writes raw logs to `agent/.runs/<jobId>.log`.
- **Next.js**: no structured logger — only `console` in a migration script.

The Python agent ships logs as a first-class signal via the OTel `LoggerProvider`
and an OTLP HTTP exporter (same `OTEL_EXPORTER_OTLP_*` resolver used for traces and
metrics). Next.js has no dedicated log pipeline — logs ride as trace context /
breadcrumbs only.

## Metrics

Custom metrics are emitted through OTel `Meter` instruments in each service and
exported via a periodic OTLP-HTTP reader (same `OTEL_EXPORTER_OTLP_*` resolver as
traces and logs) **and** Sentry's Application Metrics API (auto-on with the service
DSN). `job_id` is never a metric tag; `ticker` is tagged on all metrics.

| Metric | Type | Service | Tags |
|---|---|---|---|
| `jobs.submitted` | counter | Next.js | `outcome`, `ticker` |
| `jobs.completed` | counter | agent | `final_status`, `ticker` |
| `agent.run.duration_ms` | histogram | agent | `final_status`, `ticker` |
| `llm.tokens_in` / `llm.tokens_out` | histogram | agent | `model`, `api`, `ticker` |
| `llm.calls` | counter | agent | `model`, `api`, `outcome`, `ticker` |
| `llm.empty_response` | counter | agent | `model`, `api`, `ticker` |
| `agent.http.requests` | counter | agent | `host`, `status_code`, `ticker` |
| `agent.http.duration_ms` | histogram | agent | `host`, `ticker` |
| `agent.snapshot.fetch` | counter | agent | `outcome`, `ticker` |
| `agent.snapshot.fetch.duration_ms` | histogram | agent | `outcome`, `ticker` |
| `agent.snapshot.backfilled` | counter | agent | `ticker` |
| `agent.snapshot.field_missing` | counter | agent | `field`, `ticker` |
| `agent.snapshot.completeness` | histogram | agent | `ticker` |

Facade modules: `lib/observability/metrics.ts` (Next.js), `agent/lib/metrics.py` (agent).

## Agent Observability (Datadog LLM Obs)

Separate from the APM traces/metrics/logs above: the Python agent also emits
to Datadog's dedicated [Agent Observability](https://www.datadoghq.com/products/ai/agent-observability/)
product via the native `ddtrace.llmobs` SDK (`agent/lib/llmobs.py`), running
**alongside** the OTel spans, not instead of them.

| Span kind  | Call site                                          | Notes |
|------------|-----------------------------------------------------|-------|
| `workflow` | `agent.py` — one per job (`agent.run`)              | `session_id=JOB_ID`, set once; propagates to children |
| `agent`    | `lib/llm.py` — one per `run_agent_loop()` call      | the tool-use loop |
| `llm`      | `lib/llm.py` — one per actual model API call        | full input messages, output text, token usage |
| `tool`     | `lib/tools.py` — one per tool dispatch              | `get_financials`/`get_valuation`/`get_earnings`, args + result/error |

Full prompt/completion capture (no redaction) — the content involved is
ticker/financial-snapshot data, not user PII.

Gated on `DD_API_KEY` **and** the independent `DD_LLMOBS_ENABLED` (default on;
`"false"` disables just this signal — it's the one that ships full prompt
text). Runs in agentless mode (`agentless_enabled=True`, `ml_app=
"stock-agent"`) since Daytona sandboxes have no local Datadog Agent. Flushed
in `flush_observability()` before the sandbox self-deletes.

Evaluations (quality/faithfulness scoring) are not yet wired up.

## Backends & configuration

### Sentry (separate project per service)
- Next.js DSN: `SENTRY_DSN_NEXTJS` — configs in `sentry.server.config.ts`,
  `sentry.client.config.ts`, `sentry.edge.config.ts` (`tracesSampleRate: 1.0`).
  Client can fall back to `NEXT_PUBLIC_SENTRY_DSN`.
- Agent DSN: `SENTRY_DSN_AGENT` — bridged with `SentrySpanProcessor` + `SentryPropagator`.
- `SENTRY_AUTH_TOKEN`: CI source-map upload only (not runtime-critical).

### Datadog (`DD_API_KEY` is the master switch — unset = fully disabled)
- Next.js `dd-trace` → local Datadog Agent at `localhost:8126`, service
  `stock-agent-frontend`, `logInjection: true`.
- **Python agent** — all three signals (traces, metrics, logs) export via standard
  OTLP HTTP, resolved from the `OTEL_EXPORTER_OTLP_*` env vars.  If those vars are
  unset and `DD_API_KEY` is set (and `DD_TRACE_ENABLED != false`), all three signals
  auto-target Datadog's agentless intake (`https://otlp.<DD_SITE>/v1/<signal>`) with
  a `dd-api-key` header — no local Agent required.
  - `DD_EXPORTER=agent` opts into the local Datadog Agent on `:8126` instead.
- `DD_LLMOBS_ENABLED`: independent kill switch for Agent Observability (see
  above); defaults to on whenever `DD_API_KEY` is set.
- Other vars: `DD_SITE`, `DD_SERVICE`, `DD_ENV`, `DD_TRACE_ENABLED`.

### Trace propagation
- `TRACEPARENT` — W3C trace context; injected by Next.js (`injectTraceparent()` in
  `lib/runtime/env.ts`, using `W3CTraceContextPropagator`) and extracted by the
  Python agent.

## Key files

**Core observability**
- `lib/observability/api.ts` — Next.js span helpers (`traced`, `recordError`)
- `lib/observability/otel.ts` — Node OTel SDK setup
- `lib/observability/exporters/datadog.ts` — dd-trace init (`initDatadogIfEnabled`)
- `lib/observability/exporters/sentry.ts` — Sentry marker/setup
- `agent/lib/observability.py` — Python OTel + Sentry/Datadog exporters + propagation
- `agent/lib/llmobs.py` — Agent Observability (Datadog LLM Obs) span helpers

**Configuration**
- `instrumentation.ts` — Next.js `register` hook (initializes Datadog on `nodejs` runtime)
- `sentry.{server,client,edge}.config.ts` — Sentry configs
- `.env.example` — full env-var reference (Observability section, ~lines 67–89)

**Instrumented entry points**
- `app/api/jobs/route.ts`, `app/api/status/[jobId]/route.ts`, `app/api/cleanup/route.ts`
- `agent/agent.py`, `agent/lib/llm.py`
