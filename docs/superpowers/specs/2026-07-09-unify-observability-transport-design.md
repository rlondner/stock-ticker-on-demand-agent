# Design: Unify observability transport (Approach A)

**Date:** 2026-07-09
**Status:** Approved (design), pending implementation plan
**Scope:** Agent (`agent/`). Consolidate the agent's traces, metrics, and logs
onto a single OpenTelemetry SDK exporting via **standard OTLP**, with Datadog
reached through its **agentless OTLP intake** and Sentry through its native SDK.
Retire the two competing/bespoke metrics + logs transports.

## Background

The `main` branch currently carries **two overlapping observability stacks** that
collided when the stock-data work merged with the metrics work:

1. **OTel + native-SDK stack** (`agent/lib/metrics.py`, the `TracerProvider` in
   `observability.py`): real OTel traces + metrics, exported via OTLP (gated on
   `DD_EXPORTER=otlp`) and mirrored to Sentry (`SentrySpanProcessor`,
   `sentry_sdk.metrics`).
2. **Bespoke HTTP-intake stack** (`observability.emit_metric` /
   `observability.emit_log`): posts directly to Datadog's `/api/v2/series`
   (metrics) and `/api/v2/logs` (logs), and writes metrics as span attributes —
   built on the now-false assumption that "Sentry sunset custom metrics in Oct
   2024." Sentry Application Metrics went GA 2026-05-05.

Result: metrics are double-emitted (`agent.run.duration_ms` via the facade and
`agent.duration_ms` via `emit_metric`), logs and metrics use ad-hoc transports,
and Datadog coverage differs by signal (traces need a local Agent unless
`DD_EXPORTER=otlp`; logs/metrics use HTTP intakes).

This design unifies all three signals onto one OTel SDK and one transport model.

## Goals

- One OTel SDK in the agent with three providers — `TracerProvider`,
  `MeterProvider`, `LoggerProvider` — sharing one `Resource`.
- All Datadog delivery via **agentless OTLP** (`/v1/traces`, `/v1/metrics`,
  `/v1/logs`, `dd-api-key` header); no local Agent required. The `ddtrace`
  local-Agent path stays as an opt-in.
- **Vendor-agnostic, per-signal configuration** using the standard OpenTelemetry
  env vars, so any OTLP backend (Datadog, an OTel Collector, Grafana, Sentry's
  OTLP intake, etc.) can be targeted with no code change.
- Retire the bespoke `/api/v2/logs` and `/api/v2/series` intakes and `emit_metric`.
- Sentry keeps its native-SDK integration (trace-connected metrics + logs) as the
  default Sentry path.

## Configuration model

### Standard OTel env vars (vendor-agnostic, primary)

OTLP export is driven by the standard OpenTelemetry variables. The OTLP exporters
read these natively:

- Base (all signals): `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_HEADERS`
- Per-signal endpoint overrides: `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`,
  `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT`, `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT`
- Per-signal header overrides: `OTEL_EXPORTER_OTLP_TRACES_HEADERS`,
  `OTEL_EXPORTER_OTLP_METRICS_HEADERS`, `OTEL_EXPORTER_OTLP_LOGS_HEADERS`

Vendor auth rides in the `_HEADERS` var (e.g. `dd-api-key=...` for Datadog). A
signal is OTLP-exported iff a resolved endpoint exists for it (explicit per-signal
var, or the base var, or the Datadog convenience below).

### Datadog convenience layer (optional, thin)

So Datadog users don't hand-craft URLs: when `DD_API_KEY` is set,
`DD_TRACE_ENABLED != "false"`, and the corresponding standard `OTEL_*` var is
**not** already set, auto-fill the standard vars for the agentless intake:

- endpoint base: `https://otlp.<DD_SITE>` (default site `datadoghq.com`)
- per-signal: `<base>/v1/traces`, `<base>/v1/metrics`, `<base>/v1/logs`
- headers: `dd-api-key=<DD_API_KEY>`

Explicit `OTEL_*` vars always win over the convenience layer (so pointing at a
Collector or another vendor overrides Datadog).

### ddtrace local-Agent mode (opt-in, unchanged semantics)

`DD_EXPORTER=agent` keeps the existing `ddtrace.patch_all` path to a local Agent
on `localhost:8126` (traces + auto-instrumentation) for anyone running a real
Agent. Default is `otlp`. `DD_EXPORTER` validation still rejects unknown values.

### Sentry (native SDK, unchanged)

Gated on `SENTRY_DSN_AGENT`: `SentrySpanProcessor` (traces),
`sentry_sdk.metrics` count/distribution (metrics facade), `sentry_sdk.logger`
(logs). Pointing an `OTEL_*` endpoint at Sentry's OTLP intake is possible but not
the default.

## Architecture

`init_observability(job_id)` builds one shared `Resource`
(`service.name`, `deployment.environment`, `job.id`, `host.name`) and initializes:

| Provider | stdout (Daytona) | Sentry (native) | OTLP (any vendor / DD agentless) |
|---|---|---|---|
| `TracerProvider` | `ConsoleSpanExporter` | `SentrySpanProcessor` | `OTLPSpanExporter` → traces endpoint |
| `MeterProvider` (in `metrics.py`) | — | `sentry_sdk.metrics` | `OTLPMetricExporter` → metrics endpoint |
| `LoggerProvider` (new) | stdlib logger | `sentry_sdk.logger` | `OTLPLogExporter` → logs endpoint |

A single `resolve_otlp_target(signal)` helper returns the endpoint+headers for a
signal (standard var → base var → DD convenience → None). Each provider adds its
OTLP exporter only when its target resolves.

### Auto-instrumentation under OTLP

`ddtrace.patch_all` auto-instruments httpx/psycopg/openai only in `agent` mode.
In `otlp` mode, activate the OTel-native instrumentors already in
`requirements.txt` against the `TracerProvider` so DB/HTTP/LLM spans still flow:
`HTTPXClientInstrumentor`, `PsycopgInstrumentor`, `OpenAIInstrumentor`. (Our
manual `agent.http.*` metrics and `build_httpx_client` remain the metric source;
these instrumentors add trace spans.)

## Component changes

### `agent/lib/observability.py`
- Add `LoggerProvider` setup (OTel logs SDK + `OTLPLogExporter` + a stdout/stdlib
  handler); keep `emit_log(level, message, **attributes)` signature but route the
  body through the OTel logs API (+ Sentry logger). Remove `_datadog_log`.
- Replace the trace OTLP block with the vendor-agnostic resolver; keep the
  `ConsoleSpanExporter`, `SentrySpanProcessor`, and `ddtrace` agent-mode path.
- Add `resolve_otlp_target(signal)` and the Datadog convenience auto-fill.
- **Remove `emit_metric` and `_datadog_metric`.**
- `flush_observability` drains `TracerProvider`, `MeterProvider` (via
  `flush_metrics`), `LoggerProvider`, Sentry, and ddtrace (agent mode).

### `agent/lib/metrics.py`
- OTLP metric reader gating changes from "only `DD_EXPORTER=otlp`" to "whenever
  `resolve_otlp_target('metrics')` returns an endpoint" (shared resolver).
- Add an `llm.duration_ms` histogram + `record_llm_duration(model, api,
  duration_ms, ticker)` to absorb the retired `emit_metric("llm.duration_ms")`.
- `agent.run.duration_ms` already covers the retired `agent.duration_ms`; no new
  instrument needed there.

### Callers
- `agent/lib/llm.py`: replace `emit_metric("llm.duration_ms", …)` with
  `metrics.record_llm_duration(…)`; drop the `emit_metric` import.
- `agent/agent.py`: drop the duplicate `emit_metric("agent.duration_ms", …)`
  (covered by `record_agent_run_duration`); drop the `emit_metric` import.
- `finance.py` and other `emit_log` callers: unchanged (signature preserved).

### `.env.example` / `OTEL.md`
- Document the standard `OTEL_EXPORTER_OTLP_*` vars, the DD convenience, and the
  `DD_EXPORTER=agent` opt-in. Update `OTEL.md` transport/metrics sections.

## Error handling & lifecycle

- Every exporter init and `emit_*` path stays guarded; a telemetry failure never
  breaks the agent run. Unconfigured signals no-op.
- All three providers are flushed in `flush_observability` **before** the Daytona
  VM self-deletes; dropped telemetry on shutdown is the main risk and is tested.

## Testing (TDD)

- **Resolver matrix:** `resolve_otlp_target` for each signal across: explicit
  per-signal var, base var only, DD convenience (DD_API_KEY + DD_SITE), and
  off — asserting endpoint + headers, and that explicit vars beat the convenience.
- **Providers:** in-memory exporters assert a span, a metric, and a log record
  each reach their pipeline; a log emitted via `emit_log` lands in the
  `LoggerProvider`.
- **Gating:** off / otlp / agent modes; `DD_EXPORTER` invalid value still raises.
- **Migration:** `emit_metric` is gone; `record_llm_duration` emits
  `llm.duration_ms`; no `agent.duration_ms` double-emit remains.
- **Flush:** all three providers flushed by `flush_observability`.
- **Cardinality:** `job_id` never a metric tag (existing guard extended to the new
  `llm.duration_ms`).

## Out of scope (later)

- **Snapshot (yfinance) metrics** — `agent.snapshot.fetch` counter + latency — is
  the follow-on sub-project, layered on this unified facade once it lands.
- Next.js frontend transport is unchanged in this spec (it already uses
  `dd-trace` + `@sentry/nextjs` + the metrics facade); a parallel Node unification
  can follow if desired.

## Risks

- Rewriting the working trace/log init carries regression risk; mitigated by the
  in-memory-exporter tests and staged, TDD implementation.
- Datadog's agentless OTLP host/path may vary by site; the convenience layer
  derives `https://otlp.<DD_SITE>` and is overridable by explicit `OTEL_*` vars if
  a site differs.
- OTel logs SDK is comparatively newer; console + Sentry logging remain as
  fallbacks so log visibility never depends solely on the OTLP log pipeline.
