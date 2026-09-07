# One Completion Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a job's submitter opt into a Slack or Gmail notification (via the One/withone.ai CLI) that fires once, automatically, when their analysis completes.

**Architecture:** Per-job `notifyChannel`/`notifyDestination` are captured at submit time and stored on the `jobs` row. The existing 2.5s status-polling route (`GET /api/status/[jobId]`) is the trigger point: the first poll that observes `status === "complete"` for a job with a notification configured atomically claims it (`notified_at` column, `UPDATE ... WHERE notified_at IS NULL`) and fires a `lib/notify/one.ts` helper that shells out to the One CLI. No Python/Daytona changes — One's CLI needs Node 18+, and NextJS already is Node.

**Tech Stack:** Next.js/TypeScript (drizzle-orm, zod, vitest), `@withone/cli` (Node, invoked via `execFile`).

## Global Constraints

- `notifyChannel` is exactly `"slack" | "gmail" | null` everywhere (DB CHECK, zod enum, TS union) — mirrors the existing `Depth`-type-in-one-place pattern from the prior feature.
- `notify_channel`/`notify_destination`/`notified_at` are all nullable with no default: old rows have no notification configured and must never become eligible for the claim check.
- `ONE_SECRET` is an operator-level secret (`.env` only) — if unset, submitting with `notifyChannel` set must be rejected with 400, never silently ignored.
- The claim (`UPDATE jobs SET notified_at = now() WHERE id = $1 AND notified_at IS NULL RETURNING id`) must happen **before** the One CLI is invoked, and a failed CLI call must never re-open the claim (no retry) — this is a deliberate, documented tradeoff, not a bug to "fix" later in this plan.
- The One CLI call must never throw an uncaught exception into `GET /api/status/[jobId]`'s response path — a notification failure must not change the HTTP response returned to the polling browser.
- `@withone/cli` must be a real `package.json` dependency (not solely relied upon via `npx` auto-install) so `npx --no-install` always resolves it locally.

---

### Task 1: `jobs` notify columns (DB + Drizzle schema + TS types)

**Files:**
- Create: `db/migrations/0002_add_notify.sql`
- Modify: `lib/db/schema.ts`
- Modify: `lib/job/types.ts`
- Test: `tests/db.schema.notify.test.ts` (new)

**Interfaces:**
- Produces: `NotifyChannel = "slack" | "gmail"` (exported from `lib/db/schema.ts`), `jobs.notifyChannel`/`notifyDestination`/`notifiedAt` columns, `SerializedJob.notifyChannel: NotifyChannel | null`, `SerializedJob.notifyDestination: string | null`, `SerializedJob.notifiedAt: string | null`.

- [ ] **Step 1: Write the failing test**

```ts
// tests/db.schema.notify.test.ts
import { describe, it, expect } from "vitest";
import { jobs } from "@/lib/db/schema";

describe("jobs notify columns", () => {
  it("has notifyChannel, notifyDestination, and notifiedAt columns", () => {
    expect(jobs.notifyChannel).toBeDefined();
    expect(jobs.notifyDestination).toBeDefined();
    expect(jobs.notifiedAt).toBeDefined();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm vitest run tests/db.schema.notify.test.ts`
Expected: FAIL — the three columns are `undefined`.

- [ ] **Step 3: Add the migration**

```sql
-- db/migrations/0002_add_notify.sql
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS notify_channel TEXT
  CHECK (notify_channel IN ('slack','gmail') OR notify_channel IS NULL);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS notify_destination TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS notified_at TIMESTAMPTZ;
```

- [ ] **Step 4: Update the Drizzle schema and types**

In `lib/db/schema.ts`, add the three columns to the `jobs` table definition, after the existing `completedAt` field:

```ts
    notifyChannel: text("notify_channel"),
    notifyDestination: text("notify_destination"),
    notifiedAt: timestamp("notified_at", { withTimezone: true }),
```

At the bottom of the file, alongside the existing type exports:

```ts
export type NotifyChannel = "slack" | "gmail";
```

In `lib/job/types.ts`, add to `SerializedJob` (after the existing `completedAt: string | null; // ISO` line):

```ts
  notifyChannel: NotifyChannel | null;
  notifyDestination: string | null;
  notifiedAt: string | null; // ISO
```

Add `import type { NotifyChannel } from "@/lib/db/schema";` as a new import line at the top of the file (matching the existing separate-import style already used for `JobStatus`/`Recommendation`).

- [ ] **Step 5: Run test to verify it passes**

Run: `pnpm vitest run tests/db.schema.notify.test.ts`
Expected: PASS

- [ ] **Step 6: Apply the migration to your Neon project**

Run: `make seed`
Expected: no errors; `psql $NEON_DATABASE_URL -c "\d jobs"` shows the three new columns.

- [ ] **Step 7: Commit**

```bash
git add db/migrations/0002_add_notify.sql lib/db/schema.ts lib/job/types.ts tests/db.schema.notify.test.ts
git commit -m "feat(db): add jobs notify_channel/notify_destination/notified_at columns"
```

---

### Task 2: `/api/jobs` accepts and validates notify fields

**Files:**
- Modify: `app/api/jobs/route.ts`
- Test: `tests/api.jobs.test.ts`

**Interfaces:**
- Consumes: `NotifyChannel` (Task 1).
- Produces: `POST /api/jobs` accepts optional `notifyChannel`/`notifyDestination`, stores them on the inserted row, rejects invalid combinations and a missing `ONE_SECRET` with 400.

- [ ] **Step 1: Write the failing tests**

Add to `tests/api.jobs.test.ts` (new `it`s inside the existing `describe`):

```ts
  it("accepts a valid slack notify config", async () => {
    process.env.ONE_SECRET = "sk_test";
    const res = await POST(req({ ticker: "AAPL", notifyChannel: "slack", notifyDestination: "#analysts" }));
    expect(res.status).toBe(200);
  });

  it("accepts a valid gmail notify config", async () => {
    process.env.ONE_SECRET = "sk_test";
    const res = await POST(req({ ticker: "AAPL", notifyChannel: "gmail", notifyDestination: "jane@example.com" }));
    expect(res.status).toBe(200);
  });

  it("rejects notifyChannel without a destination", async () => {
    process.env.ONE_SECRET = "sk_test";
    const res = await POST(req({ ticker: "AAPL", notifyChannel: "slack" }));
    expect(res.status).toBe(400);
  });

  it("rejects a malformed gmail destination", async () => {
    process.env.ONE_SECRET = "sk_test";
    const res = await POST(req({ ticker: "AAPL", notifyChannel: "gmail", notifyDestination: "not-an-email" }));
    expect(res.status).toBe(400);
  });

  it("rejects a malformed slack destination", async () => {
    process.env.ONE_SECRET = "sk_test";
    const res = await POST(req({ ticker: "AAPL", notifyChannel: "slack", notifyDestination: "general" }));
    expect(res.status).toBe(400);
  });

  it("rejects a notify request when ONE_SECRET is unset", async () => {
    delete process.env.ONE_SECRET;
    const res = await POST(req({ ticker: "AAPL", notifyChannel: "slack", notifyDestination: "#analysts" }));
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toMatch(/not configured/);
  });

  it("accepts a plain submit with no notify fields regardless of ONE_SECRET", async () => {
    delete process.env.ONE_SECRET;
    const res = await POST(req({ ticker: "AAPL" }));
    expect(res.status).toBe(200);
  });
```

Add a `beforeEach`/`afterEach` pair (or extend the existing `beforeEach(() => vi.clearAllMocks())`) to delete `process.env.ONE_SECRET` before each test, so tests don't leak state:

```ts
  beforeEach(() => {
    vi.clearAllMocks();
    delete process.env.ONE_SECRET;
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pnpm vitest run tests/api.jobs.test.ts`
Expected: FAIL — the new fields aren't in the zod schema yet, so valid requests 400 and the `ONE_SECRET` gate doesn't exist.

- [ ] **Step 3: Implement**

In `app/api/jobs/route.ts`, extend the zod `Body`:

```ts
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const SLACK_DEST_RE = /^[#@][\w-]+$/;

const Body = z.object({
  ticker: z.string().regex(/^[A-Z]{1,5}$/, "ticker must be 1-5 uppercase letters"),
  notifyChannel: z.enum(["slack", "gmail"]).optional(),
  notifyDestination: z.string().optional(),
})
  .refine((b) => !b.notifyChannel || !!b.notifyDestination, {
    message: "notifyDestination is required when notifyChannel is set",
    path: ["notifyDestination"],
  })
  .refine((b) => b.notifyChannel !== "gmail" || !b.notifyDestination || EMAIL_RE.test(b.notifyDestination), {
    message: "notifyDestination must be a valid email address for gmail",
    path: ["notifyDestination"],
  })
  .refine((b) => b.notifyChannel !== "slack" || !b.notifyDestination || SLACK_DEST_RE.test(b.notifyDestination), {
    message: "notifyDestination must start with # (channel) or @ (user) for slack",
    path: ["notifyDestination"],
  });
```

In the `POST` handler, after the existing `Body.parse(...)` try/catch block (which already returns 400 on a zod failure), add the `ONE_SECRET` gate before the `db.insert`:

```ts
    if (parsed.notifyChannel && !process.env.ONE_SECRET) {
      addAttrs(span, { outcome: "rejected" });
      jobsSubmitted("rejected", parsed.ticker);
      return Response.json({ error: "notifications are not configured on this server" }, { status: 400 });
    }
```

Update the `db.insert(jobs).values({...})` call to include the notify fields:

```ts
    const [{ id: jobId }] = await db
      .insert(jobs)
      .values({ ticker: parsed.ticker, notifyChannel: parsed.notifyChannel, notifyDestination: parsed.notifyDestination })
      .returning({ id: jobs.id });
```

(If Task 1's crewai-deep-analysis branch's `depth` field has already been merged to `main` by the time this task is implemented, keep that field in the `values({...})` call too — check the current file content before editing rather than assuming a stale shape.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm vitest run tests/api.jobs.test.ts`
Expected: PASS (all tests in the file, old and new)

- [ ] **Step 5: Full frontend test suite + typecheck**

Run: `pnpm test && pnpm tsc --noEmit`
Expected: PASS — no regressions, no new type errors (check the baseline error count on `main` first with `pnpm tsc --noEmit` before this task's changes, and confirm your change introduces zero new ones — `main` may have zero or a handful of pre-existing errors depending on what's landed since the last check; the point is delta-zero, not a fixed magic number).

- [ ] **Step 6: Commit**

```bash
git add app/api/jobs/route.ts tests/api.jobs.test.ts
git commit -m "feat(api): validate and gate notifyChannel/notifyDestination on job submit"
```

---

### Task 3: the One CLI helper (`lib/notify/one.ts`)

**Files:**
- Create: `lib/notify/one.ts`
- Modify: `package.json` (add `@withone/cli` dependency)
- Test: `tests/lib/notify-one.test.ts` (new)

**Interfaces:**
- Produces: `sendCompletionNotification(job: { ticker: string; recommendation: string | null; summary: string | undefined; notifyChannel: "slack" | "gmail"; notifyDestination: string }): Promise<void>` — never throws.

- [ ] **Step 1: Write the failing tests**

```ts
// tests/lib/notify-one.test.ts
import { describe, it, expect, vi, beforeEach } from "vitest";

const execFileMock = vi.fn((_cmd: string, _args: string[], _opts: unknown, cb: (err: Error | null) => void) => cb(null));

vi.mock("node:child_process", () => ({ execFile: execFileMock }));

describe("sendCompletionNotification", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    process.env.ONE_SECRET = "sk_test";
    process.env.ONE_SLACK_CONNECTION_KEY = "conn-slack";
    process.env.ONE_SLACK_SEND_ACTION_ID = "action-slack";
    process.env.ONE_GMAIL_CONNECTION_KEY = "conn-gmail";
    process.env.ONE_GMAIL_SEND_ACTION_ID = "action-gmail";
  });

  it("builds a slack payload and invokes the CLI with the slack action/connection", async () => {
    const { sendCompletionNotification } = await import("@/lib/notify/one");
    await sendCompletionNotification({
      ticker: "AAPL", recommendation: "buy", summary: "Strong quarter.",
      notifyChannel: "slack", notifyDestination: "#analysts",
    });
    const call = execFileMock.mock.calls[0];
    expect(call[0]).toBe("npx");
    expect(call[1]).toEqual(expect.arrayContaining([
      "--no-install", "@withone/cli", "actions", "execute", "slack", "action-slack", "conn-slack",
    ]));
    const dArgIndex = (call[1] as string[]).indexOf("-d");
    const payload = JSON.parse((call[1] as string[])[dArgIndex + 1]);
    expect(payload.channel).toBe("#analysts");
    expect(payload.text).toContain("AAPL");
    expect(payload.text).toContain("buy");
  });

  it("builds a gmail payload and invokes the CLI with the gmail action/connection", async () => {
    const { sendCompletionNotification } = await import("@/lib/notify/one");
    await sendCompletionNotification({
      ticker: "MDB", recommendation: "hold", summary: "Mixed signals.",
      notifyChannel: "gmail", notifyDestination: "jane@example.com",
    });
    const call = execFileMock.mock.calls[0];
    expect(call[1]).toEqual(expect.arrayContaining([
      "actions", "execute", "gmail", "action-gmail", "conn-gmail",
    ]));
    const dArgIndex = (call[1] as string[]).indexOf("-d");
    const payload = JSON.parse((call[1] as string[])[dArgIndex + 1]);
    expect(payload.to).toBe("jane@example.com");
    expect(payload.subject).toContain("MDB");
    expect(payload.body).toContain("hold");
  });

  it("never throws when the CLI call fails", async () => {
    execFileMock.mockImplementationOnce((_cmd, _args, _opts, cb) => cb(new Error("boom")));
    const { sendCompletionNotification } = await import("@/lib/notify/one");
    await expect(sendCompletionNotification({
      ticker: "AAPL", recommendation: "buy", summary: "x",
      notifyChannel: "slack", notifyDestination: "#analysts",
    })).resolves.toBeUndefined();
  });

  it("never throws when the connection/action env vars are missing", async () => {
    delete process.env.ONE_SLACK_CONNECTION_KEY;
    const { sendCompletionNotification } = await import("@/lib/notify/one");
    await expect(sendCompletionNotification({
      ticker: "AAPL", recommendation: "buy", summary: "x",
      notifyChannel: "slack", notifyDestination: "#analysts",
    })).resolves.toBeUndefined();
    expect(execFileMock).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pnpm vitest run tests/lib/notify-one.test.ts`
Expected: FAIL — `lib/notify/one.ts` doesn't exist (`Cannot find module`).

- [ ] **Step 3: Implement**

```ts
// lib/notify/one.ts
import { execFile as execFileCb } from "node:child_process";
import { promisify } from "node:util";
import * as Sentry from "@sentry/nextjs";
import { ddLog } from "./observability-shim"; // see note below — resolve the real import path

const execFile = promisify(execFileCb);

type NotifyJob = {
  ticker: string;
  recommendation: string | null;
  summary: string | undefined;
  notifyChannel: "slack" | "gmail";
  notifyDestination: string;
};

function buildPayload(job: NotifyJob): Record<string, string> {
  const rec = job.recommendation ?? "unknown";
  const summary = job.summary ?? "";
  if (job.notifyChannel === "slack") {
    return {
      channel: job.notifyDestination,
      text: `*${job.ticker}* analysis complete — recommendation: *${rec}*\n${summary}`,
    };
  }
  return {
    to: job.notifyDestination,
    subject: `${job.ticker} analysis complete (${rec})`,
    body: summary,
  };
}

function credentialsFor(channel: "slack" | "gmail"): { connectionKey: string; actionId: string } | null {
  const prefix = channel === "slack" ? "ONE_SLACK" : "ONE_GMAIL";
  const connectionKey = process.env[`${prefix}_CONNECTION_KEY`];
  const actionId = process.env[`${prefix}_SEND_ACTION_ID`];
  if (!connectionKey || !actionId) return null;
  return { connectionKey, actionId };
}

export async function sendCompletionNotification(job: NotifyJob): Promise<void> {
  const creds = credentialsFor(job.notifyChannel);
  if (!creds || !process.env.ONE_SECRET) {
    ddLog("warn", "notify.one.skipped", { channel: job.notifyChannel, reason: "missing_credentials" });
    return;
  }
  const payload = buildPayload(job);
  try {
    await execFile("npx", [
      "--no-install", "@withone/cli", "actions", "execute",
      job.notifyChannel, creds.actionId, creds.connectionKey,
      "-d", JSON.stringify(payload), "--agent",
    ], { env: { ...process.env } });
    ddLog("info", "notify.one.sent", { channel: job.notifyChannel, ticker: job.ticker });
  } catch (e) {
    Sentry.logger?.warn?.("notify.one.failed", { channel: job.notifyChannel, ticker: job.ticker, error: String(e) });
    ddLog("warn", "notify.one.failed", { channel: job.notifyChannel, ticker: job.ticker, error: String(e) });
  }
}
```

**Before writing this file**, read `lib/observability/exporters/datadog.ts` to find the real exported name/path for the `ddLog` helper already used in `lib/daytona.ts` (the sketch above uses a placeholder import path — replace it with the real one, matching exactly how `lib/daytona.ts` imports it). Do not invent a new logging helper; reuse the existing one.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm vitest run tests/lib/notify-one.test.ts`
Expected: PASS (5 tests)

- [ ] **Step 5: Add the real dependency**

Run: `pnpm add @withone/cli`
Expected: `package.json`'s `dependencies` gains `"@withone/cli": "^<installed-version>"`, `pnpm-lock.yaml` updates.

- [ ] **Step 6: Full frontend test suite + typecheck**

Run: `pnpm test && pnpm tsc --noEmit`
Expected: PASS — zero new type errors vs. the baseline captured in Task 2.

- [ ] **Step 7: Commit**

```bash
git add lib/notify/one.ts package.json pnpm-lock.yaml tests/lib/notify-one.test.ts
git commit -m "feat(notify): add the One CLI wrapper for completion notifications"
```

---

### Task 4: wire the claim-and-send into `/api/status/[jobId]`

**Files:**
- Modify: `app/api/status/[jobId]/route.ts`
- Test: `tests/api.status.notify.test.ts` (new)

**Interfaces:**
- Consumes: `sendCompletionNotification` (Task 3).
- Produces: `GET /api/status/[jobId]` fires the notification exactly once per job, on the first poll that observes `status === "complete"` with a notify channel configured and `notified_at` still null; the returned JSON reflects the claimed `notifiedAt` in the same response.

- [ ] **Step 1: Write the failing tests**

```ts
// tests/api.status.notify.test.ts
import { describe, it, expect, vi, beforeEach } from "vitest";

const sendMock = vi.fn(async () => {});
vi.mock("@/lib/notify/one", () => ({ sendCompletionNotification: sendMock }));

const baseRow = {
  id: "job-1", ticker: "AAPL", status: "complete", recommendation: "buy",
  result: { summary: "s" }, sandboxId: "sb-1",
  createdAt: new Date(), startedAt: new Date(), completedAt: new Date(),
  error: null, notifyChannel: "slack" as const, notifyDestination: "#analysts",
  notifiedAt: null as Date | null,
};

function mockDb(row: typeof baseRow, claimSucceeds: boolean) {
  const limit = vi.fn(async () => [row]);
  const whereSelect = vi.fn(() => ({ limit }));
  const from = vi.fn(() => ({ where: whereSelect }));
  const select = vi.fn(() => ({ from }));

  const returning = vi.fn(async () => (claimSucceeds ? [{ id: row.id }] : []));
  const whereUpdate = vi.fn(() => ({ returning }));
  const set = vi.fn(() => ({ where: whereUpdate }));
  const update = vi.fn(() => ({ set }));

  return { db: { select, update }, jobs: { id: "id", status: "status", notifiedAt: "notifiedAt" }, __select: select, __update: update };
}

describe("GET /api/status/[jobId] notification trigger", () => {
  beforeEach(() => vi.clearAllMocks());

  it("sends the notification and returns notifiedAt when the job just completed", async () => {
    vi.resetModules();
    vi.doMock("@/lib/db/client", () => mockDb(baseRow, true));
    const { GET } = await import("@/app/api/status/[jobId]/route");
    const res = await GET(new Request("http://localhost"), { params: Promise.resolve({ jobId: "job-1" }) });
    const body = await res.json();
    expect(sendMock).toHaveBeenCalledTimes(1);
    expect(body.notifiedAt).toBeTruthy();
  });

  it("does not send when notifyChannel is null", async () => {
    vi.resetModules();
    vi.doMock("@/lib/db/client", () => mockDb({ ...baseRow, notifyChannel: null, notifyDestination: null }, true));
    const { GET } = await import("@/app/api/status/[jobId]/route");
    await GET(new Request("http://localhost"), { params: Promise.resolve({ jobId: "job-1" }) });
    expect(sendMock).not.toHaveBeenCalled();
  });

  it("does not send when notifiedAt is already set", async () => {
    vi.resetModules();
    vi.doMock("@/lib/db/client", () => mockDb({ ...baseRow, notifiedAt: new Date() }, true));
    const { GET } = await import("@/app/api/status/[jobId]/route");
    await GET(new Request("http://localhost"), { params: Promise.resolve({ jobId: "job-1" }) });
    expect(sendMock).not.toHaveBeenCalled();
  });

  it("does not send when status is not complete", async () => {
    vi.resetModules();
    vi.doMock("@/lib/db/client", () => mockDb({ ...baseRow, status: "running" }, true));
    const { GET } = await import("@/app/api/status/[jobId]/route");
    await GET(new Request("http://localhost"), { params: Promise.resolve({ jobId: "job-1" }) });
    expect(sendMock).not.toHaveBeenCalled();
  });

  it("does not send when the atomic claim loses the race (already claimed by a concurrent poll)", async () => {
    vi.resetModules();
    vi.doMock("@/lib/db/client", () => mockDb(baseRow, false));
    const { GET } = await import("@/app/api/status/[jobId]/route");
    await GET(new Request("http://localhost"), { params: Promise.resolve({ jobId: "job-1" }) });
    expect(sendMock).not.toHaveBeenCalled();
  });

  it("still returns 200 with the job data when the notification call rejects", async () => {
    vi.resetModules();
    sendMock.mockRejectedValueOnce(new Error("cli failed"));
    vi.doMock("@/lib/db/client", () => mockDb(baseRow, true));
    const { GET } = await import("@/app/api/status/[jobId]/route");
    const res = await GET(new Request("http://localhost"), { params: Promise.resolve({ jobId: "job-1" }) });
    expect(res.status).toBe(200);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pnpm vitest run tests/api.status.notify.test.ts`
Expected: FAIL — the route doesn't call `sendCompletionNotification` or attempt any claim yet.

- [ ] **Step 3: Implement**

```ts
// app/api/status/[jobId]/route.ts
import { and, eq, isNull } from "drizzle-orm";
import { db, jobs } from "@/lib/db/client";
import { traced, addAttrs } from "@/lib/observability/api";
import { sendCompletionNotification } from "@/lib/notify/one";

type Ctx = { params: Promise<{ jobId: string }> };

export async function GET(_req: Request, ctx: Ctx): Promise<Response> {
  const { jobId } = await ctx.params;
  return traced("api.status.get", { job_id: jobId }, async (span) => {
    const rows = await db.select().from(jobs).where(eq(jobs.id, jobId)).limit(1);
    if (rows.length === 0) {
      addAttrs(span, { outcome: "not_found" });
      return Response.json({ error: "not_found" }, { status: 404 });
    }
    let row = rows[0];
    addAttrs(span, { status: row.status });

    if (row.status === "complete" && row.notifyChannel && row.notifyDestination && !row.notifiedAt) {
      const claimed = await db
        .update(jobs)
        .set({ notifiedAt: new Date() })
        .where(and(eq(jobs.id, jobId), isNull(jobs.notifiedAt)))
        .returning({ id: jobs.id });
      if (claimed.length > 0) {
        const claimedAt = new Date();
        row = { ...row, notifiedAt: claimedAt };
        addAttrs(span, { notify_claimed: true });
        try {
          await sendCompletionNotification({
            ticker: row.ticker,
            recommendation: row.recommendation,
            summary: (row.result as { summary?: string } | null)?.summary,
            notifyChannel: row.notifyChannel as "slack" | "gmail",
            notifyDestination: row.notifyDestination,
          });
        } catch {
          // sendCompletionNotification already swallows its own errors and
          // never rejects; this catch is a last-resort guard so a future
          // change there can never break the status endpoint.
        }
      }
    }

    return Response.json(row);
  });
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm vitest run tests/api.status.notify.test.ts tests/api.status.test.ts`
Expected: PASS (both files — confirm the pre-existing `tests/api.status.test.ts` tests, which use a job row without notify fields, still pass unchanged: `notifyChannel` will be `undefined` on that mock row, which is falsy, so the new branch is skipped).

- [ ] **Step 5: Full frontend test suite + typecheck**

Run: `pnpm test && pnpm tsc --noEmit`
Expected: PASS — zero new type errors vs. the Task 2 baseline.

- [ ] **Step 6: Commit**

```bash
git add app/api/status/\[jobId\]/route.ts tests/api.status.notify.test.ts
git commit -m "feat(api): claim-and-send completion notification from the status poll"
```

---

### Task 5: `NotifyPicker` UI + `LaunchForm`/`submitAnalysis` wiring

**Files:**
- Create: `components/analyze/notify-picker.tsx`
- Modify: `components/analyze/launch-form.tsx`
- Modify: `lib/analyze/submit-analysis.ts`
- Test: `tests/components/submit-analysis.test.ts`

**Interfaces:**
- Consumes: nothing new from earlier tasks (this task's frontend pieces are independent of Tasks 1-4's backend, aside from sharing the same field names).
- Produces: `NotifyPicker({ channel, destination, onChannelChange, onDestinationChange })`, `submitAnalysis({ ..., notifyChannel?, notifyDestination? })`.

**Note:** same test-infrastructure gap as `DepthSelector`/`InvestmentThesis` from the prior feature — no `@testing-library/react`/jsdom in this repo. `NotifyPicker` is verified manually via `pnpm dev` (Step 6 below), not with an automated render test.

- [ ] **Step 1: Write the failing tests**

Add to `tests/components/submit-analysis.test.ts` (new `it`s):

```ts
  it("omits notify fields from the POST body when no channel is selected", async () => {
    const fetchImpl = makeFetch(200, { jobId: "job-1" });
    const push = vi.fn();
    await submitAnalysis({ ticker: "AAPL", fetchImpl, push });
    const body = JSON.parse((fetchImpl as any).mock.calls[0][1].body);
    expect(body.notifyChannel).toBeUndefined();
    expect(body.notifyDestination).toBeUndefined();
  });

  it("includes notify fields in the POST body when a channel is selected", async () => {
    const fetchImpl = makeFetch(200, { jobId: "job-1" });
    const push = vi.fn();
    await submitAnalysis({ ticker: "AAPL", notifyChannel: "slack", notifyDestination: "#analysts", fetchImpl, push });
    const body = JSON.parse((fetchImpl as any).mock.calls[0][1].body);
    expect(body.notifyChannel).toBe("slack");
    expect(body.notifyDestination).toBe("#analysts");
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pnpm vitest run tests/components/submit-analysis.test.ts`
Expected: FAIL — `submitAnalysis` doesn't accept/forward the new fields yet.

- [ ] **Step 3: Implement `submitAnalysis`**

In `lib/analyze/submit-analysis.ts`, extend `SubmitParams`:

```ts
export type SubmitParams = {
  ticker: string;
  notifyChannel?: "slack" | "gmail";
  notifyDestination?: string;
  fetchImpl?: typeof fetch;
  push: (path: string) => void;
};
```

Update the function signature and the request body construction:

```ts
export async function submitAnalysis({ ticker, notifyChannel, notifyDestination, fetchImpl, push }: SubmitParams): Promise<SubmitResult> {
  const doFetch: typeof fetch = fetchImpl ?? fetch;
  const value = ticker.trim().toUpperCase();
  if (!TICKER_RE.test(value)) {
    return { ok: false, error: "Ticker must be 1–5 uppercase letters." };
  }

  const body: Record<string, string> = { ticker: value };
  if (notifyChannel) {
    body.notifyChannel = notifyChannel;
    if (notifyDestination) body.notifyDestination = notifyDestination;
  }

  let res: Response;
  try {
    res = await doFetch("/api/jobs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    return { ok: false, error: "Submit failed" };
  }
  // ... rest of the function unchanged ...
```

(Keep the rest of the function — the response-handling logic after the `try/catch` — exactly as it is today; only the request-building portion above changes.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm vitest run tests/components/submit-analysis.test.ts`
Expected: PASS (all tests in the file, old and new)

- [ ] **Step 5: Implement `NotifyPicker` and wire it into `LaunchForm`**

```tsx
// components/analyze/notify-picker.tsx
"use client";

export type NotifyChannelOption = "none" | "slack" | "gmail";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const SLACK_DEST_RE = /^[#@][\w-]+$/;

export function validateDestination(channel: NotifyChannelOption, destination: string): string | null {
  if (channel === "none") return null;
  if (!destination) return "Destination is required.";
  if (channel === "gmail" && !EMAIL_RE.test(destination)) return "Enter a valid email address.";
  if (channel === "slack" && !SLACK_DEST_RE.test(destination)) return "Slack destination must start with # or @.";
  return null;
}

export function NotifyPicker({
  channel, destination, onChannelChange, onDestinationChange,
}: {
  channel: NotifyChannelOption;
  destination: string;
  onChannelChange: (c: NotifyChannelOption) => void;
  onDestinationChange: (d: string) => void;
}) {
  return (
    <div className="space-y-2">
      <label className="text-sm font-semibold text-af-on-surface">Notify me when done</label>
      <div className="flex gap-3">
        <select
          value={channel}
          onChange={(e) => onChannelChange(e.target.value as NotifyChannelOption)}
          className="border border-af-outline-variant rounded-lg px-3 py-2 text-sm bg-af-surface-container-lowest text-af-on-surface"
        >
          <option value="none">None</option>
          <option value="slack">Slack</option>
          <option value="gmail">Gmail</option>
        </select>
        {channel !== "none" && (
          <input
            type="text"
            value={destination}
            onChange={(e) => onDestinationChange(e.target.value)}
            placeholder={channel === "slack" ? "#analysts" : "you@company.com"}
            className="flex-1 border border-af-outline-variant rounded-lg px-3 py-2 text-sm bg-af-surface-container-lowest text-af-on-surface"
          />
        )}
      </div>
    </div>
  );
}
```

In `components/analyze/launch-form.tsx`: add imports `import { NotifyPicker, validateDestination, type NotifyChannelOption } from "./notify-picker";`, add state:

```ts
  const [notifyChannel, setNotifyChannel] = useState<NotifyChannelOption>("none");
  const [notifyDestination, setNotifyDestination] = useState("");
```

Render `<NotifyPicker channel={notifyChannel} destination={notifyDestination} onChannelChange={setNotifyChannel} onDestinationChange={setNotifyDestination} />` inside the existing input section, after `<DepthSelector />` (or after the ticker/depth inputs — wherever the existing input-fields block ends, matching the file's current layout).

In `onSubmit`, before calling `submitAnalysis`, add client-side validation and short-circuit on failure:

```ts
    const destErr = validateDestination(notifyChannel, notifyDestination);
    if (destErr) {
      setError(destErr);
      return;
    }
```

Update the `submitAnalysis(...)` call to pass the notify fields when a channel is selected:

```ts
      const result = await submitAnalysis({
        ticker,
        ...(notifyChannel !== "none" ? { notifyChannel, notifyDestination } : {}),
        push: router.push,
      });
```

- [ ] **Step 6: Manually verify `NotifyPicker` in the browser**

Run: `pnpm dev`, open the analyze/launch page. Confirm: selecting "None" hides the destination input; selecting "Slack" shows it with the `#analysts` placeholder; selecting "Gmail" shows it with the `you@company.com` placeholder; submitting with an invalid destination shows the inline error and does not call the API (check the network tab).

- [ ] **Step 7: Full frontend test suite + typecheck**

Run: `pnpm test && pnpm tsc --noEmit`
Expected: PASS — zero new type errors vs. the Task 2 baseline.

- [ ] **Step 8: Commit**

```bash
git add components/analyze/notify-picker.tsx components/analyze/launch-form.tsx lib/analyze/submit-analysis.ts tests/components/submit-analysis.test.ts
git commit -m "feat(frontend): add NotifyPicker and wire it into the launch form"
```

---

### Task 6: "Notified via …" badge on the job page

**Files:**
- Create: `lib/ui/notify-pill.ts`
- Create: `components/ui/notify-pill.tsx`
- Modify: `components/job/stock-header.tsx`
- Modify: `components/job/job-live-poller.tsx`
- Test: `tests/components/notify-pill.test.ts` (new — pure-function test, no rendering needed)

**Interfaces:**
- Consumes: `SerializedJob.notifyChannel`/`notifiedAt` (Task 1).
- Produces: `notifyPillProps(channel: NotifyChannel | null, notifiedAt: string | null): { label: string; className: string } | null`, `<NotifyPill channel={...} notifiedAt={...} />`.

- [ ] **Step 1: Write the failing test**

```ts
// tests/components/notify-pill.test.ts
import { describe, it, expect } from "vitest";
import { notifyPillProps } from "@/lib/ui/notify-pill";

describe("notifyPillProps", () => {
  it("returns null when notifiedAt is null", () => {
    expect(notifyPillProps("slack", null)).toBeNull();
  });

  it("returns null when channel is null", () => {
    expect(notifyPillProps(null, "2026-09-07T00:00:00Z")).toBeNull();
  });

  it("returns a Slack label when notified via slack", () => {
    const props = notifyPillProps("slack", "2026-09-07T00:00:00Z");
    expect(props?.label).toBe("Notified via Slack");
  });

  it("returns a Gmail label when notified via gmail", () => {
    const props = notifyPillProps("gmail", "2026-09-07T00:00:00Z");
    expect(props?.label).toBe("Notified via Gmail");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm vitest run tests/components/notify-pill.test.ts`
Expected: FAIL — `lib/ui/notify-pill.ts` doesn't exist.

- [ ] **Step 3: Implement**

```ts
// lib/ui/notify-pill.ts
import type { NotifyChannel } from "@/lib/db/schema";

export function notifyPillProps(
  channel: NotifyChannel | null,
  notifiedAt: string | null,
): { label: string; className: string } | null {
  if (!channel || !notifiedAt) return null;
  const label = channel === "slack" ? "Notified via Slack" : "Notified via Gmail";
  return { label, className: "bg-af-secondary-container text-af-on-secondary-container" };
}
```

```tsx
// components/ui/notify-pill.tsx
import { notifyPillProps } from "@/lib/ui/notify-pill";
import type { NotifyChannel } from "@/lib/db/schema";

export function NotifyPill({ channel, notifiedAt }: { channel: NotifyChannel | null; notifiedAt: string | null }) {
  const props = notifyPillProps(channel, notifiedAt);
  if (!props) return null;
  return (
    <span className={`inline-block px-3 py-1 rounded-full text-[12px] font-medium ${props.className}`}>
      {props.label}
    </span>
  );
}
```

In `components/job/stock-header.tsx`: add `notifyChannel: NotifyChannel | null` and `notifiedAt: string | null` to `Props`, import `NotifyPill` and `NotifyChannel`, and render `<NotifyPill channel={notifyChannel} notifiedAt={notifiedAt} />` next to the existing `<StatusPill />`/`<SignalPill />` pair.

In `components/job/job-live-poller.tsx`, pass the two new props through to `<StockHeader ... />`:

```tsx
      <StockHeader
        ticker={job.ticker}
        status={job.status}
        recommendation={job.recommendation}
        summary={job.result?.summary ?? null}
        snapshot={job.result?.snapshot ?? null}
        notifyChannel={job.notifyChannel}
        notifiedAt={job.notifiedAt}
      />
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm vitest run tests/components/notify-pill.test.ts`
Expected: PASS

- [ ] **Step 5: Manually verify the badge in the browser**

Given no live One credentials are available to actually trigger a real send in most dev setups, verify this by temporarily hardcoding a `notifiedAt` value into a job's row via the Neon SQL console (`UPDATE jobs SET notify_channel='slack', notified_at=now() WHERE id='<a completed job's id>';`), then reloading that job's page and confirming the "Notified via Slack" pill appears next to the status/signal pills. Revert the manual DB edit afterward (`UPDATE jobs SET notify_channel=NULL, notified_at=NULL WHERE id='<id>';`).

- [ ] **Step 6: Full frontend test suite + typecheck**

Run: `pnpm test && pnpm tsc --noEmit`
Expected: PASS — zero new type errors vs. the Task 2 baseline.

- [ ] **Step 7: Commit**

```bash
git add lib/ui/notify-pill.ts components/ui/notify-pill.tsx components/job/stock-header.tsx components/job/job-live-poller.tsx tests/components/notify-pill.test.ts
git commit -m "feat(frontend): show a 'Notified via …' badge once a job's notification is sent"
```

---

### Task 7: env docs + README

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

**Interfaces:**
- None (docs only).

- [ ] **Step 1: Add the operator-config block to `.env.example`**

Add after the existing Datadog block (or wherever the file's convention places a new optional-integration block — check the file's current structure before placing it):

```
# --- One (withone.ai) — completion notifications (optional) ---
# Leave ONE_SECRET unset to disable entirely: submit requests with
# notifyChannel set are rejected with 400 rather than silently ignored.
ONE_SECRET=
# Run `one connect slack` / `one connect gmail` once as the operator, then
# `one actions search slack "send message"` / `one actions search gmail
# "send email"` to find the actionId + connectionKey for each pair below.
ONE_SLACK_CONNECTION_KEY=
ONE_SLACK_SEND_ACTION_ID=
ONE_GMAIL_CONNECTION_KEY=
ONE_GMAIL_SEND_ACTION_ID=
```

- [ ] **Step 2: Add a HOW-TO section to `README.md`**

Add a new `## HOW-TO: Enable completion notifications (One / withone.ai)` section, mirroring the format of the existing Sentry/Datadog HOW-TOs (numbered steps): (1) sign up at withone.ai and install the CLI (`npm install -g @withone/cli` or rely on the project's local `@withone/cli` dependency), (2) `one init --auth manual --api-key <ONE_SECRET>` to authenticate non-interactively, (3) `one connect slack` / `one connect gmail` once to link an account, (4) `one actions search slack "send message"` (and the Gmail equivalent) to find the real `actionId`, (5) fill in the four `.env` vars from Step 1, (6) submit a job with a notify channel selected and confirm a message/email arrives once it completes.

Add a short note to the existing "Out of scope (intentional YAGNI)" list clarifying that this feature is agent-to-third-party-service auth (via One), not end-user login for the app — the end-user auth gap remains unaddressed, exactly as before.

- [ ] **Step 3: Commit**

```bash
git add .env.example README.md
git commit -m "docs: document One completion-notification setup"
```

---

## Self-Review Notes

- **Spec coverage:** §3 (architecture/flow) → Tasks 1, 4. §4 (schema/API) → Tasks 1, 2. §5 (One CLI invocation) → Task 3. §6 (frontend) → Tasks 5, 6. §7 (alternatives) → not implemented, intentionally. §8 (testing plan) → a test step embedded in every task.
- **Type consistency:** `NotifyChannel` defined once in `lib/db/schema.ts` (Task 1) and imported everywhere else (Tasks 2, 4, 6) rather than redefined. `NotifyChannelOption` (Task 5, frontend-only, includes `"none"`) is intentionally a *different, wider* type than `NotifyChannel` (backend, excludes `"none"` since a `null` column value means "no channel") — this is a deliberate distinction (the UI needs a tri-state control; the API/DB only ever store two real channel values or null), not an accidental duplicate. `sendCompletionNotification`'s parameter shape is identical between its definition (Task 3) and call site (Task 4).
- **No placeholders:** every step has literal code/commands; the one explicit "verify against the real system" item (Task 3's `ddLog` import path, and the `actionId`s the operator must discover via `one actions search`) is called out as a build-time/setup-time lookup, matching the same pattern already accepted for the Daytona SDK and CrewAI's API surface in the prior feature — not a deferred design gap.
