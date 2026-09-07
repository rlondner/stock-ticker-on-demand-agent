# CrewAI Deep-Analysis Tier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second, richer analysis path — a 4-agent CrewAI crew using You.com search/news and a Daytona code-execution tool — selectable via the existing (currently inert) depth selector, alongside the unchanged single-call "quick" path.

**Architecture:** `agent.py` branches on a new `DEPTH` env var: `quick` keeps calling today's `run_analysis` (`agent/lib/llm.py`) unchanged; `deep`/`full` call a new `run_crew_analysis` (`agent/lib/crew.py`) that runs a sequential CrewAI crew (Researcher → Fundamentals Analyst → Risk Analyst → Portfolio Manager) and returns the same dict contract. The depth flows from the NextJS `DepthSelector` UI through `/api/jobs` → the `jobs.depth` column → the sandbox env, and back through the same `mark_complete`/status-polling path with an extended (superset) result JSON.

**Tech Stack:** Next.js/TypeScript (drizzle-orm, zod, vitest), Python (CrewAI, pydantic, pytest, Daytona SDK, httpx for You.com), Neon Postgres.

## Global Constraints

- `depth` values are exactly `"quick" | "deep" | "full"` everywhere (DB CHECK, zod enum, TS union, Python).
- `YOUDOTCOM_API_KEY` lives in `.env` only — never logged, never committed, never sent to any host other than You.com's API.
- `CREW_MAX_EXECUTION_S_<TIER>` must stay below `DAYTONA_AUTO_DELETE_<TIER>_S` (documented invariant — the crew must finish and write its result before the sandbox's auto-delete fires).
- All new Python tools (You.com, Daytona code-exec) follow the existing `_observed_tool` contract in `agent/lib/tools.py`: never raise, a failure returns `{"error": ...}`, and every call emits `tool.<name>.ok`/`tool.<name>.failed` logs + a span event.
- The quick-tier path (`run_analysis`, `agent_loop.py`, `OpenAIClient`) is not modified by this plan except for the additive, optional `Thesis` fields in Task 7.
- New DB columns/result fields must not require a backfill: `depth` defaults to `'quick'`; the three new result fields are optional and absent on old rows.

---

### Task 1: `jobs.depth` column (DB + Drizzle schema + TS types)

**Files:**
- Create: `db/migrations/0002_add_depth.sql`
- Modify: `lib/db/schema.ts`
- Modify: `lib/job/types.ts`
- Test: `tests/db.schema.test.ts` (new)

**Interfaces:**
- Produces: `Depth = "quick" | "deep" | "full"` (exported from `lib/db/schema.ts`), `jobs.depth` column (drizzle), `SerializedJob.depth: Depth`.

- [ ] **Step 1: Write the failing test**

```ts
// tests/db.schema.test.ts
import { describe, it, expect } from "vitest";
import { jobs } from "@/lib/db/schema";

describe("jobs schema", () => {
  it("has a depth column defaulting to 'quick'", () => {
    expect(jobs.depth).toBeDefined();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm vitest run tests/db.schema.test.ts`
Expected: FAIL — `jobs.depth` is `undefined`.

- [ ] **Step 3: Add the migration**

```sql
-- db/migrations/0002_add_depth.sql
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS depth TEXT NOT NULL DEFAULT 'quick'
  CHECK (depth IN ('quick','deep','full'));
```

- [ ] **Step 4: Update the Drizzle schema and types**

In `lib/db/schema.ts`, add the column and export the union (after the existing `sandboxId` field, before `createdAt`):

```ts
    depth: text("depth").notNull().default("quick"),
```

At the bottom of the file, alongside the existing type exports:

```ts
export type Depth = "quick" | "deep" | "full";
```

In `lib/job/types.ts`, add to `SerializedJob`:

```ts
  depth: Depth;
```

and import it: `import type { Depth } from "@/lib/db/schema";` (add to the existing import line at the top of the file, next to `JobStatus`/`Recommendation` imports — check the current import source for those two types and match it; if they come from `lib/ui/status-pill` / `lib/ui/signal-pill` respectively, add a separate `import type { Depth } from "@/lib/db/schema";` line).

- [ ] **Step 5: Run test to verify it passes**

Run: `pnpm vitest run tests/db.schema.test.ts`
Expected: PASS

- [ ] **Step 6: Apply the migration to your Neon project**

Run: `make seed`
Expected: no errors; `psql $NEON_DATABASE_URL -c "\d jobs"` shows the `depth` column.

- [ ] **Step 7: Commit**

```bash
git add db/migrations/0002_add_depth.sql lib/db/schema.ts lib/job/types.ts tests/db.schema.test.ts
git commit -m "feat(db): add jobs.depth column (quick|deep|full)"
```

---

### Task 2: env-driven `autoDeleteInterval` in `lib/daytona.ts`

**Files:**
- Modify: `lib/daytona.ts`
- Modify: `.env.example`
- Test: `tests/daytona.test.ts`

**Interfaces:**
- Consumes: `Depth` from `lib/db/schema.ts` (Task 1).
- Produces: `spawnAnalysisSandbox(jobId: string, depth: Depth, parentSpan: Span): Promise<string>` — **signature change**, existing callers in `lib/runtime/index.ts` and `app/api/jobs/route.ts` must pass `depth` (updated in Task 3).

- [ ] **Step 1: Write the failing tests**

Add to `tests/daytona.test.ts` (inside the existing `describe("spawnAnalysisSandbox", ...)` block, after the last `it(...)`):

```ts
  it("sets DEPTH in the sandbox env and defaults autoDeleteInterval to 600 for 'quick'", async () => {
    const { spawnAnalysisSandbox } = await import("@/lib/daytona");
    const span = trace.getTracer("t").startSpan("p");
    await spawnAnalysisSandbox("job-quick", "quick", span);
    span.end();
    const call = createMock.mock.calls.at(-1)![0] as any;
    expect(call.envVars.DEPTH).toBe("quick");
    expect(call.autoDeleteInterval).toBe(600);
  });

  it("uses DAYTONA_AUTO_DELETE_DEEP_S for 'deep'", async () => {
    process.env.DAYTONA_AUTO_DELETE_DEEP_S = "930";
    const { spawnAnalysisSandbox } = await import("@/lib/daytona");
    const span = trace.getTracer("t").startSpan("p");
    await spawnAnalysisSandbox("job-deep", "deep", span);
    span.end();
    const call = createMock.mock.calls.at(-1)![0] as any;
    expect(call.envVars.DEPTH).toBe("deep");
    expect(call.autoDeleteInterval).toBe(930);
  });

  it("uses DAYTONA_AUTO_DELETE_FULL_S for 'full'", async () => {
    process.env.DAYTONA_AUTO_DELETE_FULL_S = "1530";
    const { spawnAnalysisSandbox } = await import("@/lib/daytona");
    const span = trace.getTracer("t").startSpan("p");
    await spawnAnalysisSandbox("job-full", "full", span);
    span.end();
    const call = createMock.mock.calls.at(-1)![0] as any;
    expect(call.envVars.DEPTH).toBe("full");
    expect(call.autoDeleteInterval).toBe(1530);
  });

  it("forwards YOUDOTCOM_API_KEY only when set", async () => {
    process.env.YOUDOTCOM_API_KEY = "ydc-sk-test";
    const { spawnAnalysisSandbox } = await import("@/lib/daytona");
    const span = trace.getTracer("t").startSpan("p");
    await spawnAnalysisSandbox("job-youcom", "deep", span);
    span.end();
    const call = createMock.mock.calls.at(-1)![0] as any;
    expect(call.envVars.YOUDOTCOM_API_KEY).toBe("ydc-sk-test");
  });
```

Also add `delete process.env.DAYTONA_AUTO_DELETE_DEEP_S;` and `delete process.env.DAYTONA_AUTO_DELETE_FULL_S;` and `delete process.env.YOUDOTCOM_API_KEY;` to the existing `beforeEach` block's env cleanup (next to the other `delete process.env...` lines), and update every existing `spawnAnalysisSandbox("job-...", span)` call in this file to `spawnAnalysisSandbox("job-...", "quick", span)` (the new required second argument).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pnpm vitest run tests/daytona.test.ts`
Expected: FAIL — `spawnAnalysisSandbox` doesn't accept a `depth` argument yet, `call.envVars.DEPTH` is `undefined`.

- [ ] **Step 3: Implement**

In `.env.example`, add after the `DAYTONA_TARGET=us` line:

```
# Auto-delete window per analysis depth (seconds). Must exceed the matching
# CREW_MAX_EXECUTION_S_<TIER> in agent/.env.example so the crew finishes and
# writes its result before the sandbox self-destructs.
DAYTONA_AUTO_DELETE_QUICK_S=600
DAYTONA_AUTO_DELETE_DEEP_S=900
DAYTONA_AUTO_DELETE_FULL_S=1500

# You.com API key (Search/News APIs) for the deep-analysis crew's Researcher
# and Risk Analyst agents. Forwarded into the sandbox only when set.
YOUDOTCOM_API_KEY=
```

In `lib/daytona.ts`, add an import and a small resolver function above `spawnAnalysisSandbox`:

```ts
import type { Depth } from "./db/schema";

function autoDeleteIntervalFor(depth: Depth): number {
  const key = { quick: "DAYTONA_AUTO_DELETE_QUICK_S", deep: "DAYTONA_AUTO_DELETE_DEEP_S", full: "DAYTONA_AUTO_DELETE_FULL_S" }[depth];
  const fallback = { quick: 600, deep: 900, full: 1500 }[depth];
  const raw = process.env[key];
  const parsed = raw ? Number(raw) : NaN;
  return Number.isFinite(parsed) ? parsed : fallback;
}
```

Change the function signature and body:

```ts
export async function spawnAnalysisSandbox(jobId: string, depth: Depth, parentSpan: Span): Promise<string> {
  const env: Record<string, string> = {
    JOB_ID: jobId,
    DEPTH: depth,
    NEON_DATABASE_URL: process.env.NEON_DATABASE_URL!,
    OPENAI_API_KEY: process.env.OPENAI_API_KEY!,
    DAYTONA_API_KEY: process.env.DAYTONA_API_KEY!,
    TRACEPARENT: injectTraceparent(parentSpan),
    ...forwardIfSet("OPENAI_API_URL"),
    ...forwardIfSet("OPENAI_MODEL"),
    ...forwardIfSet("OPENAI_USE_RESPONSES_API"),
    ...forwardIfSet("YOUDOTCOM_API_KEY"),
    ...forwardIfSet("SENTRY_DSN_AGENT"),
    ...forwardIfSet("DD_TRACE_ENABLED"),
    ...forwardIfSet("DD_EXPORTER"),
    ...forwardIfSet("DD_OTLP_ENDPOINT"),
    ...datadogBlockIfEnabled(),
  };
  // ... (host/span logging block unchanged) ...
```

Further down, change the `client().create({...})` call's `autoDeleteInterval: 600` to `autoDeleteInterval: autoDeleteIntervalFor(depth)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm vitest run tests/daytona.test.ts`
Expected: PASS (all tests in the file, including the pre-existing ones updated with the new argument).

- [ ] **Step 5: Commit**

```bash
git add lib/daytona.ts .env.example tests/daytona.test.ts
git commit -m "feat(daytona): thread depth through sandbox spawn, env-driven autoDeleteInterval"
```

---

### Task 3: thread `depth` through the runtime dispatcher, API route, and frontend form

**Files:**
- Modify: `lib/runtime/index.ts`
- Modify: `lib/runtime/subprocess.ts`
- Modify: `app/api/jobs/route.ts`
- Modify: `lib/analyze/submit-analysis.ts`
- Modify: `components/analyze/depth-selector.tsx`
- Modify: `components/analyze/launch-form.tsx`
- Test: `tests/api.jobs.test.ts`
- Test: `tests/components/submit-analysis.test.ts`

**Note:** this repo has no `@testing-library/react`/jsdom test environment and
no existing component is render-tested (vitest is `environment: "node"`,
`include: ["tests/**/*.test.ts"]` — pure-logic modules only). `DepthSelector`
is verified manually in Step 8a below rather than introducing new test
infrastructure for a single presentational component.

**Interfaces:**
- Consumes: `spawnAnalysisSandbox(jobId, depth, span)` (Task 2), `Depth` (Task 1).
- Produces: `spawnAgent(jobId: string, depth: Depth, parentSpan: Span): Promise<string>`, `submitAnalysis({ ticker, depth, ... })`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/api.jobs.test.ts` (new `it` inside the existing `describe`):

```ts
  it("defaults depth to 'quick' and forwards it to spawnAgent", async () => {
    const { spawnAgent } = await import("@/lib/runtime");
    await POST(req({ ticker: "AAPL" }));
    expect(spawnAgent).toHaveBeenCalledWith(expect.any(String), "quick", expect.anything());
  });

  it("accepts an explicit depth and forwards it to spawnAgent", async () => {
    const { spawnAgent } = await import("@/lib/runtime");
    await POST(req({ ticker: "AAPL", depth: "deep" }));
    expect(spawnAgent).toHaveBeenCalledWith(expect.any(String), "deep", expect.anything());
  });

  it("rejects an invalid depth with 400", async () => {
    const res = await POST(req({ ticker: "AAPL", depth: "bogus" }));
    expect(res.status).toBe(400);
  });
```

Update the `vi.mock("@/lib/runtime", ...)` at the top of the file to accept the new arg (it already does — `vi.fn(async (jobId: string) => ...)` — no change needed since vitest mocks ignore extra args, but update the mock's declared signature for clarity: `vi.fn(async (jobId: string, _depth: string) => \`sb-${jobId.slice(0, 8)}\`)`).

Add to `tests/components/submit-analysis.test.ts` (new `it`):

```ts
  it("includes depth in the POST body, defaulting to 'quick'", async () => {
    const fetchImpl = makeFetch(200, { jobId: "job-1" });
    const push = vi.fn();
    await submitAnalysis({ ticker: "AAPL", fetchImpl, push });
    expect(fetchImpl).toHaveBeenCalledWith("/api/jobs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ticker: "AAPL", depth: "quick" }),
    });
  });

  it("forwards an explicit depth", async () => {
    const fetchImpl = makeFetch(200, { jobId: "job-1" });
    const push = vi.fn();
    await submitAnalysis({ ticker: "AAPL", depth: "deep", fetchImpl, push });
    const body = JSON.parse((fetchImpl as any).mock.calls[0][1].body);
    expect(body.depth).toBe("deep");
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pnpm vitest run tests/api.jobs.test.ts tests/components/submit-analysis.test.ts`
Expected: FAIL — `spawnAgent` called without a depth arg, `submitAnalysis` doesn't send `depth`.

- [ ] **Step 3: Implement `lib/runtime/index.ts`**

```ts
import type { Span } from "@opentelemetry/api";
import type { Depth } from "@/lib/db/schema";
import { spawnAnalysisSandbox } from "@/lib/daytona";
import { spawnAnalysisSubprocess } from "@/lib/runtime/subprocess";

export async function spawnAgent(jobId: string, depth: Depth, parentSpan: Span): Promise<string> {
  const runtime = process.env.AGENT_RUNTIME ?? "daytona";
  switch (runtime) {
    case "daytona":
      return spawnAnalysisSandbox(jobId, depth, parentSpan);
    case "subprocess":
      return spawnAnalysisSubprocess(jobId, depth, parentSpan);
    default:
      throw new Error(`unknown AGENT_RUNTIME=${runtime} (expected 'daytona' or 'subprocess')`);
  }
}
```

- [ ] **Step 4: Implement `lib/runtime/subprocess.ts`**

Change the signature to `export async function spawnAnalysisSubprocess(jobId: string, depth: Depth, parentSpan: Span): Promise<string> {` (add `import type { Depth } from "@/lib/db/schema";`), and add `DEPTH: depth,` to the `env` object next to `JOB_ID: jobId,`.

- [ ] **Step 5: Implement `app/api/jobs/route.ts`**

```ts
import { z } from "zod";
import { eq } from "drizzle-orm";
import { db, jobs } from "@/lib/db/client";
import { spawnAgent } from "@/lib/runtime";
import { traced, addAttrs, recordError } from "@/lib/observability/api";
import { jobsSubmitted } from "@/lib/observability/metrics";

const Body = z.object({
  ticker: z.string().regex(/^[A-Z]{1,5}$/, "ticker must be 1-5 uppercase letters"),
  depth: z.enum(["quick", "deep", "full"]).default("quick"),
});

export async function POST(req: Request): Promise<Response> {
  return traced("api.jobs.post", { route: "POST /api/jobs" }, async (span) => {
    let parsed: z.infer<typeof Body>;
    try {
      parsed = Body.parse(await req.json());
    } catch (e) {
      addAttrs(span, { outcome: "rejected" });
      jobsSubmitted("rejected", "unknown");
      const msg = e instanceof z.ZodError ? e.issues[0]?.message ?? "invalid" : "invalid";
      return Response.json({ error: msg }, { status: 400 });
    }

    const [{ id: jobId }] = await db
      .insert(jobs)
      .values({ ticker: parsed.ticker, depth: parsed.depth })
      .returning({ id: jobs.id });
    addAttrs(span, { job_id: jobId, ticker: parsed.ticker, depth: parsed.depth });

    try {
      const sandboxId = await spawnAgent(jobId, parsed.depth, span);
      await db.update(jobs).set({ sandboxId }).where(eq(jobs.id, jobId));
      addAttrs(span, { sandbox_id: sandboxId, outcome: "accepted" });
      jobsSubmitted("accepted", parsed.ticker);
      return Response.json({ jobId });
    } catch (e) {
      recordError(span, e);
      await db
        .update(jobs)
        .set({ status: "failed", error: `sandbox_spawn_failed: ${e instanceof Error ? e.message : e}` })
        .where(eq(jobs.id, jobId));
      return Response.json({ error: "spawn_failed", jobId }, { status: 500 });
    }
  });
}
```

- [ ] **Step 6: Implement `lib/analyze/submit-analysis.ts`**

```ts
export type SubmitResult =
  | { ok: true; jobId: string }
  | { ok: false; error: string; jobId?: string };

export type Depth = "quick" | "deep" | "full";

export type SubmitParams = {
  ticker: string;
  depth?: Depth;
  fetchImpl?: typeof fetch;
  push: (path: string) => void;
};

const TICKER_RE = /^[A-Z]{1,5}$/;

export async function submitAnalysis({ ticker, depth = "quick", fetchImpl, push }: SubmitParams): Promise<SubmitResult> {
  const doFetch: typeof fetch = fetchImpl ?? fetch;
  const value = ticker.trim().toUpperCase();
  if (!TICKER_RE.test(value)) {
    return { ok: false, error: "Ticker must be 1–5 uppercase letters." };
  }

  let res: Response;
  try {
    res = await doFetch("/api/jobs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ticker: value, depth }),
    });
  } catch {
    return { ok: false, error: "Submit failed" };
  }

  const body = (await res.json().catch(() => ({}))) as { jobId?: string; error?: string };

  if (res.ok && body.jobId) {
    push(`/jobs/${body.jobId}`);
    return { ok: true, jobId: body.jobId };
  }

  if (body.jobId) {
    push(`/jobs/${body.jobId}`);
    return { ok: false, error: body.error ?? "Submit failed", jobId: body.jobId };
  }
  return { ok: false, error: body.error ?? "Submit failed" };
}
```

- [ ] **Step 7: Implement the controlled `DepthSelector`**

```tsx
// components/analyze/depth-selector.tsx
"use client";

const DEPTHS = [
  { key: "quick", icon: "speed", label: "Quick Scan", eta: "~2 mins" },
  { key: "deep", icon: "query_stats", label: "Deep Dive", eta: "~8 mins" },
  { key: "full", icon: "description", label: "Full Report", eta: "~20 mins" },
] as const;

export type DepthKey = (typeof DEPTHS)[number]["key"];

export function DepthSelector({ value, onChange }: { value: DepthKey; onChange: (key: DepthKey) => void }) {
  return (
    <div className="space-y-2">
      <label className="text-sm font-semibold text-af-on-surface">Analysis Depth</label>
      <div className="grid grid-cols-3 gap-4">
        {DEPTHS.map((d) => {
          const isSelected = value === d.key;
          return (
            <button
              key={d.key}
              type="button"
              onClick={() => onChange(d.key)}
              className={`flex flex-col items-center gap-2 p-6 border-2 rounded-xl text-center transition-all ${
                isSelected
                  ? "border-af-primary bg-af-surface-container-low"
                  : "border-af-outline-variant hover:border-af-primary"
              }`}
            >
              <span
                className={`material-symbols-outlined ${
                  isSelected ? "text-af-on-surface" : "text-af-on-surface-variant"
                }`}
                style={{ fontVariationSettings: isSelected ? "'FILL' 1" : "'FILL' 0" }}
              >
                {d.icon}
              </span>
              <span className={`text-sm font-semibold ${isSelected ? "text-af-on-surface" : "text-af-on-surface-variant"}`}>
                {d.label}
              </span>
              <span className="text-[10px] text-af-on-surface-variant">{d.eta}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 8: Wire `DepthSelector` into `LaunchForm`**

In `components/analyze/launch-form.tsx`: add `import type { DepthKey } from "./depth-selector";`, add state `const [depth, setDepth] = useState<DepthKey>("quick");`, change `<DepthSelector />` to `<DepthSelector value={depth} onChange={setDepth} />`, and change the `submitAnalysis({ ticker, push: router.push })` call to `submitAnalysis({ ticker, depth, push: router.push })`.

- [ ] **Step 8a: Manually verify `DepthSelector` in the browser**

Run: `pnpm dev`, open `http://localhost:3000/analyze` (or wherever `LaunchForm` renders). Click each of the three depth cards and confirm: the clicked card gets the `border-af-primary` highlight and the other two lose it, exactly one card is highlighted at a time, and "Quick Scan" is highlighted by default on page load.

- [ ] **Step 9: Run tests to verify they pass**

Run: `pnpm vitest run tests/api.jobs.test.ts tests/components/submit-analysis.test.ts tests/daytona.test.ts`
Expected: PASS (all three files)

- [ ] **Step 10: Full frontend test suite + typecheck**

Run: `pnpm test && pnpm tsc --noEmit`
Expected: PASS — no regressions in unrelated tests, no type errors.

- [ ] **Step 11: Commit**

```bash
git add lib/runtime/index.ts lib/runtime/subprocess.ts app/api/jobs/route.ts \
        lib/analyze/submit-analysis.ts components/analyze/depth-selector.tsx \
        components/analyze/launch-form.tsx tests/api.jobs.test.ts \
        tests/components/submit-analysis.test.ts
git commit -m "feat(frontend): wire depth selector through submit → API → sandbox spawn"
```

---

### Task 4: extended result schema + `InvestmentThesis` rendering

**Files:**
- Modify: `lib/job/types.ts`
- Modify: `components/job/investment-thesis.tsx`

**Note:** same test-infrastructure gap as Task 3 — no `@testing-library/react`/
jsdom in this repo, no component is render-tested. `InvestmentThesis`'s new
conditional sections are verified via `tsc --noEmit` (Step 2 below) plus the
manual end-to-end browser check folded into Task 10's `deep`-tier smoke run
(which is the first point in the plan a real `deep`-tier result exists to
render).

**Interfaces:**
- Consumes: `ThesisPoint` (existing, `lib/job/types.ts`).
- Produces: `SerializedJob.result.{researcher_findings,fundamentals_analysis,risk_analysis}?: ThesisPoint[]`.

- [ ] **Step 1: Extend the result type**

In `lib/job/types.ts`, add to `SerializedJob.result`, after `key_risks?: ThesisPoint[];`:

```ts
    researcher_findings?: ThesisPoint[];
    fundamentals_analysis?: ThesisPoint[];
    risk_analysis?: ThesisPoint[];
```

- [ ] **Step 2: Render the sections conditionally**

In `components/job/investment-thesis.tsx`, inside the `InvestmentThesis` function, after the existing `const risks = ...` line, add:

```ts
  const researcherFindings = result?.researcher_findings;
  const fundamentalsAnalysis = result?.fundamentals_analysis;
  const riskAnalysis = result?.risk_analysis;
```

After the closing `</div>` of the bull/bear grid and before the existing `<ThesisSection title="Key Risks" ...>` line, add:

```tsx
      {researcherFindings && (
        <ThesisSection title="Researcher Findings" points={researcherFindings} accent="text-af-secondary" />
      )}
      {fundamentalsAnalysis && (
        <ThesisSection title="Fundamentals Analysis" points={fundamentalsAnalysis} accent="text-af-secondary" />
      )}
      {riskAnalysis && (
        <ThesisSection title="Risk Analysis" points={riskAnalysis} accent="text-af-signal-hold" />
      )}
```

- [ ] **Step 3: Typecheck and run the full frontend suite**

Run: `pnpm tsc --noEmit && pnpm test`
Expected: PASS — no type errors, no regressions in existing tests (this task adds no new automated tests; visual confirmation happens in Task 10).

- [ ] **Step 4: Commit**

```bash
git add lib/job/types.ts components/job/investment-thesis.tsx
git commit -m "feat(frontend): render deep-tier researcher/fundamentals/risk sections"
```

---

### Task 5: You.com search/news tools (`agent/lib/youdotcom.py`)

**Files:**
- Create: `agent/lib/youdotcom.py`
- Modify: `agent/requirements.txt` (no new dependency — `httpx` already present)
- Modify: `agent/.env.example` → repo-root `.env.example` already covers `YOUDOTCOM_API_KEY` forwarding (Task 2); add the agent-side doc comment
- Test: `agent/tests/test_youdotcom.py` (new)

**Interfaces:**
- Consumes: `agent.lib.tools._observed_tool` (existing).
- Produces: `build_youdotcom_tools() -> dict[str, Callable]` — a registry with keys `"youdotcom_search"`, `"youdotcom_news"`, each `(args: dict) -> dict` following the `_observed_tool` contract (`{"query": ...}` in, `{"results": [{"title","url","snippet"}]}` out, or `{"error": ...}`).

- [ ] **Step 1: Write the failing tests**

```python
# agent/tests/test_youdotcom.py
import httpx
import pytest
from unittest.mock import MagicMock, patch
import lib.youdotcom as youdotcom


def _spy(monkeypatch):
    logs = []
    monkeypatch.setattr(youdotcom.tools, "emit_log",
                        lambda level, msg, **kw: logs.append((level, msg, kw)))
    span = MagicMock()
    monkeypatch.setattr(youdotcom.tools.trace, "get_current_span", lambda: span)
    return logs, span


def test_search_maps_response_to_results(monkeypatch):
    _spy(monkeypatch)
    fake_response = MagicMock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {
        "hits": [{"title": "Acme Q3 beats estimates", "url": "https://x.test/a", "description": "Acme reported..."}]
    }
    with patch.object(youdotcom.httpx, "get", return_value=fake_response) as get:
        out = youdotcom._search({"query": "Acme Q3 earnings"})
    assert out == {"results": [{"title": "Acme Q3 beats estimates", "url": "https://x.test/a", "snippet": "Acme reported..."}]}
    assert get.call_args.kwargs["params"]["query"] == "Acme Q3 earnings"


def test_search_missing_query_returns_error(monkeypatch):
    _spy(monkeypatch)
    assert youdotcom._search({}) == {"error": "missing query"}


def test_search_http_error_is_caught_by_observed_tool(monkeypatch):
    logs, span = _spy(monkeypatch)
    with patch.object(youdotcom.httpx, "get", side_effect=httpx.HTTPError("boom")):
        registry = youdotcom.build_youdotcom_tools()
        out = registry["youdotcom_search"]({"query": "Acme"})
    assert "error" in out
    assert any(m == "tool.youdotcom_search.failed" for _, m, _ in logs)


def test_news_maps_response_to_results(monkeypatch):
    _spy(monkeypatch)
    fake_response = MagicMock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {
        "news": {"results": [{"title": "Acme guidance raised", "url": "https://x.test/b", "description": "..."}]}
    }
    with patch.object(youdotcom.httpx, "get", return_value=fake_response):
        out = youdotcom._news({"query": "Acme"})
    assert out["results"][0]["title"] == "Acme guidance raised"


def test_build_youdotcom_tools_returns_matching_registry():
    registry = youdotcom.build_youdotcom_tools()
    assert set(registry.keys()) == {"youdotcom_search", "youdotcom_news"}
    assert all(callable(fn) for fn in registry.values())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent && .venv/bin/pytest tests/test_youdotcom.py -v` (or the Windows-activated equivalent per the README)
Expected: FAIL — `lib.youdotcom` doesn't exist (`ModuleNotFoundError`).

- [ ] **Step 3: Implement**

```python
# agent/lib/youdotcom.py
"""You.com Search/News API tools for the deep-analysis crew's Researcher and
Risk Analyst agents. Reuses tools.py's _observed_tool for the same
never-raises / uniform-logging contract as the yfinance tools."""
import os
import httpx
from opentelemetry import trace

from . import tools

_SEARCH_URL = "https://api.ydc-index.io/search"
_NEWS_URL = "https://api.ydc-index.io/news"
_MAX_RESULTS = 5


def _headers() -> dict:
    return {"X-API-Key": os.environ.get("YOUDOTCOM_API_KEY", "")}


def _search(args: dict) -> dict:
    query = args.get("query")
    if not query:
        return {"error": "missing query"}
    resp = httpx.get(_SEARCH_URL, headers=_headers(), params={"query": query}, timeout=15)
    resp.raise_for_status()
    hits = resp.json().get("hits", [])[:_MAX_RESULTS]
    return {"results": [
        {"title": h.get("title"), "url": h.get("url"), "snippet": h.get("description")}
        for h in hits
    ]}


def _news(args: dict) -> dict:
    query = args.get("query")
    if not query:
        return {"error": "missing query"}
    resp = httpx.get(_NEWS_URL, headers=_headers(), params={"query": query}, timeout=15)
    resp.raise_for_status()
    hits = resp.json().get("news", {}).get("results", [])[:_MAX_RESULTS]
    return {"results": [
        {"title": h.get("title"), "url": h.get("url"), "snippet": h.get("description")}
        for h in hits
    ]}


def build_youdotcom_tools() -> dict:
    """Return a name->callable registry, each wrapped by _observed_tool so a
    You.com outage or bad response can never crash the crew."""
    return {
        "youdotcom_search": tools._observed_tool("youdotcom_search", _search),
        "youdotcom_news": tools._observed_tool("youdotcom_news", _news),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agent && .venv/bin/pytest tests/test_youdotcom.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add agent/lib/youdotcom.py agent/tests/test_youdotcom.py
git commit -m "feat(agent): add You.com search/news tools for the deep-analysis crew"
```

---

### Task 6: Daytona code-exec tool (`run_python_snippet`)

**Files:**
- Modify: `agent/lib/tools.py`
- Modify: `agent/requirements.txt` (add `daytona-sdk`)
- Test: `agent/tests/test_tools.py`

**Interfaces:**
- Consumes: `_observed_tool` (existing, same file).
- Produces: `build_code_exec_tool(sandbox_id: str | None = None) -> dict[str, Callable]` — registry key `"run_python_snippet"`, `(args: dict) -> dict` with `args = {"code": "<python source>"}`, returns `{"stdout": "..."}` or `{"error": ...}`.

- [ ] **Step 1: Write the failing tests**

Add to `agent/tests/test_tools.py`:

```python
def test_run_python_snippet_missing_code_returns_error():
    assert tools._run_python_snippet({}) == {"error": "missing code"}


def test_run_python_snippet_returns_stdout(monkeypatch):
    fake_result = MagicMock(result="42\n", exit_code=0)
    fake_sandbox = MagicMock()
    fake_sandbox.process.code_run.return_value = fake_result
    fake_daytona = MagicMock()
    fake_daytona.get.return_value = fake_sandbox
    monkeypatch.setattr(tools, "_daytona_client", lambda: fake_daytona)
    out = tools._run_python_snippet({"code": "print(6*7)"}, sandbox_id="sb-1")
    assert out == {"stdout": "42\n"}
    fake_daytona.get.assert_called_once_with("sb-1")
    fake_sandbox.process.code_run.assert_called_once_with("print(6*7)")


def test_run_python_snippet_nonzero_exit_is_error(monkeypatch):
    fake_result = MagicMock(result="Traceback...", exit_code=1)
    fake_sandbox = MagicMock()
    fake_sandbox.process.code_run.return_value = fake_result
    fake_daytona = MagicMock()
    fake_daytona.get.return_value = fake_sandbox
    monkeypatch.setattr(tools, "_daytona_client", lambda: fake_daytona)
    out = tools._run_python_snippet({"code": "1/0"}, sandbox_id="sb-1")
    assert "error" in out and "Traceback" in out["error"]


def test_build_code_exec_tool_wraps_with_observed_tool(monkeypatch):
    logs, span = _spy(monkeypatch)
    monkeypatch.setattr(tools, "_run_python_snippet",
                        lambda args, sandbox_id=None: {"stdout": "ok"})
    registry = tools.build_code_exec_tool(sandbox_id="sb-1")
    out = registry["run_python_snippet"]({"code": "pass"})
    assert out == {"stdout": "ok"}
    assert any(m == "tool.run_python_snippet.ok" for _, m, _ in logs)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent && .venv/bin/pytest tests/test_tools.py -k run_python_snippet -v`
Expected: FAIL — `tools._run_python_snippet` / `tools.build_code_exec_tool` don't exist.

- [ ] **Step 3: Implement**

Add near the top of `agent/lib/tools.py`, after the `yfinance` import:

```python
_daytona_client_singleton = None


def _daytona_client():
    """Lazily construct the Daytona SDK client using the same DAYTONA_API_KEY
    already forwarded into the sandbox for self_delete. Never called at
    import time so tests never need real credentials."""
    global _daytona_client_singleton
    if _daytona_client_singleton is None:
        import os
        from daytona_sdk import Daytona, DaytonaConfig
        _daytona_client_singleton = Daytona(DaytonaConfig(api_key=os.environ["DAYTONA_API_KEY"]))
    return _daytona_client_singleton
```

Add after `_get_earnings` (before the `_schema` helper):

```python
def _run_python_snippet(args, sandbox_id=None):
    code = args.get("code")
    if not code:
        return {"error": "missing code"}
    if not sandbox_id:
        return {"error": "no sandbox_id configured for code execution"}
    sandbox = _daytona_client().get(sandbox_id)
    result = sandbox.process.code_run(code)
    if getattr(result, "exit_code", 0) != 0:
        return {"error": str(result.result)}
    return {"stdout": str(result.result)}


def build_code_exec_tool(sandbox_id: str | None = None) -> dict:
    """Return a name->callable registry (just 'run_python_snippet') for the
    Fundamentals Analyst to compute custom ratios/derived metrics via Daytona
    code execution against the sandbox the agent is already running in."""
    def _run(args):
        return _run_python_snippet(args, sandbox_id=sandbox_id)
    return {"run_python_snippet": _observed_tool("run_python_snippet", _run)}
```

Add `daytona-sdk>=0.x` to `agent/requirements.txt` (pin the exact version available at implementation time — check `pip index versions daytona-sdk` or the Daytona docs' current recommended pin) under a new `# --- Daytona code-exec tool ---` comment near the top, next to `yfinance`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agent && .venv/bin/pytest tests/test_tools.py -v`
Expected: PASS (all tests in the file, old and new)

- [ ] **Step 5: Commit**

```bash
git add agent/lib/tools.py agent/requirements.txt agent/tests/test_tools.py
git commit -m "feat(agent): add Daytona code-exec tool for custom ratio computation"
```

---

### Task 7: extend `Thesis` with optional per-agent fields

**Files:**
- Modify: `agent/lib/llm.py`
- Test: `agent/tests/test_llm.py`

**Interfaces:**
- Produces: `Thesis` gains `researcher_findings: list[ThesisPoint] = []`, `fundamentals_analysis: list[ThesisPoint] = []`, `risk_analysis: list[ThesisPoint] = []` (defaulted, so today's quick-tier JSON — which never includes these keys — still parses unchanged).

- [ ] **Step 1: Write the failing tests**

Add to `agent/tests/test_llm.py`:

```python
def test_thesis_defaults_deep_tier_fields_to_empty_list():
    t = parse_thesis(_THESIS_JSON)
    assert t.researcher_findings == []
    assert t.fundamentals_analysis == []
    assert t.risk_analysis == []


def test_thesis_accepts_deep_tier_fields_when_present():
    deep_json = _THESIS_JSON[:-1] + (
        ',"researcher_findings":[{"claim":"c","evidence":"e","source_url":null}],'
        '"fundamentals_analysis":[{"claim":"c","evidence":"e","source_url":null}],'
        '"risk_analysis":[{"claim":"c","evidence":"e","source_url":null}]}'
    )
    t = parse_thesis(deep_json)
    assert len(t.researcher_findings) == 1
    assert len(t.fundamentals_analysis) == 1
    assert len(t.risk_analysis) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent && .venv/bin/pytest tests/test_llm.py -k deep_tier -v`
Expected: FAIL — `AttributeError`/`ValidationError`, the fields don't exist on `Thesis`.

- [ ] **Step 3: Implement**

In `agent/lib/llm.py`, in the `Thesis` class, add after `key_risks: list[ThesisPoint]`:

```python
    researcher_findings: list[ThesisPoint] = Field(default_factory=list)
    fundamentals_analysis: list[ThesisPoint] = Field(default_factory=list)
    risk_analysis: list[ThesisPoint] = Field(default_factory=list)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agent && .venv/bin/pytest tests/test_llm.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add agent/lib/llm.py agent/tests/test_llm.py
git commit -m "feat(agent): add optional deep-tier fields to Thesis schema"
```

---

### Task 8: the CrewAI crew (`agent/lib/crew.py`)

**Files:**
- Create: `agent/lib/crew.py`
- Modify: `agent/requirements.txt` (add `crewai`)
- Modify: `agent/lib/metrics.py`
- Modify: `agent/.env.example` (see Task 9 — env vars added there since it's colocated with the `DEPTH` dispatch doc)
- Test: `agent/tests/test_crew.py` (new)

**Interfaces:**
- Consumes: `Snapshot`/`fetch_snapshot` (`agent/lib/finance.py`), `Thesis`/`ThesisPoint` (Task 7), `build_toolset` (`agent/lib/tools.py`), `build_code_exec_tool` (Task 6), `build_youdotcom_tools` (Task 5).
- Produces: `run_crew_analysis(ticker: str, depth: str, sandbox_id: str | None) -> dict` — same return contract as `run_analysis`: a dict with all `Thesis` fields plus `"snapshot"`.

- [ ] **Step 1: Write the failing tests**

```python
# agent/tests/test_crew.py
from unittest.mock import MagicMock, patch
import lib.crew as crew
from lib.llm import Thesis, ThesisPoint


def _fake_snapshot():
    from lib.finance import Snapshot
    return Snapshot(currency="USD", as_of="2026-09-07T00:00:00Z")


def _fake_thesis_dict():
    return {
        "recommendation": "buy", "confidence": "medium", "summary": "s",
        "bull_case": [{"claim": "c", "evidence": "e", "source_url": None}],
        "bear_case": [], "key_risks": [],
        "researcher_findings": [{"claim": "r", "evidence": "re", "source_url": "https://x.test"}],
        "fundamentals_analysis": [{"claim": "f", "evidence": "fe", "source_url": None}],
        "risk_analysis": [{"claim": "k", "evidence": "ke", "source_url": None}],
    }


def test_run_crew_analysis_returns_thesis_plus_snapshot(monkeypatch):
    monkeypatch.setattr(crew, "fetch_snapshot", lambda ticker: _fake_snapshot())
    fake_crew_instance = MagicMock()
    fake_crew_instance.kickoff.return_value = MagicMock(raw=None)
    monkeypatch.setattr(crew, "_build_crew", lambda ticker, snapshot, sandbox_id, depth: fake_crew_instance)
    monkeypatch.setattr(crew, "_extract_thesis_dict", lambda crew_output: _fake_thesis_dict())

    out = crew.run_crew_analysis("MDB", depth="deep", sandbox_id="sb-1")

    assert out["recommendation"] == "buy"
    assert out["researcher_findings"][0]["claim"] == "r"
    assert out["snapshot"]["currency"] == "USD"
    fake_crew_instance.kickoff.assert_called_once()


def test_run_crew_analysis_validates_against_thesis_schema(monkeypatch):
    monkeypatch.setattr(crew, "fetch_snapshot", lambda ticker: None)
    bad_dict = _fake_thesis_dict()
    bad_dict["recommendation"] = "strong-buy"  # invalid enum value
    fake_crew_instance = MagicMock()
    fake_crew_instance.kickoff.return_value = MagicMock(raw=None)
    monkeypatch.setattr(crew, "_build_crew", lambda ticker, snapshot, sandbox_id, depth: fake_crew_instance)
    monkeypatch.setattr(crew, "_extract_thesis_dict", lambda crew_output: bad_dict)

    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        crew.run_crew_analysis("MDB", depth="deep", sandbox_id="sb-1")


def test_max_execution_seconds_reads_env_per_depth(monkeypatch):
    monkeypatch.setenv("CREW_MAX_EXECUTION_S_DEEP", "800")
    monkeypatch.setenv("CREW_MAX_EXECUTION_S_FULL", "1400")
    assert crew._max_execution_seconds("deep") == 800
    assert crew._max_execution_seconds("full") == 1400


def test_max_execution_seconds_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("CREW_MAX_EXECUTION_S_DEEP", raising=False)
    assert crew._max_execution_seconds("deep") == 780
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent && .venv/bin/pytest tests/test_crew.py -v`
Expected: FAIL — `lib.crew` doesn't exist.

- [ ] **Step 3: Implement**

```python
# agent/lib/crew.py
"""4-agent CrewAI crew for the deep/full analysis tiers: Researcher (You.com
search/news) -> Fundamentals Analyst (yfinance tools + Daytona code-exec) ->
Risk Analyst (You.com) -> Portfolio Manager (synthesis, no tools). Sequential
process — each task's output becomes the next task's context. Mirrors
run_analysis()'s contract exactly: same input, same output dict shape, raises
on total failure so agent.py's existing except/mark_failed path needs no
changes."""
import json
import os

from crewai import Agent, Crew, LLM, Process, Task
from crewai.tools import tool as crewai_tool

from .finance import Snapshot, fetch_snapshot
from .llm import Thesis
from .prompts import _format_facts
from .tools import build_toolset, build_code_exec_tool
from .youdotcom import build_youdotcom_tools

_DEFAULT_MAX_EXECUTION_S = {"deep": 780, "full": 1380}


def _max_execution_seconds(depth: str) -> int:
    env_key = f"CREW_MAX_EXECUTION_S_{depth.upper()}"
    raw = os.environ.get(env_key)
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return _DEFAULT_MAX_EXECUTION_S.get(depth, _DEFAULT_MAX_EXECUTION_S["deep"])


def _llm() -> LLM:
    return LLM(
        model=os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.environ.get("OPENAI_API_URL") or None,
    )


def _as_crewai_tools(registry: dict, arg_name: str) -> list:
    """Adapt a name->callable(args: dict) registry (the Responses-API/tools.py
    convention) into CrewAI @tool-decorated callables taking a single named
    string argument, JSON-encoding the underlying dict result for the LLM."""
    wrapped = []
    for name, fn in registry.items():
        def _make(name=name, fn=fn):
            @crewai_tool(name)
            def _tool_fn(**kwargs):
                return json.dumps(fn({arg_name: kwargs.get(arg_name, "")}))
            return _tool_fn
        wrapped.append(_make())
    return wrapped


def _build_crew(ticker: str, snapshot: Snapshot | None, sandbox_id: str | None, depth: str) -> Crew:
    llm = _llm()
    max_exec = _max_execution_seconds(depth) // 4
    facts = _format_facts(snapshot) if snapshot else f"(No live facts available for {ticker}.)"

    youdotcom_tools = _as_crewai_tools(build_youdotcom_tools(), "query")
    financial_tools = _as_crewai_tools(build_toolset(ticker), "ticker")
    code_exec_tools = _as_crewai_tools(build_code_exec_tool(sandbox_id), "code")

    researcher = Agent(
        role="Equity Researcher",
        goal=f"Find recent news, catalysts, and management commentary about {ticker}",
        backstory="A sell-side research associate who reads every recent filing and news wire.",
        tools=youdotcom_tools, llm=llm, max_execution_time=max_exec,
    )
    fundamentals = Agent(
        role="Fundamentals Analyst",
        goal=f"Analyze {ticker}'s financials, valuation, and earnings trend, computing any custom ratios needed",
        backstory="A quant-leaning analyst who verifies every claim against hard numbers.",
        tools=[*financial_tools, *code_exec_tools], llm=llm, max_execution_time=max_exec,
    )
    risk = Agent(
        role="Risk Analyst",
        goal=f"Identify the biggest downside risks and catalysts for {ticker}",
        backstory="A skeptical analyst whose job is to find what could go wrong.",
        tools=youdotcom_tools, llm=llm, max_execution_time=max_exec,
    )
    pm = Agent(
        role="Portfolio Manager",
        goal="Synthesize the research, fundamentals, and risk analysis into one final call",
        backstory="A portfolio manager who weighs the team's research into a single buy/hold/sell decision.",
        tools=[], llm=llm, max_execution_time=max_exec,
    )

    research_task = Task(
        description=(
            f"Ticker: {ticker}\nFacts:\n{facts}\n"
            "Research recent news, catalysts, and management commentary. "
            "Return a JSON list of objects: {\"claim\": str, \"evidence\": str, \"source_url\": str|null}."
        ),
        expected_output="A JSON list of claim/evidence/source_url objects.",
        agent=researcher,
    )
    fundamentals_task = Task(
        description=(
            f"Ticker: {ticker}\nAnalyze financials, valuation, and earnings trend. "
            "Use run_python_snippet for any derived ratio not directly available. "
            "Return a JSON list of objects: {\"claim\": str, \"evidence\": str, \"source_url\": str|null}."
        ),
        expected_output="A JSON list of claim/evidence/source_url objects.",
        agent=fundamentals,
    )
    risk_task = Task(
        description=(
            f"Ticker: {ticker}\nIdentify the biggest downside risks and catalysts. "
            "Return a JSON list of objects: {\"claim\": str, \"evidence\": str, \"source_url\": str|null}."
        ),
        expected_output="A JSON list of claim/evidence/source_url objects.",
        agent=risk,
        context=[research_task],
    )
    pm_task = Task(
        description=(
            f"Ticker: {ticker}\nFacts:\n{facts}\n"
            "Using the researcher's findings, the fundamentals analysis, and the risk analysis, "
            "output ONLY a JSON object matching this schema:\n"
            "{\"recommendation\": \"buy\"|\"hold\"|\"sell\", \"confidence\": \"low\"|\"medium\"|\"high\", "
            "\"summary\": str, \"bull_case\": [...], \"bear_case\": [...], \"key_risks\": [...], "
            "\"researcher_findings\": [...], \"fundamentals_analysis\": [...], \"risk_analysis\": [...]}\n"
            "Each list item is {\"claim\": str, \"evidence\": str, \"source_url\": str|null}. "
            "Copy the upstream agents' findings verbatim into researcher_findings/fundamentals_analysis/"
            "risk_analysis; derive bull_case/bear_case/key_risks yourself from all three. Output JSON only."
        ),
        expected_output="A single JSON object matching the Thesis schema.",
        agent=pm,
        context=[research_task, fundamentals_task, risk_task],
    )

    return Crew(
        agents=[researcher, fundamentals, risk, pm],
        tasks=[research_task, fundamentals_task, risk_task, pm_task],
        process=Process.sequential,
    )


def _extract_thesis_dict(crew_output) -> dict:
    raw = getattr(crew_output, "raw", None) or str(crew_output)
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[len("json"):]
        cleaned = cleaned.strip()
    return json.loads(cleaned)


def run_crew_analysis(ticker: str, depth: str, sandbox_id: str | None) -> dict:
    snapshot = fetch_snapshot(ticker)
    crew_instance = _build_crew(ticker, snapshot, sandbox_id, depth)
    crew_output = crew_instance.kickoff()
    thesis_dict = _extract_thesis_dict(crew_output)
    thesis = Thesis(**thesis_dict)
    return {
        **thesis.model_dump(),
        "snapshot": snapshot.model_dump() if snapshot else None,
    }
```

Add `crewai>=0.100.0` to `agent/requirements.txt` under a new `# --- CrewAI deep-analysis tier ---` comment (verify the exact minimum version against whatever ships with the hackathon's provided credits/environment).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agent && .venv/bin/pytest tests/test_crew.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Add crew metrics to `agent/lib/metrics.py`**

Add two entries to the `_instruments` dict in `init_metrics` (after `"snapshot_completeness"`):

```python
        "crew_run_duration_ms": _meter.create_histogram("crew.run.duration_ms", unit="ms"),
        "crew_agent_tokens": _meter.create_histogram("crew.agent.tokens"),
```

Add two public functions at the end of the file (after `record_snapshot_completeness`):

```python
def record_crew_run_duration(final_status: str, ticker: str, depth: str, duration_ms: float) -> None:
    attrs = {"final_status": final_status, "ticker": ticker, "depth": depth}
    _hist("crew_run_duration_ms", duration_ms, attrs)
    _sentry_dist("crew.run.duration_ms", duration_ms, attrs)


def record_crew_agent_tokens(agent_role: str, tokens: int, ticker: str) -> None:
    attrs = {"agent_role": agent_role, "ticker": ticker}
    _hist("crew_agent_tokens", tokens, attrs)
    _sentry_dist("crew.agent.tokens", tokens, attrs)
```

(These are wired into `run_crew_analysis` and `agent.py` in Task 9, once the timing/host span code lands.)

- [ ] **Step 6: Run the full Python test suite**

Run: `cd agent && .venv/bin/pytest -v`
Expected: PASS — every existing test (llm, tools, agent_loop, db, finance, metrics, observability, otlp_target, prompts, self_delete) plus the new `test_crew.py`/`test_youdotcom.py`/extended `test_tools.py`/`test_llm.py`.

- [ ] **Step 7: Commit**

```bash
git add agent/lib/crew.py agent/lib/metrics.py agent/requirements.txt agent/tests/test_crew.py
git commit -m "feat(agent): add CrewAI deep-analysis crew (Researcher/Fundamentals/Risk/PM)"
```

---

### Task 9: `agent.py` dispatch on `DEPTH` + observability + env docs

**Files:**
- Modify: `agent/agent.py`
- Modify: `agent/.env.example`
- Test: `agent/tests/test_agent.py`

**Interfaces:**
- Consumes: `run_crew_analysis(ticker, depth, sandbox_id)` (Task 8), `run_analysis(ticker)` (existing).

- [ ] **Step 1: Write the failing tests**

Add to `agent/tests/test_agent.py` (check the existing file's mocking style for `run_analysis`/`get_job`/`mark_complete` first, then add analogous tests — the pattern below assumes `agent.main` imports `run_analysis` and `mark_complete` directly, matching the existing tests in this file):

```python
def test_main_dispatches_to_run_analysis_for_quick_depth(monkeypatch):
    monkeypatch.setenv("JOB_ID", "job-quick")
    monkeypatch.setattr(agent, "get_job", lambda jid: {"status": "pending", "ticker": "MDB", "depth": "quick", "sandbox_id": None})
    monkeypatch.setattr(agent, "mark_running", lambda jid: None)
    calls = {}
    monkeypatch.setattr(agent, "run_analysis", lambda ticker: calls.setdefault("quick", ticker) or {"recommendation": "buy"})
    monkeypatch.setattr(agent, "run_crew_analysis", lambda **kw: calls.setdefault("crew", kw) or {"recommendation": "buy"})
    monkeypatch.setattr(agent, "mark_complete", lambda *a, **kw: None)
    agent.main()
    assert calls == {"quick": "MDB"}


def test_main_dispatches_to_run_crew_analysis_for_deep_depth(monkeypatch):
    monkeypatch.setenv("JOB_ID", "job-deep")
    monkeypatch.setattr(agent, "get_job", lambda jid: {"status": "pending", "ticker": "MDB", "depth": "deep", "sandbox_id": "sb-1"})
    monkeypatch.setattr(agent, "mark_running", lambda jid: None)
    calls = {}
    monkeypatch.setattr(agent, "run_analysis", lambda ticker: calls.setdefault("quick", ticker) or {"recommendation": "buy"})
    monkeypatch.setattr(agent, "run_crew_analysis",
                        lambda ticker, depth, sandbox_id: calls.setdefault("crew", (ticker, depth, sandbox_id)) or {"recommendation": "buy"})
    monkeypatch.setattr(agent, "mark_complete", lambda *a, **kw: None)
    agent.main()
    assert calls == {"crew": ("MDB", "deep", "sb-1")}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent && .venv/bin/pytest tests/test_agent.py -k dispatch -v`
Expected: FAIL — `agent.run_crew_analysis` doesn't exist / `DEPTH` isn't read from the job row.

- [ ] **Step 3: Implement**

In `agent/agent.py`, add the import next to `from lib.llm import run_analysis`:

```python
from lib.crew import run_crew_analysis
```

Replace the line `result = run_analysis(ticker=job["ticker"])` with:

```python
            depth = job.get("depth") or "quick"
            span.set_attribute("depth", depth)
            if depth in ("deep", "full"):
                result = run_crew_analysis(ticker=job["ticker"], depth=depth, sandbox_id=job.get("sandbox_id"))
            else:
                result = run_analysis(ticker=job["ticker"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agent && .venv/bin/pytest tests/test_agent.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Document the env vars**

Add to `agent/.env.example` (create the file with this content if it doesn't already exist — check first; the root `.env.example` covers NextJS-forwarded vars, but if `agent/` has its own example file for local/subprocess use, add there; otherwise skip this step and rely on the root `.env.example`):

```
# --- Deep-analysis CrewAI tier (DEPTH=deep|full) ---
YOUDOTCOM_API_KEY=
# Per-tier wall-clock budget (seconds) for the whole crew, divided across its
# 4 agents. Must stay below the matching DAYTONA_AUTO_DELETE_<TIER>_S in the
# root .env.example so the crew finishes before the sandbox self-destructs.
CREW_MAX_EXECUTION_S_DEEP=780
CREW_MAX_EXECUTION_S_FULL=1380
```

- [ ] **Step 6: Run the full Python and NextJS test suites**

Run: `cd agent && .venv/bin/pytest -v && cd .. && pnpm test`
Expected: PASS — full regression check across both suites.

- [ ] **Step 7: Commit**

```bash
git add agent/agent.py agent/tests/test_agent.py agent/.env.example
git commit -m "feat(agent): dispatch to the CrewAI crew for deep/full depth tiers"
```

---

### Task 10: smoke test depth arg + README

**Files:**
- Modify: `scripts/smoke.sh`
- Modify: `README.md`

**Interfaces:**
- None (manual/e2e + docs only).

- [ ] **Step 1: Read the current `scripts/smoke.sh`** to find where it POSTs to `/api/jobs` and builds the request body, and where it reads `$1` for the ticker.

- [ ] **Step 2: Add an optional depth argument**

Change the ticker-arg line to also accept `$2`, defaulting to `quick`, e.g. (adapt to the script's actual variable names once read):

```bash
TICKER="${1:-AAPL}"
DEPTH="${2:-quick}"
```

and update the curl body to `{"ticker":"'"$TICKER"'","depth":"'"$DEPTH"'"}` (match existing quoting style in the file).

- [ ] **Step 3: Manually verify each tier**

Run (with `pnpm dev` already running in another terminal):
```bash
./scripts/smoke.sh AAPL quick
./scripts/smoke.sh AAPL deep
```
Expected: `pending → running → complete` for both; the `deep` run's final JSON includes non-empty `researcher_findings`/`fundamentals_analysis`/`risk_analysis`, and completes comfortably before `DAYTONA_AUTO_DELETE_DEEP_S`.

- [ ] **Step 3a: Manually verify the new `InvestmentThesis` sections render**

Open `http://localhost:3000/jobs/<the-deep-run's-job-id>` in a browser (the job id is printed by `smoke.sh`). Confirm the page shows "Researcher Findings", "Fundamentals Analysis", and "Risk Analysis" sections (in addition to the existing Bull Case/Bear Case/Key Risks), each populated with the crew's claim/evidence/source-link items. This is the first point in the plan a real `deep`-tier result exists, closing the loop on Task 4's `InvestmentThesis` change (which had no automated render test — see Task 4's note).

- [ ] **Step 4: Update `README.md`**

- Add a row to the "Optional — Agent runtime" table (or a new "Optional — Deep-analysis crew" table) documenting `YOUDOTCOM_API_KEY`, `DAYTONA_AUTO_DELETE_DEEP_S`/`_FULL_S`, `CREW_MAX_EXECUTION_S_DEEP`/`_FULL`.
- In "Out of scope (intentional YAGNI)", remove the line "Multi-step agent loops (planner → researcher → analyst)" since this plan implements it, and note the remaining scope boundary (One/auth integration stays out of scope, per the design spec).
- Add a short "HOW-TO: Enable the deep-analysis tier" section mirroring the existing HOW-TOs, pointing at `docs/superpowers/specs/2026-09-07-crewai-deep-analysis-design.md`.

- [ ] **Step 5: Commit**

```bash
git add scripts/smoke.sh README.md
git commit -m "docs: document the deep-analysis tier; smoke.sh accepts a depth arg"
```

---

## Self-Review Notes

- **Spec coverage:** §3 (schema/API) → Tasks 1, 3, 4. §3 autoDeleteInterval scaling → Task 2. §5 (crew/tools) → Tasks 5, 6, 8. §6 (timeouts/error handling/observability, env-driven per the follow-up request) → Tasks 2, 8, 9. §7 (testing plan) → a test step embedded in every task; `smoke.sh` → Task 10. §8 (out of scope) → not implemented, called out in Task 10 README update.
- **Type consistency:** `Depth` defined once in `lib/db/schema.ts` (Task 1) and imported everywhere else (Tasks 2, 3, 4) rather than redefined. `run_crew_analysis(ticker, depth, sandbox_id)` signature is identical between its definition (Task 8) and its call site (Task 9). `ThesisPoint` shape (`claim`/`evidence`/`source_url`) is reused verbatim for the three new result sections rather than introducing a second shape.
- **No placeholders:** every step has literal code/commands; the two "verify against installed version" notes (CrewAI's exact `max_execution_time` API surface in Task 8, the `daytona-sdk` pin in Task 6) are explicitly flagged as implementation-time lookups, not deferred design decisions — the design spec already calls these out as acceptable verify-during-build items, not gaps.
- **Pre-flight correction (post-authoring, pre-execution):** the original draft of Tasks 3 and 4 specified `@testing-library/react` component-render tests. This repo has no such dependency, no jsdom test environment (vitest is `environment: "node"`), and no existing component is render-tested. Rather than introduce new test infrastructure for two presentational components, both tasks were revised to rely on `tsc --noEmit` + a manual browser check (Task 3's Step 8a, Task 4 deferred to Task 10's Step 3a) — consistent with this repo's existing convention of testing only pure-logic modules automatically.
