# Daytona Stock-Agent Demo

A reference architecture for **short-lived AI agents hosted in Daytona sandboxes**. A user submits a stock ticker in a NextJS app; an ephemeral Daytona VM is spawned, runs an OpenAI agent that produces a buy/hold/sell analysis, writes the result to Neon Postgres, and self-deletes. The browser polls Neon until the analysis is ready.

> ⚠️ **Not financial advice. Demo only.** The LLM output is shown to users behind a disclaimer.

## Architecture at a glance

```
Browser ──► NextJS API ──► Neon (jobs row, status='pending')
              │
              └─► Daytona  ──► ephemeral VM boots
                              └─► reads job row from Neon
                              └─► OpenAI Responses API + web_search tool
                              └─► writes result + status='complete' to Neon
                              └─► self-deletes
Browser polls /api/status/[id] every 2.5s → NextJS reads Neon → UI renders
```

Observability is **OpenTelemetry-first**. Set `SENTRY_DSN_*`, `DD_API_KEY`, both, or neither — application code never changes. Same trace appears in whichever backend is configured.

## Prerequisites

| Tool | Version | Why |
|---|---|---|
| Node.js | 20+ | NextJS 16 runtime |
| pnpm | 9+ | Package manager |
| Python | 3.12+ | Agent runtime (also inside the sandbox) |
| Docker | any recent | Build the Daytona snapshot image |

Accounts (all have free tiers):

| Service | Required | What you need |
|---|---|---|
| [Neon](https://neon.tech) | yes | A project + the connection string |
| [Daytona](https://www.daytona.io) | yes | An API key + the CLI installed locally |
| [OpenAI](https://platform.openai.com) | yes | An API key with Responses API + `web_search` tool access |
| [Sentry](https://sentry.io) | optional | One project for NextJS, one for the Python agent |
| [Datadog](https://www.datadoghq.com) | optional | An API key for the chosen site (US/EU/etc.) |

## Quickstart

```powershell
git clone <this-repo>
cd daytona_demo

cp .env.example .env       # then fill in the required vars (see Configuration below)

pnpm install
make seed                  # apply migrations to your Neon project
make snapshot              # build & publish the Daytona snapshot

pnpm dev                   # http://localhost:3000
```

Submit `AAPL` in the form and wait ~30–90s.

## Configuration reference

All variables live in `.env`. `.env.example` is the source of truth — keep it in sync when adding new ones.

### Required

| Var | Source | Example | What breaks without it |
|---|---|---|---|
| `NEON_DATABASE_URL` | Neon dashboard → Connection string | `postgresql://user:pass@ep-…neon.tech/neondb` | DB calls fail everywhere |
| `OPENAI_API_KEY` | OpenAI dashboard → API Keys | `sk-proj-…` | Agent crashes when it tries to call the LLM |

### Required when `AGENT_RUNTIME=daytona` (the default)

| Var | Source | Example | What breaks without it |
|---|---|---|---|
| `DAYTONA_API_KEY` | Daytona dashboard → API Keys | `dt_abc…` | Spawn fails → 500 on submit |
| `DAYTONA_TARGET` | Daytona dashboard | `us` | Region defaults may misroute the spawn |

Set `AGENT_RUNTIME=subprocess` in `.env` to skip Daytona entirely (see *HOW-TO: Run the agent locally without Daytona* below).

### Optional — OpenAI-compatible endpoint

| Var | What it does |
|---|---|
| `OPENAI_API_URL` | Override the OpenAI base URL to point at any OpenAI-compatible endpoint (Azure OpenAI, OpenRouter, vLLM, LiteLLM, local server, …). Unset → defaults to `https://api.openai.com/v1`. Forwarded into the sandbox only when set. |
| `OPENAI_MODEL` | Override the model the agent calls. Unset → defaults to `gpt-4.1-mini`. Must be supported by whichever endpoint `OPENAI_API_URL` points at. Forwarded into the sandbox only when set. |
| `OPENAI_USE_RESPONSES_API` | Unset or `true` (default): use OpenAI's Responses API + hosted `web_search` tool. `false`: use `chat.completions` without `web_search`. **Set this to `false` for any non-OpenAI endpoint** (Ollama, vLLM, LiteLLM, OpenRouter, Azure) — most only implement `/v1/chat/completions`. Without `web_search` the model relies on its training-cutoff knowledge of the ticker. Forwarded into the sandbox only when set. |

### Optional — Agent runtime

| Var | What it does |
|---|---|
| `AGENT_RUNTIME` | `daytona` (default) spawns the agent in a Daytona sandbox. `subprocess` runs the Python agent as a detached local child process (no Daytona account needed). Unknown values cause the API route to throw on the next submit. |

### Optional — Sentry block (omit entirely to disable Sentry)

| Var | What it does |
|---|---|
| `SENTRY_DSN_NEXTJS` | DSN for the NextJS Sentry project |
| `SENTRY_DSN_AGENT` | DSN for the Python agent Sentry project (separate project recommended) |
| `SENTRY_AUTH_TOKEN` | Source-map upload during CI; not needed at runtime |

### Optional — Datadog block (omit entirely to disable Datadog)

| Var | What it does |
|---|---|
| `DD_API_KEY` | Master switch for Datadog. If unset, Datadog is fully disabled. |
| `DD_SITE` | `datadoghq.com` / `datadoghq.eu` / `us3.datadoghq.com` / etc. |
| `DD_SERVICE` | Service name in Datadog. `stock-agent-frontend` for NextJS; `stock-agent` is forced inside the sandbox. |
| `DD_ENV` | `development` / `staging` / `production` |
| `DD_TRACE_ENABLED` | `false` short-circuits dd-trace initialization (NextJS + agent). Use when running locally without a Datadog Agent on `localhost:8126` to silence the "failed to send, dropping N traces" warnings. Leave unset/`true` to ship traces. |
| `DD_EXPORTER` | **Python agent only.** `agent` (default) → ddtrace + local Datadog Agent on `localhost:8126`. `otlp` → OTLP HTTP exporter ships directly to Datadog's intake (no Agent needed — ideal for Daytona sandboxes). With `otlp`, you lose ddtrace's auto-instrumentation (httpx/psycopg/openai/logging) and only the explicit OTel spans we create get shipped. NextJS continues to use dd-trace regardless. |
| `DD_OTLP_ENDPOINT` | Required when `DD_EXPORTER=otlp`. The exact OTLP HTTP intake URL (Datadog has shifted this path across documentation versions — copy it from your account's OTLP-ingest page). The agent posts span batches to this URL with a `DD-API-KEY` header. |

## HOW-TO: Provision Neon

1. Sign up at [neon.tech](https://neon.tech) and create a project.
2. Open the project → **Connection details** → copy the connection string.
3. Paste it into `.env` as `NEON_DATABASE_URL=…`.
4. Apply the migrations:
   ```powershell
   make seed
   ```
5. Verify the table exists in the Neon SQL Editor:
   ```sql
   SELECT table_name FROM information_schema.tables WHERE table_schema='public';
   ```
   You should see `jobs`.

## HOW-TO: Run the agent locally (without Daytona)

For onboarding, demos behind a corporate firewall, or fast iteration on the Python agent without rebuilding the snapshot.

1. Create a Python venv at `agent/.venv` and install the agent's deps:
   ```powershell
   cd agent
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   cd ..
   ```
   (POSIX: `python3 -m venv .venv` and `source .venv/bin/activate`.)

2. In `.env`, set:
   ```
   AGENT_RUNTIME=subprocess
   ```
   You can leave `DAYTONA_API_KEY` and `DAYTONA_TARGET` blank in this mode.

3. Run the app as usual:
   ```powershell
   pnpm dev
   ```
   Submit a ticker on `http://localhost:3000`. NextJS will spawn `python agent/agent.py` as a detached subprocess instead of calling Daytona. The job row gets `sandbox_id='local-<jobId>'` and the polling UI works unchanged.

4. Agent logs go to `agent/.runs/<jobId>.log`. Tail one with:
   ```powershell
   Get-Content -Wait agent\.runs\<jobId>.log
   ```
   (POSIX: `tail -f agent/.runs/<jobId>.log`.)

### Iterating on the agent without NextJS

For Python-only iteration, use the standalone driver:

```powershell
cd agent
.\.venv\Scripts\Activate.ps1
python analyze.py AAPL
```

Or from the repo root:
```powershell
make agent-local TICKER=AAPL
```

The driver inserts a pending row, runs `agent.main()` in-process, and prints the final result row as JSON. Exit code is 0 on `complete`, 1 on `failed`, 2 on bad args.

## HOW-TO: Provision Daytona

1. Sign up at [daytona.io](https://www.daytona.io) and create an API key.
2. Install the Daytona CLI per the [docs](https://www.daytona.io/docs/getting-started/installation/).
3. `daytona login` — authenticate with the API key when prompted.
4. Add the key to `.env`:
   ```
   DAYTONA_API_KEY=…
   DAYTONA_TARGET=us
   ```
5. Build and publish the snapshot:
   ```powershell
   make snapshot
   ```
6. Verify the snapshot is published:
   ```powershell
   daytona snapshot list
   ```
   `stock-agent:latest` should appear.

## HOW-TO: Get an OpenAI key

1. Sign up at [platform.openai.com](https://platform.openai.com).
2. **Settings → API keys → Create new secret key.**
3. Make sure your account has access to the **Responses API** and the **`web_search` built-in tool**.
4. Add to `.env`:
   ```
   OPENAI_API_KEY=sk-…
   ```

The agent uses the model `gpt-4.1-mini` by default with the `web_search` tool. Expected cost per analysis: ~$0.05–$0.20.

To route requests to an OpenAI-compatible endpoint instead, set `OPENAI_API_URL` in `.env` (e.g. `https://my-proxy.example.com/v1`). The agent passes it as the SDK's `base_url`; the model name and `web_search` tool must be supported by the target endpoint. Set `OPENAI_MODEL` in `.env` to pick a different model (e.g. `gpt-4.1`, `gpt-4o`, or a model name your endpoint recognizes).

For endpoints that don't implement the Responses API (Ollama, vLLM, LiteLLM, OpenRouter, Azure, …), also set `OPENAI_USE_RESPONSES_API=false`. The agent then uses `chat.completions` and drops the `web_search` tool — the model will rely on its training-cutoff knowledge of the ticker rather than live web data.

## HOW-TO: Enable Sentry only

1. Create two Sentry projects: one for the NextJS frontend, one for the Python agent.
2. Copy each project's DSN.
3. Add to `.env` (omit the Datadog block entirely):
   ```
   SENTRY_DSN_NEXTJS=https://…@oN.ingest.sentry.io/N
   SENTRY_DSN_AGENT=https://…@oN.ingest.sentry.io/M
   ```
4. Restart `pnpm dev` so NextJS picks up the env vars.
5. Submit a ticker. Within ~30s the trace appears in **Sentry Performance** of the NextJS project, and once the sandbox runs, a linked child trace appears in the agent project.
6. To verify error capture, set the OpenAI key to garbage temporarily and submit. The crash appears in **Sentry Issues** of the agent project with the full traceback.

## HOW-TO: Enable Datadog only

1. Get your Datadog API key from **Organization Settings → API Keys**.
2. Add to `.env` (omit the Sentry block entirely):
   ```
   DD_API_KEY=…
   DD_SITE=datadoghq.com
   DD_SERVICE=stock-agent-frontend
   DD_ENV=development
   ```
3. Restart `pnpm dev`.
4. Submit a ticker. In Datadog APM → Service Catalog you should see `stock-agent-frontend` and (once the agent runs) `stock-agent` with a unified trace tying them together via the W3C `traceparent`.
5. Custom span attributes (`tokens_in`, `tokens_out`, `cost_usd`, `ticker`, `recommendation`) appear as tags on each span.

### Datadog transport: Agent vs. OTLP direct

`dd-trace` defaults to shipping traces to a local Datadog Agent on `localhost:8126`. Three choices for where that Agent lives:

| Choice | When | What to set |
|---|---|---|
| Local Agent | You run `gcr.io/datadoghq/agent` via Docker, or install the Agent on your host | Default. No extra env vars. |
| Remote shared Agent | You host one Agent (a small VM, Fly machine, ECS task) that all sandboxes ship to | `DD_AGENT_HOST=<host>` + `DD_TRACE_AGENT_PORT=8126`. *Not yet forwarded into the sandbox env — add `forwardIfSet` calls in `lib/daytona.ts` if you go this route.* |
| **No Agent (OTLP direct)** | You don't want to host any Agent. Works inside Daytona sandboxes too. **Python agent only — NextJS still uses dd-trace.** | `DD_EXPORTER=otlp` + `DD_OTLP_ENDPOINT=<your Datadog OTLP HTTP intake URL>` |

**To run the Python agent without any Datadog Agent:**

1. Set in `.env`:
   ```
   DD_API_KEY=…
   DD_SITE=datadoghq.com
   DD_EXPORTER=otlp
   DD_OTLP_ENDPOINT=<copy the exact URL from Datadog's "OpenTelemetry → Direct ingest" docs for your account>
   ```
2. Restart `pnpm dev`. The Python agent will register an OTLP HTTP span exporter (with a `DD-API-KEY` header) instead of calling `ddtrace.patch_all()`.
3. **Trade-off:** in OTLP mode, only the explicit OTel spans the agent creates (`agent.run`, `llm.analyze`) reach Datadog. dd-trace's auto-instrumentation (httpx, psycopg, openai, logging) is skipped. You see fewer spans per trace; the parent/child structure is the same.
4. To test both transports locally, leave `DD_EXPORTER` unset while you have an Agent on `localhost:8126`, then flip to `DD_EXPORTER=otlp` to verify the agentless path.

## HOW-TO: Enable both

Set both blocks. There is no flag — both are wired in parallel based on which env vars are present. Same instrumentation, two destinations. Useful when migrating between vendors or running A/B for a stakeholder review.

## HOW-TO: Run with no observability backend

Leave both blocks empty. OTel runs in no-op mode; the demo still works end-to-end. Use the **`/admin` page** and the `jobs` table directly as the audit trail. The `error` column holds the full traceback on failures; `sandbox_id` links each job to the Daytona dashboard logs.

## Running the app

```powershell
pnpm dev
```

- `http://localhost:3000` — submit form + recent jobs
- `http://localhost:3000/jobs/<id>` — single-job detail with live polling
- `http://localhost:3000/admin` — operator view (all jobs, durations, errors)

## Running the tests

NextJS tests (mock the Daytona SDK and Neon):

```powershell
pnpm test
```

Python agent tests:

```powershell
cd agent
.\.venv\Scripts\Activate.ps1
pytest
```

Several Python tests require `NEON_DATABASE_URL` and will skip cleanly if it's not set:

```powershell
$env:NEON_DATABASE_URL = "postgresql://..."
pytest
```

## Running the end-to-end smoke

In one terminal:
```powershell
pnpm dev
```

In another (Git Bash or WSL — the script is bash):
```bash
./scripts/smoke.sh AAPL
```

Expected: `pending → running → complete` over ~30–90 seconds, then the script prints the full JSON result.

## Operating the demo

| Task | How |
|---|---|
| See all jobs | `http://localhost:3000/admin` |
| Sweep stuck `running` rows older than 10min | `curl -X POST http://localhost:3000/api/cleanup` |
| Inspect a specific sandbox's logs | Daytona dashboard → Sandboxes → search by the `sandbox_id` from the job row |
| Wipe all demo data | `psql $NEON_DATABASE_URL -c "TRUNCATE jobs;"` |

## Troubleshooting

### Submit returns 500 with `spawn_failed`
- **Symptom:** `/api/jobs` returns 500; the job row has `status='failed'` and `error='sandbox_spawn_failed: ...'`.
- **Cause:** `DAYTONA_API_KEY` invalid, Daytona quota exceeded, or the `stock-agent:latest` snapshot was never published.
- **Fix:** Run `daytona snapshot list` and verify `stock-agent:latest` exists. If not, `make snapshot`. If the key is the issue, regenerate it in the Daytona dashboard.

### Job stuck in `pending` forever
- **Symptom:** UI shows spinner for minutes; the row is `pending` and `sandbox_id` is set.
- **Cause:** The sandbox spawned but the agent never marked `running` — usually a Neon connectivity issue from inside the sandbox.
- **Fix:** Check Daytona logs for the sandbox. Verify the sandbox got the `NEON_DATABASE_URL` env var. Confirm Neon allows connections from the Daytona network.

### Job stuck in `running` forever
- **Symptom:** Row is `running` for > 10min.
- **Cause:** OpenAI hang, or the agent crashed *between* `mark_running` and the LLM call without the `except` block running.
- **Fix:** `curl -X POST http://localhost:3000/api/cleanup` — sweeps rows older than 10min into `failed` with `error='timeout'`. The Daytona `autoDeleteInterval=600` kills the sandbox on its own.

### LLM returns invalid JSON
- **Symptom:** Job goes `running → failed`; `error` starts with `ValueError: LLM did not return valid JSON`.
- **Cause:** The model wrapped its output in markdown, added a preamble, or hallucinated extra prose.
- **Fix:** Inspect the row's `error` and the sandbox logs. The fix is usually a prompt tweak in `agent/lib/prompts.py`. The `parse_response()` helper already strips ` ```json ` fences — extend it if you find a new failure shape.

### Sentry / Datadog showing nothing
- **Symptom:** Backend is configured but no spans or events appear.
- **Cause (most common):** env vars set in your shell are not visible to NextJS because you didn't restart `pnpm dev` after editing `.env`. Or, for the agent, the env var isn't forwarded into the sandbox (check `lib/daytona.ts:datadogBlockIfEnabled` / `forwardIfSet`).
- **Fix:** Stop the dev server, confirm `process.env.SENTRY_DSN_NEXTJS` or `process.env.DD_API_KEY` is set in the shell launching `pnpm dev`, restart. For the sandbox side: submit a job, then check the Daytona dashboard for the sandbox's env vars.

### dd-trace logs "failed to send, dropping N traces to intake at http://localhost:8126"
- **Symptom:** Either NextJS or the Python agent logs the dropped-traces warning repeatedly. The app still works.
- **Cause:** `DD_API_KEY` is set, so dd-trace initializes and tries to ship traces to a local Datadog Agent on `localhost:8126`. No Agent is running there (typical when running with `AGENT_RUNTIME=subprocess` for local dev).
- **Fix:** Add `DD_TRACE_ENABLED=false` to `.env` (or your shell). Both runners (`lib/observability/exporters/datadog.ts` and `agent/lib/observability.py`) short-circuit when this is `false`, and it's forwarded into both the sandbox and the local subprocess. To keep Datadog active in Daytona-mode runs, leave it unset — only set it when iterating locally.

### Sandbox not self-deleting
- **Symptom:** Daytona dashboard shows lots of stopped-but-not-deleted sandboxes.
- **Cause:** `self_delete()` is intentionally swallowed-error code; a Daytona API hiccup will leave the sandbox until `autoDeleteInterval` expires (10min).
- **Fix:** This is expected — it's the safety net. If the count gets unwieldy, batch delete in the Daytona dashboard. If you see this constantly, check that `DAYTONA_API_KEY` is forwarded into the sandbox env (it must be, for self-delete to work).

### Local Neon migration fails
- **Symptom:** `make seed` errors with permission denied or table-already-exists.
- **Cause:** Wrong DB user, or you've already applied the migration and the `IF NOT EXISTS` guard is missing.
- **Fix:** The provided `0001_init.sql` uses `IF NOT EXISTS` clauses — re-running is safe. If permissions fail, use the Neon dashboard SQL editor to apply manually.

## Project layout

```
.
├── app/                  NextJS App Router pages and API routes
├── lib/                  NextJS shared code (db, daytona, observability)
├── components/           shadcn/ui + project components
├── agent/                Python agent — source for the Daytona snapshot
├── db/migrations/        SQL migrations applied by scripts/apply_migration.mts
├── scripts/              build_snapshot.sh, apply_migration.mts, smoke.sh
├── tests/                NextJS tests (vitest)
└── docs/superpowers/
    ├── specs/            Design documents
    └── plans/            Implementation plans
```

## Out of scope (intentional YAGNI)

- Real authentication (schema is multi-user-ready; auth provider is not wired)
- Persistent agent memory across runs
- Multi-step agent loops (planner → researcher → analyst)
- Cost budgeting per user
- Rate limiting / abuse prevention
- Streaming the LLM output to the UI as it generates
- Vercel deploy automation
- Production Daytona quota / region failover

Full rationale in `docs/superpowers/specs/2026-06-22-daytona-stock-agent-design.md` § 11.

## Where to dig deeper

- **Design / why it's built this way:** `docs/superpowers/specs/2026-06-22-daytona-stock-agent-design.md`
- **Implementation plan / how it was built:** `docs/superpowers/plans/2026-06-22-daytona-stock-agent.md`
