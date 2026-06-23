---
title: Local Agent Runtime — Design
date: 2026-06-23
status: draft
purpose: Add a no-Daytona local mode for running the Python agent, switchable via env var
---

# Local Agent Runtime

## 1. Purpose

Let developers run the full job lifecycle end-to-end **without provisioning Daytona**, by spawning the existing Python agent as a local child process from the NextJS API. Useful for:

- Onboarding (no Daytona account required to see the app work)
- Iterating on the agent's Python code without rebuilding the snapshot on every change
- Demoing on a plane / behind a corporate firewall / in CI

This is **additive**. Daytona stays the default and the production-shaped path. Local mode is an opt-in development convenience, not a replacement.

## 2. Decisions

| # | Decision | Choice | Why |
|---|---|---|---|
| D1 | Switch shape | `AGENT_RUNTIME=daytona\|subprocess`, default `daytona` | Existing setups keep working with zero change; the descriptive name signals "this picks which runtime executes the agent" |
| D2 | Local exec model | NextJS spawns `python agent/agent.py` as a detached subprocess | Mirrors the prod path: same UI flow, same DB polling, same env-var contract |
| D3 | Python interpreter | Always use `agent/.venv` (Windows `Scripts/python.exe` or POSIX `bin/python`) | One unambiguous interpreter; fails fast with an actionable error if missing |
| D4 | sandbox_id | Synthetic `local-<jobId>` | Keeps the column populated so admin page renders unchanged; `local-` prefix is a guard `self_delete` can detect |
| D5 | Subprocess stdio | `agent/.runs/<jobId>.log` | Persistent per-job log, no terminal noise, easy `tail -f` for debugging |
| D6 | Standalone CLI | `agent/analyze.py <TICKER>` driver | Lets Python devs iterate on the agent without `pnpm dev` in the loop |
| D7 | Test coverage | Unit (dispatcher + subprocess builder) + real-Python integration | High confidence on the new path; integration test mocks the LLM via `OPENAI_API_URL` to stay free/deterministic |

## 3. Architecture

```
app/api/jobs/route.ts
        │
        └─► lib/runtime/index.ts (dispatcher)
                ├─► AGENT_RUNTIME=daytona     → lib/daytona.ts (existing, unchanged)
                └─► AGENT_RUNTIME=subprocess  → lib/runtime/subprocess.ts (new)
                                                       │
                                                       └─► spawn agent/.venv python
                                                              agent/agent.py
                                                              stdio → agent/.runs/<jobId>.log
```

Both runners share the signature `(jobId: string, parentSpan: Span) => Promise<string>` and return the value to write into `jobs.sandbox_id`. The route writes the row, calls the dispatcher, updates `sandbox_id` — no further branching at the route level.

The W3C-traceparent injection helper (`ensurePropagator()`) and `forwardIfSet()` / `datadogBlockIfEnabled()` move out of `lib/daytona.ts` into `lib/runtime/env.ts` so both runners share them.

## 4. Subprocess runner internals

`lib/runtime/subprocess.ts:spawnAnalysisSubprocess(jobId, parentSpan)`:

1. **Resolve Python**: pick `<repo>/agent/.venv/Scripts/python.exe` on Windows, else `bin/python`. If absent, throw `Error('agent venv not found — run pip install -r agent/requirements.txt in agent/.venv')`.

2. **Build env**:
   - Required: `JOB_ID`, `NEON_DATABASE_URL`, `OPENAI_API_KEY`
   - Trace: `TRACEPARENT` injected via the shared propagator helper
   - Forwarded if set: `OPENAI_API_URL`, `OPENAI_MODEL`, `SENTRY_DSN_AGENT`, `DD_*` block
   - **Not** forwarded: `DAYTONA_API_KEY` (local mode has no sandbox to delete)

3. **Open log file**: `mkdir -p agent/.runs/`, then `fs.openSync('agent/.runs/<jobId>.log', 'a')` to get an fd.

4. **Spawn detached**:
   ```ts
   const child = spawn(pythonPath, ['agent.py'], {
     cwd: path.join(repoRoot, 'agent'),
     env,
     stdio: ['ignore', logFd, logFd],
     detached: true,
   });
   child.unref();
   ```

5. **Return** `'local-' + jobId`.

## 5. Standalone Python driver

`agent/analyze.py` — iterate on the agent without NextJS.

```powershell
cd agent
.\.venv\Scripts\Activate.ps1
python analyze.py AAPL
```

Behavior:

- Args: positional `ticker`, `--wait/--no-wait` (default wait).
- Validates `^[A-Z]{1,5}$`.
- Connects to Neon via `lib/db._conn()`.
- `INSERT INTO jobs (ticker) VALUES (...) RETURNING id` → `job_id`.
- Sets `os.environ['JOB_ID']` + `os.environ.setdefault('DAYTONA_SANDBOX_ID', f'local-{job_id}')`.
- Calls `agent.main()` directly (in-process).
- If `--wait`: polls the row, prints final `result` (or `error`) as JSON. Exit 0 on `complete`, 1 on `failed`.

Discoverability: `make agent-local TICKER=AAPL` runs the driver via the venv's Python so Windows users without an activated venv can still kick it off.

## 6. self_delete guard

`agent/lib/self_delete.py` gets one line:

```python
if sid and sid.startswith('local-'):
    return
```

Prevents a bogus DELETE against the Daytona API in case a local run somehow has `DAYTONA_API_KEY` in its env (e.g. inherited from the shell).

## 7. Configuration

`.env.example` gains:

```
# Agent runtime: 'daytona' (default) or 'subprocess' (run the Python agent as a local child process)
AGENT_RUNTIME=daytona
```

README updates:

- New section "HOW-TO: Run the agent locally (without Daytona)" with the `AGENT_RUNTIME=subprocess` flow and the `analyze.py` driver.
- Configuration reference table gains `AGENT_RUNTIME`.
- Daytona prerequisite note: not required when `AGENT_RUNTIME=subprocess`.

`.gitignore` gains `agent/.runs/`.

## 8. Tests

**Dispatcher unit** (`tests/runtime.test.ts`):
- `AGENT_RUNTIME` unset → daytona runner is called.
- `AGENT_RUNTIME=daytona` → same.
- `AGENT_RUNTIME=subprocess` → subprocess runner is called.
- Unknown value → throws.

**Subprocess builder unit** (`tests/runtime.subprocess.test.ts`):
- Mocks `child_process.spawn` + `fs`. Asserts argv, cwd, env keys, `detached: true`, `unref()` called.
- Asserts returns `'local-' + jobId`.
- Asserts throws when the venv Python is absent.

**Real-Python integration** (`tests/runtime.subprocess.integration.test.ts`):
- Skipped unless `NEON_DATABASE_URL` and `OPENAI_API_KEY` are set.
- Stands up a local Vitest HTTP server that returns a canned `output_text` matching the `Analysis` schema; sets `OPENAI_API_URL` to its address. No real LLM call.
- Inserts a pending row via drizzle, calls `spawnAnalysisSubprocess(jobId, span)`, polls up to 30s.
- Asserts `status='complete'`, `recommendation in {buy,hold,sell}`, `sandbox_id='local-<jobId>'`, log file exists.
- `afterEach` deletes the row.

## 9. Out of scope

- A long-lived local worker that polls the jobs table (would be a much bigger change; the subprocess model already covers the use case).
- Auto-installing the agent venv from NextJS — venv setup remains a one-time manual step documented in the README.
- Process tracking / kill from the admin page — the existing `cleanup` endpoint already sweeps stuck rows.
- Forwarding container/sandbox lifecycle hooks (start/stop times) to OTel from the subprocess path — same trace ID flows through `TRACEPARENT`, that's enough for the demo.

## 10. Files touched / added

| Path | Change |
|---|---|
| `lib/runtime/index.ts` | **new** — dispatcher |
| `lib/runtime/subprocess.ts` | **new** — subprocess runner |
| `lib/runtime/env.ts` | **new** — shared env helpers (propagator, forwardIfSet, datadog block) |
| `lib/daytona.ts` | refactor: keep `spawnAnalysisSandbox`, import shared helpers from `lib/runtime/env.ts` |
| `app/api/jobs/route.ts` | replace `spawnAnalysisSandbox` import with `spawnAgent` from dispatcher |
| `agent/analyze.py` | **new** — standalone CLI |
| `agent/lib/self_delete.py` | one-line guard for `local-` prefix |
| `tests/runtime.test.ts` | **new** |
| `tests/runtime.subprocess.test.ts` | **new** |
| `tests/runtime.subprocess.integration.test.ts` | **new** |
| `.env.example` | add `AGENT_RUNTIME=daytona` |
| `.gitignore` | add `agent/.runs/` |
| `Makefile` | add `agent-local` target |
| `README.md` | new HOW-TO section + config table update |
