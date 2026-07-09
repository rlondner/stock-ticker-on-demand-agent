# Design: OpenTelemetry Metrics (Project A)

**Date:** 2026-07-09
**Status:** Approved (design), pending implementation plan
**Scope:** Add custom OTel metrics to the existing Next.js frontend and Python
agent, exported via vendor-neutral OTLP **and** Sentry's native metrics SDK.

## Background

The repo is currently instrumented for **traces** (and trace-correlated logs)
only — see `OTEL.md`. There is no `MeterProvider` or metric reader on either
service. This design adds metrics without disturbing the existing trace/Sentry/
Datadog wiring.

### Backend decision

- **OTLP-generic** metrics via `PeriodicExportingMetricReader` + OTLP-HTTP
  exporter. Vendor-neutral: targets `DD_OTLP_ENDPOINT` (Datadog OTLP intake) or
  any OTel Collector, reusing the endpoint/header resolution the Python OTLP
  *trace* path already uses.
- **Sentry native metrics** via the SDK metrics API. Sentry's older metrics
  product was deprecated in 2024, but a new trace-connected **Application
  Metrics** product went **GA on 2026-05-05** and is the current, supported path.
  - `@sentry/nextjs` 10.59.0 already satisfies the ≥10.25.0 requirement.
  - `sentry-sdk` must be bumped from `>=2.15.0` to **`>=2.44.0`** (Python metrics
    support).

### Out of scope (deferred to Project B)

There is **no `yfinance` or stock-price API** in this repo; the agent gathers
evidence via OpenAI's Responses API `web_search` tool (`agent/lib/llm.py:120`).
Actually integrating a price API + its metrics is a separate feature and gets its
own brainstorm → spec → plan cycle. This spec covers only instrumentation of code
that already exists.

## Architecture — dual-emit facade

Every metric is recorded once through a thin **facade** that fans out to two
independently-gated sinks:

1. **OTel `Meter` instruments** → periodic reader → OTLP-HTTP exporter.
2. **Sentry native metrics** (`Sentry.metrics.*` / `sentry_sdk.metrics.*`).

Guarantees:

- Both sinks no-op when unconfigured (mirrors today's trace setup).
- All init and emit paths are wrapped in try/except (Python) / try-catch (Node);
  a metrics failure MUST NOT break a request or the agent run.
- `job_id` is **never** a metric tag (unbounded cardinality).
- `ticker` **is** tagged on all metrics (explicit user choice). This is the main
  Datadog custom-metric cost driver and can be stripped from the OTLP emit later
  without touching call sites.

## Metric inventory

| Metric | Type | Emitted from | Tags |
|---|---|---|---|
| `jobs.submitted` | counter | Node `api.jobs.post` | `outcome` (accepted/rejected), `ticker` |
| `jobs.completed` | counter | Py `agent.run` | `final_status` (complete/failed), `ticker` |
| `agent.run.duration_ms` | distribution | Py `agent.run` | `final_status`, `ticker` |
| `llm.tokens_in` | distribution | Py `llm.analyze` | `model`, `api`, `ticker` |
| `llm.tokens_out` | distribution | Py `llm.analyze` | `model`, `api`, `ticker` |
| `llm.calls` | counter | Py `llm.analyze` | `model`, `api`, `outcome`, `ticker` |
| `llm.empty_response` | counter | Py `llm.analyze` | `model`, `api`, `ticker` |
| `llm.web_search.used` | counter | Py `llm.analyze` | `api`, `ticker` |
| `agent.http.requests` | counter | Py httpx event-hook | `host`, `status_code`, `ticker` |
| `agent.http.duration_ms` | distribution | Py httpx event-hook | `host`, `ticker` |

Notes:

- `jobs.submitted` is the only metric on the Node side — Node sees job submission
  and status polling; everything else (completion, duration, LLM, HTTP) happens
  inside the Python agent.
- `agent.http.*` are derived from an httpx event-hook (the OTel httpx
  instrumentation emits spans, not metrics), giving one metric path for all
  outbound calls including OpenAI.

## Components / files

### Node (Next.js)

- `lib/observability/metrics.ts` *(new)* — `initMetrics()` builds a
  `MeterProvider` + OTLP metric reader; exports a typed `metrics` facade
  (e.g. `metrics.jobsSubmitted(outcome, ticker)`) that also mirrors to Sentry.
- `lib/observability/otel.ts` — call `initMetrics()` alongside the existing
  `sdk.start()`.
- `app/api/jobs/route.ts` — emit `jobs.submitted` inside the existing `traced()`
  span for `api.jobs.post`.
- `package.json` — add `@opentelemetry/sdk-metrics` and
  `@opentelemetry/exporter-metrics-otlp-http`.

### Python (agent)

- `agent/lib/metrics.py` *(new)* — `init_metrics(resource)` builds a
  `MeterProvider` + `PeriodicExportingMetricReader(OTLPMetricExporter)` reusing
  the OTLP endpoint/header logic from `observability.py`; exposes a typed facade
  with a Sentry mirror.
- `agent/lib/observability.py` — call `init_metrics()` from `init_observability()`
  (share the `Resource`); add meter-provider flush to `flush_observability()`.
- `agent/agent.py` — emit `jobs.completed` and `agent.run.duration_ms` from the
  `agent.run` span.
- `agent/lib/llm.py` — emit `llm.tokens_in`, `llm.tokens_out`, `llm.calls`,
  `llm.empty_response`, `llm.web_search.used`; register an httpx event-hook for
  `agent.http.requests` and `agent.http.duration_ms`.
- `agent/requirements.txt` — bump `sentry-sdk[opentelemetry]` to `>=2.44.0`. The
  OTLP metrics exporter already ships inside the installed
  `opentelemetry-exporter-otlp-proto-http`.

### Docs / config

- `.env.example` — document metrics gating (reuses `DD_OTLP_ENDPOINT` /
  `DD_API_KEY`; Sentry metrics auto-on with the existing `SENTRY_DSN_*`).
- `OTEL.md` — flip the Metrics section from ❌ to ✅ with this inventory.

## Configuration & gating

- **OTLP metrics export**: enabled when the OTLP endpoint is configured (reuse
  `DD_OTLP_ENDPOINT` + `DD_API_KEY` header, consistent with the existing
  `DD_EXPORTER=otlp` trace path). No new dedicated env var.
- **Sentry metrics**: auto-on when `SENTRY_DSN_NEXTJS` / `SENTRY_DSN_AGENT` is set
  and the SDK version supports metrics.
- Disabled/unconfigured → facade no-ops.

## Error handling & lifecycle

- All init + emit guarded; metrics never propagate exceptions to callers.
- Metric readers MUST be flushed before shutdown — in `flush_observability()`
  (Python, before the Daytona VM is deleted) and on Node shutdown. Buffered
  metrics are otherwise lost. This is the primary lifecycle risk and gets explicit
  test coverage.

## Testing (TDD)

- **Python**: `InMemoryMetricReader` asserts each instrument records the expected
  value and attributes; Sentry metrics mocked. Extends the patterns in
  `agent/tests/test_observability.py`.
- **Node**: in-memory / manual metric reader asserts `jobs.submitted`; Sentry
  mocked.
- **Cardinality guard**: a test asserting `job_id` is absent from every metric's
  attribute set.
- **Flush**: a test asserting the meter provider is flushed by
  `flush_observability()`.

## Risks / open considerations

- `ticker` cardinality on Datadog custom metrics (accepted; reversible).
- httpx event-hook must not double-count retries vs. the OTel span layer — the
  hook counts transport-level requests, which is the intended semantics.
- Reusing `DD_OTLP_ENDPOINT` couples "OTLP metrics" to the Datadog-named var; kept
  for consistency with the existing trace path. A generic
  `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` override can be added later if a non-DD
  collector is introduced.
