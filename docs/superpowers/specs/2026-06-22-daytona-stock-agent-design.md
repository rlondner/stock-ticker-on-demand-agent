---
title: Daytona Stock-Agent Demo — Design
date: 2026-06-22
status: draft
purpose: Learning project + reference architecture for clients
---

# Daytona Stock-Agent Demo

## 1. Purpose

A demo that shows how to use **short-lived AI agents hosted in Daytona sandboxes**, using a believable workload (stock buy/hold/sell analysis). The Daytona ephemeral-VM pattern is the showcase; stock analysis is the carrier.

Dual audience:

- **Learning** — actually understand every piece end-to-end (NextJS, Neon, Daytona, OpenAI, Sentry, Datadog).
- **Reference architecture for clients** — production-shaped patterns clients can adapt: error handling, retries, observability, multi-user-ready schema.

Explicitly *not* a real financial product. The UI carries a "demo, not financial advice" disclaimer.

## 2. Decisions

| # | Decision | Choice | Why |
|---|---|---|---|
| D1 | Hybrid cloud broker | **No Azure Functions** — NextJS API routes do everything | Fewer moving parts; clients can layer a broker on later |
| D2 | LLM provider | OpenAI today, behind a `LLMClient` interface | Model-agnostic per user preference; trivial to add Anthropic/Gemini later |
| D3 | Result delivery to UI | Client polls `/api/status/[jobId]` → NextJS reads Neon | No tunnels, no webhooks; VM is write-only against Neon |
| D4 | Sandbox provisioning | Prebuilt Daytona snapshot with deps + agent code baked in | ~5–10s spawn vs 30–60s pip-install; production-shaped |
| D5 | Auth | No login flow; schema has `user_id` (defaulted to `"demo-user"`) | Easy upgrade path to multi-user without schema migration |
| D6 | VM ↔ job model | **One VM per ticker submission**; self-deletes when done | True ephemeral fan-out — best showcase of the Daytona pattern |
| D7 | Sandbox entrypoint | Docker `CMD` runs `python agent.py` on boot | NextJS code is `dt.create()` only — one call |
| D8 | Observability | **OpenTelemetry-first**; Sentry and Datadog as interchangeable exporters with full feature parity | Vendor-neutral instrumentation; users pick Sentry, Datadog, both, or neither via env vars without code changes |

## 3. Architecture & data flow

```
┌─────────────┐                                ┌─────────────┐
│  Browser    │  (1) POST /api/jobs            │ Daytona     │
│  NextJS app │ ─────────────────────────┐     │ Cloud       │
└──────┬──────┘                          │     └──────▲──────┘
       │                                 │            │ (3) sandbox.create()
       │                                 ▼            │     with snapshot
       │                          ┌─────────────┐     │     + env vars
       │  (5) poll                │  NextJS     │ ────┘     (jobId, NEON_URL,
       │      /api/status/[id]    │  API routes │           OPENAI_KEY,
       │   ◄──────────────────────┤  (Node)     │           TRACEPARENT,
       │                          └──────┬──────┘           + any of SENTRY_DSN_*
       │                                 │                  / DD_API_KEY ...)
       │                                 │ (2) INSERT job row (status=pending)
       │                                 ▼          (6) SELECT result on poll
       │                          ┌─────────────┐
       │                          │   Neon      │◄──┐
       │                          │  Postgres   │   │ (4b) UPDATE row
       │                          └─────────────┘   │      status=complete
       │                                            │      result=...
       └─                                ┌──────────┴──────────┐
                                         │   Daytona Sandbox    │
                                         │   (ephemeral VM)     │
                                         │   ┌──────────────┐   │
                                         │   │ Python agent │   │ (4a) Read job row,
                                         │   │ + OpenAI SDK │   │      call LLM,
                                         │   │ + web tools  │   │      analyze ticker
                                         │   │ + OTel SDK   │   │
                                         │   │ (Sentry/DD   │   │
                                         │   │  exporters)  │   │
                                         │   └──────────────┘   │
                                         │                      │ (4c) flush o18y,
                                         └──────────────────────┘      sandbox.delete()
```

### Lifecycle (single ticker submission)

1. User submits `AAPL` in the browser.
2. NextJS `/api/jobs` inserts a row into Neon: `{id, ticker, user_id, status:'pending', created_at}`.
3. Same handler calls Daytona TS SDK `dt.create({snapshot:"stock-agent:latest", envVars:{...}})`. Returns `{jobId}` to the client.
4. Sandbox boots (~5–10s) and runs `CMD = python /app/agent.py` (which initializes OTel + whichever exporters are configured):
   - 4a. SELECT row by `JOB_ID`; mark `status='running'`, set `started_at`, `sandbox_id`.
   - 4b. Run LLM agent. UPDATE row with `recommendation`, `result`, `status='complete'`, `completed_at`.
   - 4c. Flush all active observability exporters. Call Daytona REST API to delete self.
5. Browser polls `/api/status/[jobId]` every 2.5s.
6. NextJS reads the row from Neon. When `status='complete'` or `'failed'`, polling stops and the UI renders.

**Invariant:** the sandbox never accepts inbound connections. No tunnels, no webhooks, no public IP. Pure write-out → die.

## 4. Database schema (Neon Postgres)

```sql
CREATE TABLE jobs (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        TEXT NOT NULL DEFAULT 'demo-user',
  ticker         TEXT NOT NULL,
  status         TEXT NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending','running','complete','failed')),
  recommendation TEXT
                   CHECK (recommendation IN ('buy','hold','sell') OR recommendation IS NULL),
  result         JSONB,
  error          TEXT,
  sandbox_id     TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at     TIMESTAMPTZ,
  completed_at   TIMESTAMPTZ
);

CREATE INDEX jobs_user_status_created_idx
  ON jobs (user_id, status, created_at DESC);
```

### Notes

- `result` is **JSONB** so the agent returns a structured payload (`summary`, `signals`, sources) without locking the shape today.
- `recommendation` is a **separate column** — UI shows it prominently and may filter by it later.
- `status` transitions: `pending → running → complete | failed`. The API only writes `pending`; only the sandbox writes the rest.
- Every `mark_*` operation uses a single `UPDATE ... WHERE status IN (...)` so terminal states are never overwritten.
- `sandbox_id` ties a job to its Daytona sandbox for cross-cloud debugging.
- `started_at` / `completed_at` give free latency metrics.

### Migrations

Single `0001_init.sql` for the demo. **Drizzle ORM** on the NextJS side (type-safe, has Neon serverless support); **psycopg** directly in the Python sandbox (no ORM — fewer deps in the image).

## 5. NextJS application

NextJS 15 (App Router) + TypeScript + Tailwind + shadcn/ui + Drizzle ORM + Daytona TS SDK.

```
app/
├── page.tsx                      # Submit form + jobs list
├── jobs/[id]/page.tsx            # Single job detail (polls until complete)
├── admin/page.tsx                # Recent jobs operator view
└── api/
    ├── jobs/route.ts             # POST: create job + spawn sandbox
    ├── status/[jobId]/route.ts   # GET:  return job row from Neon
    └── cleanup/route.ts          # POST: sweep stuck `running` rows
lib/
├── db/
│   ├── schema.ts                 # Drizzle schema (mirrors section 4)
│   └── client.ts                 # Neon serverless driver
├── daytona.ts                    # Thin Daytona SDK wrapper
└── observability/
    ├── otel.ts                   # OTel SDK init; picks exporters from env
    ├── api.ts                    # traced(), recordError(), addAttrs() helpers
    └── exporters/
        ├── sentry.ts             # @sentry/nextjs (OTel-mode) — active iff SENTRY_DSN_NEXTJS set
        └── datadog.ts            # dd-trace (OTel-compat) — active iff DD_API_KEY set
sentry.client.config.ts           # only present if Sentry is in use
sentry.server.config.ts
sentry.edge.config.ts
```

### Routes

| Route | Method | Behavior |
|---|---|---|
| `/` | page | Form to submit a ticker; list of recent jobs for `demo-user` with status badges. |
| `/api/jobs` | POST | Validate ticker (`^[A-Z]{1,5}$`); insert row `status='pending'`; spawn sandbox; return `{jobId}`. On spawn failure, update row `status='failed'`. |
| `/jobs/[id]` | page | Job detail. Client component polls `/api/status/[jobId]` every 2.5s. Shows spinner + sandbox id + elapsed timer while running; final result when complete; error when failed. |
| `/api/status/[jobId]` | GET | Returns the job row. Client stops polling when status is `complete` or `failed`. |
| `/admin` | page | Recent jobs table (status, duration, recommendation, error). Manual "mark failed" button for stuck rows. |
| `/api/cleanup` | POST | Marks any `running` row older than 10 minutes as `failed` with `error='timeout'`. Triggered by Vercel Cron or hit manually. |

### Daytona spawn

```ts
import { Daytona } from "@daytonaio/sdk";
import { context, propagation, trace, Span } from "@opentelemetry/api";

const dt = new Daytona({ apiKey: process.env.DAYTONA_API_KEY! });

export async function spawnAnalysisSandbox(jobId: string, parentSpan: Span) {
  // Extract the W3C traceparent using OTel's propagation API. This is
  // vendor-neutral — Sentry and Datadog both honor it on the receiving side.
  const carrier: Record<string, string> = {};
  propagation.inject(trace.setSpan(context.active(), parentSpan), carrier);

  // Build the env block. Observability vars are forwarded ONLY if set in
  // NextJS's env — so a "Sentry-only" or "Datadog-only" deployment passes
  // through the same way without code changes.
  const env: Record<string, string> = {
    JOB_ID: jobId,
    NEON_DATABASE_URL: process.env.NEON_DATABASE_URL!,
    OPENAI_API_KEY: process.env.OPENAI_API_KEY!,
    DAYTONA_API_KEY: process.env.DAYTONA_API_KEY!,         // for self-delete
    TRACEPARENT: carrier.traceparent ?? "",
    ...forwardIfSet("SENTRY_DSN_AGENT"),
    ...datadogBlockIfEnabled(),
  };

  const sandbox = await dt.create({
    snapshot: "stock-agent:latest",
    envVars: env,
    autoStopInterval: 0,
    autoDeleteInterval: 600,                                // safety net: hard-kill at 10min
  });
  return sandbox.id;
}

// Forward an env var only if set locally — keeps the spawn site declarative.
function forwardIfSet(k: string): Record<string, string> {
  return process.env[k] ? { [k]: process.env[k]! } : {};
}

// The Datadog block is forwarded as a unit: nothing if DD_API_KEY is unset,
// otherwise key + site + service + env (with sandbox-side defaults).
function datadogBlockIfEnabled(): Record<string, string> {
  if (!process.env.DD_API_KEY) return {};
  return {
    DD_API_KEY: process.env.DD_API_KEY,
    DD_SITE:    process.env.DD_SITE    ?? "datadoghq.com",
    DD_SERVICE: "stock-agent",
    DD_ENV:     process.env.DD_ENV     ?? (process.env.NODE_ENV ?? "development"),
  };
}
```

**No `executeCommand` call needed.** The snapshot's `CMD` runs the agent on boot. NextJS does `dt.create()` and returns.

### UI shape

Two-column layout, intentionally simple — the backend pattern is the star:

- **Left:** ticker input, submit button, list of recent jobs (ticker, status badge, age).
- **Right (when a job is selected):** status banner (spinner / green / red), recommendation badge (BUY/HOLD/SELL), summary, key signals with evidence + source URLs, sandbox metadata (id, started_at, duration), and the **"demo, not financial advice"** disclaimer.

### Environment

Core (required):
```
DAYTONA_API_KEY=...
DAYTONA_TARGET=us
NEON_DATABASE_URL=...
OPENAI_API_KEY=...
```

Observability (all optional — set the block for whichever vendor(s) you want):
```
# --- Sentry block (omit entirely to disable Sentry) ---
SENTRY_DSN_NEXTJS=...
SENTRY_DSN_AGENT=...
SENTRY_AUTH_TOKEN=...               # only needed for source-map upload in CI

# --- Datadog block (omit entirely to disable Datadog) ---
DD_API_KEY=...
DD_SITE=datadoghq.com               # or datadoghq.eu, us3, ...
DD_SERVICE=stock-agent-frontend     # overridden to "stock-agent" inside the sandbox
DD_ENV=development
```

Setting neither block is supported: OTel runs in no-op mode and the app still works (the `jobs` table remains the audit trail). Setting both is also supported — every signal goes to both vendors in parallel.

## 6. Daytona sandbox & Python agent

### Snapshot image

```
stock-agent-image/
├── Dockerfile
├── requirements.txt
├── agent.py                 # entrypoint
└── lib/
    ├── db.py                # Neon access (psycopg)
    ├── llm.py               # model-agnostic LLM client
    ├── tools.py             # web search tool
    ├── prompts.py           # system prompt + result schema
    ├── observability.py     # OTel init + exporter wiring (Sentry/Datadog) + flush
    └── self_delete.py       # Daytona REST call to delete own sandbox
```

### Dockerfile

```dockerfile
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent.py ./
COPY lib/ ./lib/

CMD ["python", "/app/agent.py"]
```

### `requirements.txt`

```
openai
psycopg[binary]
pydantic
tenacity
httpx
# --- OpenTelemetry core (always installed) ---
opentelemetry-api
opentelemetry-sdk
opentelemetry-instrumentation-httpx
opentelemetry-instrumentation-psycopg
opentelemetry-instrumentation-openai
opentelemetry-instrumentation-logging
# --- Vendor exporters (always installed; active only if env says so) ---
sentry-sdk[opentelemetry]
ddtrace
```

Both vendor SDKs are installed in the image but only initialized at runtime if their env vars are present. This keeps a single snapshot working for any deployment configuration (Sentry-only, Datadog-only, both, or neither).

### `agent.py` (skeleton)

```python
import os, sys, traceback
from opentelemetry import trace
from lib.observability import init_observability, flush_observability, record_error
from lib.db import get_job, mark_running, mark_complete, mark_failed
from lib.llm import run_analysis
from lib.self_delete import self_delete

JOB_ID = os.environ["JOB_ID"]

def main():
    # Initializes OTel + whichever vendor exporters are configured (Sentry,
    # Datadog, both, or none). Continues the incoming W3C trace from TRACEPARENT.
    init_observability(job_id=JOB_ID)
    tracer = trace.get_tracer("stock-agent")

    with tracer.start_as_current_span("agent.run") as span:
        span.set_attribute("job_id", JOB_ID)
        try:
            job = get_job(JOB_ID)
            if job is None or job["status"] != "pending":
                # Idempotency guard — another sandbox already picked this up
                print(f"job {JOB_ID} not pending; exiting", file=sys.stderr)
                return
            span.set_attribute("ticker", job["ticker"])
            mark_running(JOB_ID)

            result = run_analysis(ticker=job["ticker"])
            mark_complete(JOB_ID,
                          recommendation=result["recommendation"],
                          result=result)
        except Exception as e:
            # record_error() dispatches to every active exporter; OTel span gets
            # exception event + ERROR status. Vendor-neutral.
            record_error(span, e)
            mark_failed(JOB_ID,
                        error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
            raise
        finally:
            flush_observability()         # MUST flush all exporters before VM dies
            try: self_delete()
            except Exception: pass

if __name__ == "__main__":
    main()
```

### Three design rules baked into the agent

1. **Idempotency check** — re-read the row's status before working. If two sandboxes ever pick up the same `JOB_ID`, only one proceeds.
2. **`finally` runs always** — even on crash, the sandbox flushes observability *then* self-deletes. `autoDeleteInterval=600` is the safety net.
3. **`mark_failed` writes the full traceback** — the row's `error` column becomes the cross-cloud debug log.

### `lib/llm.py` — model-agnostic boundary

```python
from typing import Protocol
from pydantic import BaseModel

class Signal(BaseModel):
    label: str
    evidence: str
    source: str | None = None

class Analysis(BaseModel):
    recommendation: str  # "buy" | "hold" | "sell"
    summary: str
    signals: list[Signal]

class LLMClient(Protocol):
    def analyze(self, ticker: str) -> Analysis: ...

class OpenAIClient:
    """Default: OpenAI Responses API with the built-in web_search tool.
    OTel auto-instrumentation captures the LLM call as a child span; the
    client adds custom attributes (tokens_in, tokens_out, cost_usd, model)."""
    def analyze(self, ticker: str) -> Analysis: ...

def run_analysis(ticker: str) -> dict:
    client: LLMClient = OpenAIClient()
    return client.analyze(ticker).model_dump()
```

A second client class (Anthropic, Gemini, local) is a drop-in. The `Analysis` Pydantic model is the contract — same JSON shape regardless of provider.

### Analysis behavior

- OpenAI Responses API with the `web_search` built-in tool.
- System prompt asks for structured `Analysis` JSON (recommendation, 3–5 signals with evidence + source URL, plain-English summary).
- One-shot call (not a multi-step agent loop — the chosen model is "model-agnostic," not "showy agentic").
- `tenacity` retries on transient errors only (rate limit, connection, 5xx) — 3 attempts, exponential backoff (1s → 4s → 16s).

### Sandbox lifecycle, end to end

| t      | event |
|--------|-------|
| 0s     | NextJS `dt.create()` — spawning |
| 5–10s  | Sandbox boots; `CMD` runs `python /app/agent.py`; `init_observability()` wires OTel + active exporters |
| 10s    | Agent reads job row, marks `running` |
| 10–60s | LLM call(s) — web search + reasoning |
| ~60s   | Agent writes `complete` + `result` to Neon |
| ~61s   | `flush_observability()` — every active exporter drains (Sentry, Datadog, or both) |
| ~62s   | `DELETE /sandbox/{id}` — VM gone |
| (safety net) | `autoDeleteInterval=600` reclaims any stuck VM |

## 7. Observability

**Design principle: full vendor parity.** Users can deploy with Sentry, Datadog, both, or neither — and lose no feature in any configuration. Achieved by making OpenTelemetry the in-code instrumentation API and treating Sentry/Datadog as interchangeable exporters wired in by environment variable.

### 7.1 The pattern

All instrumentation — spans, errors, metrics-as-span-attributes, structured logs — is written against the **OpenTelemetry API**. The OTel SDK is wired with one or both of the following exporters at startup:

- **Sentry exporter** — `sentry-sdk[opentelemetry]` (Python), `@sentry/nextjs` ≥ v8 with OTel mode (Node). Sentry SDK ingests the OTel pipeline.
- **Datadog exporter** — `ddtrace` in OTel-compatibility mode (Python), `dd-trace` Node SDK as OTel provider (Node).

Activation is purely env-var-driven, with no code branches in the application:

| Env vars present | Active backends |
|---|---|
| `SENTRY_DSN_*` only | Sentry |
| `DD_API_KEY` only | Datadog |
| Both | Both (signals fan out to both vendors) |
| Neither | None — OTel runs in no-op mode; the app still works |

The application code never imports `sentry_sdk` or `ddtrace` directly. It calls OTel APIs and project-local helpers in `lib/observability/`.

### 7.2 Feature parity matrix

Every observability capability the demo cares about is achievable on either backend with **the same instrumentation call**:

| Capability | How we instrument | Sentry surface | Datadog surface |
|---|---|---|---|
| Errors with traceback | `span.record_exception(e)` + `span.set_status(StatusCode.ERROR)`; project helper `record_error(span, e)` | Sentry Errors (auto-derived from error spans, with full traceback) | Datadog Error Tracking (auto-derived from error spans) |
| Distributed trace across cloud | W3C `traceparent` env var (`TRACEPARENT`) — vendor-neutral | Sentry Performance (continued trace) | Datadog APM (continued trace) |
| Custom span | `tracer.start_as_current_span("name")` | Sentry Performance | Datadog APM |
| "Metric" (count, duration, value) | `span.set_attribute("name", value)` | Sentry Insights (span-derived metrics) | Datadog metrics (span-derived + tag filters) |
| Structured logs | OTel `LoggerProvider`; project helper `log.info(event=..., **attrs)` | Sentry Logs (correlated by `trace_id`) | Datadog Logs (correlated by `trace_id`) |
| Tagging (`job_id`, `ticker`, …) | `span.set_attribute(...)` once | Visible as span tags / scope | Visible as span tags / log attrs |
| Cross-cloud correlation | `trace_id` propagates via `traceparent` | One unified trace in Sentry | One unified trace in Datadog |

**Why span attributes for "metrics"?** Sentry deprecated standalone custom metrics in late 2024; the modern path on both vendors is "derive metrics from spans." Treating span attributes as the canonical metric channel means a single `span.set_attribute("llm.tokens.input", n)` call lights up in both vendor UIs.

**No feature loss in either configuration.** A Sentry-only deployment gets distributed traces (Sentry Performance), metrics (Sentry Insights), errors, and logs. A Datadog-only deployment gets the same set via Datadog's surfaces. Same code path either way.

### 7.3 NextJS wiring

```
lib/observability/
├── otel.ts             # OTel SDK init; reads env and registers exporters
├── api.ts              # traced(), recordError(), addAttrs() — what app code calls
└── exporters/
    ├── sentry.ts       # Initializes @sentry/nextjs in OTel mode iff SENTRY_DSN_NEXTJS set
    └── datadog.ts      # Initializes dd-trace as OTel provider iff DD_API_KEY set
```

`otel.ts` registers both exporters when their vars are set — they run in parallel. App code:

```ts
import { traced, recordError, addAttrs } from "@/lib/observability/api";

export async function POST(req: Request) {
  return traced("api.jobs.post", { route: "POST /api/jobs" }, async (span) => {
    const { ticker } = await req.json();
    addAttrs(span, { ticker });
    try {
      const jobId = await insertJob(ticker);
      const sandboxId = await spawnAnalysisSandbox(jobId, span);
      addAttrs(span, { job_id: jobId, sandbox_id: sandboxId, outcome: "accepted" });
      return Response.json({ jobId });
    } catch (e) {
      recordError(span, e);
      throw e;
    }
  });
}
```

Source maps are uploaded in CI when `SENTRY_AUTH_TOKEN` is set; the upload step is a no-op otherwise. No Sentry-specific code lives in routes.

### 7.4 Python agent wiring

`lib/observability.py` exposes three functions:

```python
def init_observability(job_id: str) -> None:
    """
    1. Build OTel TracerProvider, MeterProvider, LoggerProvider.
    2. Install auto-instrumentation for httpx, psycopg, openai, logging.
    3. If SENTRY_DSN_AGENT set: initialize sentry-sdk[opentelemetry] and
       attach it to the OTel pipeline (per the SDK's current OTel guide).
       Sentry receives spans/errors via OTel; no code path changes.
    4. If DD_API_KEY set: configure ddtrace as an OTel-compatible exporter
       (or wire an OTLP exporter at the Datadog Agent endpoint).
    5. Read TRACEPARENT env var via OTel's propagator; set it as the active
       OTel context so the span tree continues across cloud boundaries.
    6. Set job_id as a resource attribute (every span/log/error inherits it).
    """

def record_error(span, exc: Exception) -> None:
    """Vendor-neutral: span.record_exception(); span.set_status(ERROR).
       Both Sentry and Datadog auto-pick this up as an error event."""

def flush_observability(timeout_s: float = 5.0) -> None:
    """Called from the agent.py finally block. Drains every active exporter
       before the VM is deleted:
         - OTel TracerProvider.shutdown(timeout_s)
         - OTel MeterProvider.shutdown(timeout_s)
         - OTel LoggerProvider.shutdown(timeout_s)
         - sentry_sdk.flush(timeout_s)   # iff Sentry initialized
         - ddtrace.tracer.shutdown(timeout_s)   # iff Datadog initialized
       Without this, events die with the VM. This is the most important
       function in the file."""
```

### 7.5 Custom span attributes (the metrics surface)

Both backends derive metrics from these. Instrument once; vendor surfaces them in its own UI.

| Span | Attributes |
|---|---|
| `api.jobs.post` | `job_id`, `ticker`, `user_id`, `outcome` (`accepted`/`rejected`) |
| `daytona.create.sandbox` | `job_id`, `snapshot`, `spawn_ms`, `outcome` |
| `agent.run` | `job_id`, `ticker`, `final_status`, `duration_ms` |
| `llm.analyze` | `model`, `tokens_in`, `tokens_out`, `cost_usd`, `tool_calls` |
| `db.update.job` | `job_id`, `from_status`, `to_status` |
| `sandbox.self_delete` | `job_id`, `outcome` |

### 7.6 Span tree (one trace, either vendor)

```
api.jobs.post                               (NextJS)
├── db.insert.jobs
└── daytona.create.sandbox
        ↓  (W3C traceparent crosses cloud)
        agent.run                            (Python)
        ├── db.select.job
        ├── db.update.job (running)
        ├── llm.analyze
        │   ├── openai.request
        │   └── tool.web_search
        ├── db.update.job (complete)
        └── sandbox.self_delete
```

This is the same trace in Sentry Performance and in Datadog APM — the OTel `trace_id` is identical, the structure is identical.

### 7.7 Logs

- Agent writes structured JSON to stdout via a Python `logging` handler bridged to OTel `LoggerProvider` (`{event, job_id, ticker, trace_id, ...}`).
- OTel `LogsRecorder` ships them through whichever exporter is active:
  - Sentry: routed to Sentry Logs, correlated to spans by `trace_id`.
  - Datadog: routed to Datadog Logs, same correlation.
- Stdout itself is preserved as a fallback — Daytona captures sandbox stdout, viewable in the Daytona dashboard.

### 7.8 The `jobs` table is the cross-cloud audit trail

Independent of any observability backend, every state transition is recorded in Postgres with timestamps; `sandbox_id` ties to Daytona logs; `error` holds the traceback. This survives even when neither Sentry nor Datadog is configured — and is also the local-dev story (no vendor account required to debug).

## 8. Error handling

| Failure | Where caught | Handling |
|---|---|---|
| Invalid ticker (`"foo!"`) | NextJS `/api/jobs` validation | 400; no row, no sandbox |
| Neon insert fails | NextJS `/api/jobs` | 500; observability records error via OTel span (surfaces in whichever backend is configured); no sandbox spawned |
| Daytona spawn fails | NextJS `/api/jobs` | Row → `status='failed'` with `error='sandbox_spawn_failed: ...'`; client sees on next poll; OTel span marked error |
| Sandbox boots but agent crashes | `agent.py` top-level try/except | Writes traceback to `error`; marks `failed`; `record_error(span, e)` (vendor-neutral); still flushes + self-deletes |
| LLM API errors (rate limit, 5xx) | `tenacity` retry in `lib/llm.py` | 3 retries with exponential backoff (1s, 4s, 16s); if still failing → re-raise → agent crash path |
| Sandbox hangs (LLM never returns) | Daytona `autoDeleteInterval=600` | Hard-killed after 10min; row stays `running` |
| Stuck `running` rows | `/api/cleanup` sweep (cron or manual) | Older than 10min → `status='failed'`, `error='timeout'` |
| Neon connection from sandbox fails | Agent crashes before `mark_running` | Row stays `pending`; cleanup sweep flips it to `failed` after timeout |
| Self-delete API call fails | `agent.py` `finally` | Sandbox keeps running until `autoDeleteInterval`; logged but non-fatal |
| Two sandboxes process the same job | Idempotency guard in `agent.py` | Second sees `status != 'pending'` and exits without writing |

**Concrete rules baked in:**

- Every NextJS API route wraps its body in try/catch and returns `{ error: string }` with a 4xx/5xx — never throws to the framework's default handler.
- Every `mark_*` DB function uses `UPDATE ... WHERE status IN (...)` so terminal states are never overwritten.
- `tenacity` only retries transient errors, not 4xx.

## 9. Testing

| Layer | Test | Tool |
|---|---|---|
| Schema/migrations | Apply migration to a throwaway Neon branch in CI, `pg_dump --schema-only`, snapshot-compare | `pg_dump` + git diff |
| NextJS API | Integration tests against a Neon branch. **Mock the Daytona SDK** (CI must not spawn sandboxes). Assert: valid ticker → row inserted + spawn called; invalid → 400; status reflects DB state. | `vitest` + `msw` |
| `lib/llm.py` Pydantic schema | Unit: feed canned LLM responses, assert `Analysis` parses; malformed JSON raises | `pytest` |
| `agent.py` end-to-end | Integration: stub `LLMClient` with a fake; run `main()` against a Neon branch; assert row transitions `pending → running → complete` with the right payload. | `pytest` |
| Full smoke (manual + optional nightly) | Real ticker, real OpenAI, real Daytona, real Neon — one end-to-end run | Shell script |

**Neon branches** are the test secret weapon: each test run gets a fresh branch (copy-on-write), torn down at the end. ~1s to create. Worth mentioning to clients as itself a reference-architecture point.

**Skipped on purpose:** load tests, contract tests between sandbox and NextJS (they only talk through the DB, which Drizzle + Pydantic already validate), and full e2e in the main CI loop (slow, flaky, costs tokens).

## 10. Local development

For a reference arch, "new dev runs it in 10 minutes" matters.

- No `docker compose` — Neon and Daytona are hosted; only NextJS runs locally (`pnpm dev`).
- A `make snapshot` target builds and publishes the Daytona snapshot.
- `.env.example` lists every required var with comments.
- A `make seed` target creates a Neon dev branch and applies `0001_init.sql`.

## 11. Out of scope (intentional YAGNI)

- Real authentication (schema is multi-user-ready; auth provider is not wired)
- Persistent agent state / memory across runs
- Multi-step agent loops (planner → researcher → analyst)
- Cost budgeting per user
- Rate limiting / abuse prevention
- Streaming the LLM output to the UI as it generates
- Vercel deploy automation
- Production Daytona quota / region failover

## 12. Open questions

None that block implementation. The following are deferred design decisions, not unknowns:

- Which Anthropic/Gemini client to add second when we want to demo provider-swap.
- Whether the `result` JSONB shape should be promoted to dedicated columns once we stop changing it.
- Whether to add a `job_events` append-only table for richer step-level telemetry.
