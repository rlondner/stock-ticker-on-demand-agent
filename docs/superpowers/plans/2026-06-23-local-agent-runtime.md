# Local Agent Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `AGENT_RUNTIME=daytona|subprocess` switch in the NextJS app so developers can run the existing Python agent as a local detached subprocess (no Daytona) for fast iteration and onboarding.

**Architecture:** A thin dispatcher (`lib/runtime/index.ts`) reads `AGENT_RUNTIME` and routes to either `lib/daytona.ts` (existing, unchanged behavior) or a new `lib/runtime/subprocess.ts`. Shared helpers (W3C propagator, env forwarders) move into `lib/runtime/env.ts`. The subprocess runner spawns `agent/.venv/{Scripts|bin}/python agent/agent.py` detached, writes stdout/stderr to `agent/.runs/<jobId>.log`, and returns a synthetic `local-<jobId>` sandbox id. A standalone `agent/analyze.py` CLI lets Python devs iterate without `pnpm dev`.

**Tech Stack:** Node 20 + Next 16, vitest, drizzle-orm + Neon, Python 3.12, OpenTelemetry, @opentelemetry/sdk-trace-base (test-only), child_process.spawn.

**Spec:** `docs/superpowers/specs/2026-06-23-local-agent-runtime-design.md`

---

## File map

**Create:**
- `lib/runtime/env.ts` — shared `ensurePropagator()`, `forwardIfSet()`, `datadogBlockIfEnabled()` (moved out of `lib/daytona.ts`)
- `lib/runtime/index.ts` — `spawnAgent(jobId, parentSpan)` dispatcher
- `lib/runtime/subprocess.ts` — `spawnAnalysisSubprocess(jobId, parentSpan)` runner
- `agent/analyze.py` — standalone CLI driver
- `tests/runtime.test.ts` — dispatcher unit tests
- `tests/runtime.subprocess.test.ts` — subprocess builder unit tests
- `tests/runtime.subprocess.integration.test.ts` — real-Python integration test

**Modify:**
- `lib/daytona.ts` — import shared helpers from `lib/runtime/env.ts`; remove the duplicated copies
- `app/api/jobs/route.ts` — swap `spawnAnalysisSandbox` import for `spawnAgent` from the dispatcher
- `agent/lib/self_delete.py` — add a one-line `local-` prefix guard
- `.env.example` — add `AGENT_RUNTIME=daytona`
- `.gitignore` — add `agent/.runs/`
- `Makefile` — add `agent-local` target
- `README.md` — new HOW-TO section + config table entry

---

## Task 1: Extract shared env helpers

Pull the W3C propagator, `forwardIfSet`, and `datadogBlockIfEnabled` out of `lib/daytona.ts` into a shared module so both runners can use them. This is a pure refactor — behavior must not change. Existing `tests/daytona.test.ts` exercises all three helpers, so it serves as our regression guard.

**Files:**
- Create: `lib/runtime/env.ts`
- Modify: `lib/daytona.ts`
- Test: `tests/daytona.test.ts` (existing — runs unchanged as the safety net)

- [ ] **Step 1: Run existing daytona tests to confirm green baseline**

Run: `pnpm test tests/daytona.test.ts`
Expected: 7 tests pass.

- [ ] **Step 2: Create the shared env helpers module**

Create `lib/runtime/env.ts`:

```ts
import { context, propagation, trace, type Span } from "@opentelemetry/api";
import { W3CTraceContextPropagator } from "@opentelemetry/core";

let _propagatorReady = false;
function ensurePropagator(): void {
  if (_propagatorReady) return;
  propagation.setGlobalPropagator(new W3CTraceContextPropagator());
  _propagatorReady = true;
}

export function injectTraceparent(parentSpan: Span): string {
  ensurePropagator();
  const carrier: Record<string, string> = {};
  propagation.inject(trace.setSpan(context.active(), parentSpan), carrier);
  return carrier.traceparent ?? "";
}

export function forwardIfSet(k: string): Record<string, string> {
  return process.env[k] ? { [k]: process.env[k]! } : {};
}

export function datadogBlockIfEnabled(): Record<string, string> {
  if (!process.env.DD_API_KEY) return {};
  return {
    DD_API_KEY: process.env.DD_API_KEY,
    DD_SITE: process.env.DD_SITE ?? "datadoghq.com",
    DD_SERVICE: "stock-agent",
    DD_ENV: process.env.DD_ENV ?? process.env.NODE_ENV ?? "development",
  };
}
```

- [ ] **Step 3: Rewrite `lib/daytona.ts` to use the shared helpers**

Replace the entire file with:

```ts
import { Daytona } from "@daytonaio/sdk";
import { type Span } from "@opentelemetry/api";
import { injectTraceparent, forwardIfSet, datadogBlockIfEnabled } from "./runtime/env";

let _dt: Daytona | undefined;
function client(): Daytona {
  if (!_dt) {
    const apiKey = process.env.DAYTONA_API_KEY;
    if (!apiKey) throw new Error("DAYTONA_API_KEY is not set");
    _dt = new Daytona({ apiKey });
  }
  return _dt;
}

export async function spawnAnalysisSandbox(jobId: string, parentSpan: Span): Promise<string> {
  const env: Record<string, string> = {
    JOB_ID: jobId,
    NEON_DATABASE_URL: process.env.NEON_DATABASE_URL!,
    OPENAI_API_KEY: process.env.OPENAI_API_KEY!,
    DAYTONA_API_KEY: process.env.DAYTONA_API_KEY!,
    TRACEPARENT: injectTraceparent(parentSpan),
    ...forwardIfSet("OPENAI_API_URL"),
    ...forwardIfSet("OPENAI_MODEL"),
    ...forwardIfSet("SENTRY_DSN_AGENT"),
    ...datadogBlockIfEnabled(),
  };

  const sandbox = await client().create({
    snapshot: "stock-agent:latest",
    envVars: env,
    autoStopInterval: 0,
    autoDeleteInterval: 600,
  });
  return sandbox.id;
}
```

- [ ] **Step 4: Run existing daytona tests to confirm refactor is behavior-preserving**

Run: `pnpm test tests/daytona.test.ts`
Expected: 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add lib/runtime/env.ts lib/daytona.ts
git commit -m "refactor: extract shared env helpers to lib/runtime/env.ts"
```

---

## Task 2: Dispatcher with failing tests

Write tests for the dispatcher first. The dispatcher reads `AGENT_RUNTIME` and routes to one of the two runners. Unknown values throw a clear error.

**Files:**
- Create: `tests/runtime.test.ts`
- Create: `lib/runtime/index.ts`

- [ ] **Step 1: Write the failing dispatcher tests**

Create `tests/runtime.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { trace } from "@opentelemetry/api";
import { BasicTracerProvider } from "@opentelemetry/sdk-trace-base";

const daytonaMock = vi.fn(async () => "sb-from-daytona");
const subprocessMock = vi.fn(async () => "local-from-subprocess");

vi.mock("@/lib/daytona", () => ({ spawnAnalysisSandbox: daytonaMock }));
vi.mock("@/lib/runtime/subprocess", () => ({ spawnAnalysisSubprocess: subprocessMock }));

trace.setGlobalTracerProvider(new BasicTracerProvider());

describe("spawnAgent dispatcher", () => {
  beforeEach(() => {
    delete process.env.AGENT_RUNTIME;
    daytonaMock.mockClear();
    subprocessMock.mockClear();
  });

  it("defaults to daytona when AGENT_RUNTIME is unset", async () => {
    const { spawnAgent } = await import("@/lib/runtime");
    const span = trace.getTracer("t").startSpan("p");
    const id = await spawnAgent("job-1", span);
    span.end();
    expect(daytonaMock).toHaveBeenCalledWith("job-1", span);
    expect(subprocessMock).not.toHaveBeenCalled();
    expect(id).toBe("sb-from-daytona");
  });

  it("dispatches to daytona when AGENT_RUNTIME=daytona", async () => {
    process.env.AGENT_RUNTIME = "daytona";
    const { spawnAgent } = await import("@/lib/runtime");
    const span = trace.getTracer("t").startSpan("p");
    await spawnAgent("job-2", span);
    span.end();
    expect(daytonaMock).toHaveBeenCalledWith("job-2", span);
    expect(subprocessMock).not.toHaveBeenCalled();
  });

  it("dispatches to subprocess when AGENT_RUNTIME=subprocess", async () => {
    process.env.AGENT_RUNTIME = "subprocess";
    const { spawnAgent } = await import("@/lib/runtime");
    const span = trace.getTracer("t").startSpan("p");
    const id = await spawnAgent("job-3", span);
    span.end();
    expect(subprocessMock).toHaveBeenCalledWith("job-3", span);
    expect(daytonaMock).not.toHaveBeenCalled();
    expect(id).toBe("local-from-subprocess");
  });

  it("throws on unknown AGENT_RUNTIME value", async () => {
    process.env.AGENT_RUNTIME = "kubernetes";
    const { spawnAgent } = await import("@/lib/runtime");
    const span = trace.getTracer("t").startSpan("p");
    await expect(spawnAgent("job-4", span)).rejects.toThrow(/unknown AGENT_RUNTIME/i);
    span.end();
  });
});
```

- [ ] **Step 2: Run dispatcher tests to confirm they fail**

Run: `pnpm test tests/runtime.test.ts`
Expected: All 4 tests fail with module-resolution errors for `@/lib/runtime`.

- [ ] **Step 3: Implement the dispatcher**

Create `lib/runtime/index.ts`:

```ts
import type { Span } from "@opentelemetry/api";
import { spawnAnalysisSandbox } from "@/lib/daytona";
import { spawnAnalysisSubprocess } from "@/lib/runtime/subprocess";

export async function spawnAgent(jobId: string, parentSpan: Span): Promise<string> {
  const runtime = process.env.AGENT_RUNTIME ?? "daytona";
  switch (runtime) {
    case "daytona":
      return spawnAnalysisSandbox(jobId, parentSpan);
    case "subprocess":
      return spawnAnalysisSubprocess(jobId, parentSpan);
    default:
      throw new Error(`unknown AGENT_RUNTIME=${runtime} (expected 'daytona' or 'subprocess')`);
  }
}
```

Note: `lib/runtime/subprocess.ts` doesn't exist yet. The dispatcher test mocks it via `vi.mock`, so the static `import` resolves against the mock — the file only needs to exist before the next task. We'll create it in Task 3.

- [ ] **Step 4: Create a minimal placeholder for subprocess.ts so the import resolves**

Create `lib/runtime/subprocess.ts`:

```ts
import type { Span } from "@opentelemetry/api";

export async function spawnAnalysisSubprocess(_jobId: string, _parentSpan: Span): Promise<string> {
  throw new Error("not implemented yet");
}
```

This placeholder gets fully replaced in Task 3.

- [ ] **Step 5: Run dispatcher tests to confirm they pass**

Run: `pnpm test tests/runtime.test.ts`
Expected: 4 tests pass.

- [ ] **Step 6: Confirm we haven't broken existing tests**

Run: `pnpm test`
Expected: All tests pass (existing + 4 new).

- [ ] **Step 7: Commit**

```bash
git add lib/runtime/index.ts lib/runtime/subprocess.ts tests/runtime.test.ts
git commit -m "feat(runtime): AGENT_RUNTIME dispatcher with placeholder subprocess runner"
```

---

## Task 3: Subprocess runner (TDD)

Implement the real subprocess runner. Mock `child_process.spawn` and `fs` so tests are fast and OS-agnostic.

**Files:**
- Modify: `lib/runtime/subprocess.ts` (replace the placeholder from Task 2)
- Create: `tests/runtime.subprocess.test.ts`

- [ ] **Step 1: Write the failing subprocess tests**

Create `tests/runtime.subprocess.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { trace } from "@opentelemetry/api";
import { BasicTracerProvider } from "@opentelemetry/sdk-trace-base";

const spawnMock = vi.fn();
const unrefMock = vi.fn();
const existsSyncMock = vi.fn();
const mkdirSyncMock = vi.fn();
const openSyncMock = vi.fn(() => 42);

vi.mock("node:child_process", () => ({ spawn: spawnMock }));
vi.mock("node:fs", () => ({
  existsSync: existsSyncMock,
  mkdirSync: mkdirSyncMock,
  openSync: openSyncMock,
}));

trace.setGlobalTracerProvider(new BasicTracerProvider());

describe("spawnAnalysisSubprocess", () => {
  beforeEach(() => {
    process.env.NEON_DATABASE_URL = "postgresql://test";
    process.env.OPENAI_API_KEY = "sk-test";
    delete process.env.OPENAI_API_URL;
    delete process.env.OPENAI_MODEL;
    delete process.env.SENTRY_DSN_AGENT;
    delete process.env.DD_API_KEY;
    delete process.env.DAYTONA_API_KEY;
    spawnMock.mockReset();
    spawnMock.mockReturnValue({ unref: unrefMock, pid: 9999 });
    existsSyncMock.mockReset().mockReturnValue(true);
    mkdirSyncMock.mockReset();
    openSyncMock.mockClear();
    unrefMock.mockClear();
  });

  it("returns 'local-<jobId>' and spawns the agent with the required env", async () => {
    const { spawnAnalysisSubprocess } = await import("@/lib/runtime/subprocess");
    const span = trace.getTracer("t").startSpan("p");
    const id = await spawnAnalysisSubprocess("job-abc", span);
    span.end();
    expect(id).toBe("local-job-abc");

    expect(spawnMock).toHaveBeenCalledTimes(1);
    const [pythonPath, argv, opts] = spawnMock.mock.calls[0] as [string, string[], any];
    expect(pythonPath).toMatch(/agent[\\/]\.venv[\\/](Scripts[\\/]python\.exe|bin[\\/]python)$/);
    expect(argv).toEqual(["agent.py"]);
    expect(opts.cwd).toMatch(/[\\/]agent$/);
    expect(opts.detached).toBe(true);
    expect(opts.stdio).toEqual(["ignore", 42, 42]);
    expect(opts.env.JOB_ID).toBe("job-abc");
    expect(opts.env.NEON_DATABASE_URL).toBe("postgresql://test");
    expect(opts.env.OPENAI_API_KEY).toBe("sk-test");
    expect(opts.env.TRACEPARENT).toMatch(/^00-/);
    expect(opts.env.DAYTONA_API_KEY).toBeUndefined();
    expect(unrefMock).toHaveBeenCalledTimes(1);
  });

  it("forwards OPENAI_API_URL, OPENAI_MODEL, SENTRY_DSN_AGENT only when set", async () => {
    process.env.OPENAI_API_URL = "https://proxy.example.com/v1";
    process.env.OPENAI_MODEL = "gpt-4.1";
    process.env.SENTRY_DSN_AGENT = "https://x@sentry.io/1";
    const { spawnAnalysisSubprocess } = await import("@/lib/runtime/subprocess");
    const span = trace.getTracer("t").startSpan("p");
    await spawnAnalysisSubprocess("job-fwd", span);
    span.end();
    const opts = spawnMock.mock.calls.at(-1)![2];
    expect(opts.env.OPENAI_API_URL).toBe("https://proxy.example.com/v1");
    expect(opts.env.OPENAI_MODEL).toBe("gpt-4.1");
    expect(opts.env.SENTRY_DSN_AGENT).toBe("https://x@sentry.io/1");
  });

  it("forwards the Datadog block when DD_API_KEY is set", async () => {
    process.env.DD_API_KEY = "dd-key";
    const { spawnAnalysisSubprocess } = await import("@/lib/runtime/subprocess");
    const span = trace.getTracer("t").startSpan("p");
    await spawnAnalysisSubprocess("job-dd", span);
    span.end();
    const opts = spawnMock.mock.calls.at(-1)![2];
    expect(opts.env.DD_API_KEY).toBe("dd-key");
    expect(opts.env.DD_SERVICE).toBe("stock-agent");
    expect(opts.env.DD_SITE).toBe("datadoghq.com");
  });

  it("never forwards DAYTONA_API_KEY", async () => {
    process.env.DAYTONA_API_KEY = "dt-key";
    const { spawnAnalysisSubprocess } = await import("@/lib/runtime/subprocess");
    const span = trace.getTracer("t").startSpan("p");
    await spawnAnalysisSubprocess("job-no-dt", span);
    span.end();
    const opts = spawnMock.mock.calls.at(-1)![2];
    expect(opts.env.DAYTONA_API_KEY).toBeUndefined();
  });

  it("creates agent/.runs/ and opens a per-job log file", async () => {
    const { spawnAnalysisSubprocess } = await import("@/lib/runtime/subprocess");
    const span = trace.getTracer("t").startSpan("p");
    await spawnAnalysisSubprocess("job-log", span);
    span.end();
    expect(mkdirSyncMock).toHaveBeenCalledWith(
      expect.stringMatching(/agent[\\/]\.runs$/),
      { recursive: true },
    );
    expect(openSyncMock).toHaveBeenCalledWith(
      expect.stringMatching(/agent[\\/]\.runs[\\/]job-log\.log$/),
      "a",
    );
  });

  it("throws a clear error when the venv Python is missing", async () => {
    existsSyncMock.mockReturnValue(false);
    const { spawnAnalysisSubprocess } = await import("@/lib/runtime/subprocess");
    const span = trace.getTracer("t").startSpan("p");
    await expect(spawnAnalysisSubprocess("job-no-venv", span)).rejects.toThrow(
      /agent venv not found/i,
    );
    span.end();
  });
});
```

- [ ] **Step 2: Run subprocess tests to confirm they fail**

Run: `pnpm test tests/runtime.subprocess.test.ts`
Expected: All 6 tests fail — the placeholder throws `not implemented yet`.

- [ ] **Step 3: Implement the real subprocess runner**

Replace the contents of `lib/runtime/subprocess.ts` with:

```ts
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, openSync } from "node:fs";
import path from "node:path";
import type { Span } from "@opentelemetry/api";
import { injectTraceparent, forwardIfSet, datadogBlockIfEnabled } from "./env";

function resolvePythonPath(): string {
  const repoRoot = process.cwd();
  const isWindows = process.platform === "win32";
  const rel = isWindows
    ? path.join("agent", ".venv", "Scripts", "python.exe")
    : path.join("agent", ".venv", "bin", "python");
  return path.join(repoRoot, rel);
}

export async function spawnAnalysisSubprocess(
  jobId: string,
  parentSpan: Span,
): Promise<string> {
  const pythonPath = resolvePythonPath();
  if (!existsSync(pythonPath)) {
    throw new Error(
      `agent venv not found at ${pythonPath} — run \`pip install -r agent/requirements.txt\` in agent/.venv`,
    );
  }

  const repoRoot = process.cwd();
  const agentDir = path.join(repoRoot, "agent");
  const runsDir = path.join(agentDir, ".runs");
  mkdirSync(runsDir, { recursive: true });
  const logPath = path.join(runsDir, `${jobId}.log`);
  const logFd = openSync(logPath, "a");

  const env: Record<string, string> = {
    ...process.env as Record<string, string>,
    JOB_ID: jobId,
    NEON_DATABASE_URL: process.env.NEON_DATABASE_URL!,
    OPENAI_API_KEY: process.env.OPENAI_API_KEY!,
    TRACEPARENT: injectTraceparent(parentSpan),
    ...forwardIfSet("OPENAI_API_URL"),
    ...forwardIfSet("OPENAI_MODEL"),
    ...forwardIfSet("SENTRY_DSN_AGENT"),
    ...datadogBlockIfEnabled(),
  };
  // Never forward Daytona credentials into a local subprocess.
  delete env.DAYTONA_API_KEY;

  const child = spawn(pythonPath, ["agent.py"], {
    cwd: agentDir,
    env,
    stdio: ["ignore", logFd, logFd],
    detached: true,
  });
  child.unref();

  return `local-${jobId}`;
}
```

Why `...process.env` and then `delete env.DAYTONA_API_KEY`: inheriting the parent env keeps things like `PATH` and `SystemRoot` (needed on Windows for Python to start), but the explicit delete documents and enforces the "Daytona key never leaks into local mode" decision (spec §4).

- [ ] **Step 4: Run subprocess tests to confirm they pass**

Run: `pnpm test tests/runtime.subprocess.test.ts`
Expected: 6 tests pass.

- [ ] **Step 5: Confirm full suite still green**

Run: `pnpm test`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add lib/runtime/subprocess.ts tests/runtime.subprocess.test.ts
git commit -m "feat(runtime): subprocess runner for local agent execution"
```

---

## Task 4: Wire the dispatcher into the API route

Swap the direct `spawnAnalysisSandbox` import in the jobs route for the dispatcher, so `AGENT_RUNTIME` actually affects user submissions.

**Files:**
- Modify: `app/api/jobs/route.ts`

- [ ] **Step 1: Update the import and call site**

In `app/api/jobs/route.ts`, change line 3 from:

```ts
import { spawnAnalysisSandbox } from "@/lib/daytona";
```

to:

```ts
import { spawnAgent } from "@/lib/runtime";
```

And change the call on line 29 from:

```ts
      const sandboxId = await spawnAnalysisSandbox(jobId, span);
```

to:

```ts
      const sandboxId = await spawnAgent(jobId, span);
```

No other changes in this file.

- [ ] **Step 2: Run the full test suite**

Run: `pnpm test`
Expected: All tests pass — the existing daytona tests still cover the daytona path (now through the dispatcher's default branch); the new runtime tests cover dispatching.

- [ ] **Step 3: Commit**

```bash
git add app/api/jobs/route.ts
git commit -m "feat(api): route jobs through AGENT_RUNTIME dispatcher"
```

---

## Task 5: Guard `self_delete` against synthetic `local-` ids

Prevent `agent/lib/self_delete.py` from making a bogus DELETE call against the Daytona API when the agent runs locally and somehow has `DAYTONA_API_KEY` in its env.

**Files:**
- Modify: `agent/lib/self_delete.py`
- Create: `agent/tests/test_self_delete.py` (if `agent/tests/` exists; otherwise put it next to existing tests)

- [ ] **Step 1: Locate the agent test directory**

Run: `ls agent/tests/`
Expected: Existing test files. If `agent/tests/` doesn't exist, create it before Step 2.

- [ ] **Step 2: Write the failing test**

Create `agent/tests/test_self_delete_local_guard.py` (style matches the sibling `test_self_delete.py`):

```python
from unittest.mock import patch
from lib.self_delete import self_delete


def test_skips_http_call_for_local_prefix(monkeypatch):
    monkeypatch.setenv("DAYTONA_API_KEY", "dt-key")
    with patch("httpx.delete") as mock_del:
        self_delete(sandbox_id="local-abc123")
        mock_del.assert_not_called()


def test_skips_http_call_for_env_local_prefix(monkeypatch):
    monkeypatch.setenv("DAYTONA_API_KEY", "dt-key")
    monkeypatch.setenv("DAYTONA_SANDBOX_ID", "local-from-env")
    with patch("httpx.delete") as mock_del:
        self_delete()
        mock_del.assert_not_called()
```

The existing `test_self_delete_uses_parameter_when_provided` in `test_self_delete.py` already covers the positive case (real `sb-*` id triggers the HTTP call), so no need to repeat it here.

- [ ] **Step 3: Run the test to confirm it fails**

Run: `cd agent && .venv/Scripts/pytest tests/test_self_delete_local_guard.py -v` (POSIX: `.venv/bin/pytest`)
Expected: `test_skips_http_call_for_local_prefix` fails — `httpx.delete` is called.

- [ ] **Step 4: Add the guard**

Edit `agent/lib/self_delete.py`. After line 10 (after `if not sid or not api_key: return`), add:

```python
    if sid.startswith("local-"):
        return
```

The full function should now read:

```python
def self_delete(sandbox_id: str | None = None) -> None:
    """DELETE this sandbox via the Daytona REST API. Never raises.
    Safety net: Daytona's autoDeleteInterval reclaims the sandbox if this fails.

    sandbox_id is preferred; falls back to the DAYTONA_SANDBOX_ID env var."""
    sid = sandbox_id or os.environ.get("DAYTONA_SANDBOX_ID")
    api_key = os.environ.get("DAYTONA_API_KEY")
    if not sid or not api_key:
        return
    if sid.startswith("local-"):
        return
    base = os.environ.get("DAYTONA_API_URL", "https://app.daytona.io/api")
    try:
        httpx.delete(
            f"{base}/sandbox/{sid}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
    except Exception:
        pass
```

- [ ] **Step 5: Run the tests to confirm both pass**

Run: `cd agent && .venv/Scripts/pytest tests/test_self_delete_local_guard.py -v`
Expected: 2 tests pass.

- [ ] **Step 6: Commit**

```bash
git add agent/lib/self_delete.py agent/tests/test_self_delete_local_guard.py
git commit -m "feat(agent): guard self_delete against synthetic local- sandbox ids"
```

---

## Task 6: Standalone Python CLI driver

`agent/analyze.py` — insert a pending row + run the agent in-process. Lets Python devs iterate without `pnpm dev`.

**Files:**
- Create: `agent/analyze.py`

- [ ] **Step 1: Create the driver**

Create `agent/analyze.py`:

```python
"""Standalone driver: insert a pending job row, then run the agent in-process.

Usage:
    python analyze.py <TICKER> [--no-wait]

Requires NEON_DATABASE_URL and OPENAI_API_KEY in the environment.
"""
import argparse
import json
import os
import re
import sys
import time

from lib.db import _conn

TICKER_RE = re.compile(r"^[A-Z]{1,5}$")


def insert_pending(ticker: str) -> str:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO jobs (ticker) VALUES (%s) RETURNING id::text",
            (ticker,),
        )
        row = cur.fetchone()
        c.commit()
        return row["id"]


def poll_until_terminal(job_id: str, timeout_s: float = 180.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        with _conn() as c:
            cur = c.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
            row = cur.fetchone()
        if row and row["status"] in ("complete", "failed"):
            return row
        time.sleep(1.0)
    raise TimeoutError(f"job {job_id} did not reach a terminal state in {timeout_s}s")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the stock agent locally against a fresh job row.")
    parser.add_argument("ticker", help="1-5 uppercase letters, e.g. AAPL")
    parser.add_argument("--no-wait", action="store_true", help="exit immediately after agent.main() returns")
    args = parser.parse_args()

    ticker = args.ticker.strip()
    if not TICKER_RE.match(ticker):
        print(f"invalid ticker {ticker!r}: must match {TICKER_RE.pattern}", file=sys.stderr)
        return 2

    if "NEON_DATABASE_URL" not in os.environ:
        print("NEON_DATABASE_URL is required", file=sys.stderr)
        return 2
    if "OPENAI_API_KEY" not in os.environ:
        print("OPENAI_API_KEY is required", file=sys.stderr)
        return 2

    job_id = insert_pending(ticker)
    print(f"inserted job {job_id} (ticker={ticker})", file=sys.stderr)

    # IMPORTANT: agent.py reads JOB_ID into a module-level constant at import time
    # (agent.py:10), so the env var MUST be set BEFORE the import. Defer the import.
    os.environ["JOB_ID"] = job_id
    os.environ.setdefault("DAYTONA_SANDBOX_ID", f"local-{job_id}")

    import agent as agent_module  # deferred — see comment above

    try:
        agent_module.main()
    except Exception as e:
        print(f"agent.main() raised: {e}", file=sys.stderr)

    if args.no_wait:
        return 0

    row = poll_until_terminal(job_id)
    payload = {
        "id": str(row["id"]),
        "ticker": row["ticker"],
        "status": row["status"],
        "recommendation": row["recommendation"],
        "result": row["result"],
        "error": row["error"],
    }
    print(json.dumps(payload, indent=2, default=str))
    return 0 if row["status"] == "complete" else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke-test the driver against a real Neon (manual)**

Skip this step if you don't have `NEON_DATABASE_URL` and `OPENAI_API_KEY` handy locally — Task 7 will cover automated verification.

Run (Windows):
```powershell
cd agent
.\.venv\Scripts\Activate.ps1
python analyze.py AAPL
```

Expected: stderr line `inserted job <uuid> (ticker=AAPL)`, then JSON with `status: "complete"` on stdout within ~60s.

- [ ] **Step 3: Commit**

```bash
git add agent/analyze.py
git commit -m "feat(agent): standalone analyze.py CLI driver"
```

---

## Task 7: Real-Python integration test

Verifies the full subprocess path actually runs Python against Neon, with the LLM mocked via `OPENAI_API_URL` pointed at a local HTTP server. Skipped cleanly when required secrets are absent.

**Files:**
- Create: `tests/runtime.subprocess.integration.test.ts`

- [ ] **Step 1: Confirm OpenAI Responses-API shape from the agent code**

Re-read `agent/lib/llm.py` lines 57-70 — the agent calls `self._client.responses.create(...)` and uses `resp.output_text`. The OpenAI SDK's Responses API hits `POST /v1/responses` and expects a JSON body with `output_text` (and optionally `usage`). The local mock server must return exactly that shape.

- [ ] **Step 2: Write the integration test**

Create `tests/runtime.subprocess.integration.test.ts`:

```ts
import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { trace } from "@opentelemetry/api";
import { BasicTracerProvider } from "@opentelemetry/sdk-trace-base";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { eq } from "drizzle-orm";

const haveSecrets = !!process.env.NEON_DATABASE_URL && !!process.env.OPENAI_API_KEY;

// Minimal OpenAI Responses-API payload. The Python SDK's response parser is
// fairly forgiving — it requires `output_text` (or the nested `output[].content`
// shape) plus core fields. If a future SDK version tightens this, expand here.
const ANALYSIS_JSON = JSON.stringify({
  recommendation: "hold",
  summary: "deterministic test fixture",
  signals: [{ label: "test-signal", evidence: "fixture only", source: null }],
});

const FAKE_RESPONSE = {
  id: "resp_test_fixture",
  object: "response",
  created_at: 1_000_000_000,
  status: "completed",
  model: "gpt-4.1-mini",
  output: [
    {
      type: "message",
      id: "msg_test",
      status: "completed",
      role: "assistant",
      content: [{ type: "output_text", text: ANALYSIS_JSON, annotations: [] }],
    },
  ],
  output_text: ANALYSIS_JSON,
  usage: { input_tokens: 1, output_tokens: 1, total_tokens: 2 },
};

let server: http.Server | undefined;
let serverUrl = "";

beforeAll(async () => {
  trace.setGlobalTracerProvider(new BasicTracerProvider());
  if (!haveSecrets) return;

  server = http.createServer((_req, res) => {
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(FAKE_RESPONSE));
  });
  await new Promise<void>((resolve) => server!.listen(0, "127.0.0.1", resolve));
  const addr = server!.address();
  if (typeof addr === "object" && addr) {
    serverUrl = `http://127.0.0.1:${addr.port}/v1`;
  }
});

afterAll(async () => {
  if (server) await new Promise<void>((r) => server!.close(() => r()));
});

describe.skipIf(!haveSecrets)("subprocess runner integration", () => {
  it("runs the real Python agent end-to-end and marks the job complete", async () => {
    process.env.OPENAI_API_URL = serverUrl;
    process.env.AGENT_RUNTIME = "subprocess";

    const { db, jobs } = await import("@/lib/db/client");
    const { spawnAnalysisSubprocess } = await import("@/lib/runtime/subprocess");

    const [{ id: jobId }] = await db
      .insert(jobs)
      .values({ ticker: "TEST" })
      .returning({ id: jobs.id });

    try {
      const span = trace.getTracer("integration").startSpan("p");
      const sandboxId = await spawnAnalysisSubprocess(jobId, span);
      span.end();
      expect(sandboxId).toBe(`local-${jobId}`);

      const logPath = path.resolve(process.cwd(), "agent", ".runs", `${jobId}.log`);
      expect(fs.existsSync(logPath)).toBe(true);

      const deadline = Date.now() + 30_000;
      let status = "pending";
      let row: any;
      while (Date.now() < deadline) {
        const rows = await db.select().from(jobs).where(eq(jobs.id, jobId));
        row = rows[0];
        status = row?.status ?? "pending";
        if (status === "complete" || status === "failed") break;
        await new Promise((r) => setTimeout(r, 500));
      }

      expect(status, `final status; error=${row?.error}`).toBe("complete");
      expect(["buy", "hold", "sell"]).toContain(row.recommendation);
    } finally {
      await db.delete(jobs).where(eq(jobs.id, jobId));
    }
  }, 60_000);
});
```

- [ ] **Step 3: Run the integration test with secrets**

Run (assuming `NEON_DATABASE_URL` and `OPENAI_API_KEY` are set in your shell):
```bash
pnpm test tests/runtime.subprocess.integration.test.ts
```
Expected: 1 test passes within ~30s. The Python agent runs against the local HTTP mock; no OpenAI cost.

- [ ] **Step 4: Run the integration test without secrets to confirm skip**

Run:
```bash
NEON_DATABASE_URL= OPENAI_API_KEY= pnpm test tests/runtime.subprocess.integration.test.ts
```
Expected: 1 test skipped, 0 failed.

- [ ] **Step 5: Commit**

```bash
git add tests/runtime.subprocess.integration.test.ts
git commit -m "test(runtime): real-Python integration test for subprocess runner"
```

---

## Task 8: Configuration files + Makefile target + .gitignore

Plumbing so the feature is discoverable and the log directory doesn't get committed.

**Files:**
- Modify: `.env.example`
- Modify: `.gitignore`
- Modify: `Makefile`

- [ ] **Step 1: Update `.env.example`**

Add at the top of the file, immediately after the `# === Required ===` block. Insert this new block before line 7 (the `# Optional — override to use an OpenAI-compatible endpoint` comment):

```
# Agent runtime: 'daytona' (default) or 'subprocess' (run the Python agent
# as a local child process — no Daytona account needed for local dev).
AGENT_RUNTIME=daytona

```

- [ ] **Step 2: Update `.gitignore`**

Append:

```
# Local agent runs
agent/.runs/
```

- [ ] **Step 3: Add the `agent-local` Make target**

In `Makefile`, append. The `AGENT_PY` variable picks the right interpreter at parse time using Make's `wildcard` — relative to `agent/` so the recipe can `cd` once:

```
AGENT_PY := $(if $(wildcard agent/.venv/Scripts/python.exe),.venv/Scripts/python.exe,.venv/bin/python)

agent-local:
	cd agent && ./$(AGENT_PY) analyze.py $(TICKER)
```

Also update the `.PHONY` line to include the new target. Change line 1 from:

```
.PHONY: dev test seed snapshot smoke clean
```

to:

```
.PHONY: dev test seed snapshot smoke clean agent-local
```

- [ ] **Step 4: Run the full Node test suite to confirm nothing broke**

Run: `pnpm test`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add .env.example .gitignore Makefile
git commit -m "chore: AGENT_RUNTIME config, agent/.runs/ ignore, agent-local make target"
```

---

## Task 9: README documentation

Make the feature discoverable from the README.

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the Configuration reference required-vars table**

In `README.md`, in the "### Required" subsection of "## Configuration reference" (around lines 62-69), the table currently has 4 rows (DAYTONA_API_KEY, DAYTONA_TARGET, NEON_DATABASE_URL, OPENAI_API_KEY).

Replace the "### Required" subsection (lines 62-69) with:

```markdown
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
```

- [ ] **Step 2: Add a new "### Optional — Agent runtime" block**

Immediately after the "### Optional — OpenAI-compatible endpoint" subsection (around line 77), add:

```markdown
### Optional — Agent runtime

| Var | What it does |
|---|---|
| `AGENT_RUNTIME` | `daytona` (default) spawns the agent in a Daytona sandbox. `subprocess` runs the Python agent as a detached local child process (no Daytona account needed). Unknown values cause the API route to throw on the next submit. |
```

- [ ] **Step 3: Add the HOW-TO section**

Immediately before `## HOW-TO: Provision Daytona` (currently around line 110), insert:

````markdown
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

````

- [ ] **Step 4: Sanity-check the README renders**

Run: `cat README.md | head -200` and visually confirm the new sections are well-formed.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs(readme): HOW-TO for AGENT_RUNTIME=subprocess local mode"
```

---

## Task 10: Final verification

Single sweep to confirm everything works together.

- [ ] **Step 1: Run the full Node test suite**

Run: `pnpm test`
Expected: All tests pass. Integration test skips if `NEON_DATABASE_URL` is unset; passes if set.

- [ ] **Step 2: Run the Python agent tests**

Run:
```powershell
cd agent
.\.venv\Scripts\Activate.ps1
pytest
```
Expected: All pre-existing tests still pass; the new `test_self_delete_local_guard.py` passes.

- [ ] **Step 3: Manual smoke — daytona mode unchanged**

With `AGENT_RUNTIME` unset (or `=daytona`) and `DAYTONA_API_KEY` set, run `pnpm dev` and submit `AAPL`. Job should reach `complete` via the Daytona path within ~90s. Confirms the refactor was behavior-preserving.

- [ ] **Step 4: Manual smoke — subprocess mode**

Stop `pnpm dev`. Add `AGENT_RUNTIME=subprocess` to `.env`. Restart `pnpm dev`. Submit `AAPL`. Confirm:
- Job row gets `sandbox_id='local-<uuid>'`.
- `agent/.runs/<uuid>.log` appears and contains the agent's startup prints.
- Job reaches `complete` within ~60s.
- No Daytona API calls visible in the Daytona dashboard.

- [ ] **Step 5: Final commit (if any cleanup was needed)**

If everything passed without further edits, nothing to commit. Otherwise:
```bash
git add -p
git commit -m "chore: post-verification cleanup"
```
