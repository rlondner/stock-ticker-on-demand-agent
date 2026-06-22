# Daytona Stock-Agent Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a demo NextJS app where users submit a stock ticker, an ephemeral Daytona sandbox runs an OpenAI agent against it, and a buy/hold/sell analysis is polled back from a Neon Postgres job row — with OpenTelemetry instrumentation that exports to Sentry, Datadog, both, or neither without code changes.

**Architecture:** NextJS 15 App Router + Drizzle ORM against Neon Postgres + Daytona TS SDK to spawn ephemeral Python sandboxes. The sandbox runs an OpenAI agent with web search, writes the result to Neon, then self-deletes. The browser polls a status route until the row's status flips to `complete` or `failed`. Observability is OTel-first; Sentry and Datadog are interchangeable exporters wired by env vars.

**Tech Stack:**
- **Frontend/API:** NextJS 15 (App Router), TypeScript, Tailwind, shadcn/ui, Drizzle ORM, Daytona TS SDK
- **Database:** Neon Postgres (branches for tests)
- **Sandbox runtime:** Daytona Cloud, prebuilt Python 3.12 snapshot
- **Agent:** OpenAI Responses API + `web_search` tool, psycopg, tenacity, pydantic
- **Observability:** OpenTelemetry SDKs (Node + Python); `@sentry/nextjs` / `sentry-sdk[opentelemetry]`; `dd-trace` / `ddtrace`
- **Test:** vitest (Node), pytest (Python), msw for HTTP mocks

**Reference spec:** `docs/superpowers/specs/2026-06-22-daytona-stock-agent-design.md`

---

## File Structure

Repo layout — NextJS at root, Python agent in `agent/`, database migrations in `db/`, scripts in `scripts/`.

```
daytona_demo/
├── package.json                          # NextJS app
├── pnpm-lock.yaml
├── next.config.ts
├── tsconfig.json
├── tailwind.config.ts
├── vitest.config.ts
├── drizzle.config.ts
├── .env.example
├── .gitignore
├── Makefile
├── README.md
│
├── app/                                  # NextJS App Router
│   ├── layout.tsx
│   ├── page.tsx                          # submit form + jobs list
│   ├── jobs/[id]/page.tsx                # job detail + polling
│   ├── admin/page.tsx                    # operator view
│   └── api/
│       ├── jobs/route.ts                 # POST: create + spawn
│       ├── status/[jobId]/route.ts       # GET:  return row
│       └── cleanup/route.ts              # POST: sweep stuck rows
│
├── lib/
│   ├── db/
│   │   ├── schema.ts                     # Drizzle schema
│   │   └── client.ts                     # Neon serverless driver
│   ├── daytona.ts                        # spawn wrapper
│   └── observability/
│       ├── otel.ts                       # OTel SDK init + exporter selection
│       ├── api.ts                        # traced(), recordError(), addAttrs()
│       └── exporters/
│           ├── sentry.ts
│           └── datadog.ts
│
├── components/                           # shadcn/ui components
│
├── db/
│   └── migrations/
│       └── 0001_init.sql                 # initial schema
│
├── agent/                                # Daytona snapshot source
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── agent.py                          # entrypoint
│   ├── lib/
│   │   ├── __init__.py
│   │   ├── db.py
│   │   ├── llm.py
│   │   ├── tools.py
│   │   ├── prompts.py
│   │   ├── observability.py
│   │   └── self_delete.py
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py
│       ├── test_db.py
│       ├── test_llm.py
│       └── test_agent.py
│
├── tests/                                # NextJS tests (vitest)
│   ├── api.jobs.test.ts
│   ├── api.status.test.ts
│   ├── api.cleanup.test.ts
│   └── daytona.test.ts
│
├── scripts/
│   ├── apply_migration.ts                # one-shot: apply migrations to Neon
│   └── build_snapshot.sh                 # build + publish Daytona snapshot
│
└── docs/superpowers/
    ├── specs/2026-06-22-daytona-stock-agent-design.md
    └── plans/2026-06-22-daytona-stock-agent.md
```

### Responsibilities

| File | Responsibility |
|---|---|
| `lib/db/schema.ts` | Drizzle schema mirror of `0001_init.sql` |
| `lib/db/client.ts` | Single Neon client + db helper exports |
| `lib/daytona.ts` | `spawnAnalysisSandbox(jobId, parentSpan)` |
| `lib/observability/otel.ts` | OTel SDK boot; reads env, registers exporters |
| `lib/observability/api.ts` | Vendor-neutral helpers app code calls |
| `app/api/jobs/route.ts` | Validate ticker → insert row → spawn → return jobId |
| `app/api/status/[jobId]/route.ts` | Return row state for polling |
| `app/api/cleanup/route.ts` | Sweep stuck `running` rows older than 10min |
| `agent/agent.py` | Entrypoint; orchestration; idempotency; flush; self-delete |
| `agent/lib/db.py` | `get_job`, `mark_running`, `mark_complete`, `mark_failed` |
| `agent/lib/llm.py` | `LLMClient` protocol + `OpenAIClient`; `Analysis` pydantic model |
| `agent/lib/observability.py` | `init_observability`, `record_error`, `flush_observability` |
| `agent/lib/self_delete.py` | DELETE call to Daytona REST API |
| `db/migrations/0001_init.sql` | `jobs` table + index |

---

## Prerequisites (before Task 1)

Before starting, the engineer needs:

1. **Node.js 20+** and **pnpm 9+** installed.
2. **Python 3.12+** installed.
3. **Docker** installed (for building the Daytona snapshot image).
4. **A Neon account** (free tier is fine). Create a project; note the connection string.
5. **A Daytona account** (free tier is fine). Create an API key.
6. **An OpenAI API key** with access to the Responses API and `web_search` tool.
7. **Optional:** Sentry account (separate projects for NextJS and Python recommended) and/or Datadog account with API key. Both are optional; skip if you don't have them.

Verify each with:
```bash
node --version    # v20+
pnpm --version    # v9+
python --version  # 3.12+
docker --version  # any recent
```

---

## Task 1: Initialize the repo

**Files:**
- Create: `.gitignore`
- Create: `README.md`
- Create: `.env.example`

- [ ] **Step 1: Initialize git and create top-level files**

```bash
cd C:\Users\rlond\Documents\GitHub\daytona_demo
git init
git branch -m main
```

- [ ] **Step 2: Write `.gitignore`**

```gitignore
# Node
node_modules/
.next/
out/
.turbo/

# Python
__pycache__/
*.pyc
.venv/
.pytest_cache/

# Env
.env
.env.local
.env.*.local

# OS
.DS_Store
Thumbs.db

# Editor
.vscode/
.idea/
```

- [ ] **Step 3: Write `.env.example`**

```
# === Required ===
DAYTONA_API_KEY=
DAYTONA_TARGET=us
NEON_DATABASE_URL=
OPENAI_API_KEY=

# === Observability (optional — set the block for whichever vendor you want) ===
# Sentry
SENTRY_DSN_NEXTJS=
SENTRY_DSN_AGENT=
SENTRY_AUTH_TOKEN=

# Datadog
DD_API_KEY=
DD_SITE=datadoghq.com
DD_SERVICE=stock-agent-frontend
DD_ENV=development
```

- [ ] **Step 4: Write a minimal `README.md`**

```markdown
# Daytona Stock-Agent Demo

A demo showing short-lived AI agents hosted in Daytona sandboxes. A user submits
a stock ticker; an ephemeral Daytona VM runs an OpenAI agent that produces a
buy/hold/sell analysis; the NextJS app polls Neon Postgres until the result is ready.

See `docs/superpowers/specs/2026-06-22-daytona-stock-agent-design.md` for the design,
and `docs/superpowers/plans/2026-06-22-daytona-stock-agent.md` for the implementation plan.

## Quickstart

1. Copy `.env.example` to `.env` and fill in required vars.
2. `pnpm install`
3. `make seed` — applies migrations to Neon
4. `make snapshot` — builds and publishes the Daytona snapshot
5. `pnpm dev` — start NextJS at http://localhost:3000
```

- [ ] **Step 5: Commit**

```bash
git add .gitignore README.md .env.example
git commit -m "chore: initial repo scaffold"
```

---

## Task 2: Write the database migration

**Files:**
- Create: `db/migrations/0001_init.sql`

- [ ] **Step 1: Create the migration directory and file**

```bash
mkdir -p db/migrations
```

- [ ] **Step 2: Write the SQL**

`db/migrations/0001_init.sql`:

```sql
CREATE TABLE IF NOT EXISTS jobs (
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

CREATE INDEX IF NOT EXISTS jobs_user_status_created_idx
  ON jobs (user_id, status, created_at DESC);
```

- [ ] **Step 3: Write the migration-runner script**

`scripts/apply_migration.ts`:

```typescript
import { neon } from "@neondatabase/serverless";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const dbUrl = process.env.NEON_DATABASE_URL;
if (!dbUrl) {
  console.error("NEON_DATABASE_URL is not set");
  process.exit(1);
}

const sql = neon(dbUrl);
const dir = "db/migrations";
const files = readdirSync(dir).filter((f) => f.endsWith(".sql")).sort();

for (const f of files) {
  console.log(`Applying ${f}...`);
  const stmt = readFileSync(join(dir, f), "utf8");
  // Neon HTTP driver doesn't support multi-statement; split on ;
  for (const part of stmt.split(/;\s*$/m).map(s => s.trim()).filter(Boolean)) {
    await sql(part);
  }
}
console.log("Done.");
```

- [ ] **Step 4: Commit**

```bash
git add db/migrations/0001_init.sql scripts/apply_migration.ts
git commit -m "feat(db): initial jobs schema"
```

(We'll wire it into the Makefile after the NextJS scaffold installs the `@neondatabase/serverless` package in Task 4.)

---

## Task 3: Bootstrap the NextJS app

**Files:**
- Create: `package.json`, `next.config.ts`, `tsconfig.json`, `app/layout.tsx`, `app/page.tsx`, `tailwind.config.ts`, `postcss.config.mjs`, `app/globals.css`

- [ ] **Step 1: Create the NextJS app at the repo root**

```bash
pnpm create next-app@latest . --typescript --tailwind --eslint --app --src-dir=false --import-alias="@/*" --use-pnpm
```

When prompted to overwrite the existing `.gitignore` and `README.md`, decline (`n`). When prompted about Turbopack, accept the default.

- [ ] **Step 2: Verify the app boots**

```bash
pnpm dev
```

Expected: NextJS dev server on http://localhost:3000 showing the default page.

Stop with Ctrl-C.

- [ ] **Step 3: Replace `app/page.tsx` with a temporary placeholder**

```tsx
export default function Home() {
  return (
    <main className="p-8">
      <h1 className="text-2xl font-bold">Daytona Stock-Agent Demo</h1>
      <p className="text-sm text-slate-500">Scaffolding in progress.</p>
    </main>
  );
}
```

- [ ] **Step 4: Verify it still renders**

```bash
pnpm dev
```

Open http://localhost:3000. Expected: the new heading.

- [ ] **Step 5: Commit**

```bash
git add .
git commit -m "feat: bootstrap NextJS 15 app"
```

---

## Task 4: Install runtime dependencies and wire Drizzle

**Files:**
- Modify: `package.json` (via pnpm)
- Create: `drizzle.config.ts`
- Create: `lib/db/schema.ts`
- Create: `lib/db/client.ts`

- [ ] **Step 1: Install runtime dependencies**

```bash
pnpm add @neondatabase/serverless drizzle-orm @daytonaio/sdk @opentelemetry/api zod
pnpm add -D drizzle-kit tsx vitest @vitest/coverage-v8 msw
```

- [ ] **Step 2: Write the Drizzle schema**

`lib/db/schema.ts`:

```typescript
import { pgTable, uuid, text, timestamp, jsonb, index } from "drizzle-orm/pg-core";

export const jobs = pgTable(
  "jobs",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    userId: text("user_id").notNull().default("demo-user"),
    ticker: text("ticker").notNull(),
    status: text("status").notNull().default("pending"),
    recommendation: text("recommendation"),
    result: jsonb("result"),
    error: text("error"),
    sandboxId: text("sandbox_id"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    startedAt: timestamp("started_at", { withTimezone: true }),
    completedAt: timestamp("completed_at", { withTimezone: true }),
  },
  (t) => ({
    userStatusCreatedIdx: index("jobs_user_status_created_idx").on(
      t.userId, t.status, t.createdAt,
    ),
  }),
);

export type Job = typeof jobs.$inferSelect;
export type NewJob = typeof jobs.$inferInsert;
export type JobStatus = "pending" | "running" | "complete" | "failed";
export type Recommendation = "buy" | "hold" | "sell";
```

- [ ] **Step 3: Write the Drizzle client**

`lib/db/client.ts`:

```typescript
import { neon } from "@neondatabase/serverless";
import { drizzle } from "drizzle-orm/neon-http";
import * as schema from "./schema";

const url = process.env.NEON_DATABASE_URL;
if (!url) throw new Error("NEON_DATABASE_URL is required");

const sql = neon(url);
export const db = drizzle(sql, { schema });
export * from "./schema";
```

- [ ] **Step 4: Write `drizzle.config.ts`**

```typescript
import type { Config } from "drizzle-kit";

export default {
  schema: "./lib/db/schema.ts",
  out: "./db/migrations-drizzle",      // separate from hand-authored migrations
  dialect: "postgresql",
  dbCredentials: { url: process.env.NEON_DATABASE_URL! },
} satisfies Config;
```

- [ ] **Step 5: Apply the migration to your Neon project**

Make sure `NEON_DATABASE_URL` is set in `.env` (or your shell), then:

```bash
pnpm exec tsx scripts/apply_migration.ts
```

Expected output:
```
Applying 0001_init.sql...
Done.
```

- [ ] **Step 6: Verify the table exists**

```bash
pnpm exec tsx -e "import { neon } from '@neondatabase/serverless'; const sql = neon(process.env.NEON_DATABASE_URL); console.log(await sql\`SELECT table_name FROM information_schema.tables WHERE table_schema='public'\`)"
```

Expected: includes `{ table_name: 'jobs' }`.

- [ ] **Step 7: Commit**

```bash
git add .
git commit -m "feat(db): drizzle schema + neon client + apply migration"
```

---

## Task 5: Write the OTel scaffold (no exporters yet)

**Files:**
- Create: `lib/observability/otel.ts`
- Create: `lib/observability/api.ts`

The observability layer is built early so all routes use the same helpers from day one. Exporters (Sentry, Datadog) are added later as drop-ins.

- [ ] **Step 1: Install OTel core packages**

```bash
pnpm add @opentelemetry/sdk-node @opentelemetry/resources @opentelemetry/semantic-conventions @opentelemetry/auto-instrumentations-node
```

- [ ] **Step 2: Write the OTel boot**

`lib/observability/otel.ts`:

```typescript
import { NodeSDK } from "@opentelemetry/sdk-node";
import { Resource } from "@opentelemetry/resources";
import { SemanticResourceAttributes as Attr } from "@opentelemetry/semantic-conventions";
import { getNodeAutoInstrumentations } from "@opentelemetry/auto-instrumentations-node";

let sdk: NodeSDK | undefined;

export function initOtel(): void {
  if (sdk) return;                                 // idempotent
  sdk = new NodeSDK({
    resource: new Resource({
      [Attr.SERVICE_NAME]: process.env.DD_SERVICE ?? "stock-agent-frontend",
      [Attr.DEPLOYMENT_ENVIRONMENT]: process.env.DD_ENV ?? process.env.NODE_ENV ?? "development",
    }),
    instrumentations: [getNodeAutoInstrumentations()],
  });
  sdk.start();
}
```

- [ ] **Step 3: Write the vendor-neutral helpers**

`lib/observability/api.ts`:

```typescript
import { trace, SpanStatusCode, type Span } from "@opentelemetry/api";

const tracer = trace.getTracer("stock-agent-frontend");

export async function traced<T>(
  name: string,
  attrs: Record<string, string | number | boolean> | undefined,
  fn: (span: Span) => Promise<T>,
): Promise<T> {
  return tracer.startActiveSpan(name, async (span) => {
    if (attrs) for (const [k, v] of Object.entries(attrs)) span.setAttribute(k, v);
    try {
      return await fn(span);
    } catch (e) {
      recordError(span, e);
      throw e;
    } finally {
      span.end();
    }
  });
}

export function recordError(span: Span, e: unknown): void {
  const err = e instanceof Error ? e : new Error(String(e));
  span.recordException(err);
  span.setStatus({ code: SpanStatusCode.ERROR, message: err.message });
}

export function addAttrs(span: Span, attrs: Record<string, string | number | boolean>): void {
  for (const [k, v] of Object.entries(attrs)) span.setAttribute(k, v);
}
```

- [ ] **Step 4: Write a smoke test**

`tests/observability.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { traced, recordError, addAttrs } from "@/lib/observability/api";
import { trace } from "@opentelemetry/api";

describe("observability helpers", () => {
  it("traced() runs fn and returns its result", async () => {
    const result = await traced("test.span", { foo: "bar" }, async (_span) => 42);
    expect(result).toBe(42);
  });

  it("traced() re-throws errors and marks the span", async () => {
    await expect(
      traced("test.error", undefined, async () => { throw new Error("boom"); })
    ).rejects.toThrow("boom");
  });

  it("addAttrs and recordError work without a real exporter", () => {
    const span = trace.getTracer("t").startSpan("s");
    addAttrs(span, { a: 1, b: "x" });
    recordError(span, new Error("oops"));
    span.end();
    // No assertion — we only verify these don't throw with no-op tracer.
  });
});
```

- [ ] **Step 5: Configure vitest**

`vitest.config.ts`:

```typescript
import { defineConfig } from "vitest/config";
import { resolve } from "node:path";

export default defineConfig({
  test: {
    environment: "node",
    globals: false,
    include: ["tests/**/*.test.ts"],
  },
  resolve: {
    alias: { "@": resolve(__dirname, ".") },
  },
});
```

Add the test script to `package.json` (in the `scripts` block):

```json
"test": "vitest run",
"test:watch": "vitest"
```

- [ ] **Step 6: Run the test**

```bash
pnpm test
```

Expected: 3 tests pass.

- [ ] **Step 7: Commit**

```bash
git add .
git commit -m "feat(observability): OTel scaffold and vendor-neutral helpers"
```

---

## Task 6: Write the `/api/jobs` POST route (with Daytona spawn mocked)

**Files:**
- Create: `app/api/jobs/route.ts`
- Create: `lib/daytona.ts` (stub for now; real impl in Task 8)
- Create: `tests/api.jobs.test.ts`

- [ ] **Step 1: Write the test first**

`tests/api.jobs.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { POST } from "@/app/api/jobs/route";

vi.mock("@/lib/daytona", () => ({
  spawnAnalysisSandbox: vi.fn(async (jobId: string) => `sb-${jobId.slice(0, 8)}`),
}));

vi.mock("@/lib/db/client", () => {
  const rows: Array<{ id: string; ticker: string; status: string; sandbox_id?: string }> = [];
  const insertReturning = vi.fn(async (data: { ticker: string }) => {
    const id = crypto.randomUUID();
    const row = { id, ticker: data.ticker, status: "pending" };
    rows.push(row);
    return [{ id }];
  });
  return {
    db: {
      insert: () => ({ values: (v: any) => ({ returning: () => insertReturning(v) }) }),
      update: () => ({ set: () => ({ where: () => Promise.resolve() }) }),
    },
    jobs: {},
    __rows: rows,
  };
});

function req(body: unknown): Request {
  return new Request("http://localhost/api/jobs", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("POST /api/jobs", () => {
  beforeEach(() => vi.clearAllMocks());

  it("rejects an empty ticker with 400", async () => {
    const res = await POST(req({ ticker: "" }));
    expect(res.status).toBe(400);
  });

  it("rejects a malformed ticker with 400", async () => {
    const res = await POST(req({ ticker: "foo!" }));
    expect(res.status).toBe(400);
  });

  it("accepts a valid ticker and returns jobId", async () => {
    const res = await POST(req({ ticker: "AAPL" }));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.jobId).toMatch(/^[0-9a-f-]{36}$/);
  });
});
```

- [ ] **Step 2: Run the test — expect failure**

```bash
pnpm test tests/api.jobs.test.ts
```

Expected: FAIL (no `route.ts` yet).

- [ ] **Step 3: Write the Daytona stub**

`lib/daytona.ts`:

```typescript
import type { Span } from "@opentelemetry/api";

// Real implementation lands in Task 8. For now this stub lets the API route
// be tested independently.
export async function spawnAnalysisSandbox(_jobId: string, _parentSpan: Span): Promise<string> {
  return "sb-stub";
}
```

- [ ] **Step 4: Write the route**

`app/api/jobs/route.ts`:

```typescript
import { z } from "zod";
import { eq } from "drizzle-orm";
import { db, jobs } from "@/lib/db/client";
import { spawnAnalysisSandbox } from "@/lib/daytona";
import { traced, addAttrs, recordError } from "@/lib/observability/api";

const Body = z.object({
  ticker: z.string().regex(/^[A-Z]{1,5}$/, "ticker must be 1-5 uppercase letters"),
});

export async function POST(req: Request): Promise<Response> {
  return traced("api.jobs.post", { route: "POST /api/jobs" }, async (span) => {
    let parsed: z.infer<typeof Body>;
    try {
      parsed = Body.parse(await req.json());
    } catch (e) {
      addAttrs(span, { outcome: "rejected" });
      const msg = e instanceof z.ZodError ? e.errors[0]?.message ?? "invalid" : "invalid";
      return Response.json({ error: msg }, { status: 400 });
    }

    const [{ id: jobId }] = await db
      .insert(jobs)
      .values({ ticker: parsed.ticker })
      .returning({ id: jobs.id });
    addAttrs(span, { job_id: jobId, ticker: parsed.ticker });

    try {
      const sandboxId = await spawnAnalysisSandbox(jobId, span);
      await db.update(jobs).set({ sandboxId }).where(eq(jobs.id, jobId));
      addAttrs(span, { sandbox_id: sandboxId, outcome: "accepted" });
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

- [ ] **Step 5: Run the test — expect pass**

```bash
pnpm test tests/api.jobs.test.ts
```

Expected: 3 passes.

- [ ] **Step 6: Commit**

```bash
git add .
git commit -m "feat(api): POST /api/jobs with validation and instrumentation"
```

---

## Task 7: Write the `/api/status/[jobId]` GET route

**Files:**
- Create: `app/api/status/[jobId]/route.ts`
- Create: `tests/api.status.test.ts`

- [ ] **Step 1: Write the test**

`tests/api.status.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { GET } from "@/app/api/status/[jobId]/route";

const fakeRow = {
  id: "11111111-1111-1111-1111-111111111111",
  ticker: "AAPL",
  status: "complete",
  recommendation: "buy",
  result: { summary: "test", signals: [] },
  sandboxId: "sb-x",
  createdAt: new Date("2026-06-22T10:00:00Z"),
  startedAt: new Date("2026-06-22T10:00:05Z"),
  completedAt: new Date("2026-06-22T10:00:50Z"),
  error: null,
};

vi.mock("@/lib/db/client", () => {
  const limit = vi.fn(async () => [fakeRow]);
  const where = vi.fn(() => ({ limit }));
  const from = vi.fn(() => ({ where }));
  const select = vi.fn(() => ({ from }));
  return { db: { select }, jobs: { id: "id" }, __limit: limit };
});

describe("GET /api/status/[jobId]", () => {
  beforeEach(() => vi.clearAllMocks());

  it("returns the job row", async () => {
    const res = await GET(new Request("http://localhost"), { params: Promise.resolve({ jobId: fakeRow.id }) });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.id).toBe(fakeRow.id);
    expect(body.status).toBe("complete");
    expect(body.recommendation).toBe("buy");
  });

  it("returns 404 when job not found", async () => {
    const dbMod = await import("@/lib/db/client") as any;
    dbMod.__limit.mockResolvedValueOnce([]);
    const res = await GET(new Request("http://localhost"), { params: Promise.resolve({ jobId: "00000000-0000-0000-0000-000000000000" }) });
    expect(res.status).toBe(404);
  });
});
```

- [ ] **Step 2: Run the test — expect failure**

```bash
pnpm test tests/api.status.test.ts
```

Expected: FAIL.

- [ ] **Step 3: Write the route**

`app/api/status/[jobId]/route.ts`:

```typescript
import { eq } from "drizzle-orm";
import { db, jobs } from "@/lib/db/client";
import { traced, addAttrs } from "@/lib/observability/api";

type Ctx = { params: Promise<{ jobId: string }> };

export async function GET(_req: Request, ctx: Ctx): Promise<Response> {
  const { jobId } = await ctx.params;
  return traced("api.status.get", { job_id: jobId }, async (span) => {
    const rows = await db.select().from(jobs).where(eq(jobs.id, jobId)).limit(1);
    if (rows.length === 0) {
      addAttrs(span, { outcome: "not_found" });
      return Response.json({ error: "not_found" }, { status: 404 });
    }
    const row = rows[0];
    addAttrs(span, { status: row.status });
    return Response.json(row);
  });
}
```

- [ ] **Step 4: Run the test — expect pass**

```bash
pnpm test tests/api.status.test.ts
```

Expected: 2 passes.

- [ ] **Step 5: Commit**

```bash
git add .
git commit -m "feat(api): GET /api/status/[jobId]"
```

---

## Task 8: Implement the real Daytona spawn

**Files:**
- Modify: `lib/daytona.ts`
- Create: `tests/daytona.test.ts`

- [ ] **Step 1: Replace the stub with the real spawn**

`lib/daytona.ts`:

```typescript
import { Daytona } from "@daytonaio/sdk";
import { context, propagation, trace, type Span } from "@opentelemetry/api";

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
  const carrier: Record<string, string> = {};
  propagation.inject(trace.setSpan(context.active(), parentSpan), carrier);

  const env: Record<string, string> = {
    JOB_ID: jobId,
    NEON_DATABASE_URL: process.env.NEON_DATABASE_URL!,
    OPENAI_API_KEY: process.env.OPENAI_API_KEY!,
    DAYTONA_API_KEY: process.env.DAYTONA_API_KEY!,
    TRACEPARENT: carrier.traceparent ?? "",
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

function forwardIfSet(k: string): Record<string, string> {
  return process.env[k] ? { [k]: process.env[k]! } : {};
}

function datadogBlockIfEnabled(): Record<string, string> {
  if (!process.env.DD_API_KEY) return {};
  return {
    DD_API_KEY: process.env.DD_API_KEY,
    DD_SITE: process.env.DD_SITE ?? "datadoghq.com",
    DD_SERVICE: "stock-agent",
    DD_ENV: process.env.DD_ENV ?? process.env.NODE_ENV ?? "development",
  };
}
```

- [ ] **Step 2: Write a unit test that mocks the SDK**

`tests/daytona.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { trace } from "@opentelemetry/api";

const createMock = vi.fn(async () => ({ id: "sb-12345" }));

vi.mock("@daytonaio/sdk", () => ({
  Daytona: vi.fn(() => ({ create: createMock })),
}));

describe("spawnAnalysisSandbox", () => {
  beforeEach(() => {
    process.env.DAYTONA_API_KEY = "dt-test";
    process.env.NEON_DATABASE_URL = "postgresql://test";
    process.env.OPENAI_API_KEY = "sk-test";
    delete process.env.SENTRY_DSN_AGENT;
    delete process.env.DD_API_KEY;
    createMock.mockClear();
  });

  it("returns the sandbox id and passes JOB_ID + TRACEPARENT", async () => {
    const { spawnAnalysisSandbox } = await import("@/lib/daytona");
    const span = trace.getTracer("t").startSpan("parent");
    const id = await spawnAnalysisSandbox("job-abc", span);
    span.end();
    expect(id).toBe("sb-12345");
    const call = createMock.mock.calls[0][0] as any;
    expect(call.snapshot).toBe("stock-agent:latest");
    expect(call.envVars.JOB_ID).toBe("job-abc");
    expect(call.envVars.TRACEPARENT).toMatch(/^00-/);
    expect(call.envVars.SENTRY_DSN_AGENT).toBeUndefined();
    expect(call.envVars.DD_API_KEY).toBeUndefined();
  });

  it("forwards Sentry DSN only when set", async () => {
    process.env.SENTRY_DSN_AGENT = "https://x@sentry.io/1";
    const { spawnAnalysisSandbox } = await import("@/lib/daytona");
    const span = trace.getTracer("t").startSpan("p");
    await spawnAnalysisSandbox("job-2", span);
    span.end();
    const call = createMock.mock.calls.at(-1)![0] as any;
    expect(call.envVars.SENTRY_DSN_AGENT).toBe("https://x@sentry.io/1");
  });

  it("forwards Datadog block only when DD_API_KEY is set", async () => {
    process.env.DD_API_KEY = "dd-key";
    const { spawnAnalysisSandbox } = await import("@/lib/daytona");
    const span = trace.getTracer("t").startSpan("p");
    await spawnAnalysisSandbox("job-3", span);
    span.end();
    const call = createMock.mock.calls.at(-1)![0] as any;
    expect(call.envVars.DD_API_KEY).toBe("dd-key");
    expect(call.envVars.DD_SERVICE).toBe("stock-agent");
    expect(call.envVars.DD_SITE).toBe("datadoghq.com");
  });
});
```

- [ ] **Step 3: Run the test**

```bash
pnpm test tests/daytona.test.ts
```

Expected: 3 passes.

- [ ] **Step 4: Commit**

```bash
git add .
git commit -m "feat(daytona): real spawn with W3C traceparent + conditional vendor env forwarding"
```

---

## Task 9: Build the home page (submit form + recent jobs)

**Files:**
- Modify: `app/page.tsx`
- Create: `components/submit-form.tsx`
- Create: `components/jobs-list.tsx`

- [ ] **Step 1: Install shadcn primitives we'll need**

```bash
pnpm dlx shadcn@latest init -d
pnpm dlx shadcn@latest add button input badge card
```

When the init step asks for style/color, accept defaults.

- [ ] **Step 2: Write the submit form component**

`components/submit-form.tsx`:

```tsx
"use client";
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function SubmitForm() {
  const [ticker, setTicker] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const router = useRouter();

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const value = ticker.trim().toUpperCase();
    if (!/^[A-Z]{1,5}$/.test(value)) {
      setError("Ticker must be 1–5 uppercase letters.");
      return;
    }
    startTransition(async () => {
      const res = await fetch("/api/jobs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ ticker: value }),
      });
      const body = await res.json();
      if (!res.ok) { setError(body.error ?? "Submit failed"); return; }
      router.push(`/jobs/${body.jobId}`);
    });
  }

  return (
    <form onSubmit={onSubmit} className="flex gap-2 items-start">
      <Input
        value={ticker}
        onChange={(e) => setTicker(e.target.value)}
        placeholder="AAPL"
        maxLength={5}
        aria-label="ticker"
        className="w-32 uppercase"
      />
      <Button type="submit" disabled={pending}>
        {pending ? "Analyzing…" : "Analyze"}
      </Button>
      {error && <p className="text-red-600 text-sm self-center">{error}</p>}
    </form>
  );
}
```

- [ ] **Step 3: Write the recent-jobs list component**

`components/jobs-list.tsx`:

```tsx
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { desc, eq } from "drizzle-orm";
import { db, jobs } from "@/lib/db/client";

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  pending: "outline",
  running: "secondary",
  complete: "default",
  failed: "destructive",
};

export async function JobsList() {
  const rows = await db
    .select()
    .from(jobs)
    .where(eq(jobs.userId, "demo-user"))
    .orderBy(desc(jobs.createdAt))
    .limit(20);

  if (rows.length === 0) return <p className="text-sm text-slate-500">No jobs yet.</p>;

  return (
    <ul className="space-y-1">
      {rows.map((j) => (
        <li key={j.id}>
          <Link href={`/jobs/${j.id}`} className="flex items-center gap-3 p-2 rounded hover:bg-slate-50">
            <span className="font-mono w-16">{j.ticker}</span>
            <Badge variant={STATUS_VARIANT[j.status] ?? "outline"}>{j.status}</Badge>
            {j.recommendation && <Badge variant="default">{j.recommendation.toUpperCase()}</Badge>}
            <span className="text-xs text-slate-500 ml-auto">{j.createdAt.toISOString()}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
```

- [ ] **Step 4: Replace the home page**

`app/page.tsx`:

```tsx
import { SubmitForm } from "@/components/submit-form";
import { JobsList } from "@/components/jobs-list";

export const dynamic = "force-dynamic";

export default function Home() {
  return (
    <main className="p-8 max-w-3xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold">Daytona Stock-Agent Demo</h1>
        <p className="text-sm text-slate-500">
          Submit a stock ticker; an ephemeral Daytona VM runs an AI agent and writes the result to Neon.
        </p>
      </div>
      <SubmitForm />
      <section>
        <h2 className="text-lg font-semibold mb-2">Recent jobs</h2>
        <JobsList />
      </section>
      <p className="text-xs text-slate-400">Demo only — not financial advice.</p>
    </main>
  );
}
```

- [ ] **Step 5: Verify in the browser**

```bash
pnpm dev
```

Open http://localhost:3000. Submit `AAPL`. You should be redirected to `/jobs/<uuid>` (which is still a 404 — we build that next).

Returning to `/`, the new job should appear in "Recent jobs" with status `pending` (because the stub returned `sb-stub` and didn't actually spawn anything that updates the row).

Stop the dev server.

- [ ] **Step 6: Commit**

```bash
git add .
git commit -m "feat(ui): home page with submit form and recent jobs list"
```

---

## Task 10: Build the job detail page with polling

**Files:**
- Create: `app/jobs/[id]/page.tsx`
- Create: `components/job-detail.tsx`

- [ ] **Step 1: Write the client-side detail component**

`components/job-detail.tsx`:

```tsx
"use client";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";

type Job = {
  id: string;
  ticker: string;
  status: "pending" | "running" | "complete" | "failed";
  recommendation: "buy" | "hold" | "sell" | null;
  result: { summary?: string; signals?: Array<{ label: string; evidence: string; source: string | null }> } | null;
  error: string | null;
  sandboxId: string | null;
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
};

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  pending: "outline",
  running: "secondary",
  complete: "default",
  failed: "destructive",
};

export function JobDetail({ initialJob }: { initialJob: Job }) {
  const [job, setJob] = useState(initialJob);

  useEffect(() => {
    if (job.status === "complete" || job.status === "failed") return;
    const id = setInterval(async () => {
      const res = await fetch(`/api/status/${job.id}`);
      if (!res.ok) return;
      const next: Job = await res.json();
      setJob(next);
      if (next.status === "complete" || next.status === "failed") clearInterval(id);
    }, 2500);
    return () => clearInterval(id);
  }, [job.id, job.status]);

  const elapsedMs = job.completedAt
    ? new Date(job.completedAt).getTime() - new Date(job.createdAt).getTime()
    : Date.now() - new Date(job.createdAt).getTime();

  return (
    <div className="space-y-6">
      <div className="flex items-baseline gap-3">
        <h1 className="text-2xl font-mono">{job.ticker}</h1>
        <Badge variant={STATUS_VARIANT[job.status]}>{job.status}</Badge>
        {job.recommendation && (
          <Badge variant="default" className="text-base">{job.recommendation.toUpperCase()}</Badge>
        )}
      </div>

      {(job.status === "pending" || job.status === "running") && (
        <p className="text-sm text-slate-500">
          Sandbox {job.sandboxId ?? "spawning…"} · {Math.round(elapsedMs / 1000)}s elapsed
        </p>
      )}

      {job.status === "failed" && job.error && (
        <Card className="p-4 border-red-300 bg-red-50">
          <pre className="text-xs whitespace-pre-wrap">{job.error}</pre>
        </Card>
      )}

      {job.status === "complete" && job.result && (
        <>
          <p>{job.result.summary}</p>
          <ul className="space-y-2">
            {(job.result.signals ?? []).map((s, i) => (
              <li key={i} className="text-sm">
                <strong>{s.label}:</strong> {s.evidence}
                {s.source && <> · <a href={s.source} className="text-blue-600 underline" target="_blank" rel="noreferrer">source</a></>}
              </li>
            ))}
          </ul>
          <p className="text-xs text-slate-400">Completed in {Math.round(elapsedMs / 1000)}s · Demo only — not financial advice.</p>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Write the server page**

`app/jobs/[id]/page.tsx`:

```tsx
import { notFound } from "next/navigation";
import { eq } from "drizzle-orm";
import { db, jobs } from "@/lib/db/client";
import { JobDetail } from "@/components/job-detail";

export const dynamic = "force-dynamic";

export default async function JobPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const rows = await db.select().from(jobs).where(eq(jobs.id, id)).limit(1);
  if (rows.length === 0) notFound();
  const row = rows[0];
  const initial = {
    ...row,
    createdAt: row.createdAt.toISOString(),
    startedAt: row.startedAt ? row.startedAt.toISOString() : null,
    completedAt: row.completedAt ? row.completedAt.toISOString() : null,
  };
  return (
    <main className="p-8 max-w-3xl mx-auto">
      <JobDetail initialJob={initial as any} />
    </main>
  );
}
```

- [ ] **Step 3: Verify in the browser**

```bash
pnpm dev
```

Submit a new ticker on `/`. You should land on `/jobs/<uuid>` showing status `pending` with the elapsed timer counting up. (The job won't ever complete yet — that needs the agent.)

- [ ] **Step 4: Commit**

```bash
git add .
git commit -m "feat(ui): job detail page with polling"
```

---

## Task 11: Scaffold the Python agent project

**Files:**
- Create: `agent/Dockerfile`
- Create: `agent/requirements.txt`
- Create: `agent/lib/__init__.py`
- Create: `agent/tests/__init__.py`
- Create: `agent/tests/conftest.py`
- Create: `agent/pyproject.toml`

- [ ] **Step 1: Create the directory tree**

```bash
mkdir -p agent/lib agent/tests
```

- [ ] **Step 2: Write `agent/requirements.txt`**

```
openai>=1.50.0
psycopg[binary]>=3.2.0
pydantic>=2.7.0
tenacity>=9.0.0
httpx>=0.27.0

# --- OpenTelemetry core (always installed) ---
opentelemetry-api>=1.27.0
opentelemetry-sdk>=1.27.0
opentelemetry-instrumentation-httpx>=0.48b0
opentelemetry-instrumentation-psycopg>=0.48b0
opentelemetry-instrumentation-openai>=0.30.0
opentelemetry-instrumentation-logging>=0.48b0

# --- Vendor exporters (always installed; active only if env says so) ---
sentry-sdk[opentelemetry]>=2.15.0
ddtrace>=2.13.0
```

- [ ] **Step 3: Write `agent/pyproject.toml` for testing**

```toml
[project]
name = "stock-agent"
version = "0.1.0"
requires-python = ">=3.12"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
addopts = "-v"
```

- [ ] **Step 4: Write the Dockerfile**

`agent/Dockerfile`:

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

- [ ] **Step 5: Set up a Python venv and install deps**

```powershell
cd agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # PowerShell on Windows
# (bash:  source .venv/bin/activate    cmd:  .venv\Scripts\activate.bat)
pip install -r requirements.txt
pip install pytest pytest-mock
```

- [ ] **Step 6: Write empty `__init__.py` files**

`agent/lib/__init__.py`: (empty)
`agent/tests/__init__.py`: (empty)

- [ ] **Step 7: Write `agent/tests/conftest.py`**

```python
import os
import pytest

@pytest.fixture(autouse=True)
def reset_env(monkeypatch):
    """Ensure each test starts from a known env baseline."""
    for var in ("SENTRY_DSN_AGENT", "DD_API_KEY", "TRACEPARENT", "JOB_ID"):
        monkeypatch.delenv(var, raising=False)
    yield
```

- [ ] **Step 8: Sanity-check pytest works**

```powershell
cd agent
.\.venv\Scripts\Activate.ps1
pytest
```

Expected: "no tests ran" (clean exit code 5; pytest returns 5 when no tests collected).

- [ ] **Step 9: Commit**

```bash
cd ..
git add agent/
git commit -m "feat(agent): scaffold Python project with deps and pytest"
```

---

## Task 12: Implement `agent/lib/db.py`

**Files:**
- Create: `agent/lib/db.py`
- Create: `agent/tests/test_db.py`

- [ ] **Step 1: Write the test (uses a real Neon branch — provide `NEON_DATABASE_URL`)**

`agent/tests/test_db.py`:

```python
import os
import uuid
import pytest
import psycopg

@pytest.fixture
def neon_url():
    url = os.environ.get("NEON_DATABASE_URL")
    if not url:
        pytest.skip("NEON_DATABASE_URL not set — skipping integration test")
    return url

@pytest.fixture
def fresh_job(neon_url):
    """Inserts a fresh pending job and returns its id; cleans up after."""
    job_id = str(uuid.uuid4())
    with psycopg.connect(neon_url) as conn:
        conn.execute(
            "INSERT INTO jobs (id, ticker, status) VALUES (%s, %s, 'pending')",
            (job_id, "TEST"),
        )
        conn.commit()
    yield job_id
    with psycopg.connect(neon_url) as conn:
        conn.execute("DELETE FROM jobs WHERE id = %s", (job_id,))
        conn.commit()

def test_get_job_returns_row(neon_url, fresh_job, monkeypatch):
    monkeypatch.setenv("NEON_DATABASE_URL", neon_url)
    from lib.db import get_job
    row = get_job(fresh_job)
    assert row is not None
    assert row["ticker"] == "TEST"
    assert row["status"] == "pending"

def test_get_job_returns_none_for_missing(neon_url, monkeypatch):
    monkeypatch.setenv("NEON_DATABASE_URL", neon_url)
    from lib.db import get_job
    assert get_job("00000000-0000-0000-0000-000000000000") is None

def test_mark_running_transitions_from_pending(neon_url, fresh_job, monkeypatch):
    monkeypatch.setenv("NEON_DATABASE_URL", neon_url)
    from lib.db import mark_running, get_job
    mark_running(fresh_job)
    row = get_job(fresh_job)
    assert row["status"] == "running"
    assert row["started_at"] is not None

def test_mark_running_does_not_overwrite_terminal(neon_url, fresh_job, monkeypatch):
    monkeypatch.setenv("NEON_DATABASE_URL", neon_url)
    from lib.db import mark_running, mark_complete, get_job
    mark_running(fresh_job)
    mark_complete(fresh_job, recommendation="buy", result={"summary": "ok"})
    # Try to revert — should be a no-op because status is terminal.
    mark_running(fresh_job)
    row = get_job(fresh_job)
    assert row["status"] == "complete"

def test_mark_complete_sets_result_and_recommendation(neon_url, fresh_job, monkeypatch):
    monkeypatch.setenv("NEON_DATABASE_URL", neon_url)
    from lib.db import mark_running, mark_complete, get_job
    mark_running(fresh_job)
    mark_complete(fresh_job, recommendation="hold", result={"summary": "neutral", "signals": []})
    row = get_job(fresh_job)
    assert row["status"] == "complete"
    assert row["recommendation"] == "hold"
    assert row["result"]["summary"] == "neutral"
    assert row["completed_at"] is not None

def test_mark_failed_writes_error(neon_url, fresh_job, monkeypatch):
    monkeypatch.setenv("NEON_DATABASE_URL", neon_url)
    from lib.db import mark_failed, get_job
    mark_failed(fresh_job, error="ValueError: nope")
    row = get_job(fresh_job)
    assert row["status"] == "failed"
    assert "ValueError" in row["error"]
```

- [ ] **Step 2: Run the test — expect failure (module doesn't exist)**

```powershell
cd agent
.\.venv\Scripts\Activate.ps1
pytest tests/test_db.py
```

Expected: ImportError on `lib.db`.

- [ ] **Step 3: Write `agent/lib/db.py`**

```python
import os
from typing import Any
import psycopg
from psycopg.rows import dict_row

def _conn():
    url = os.environ["NEON_DATABASE_URL"]
    return psycopg.connect(url, row_factory=dict_row)

def get_job(job_id: str) -> dict[str, Any] | None:
    with _conn() as c:
        cur = c.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
        return cur.fetchone()

def mark_running(job_id: str) -> None:
    """Transition pending -> running. No-op if status is terminal."""
    with _conn() as c:
        c.execute(
            "UPDATE jobs SET status='running', started_at=now() "
            "WHERE id=%s AND status='pending'",
            (job_id,),
        )
        c.commit()

def mark_complete(job_id: str, *, recommendation: str, result: dict) -> None:
    """Transition running -> complete. Only writes if status is pending or running."""
    from psycopg.types.json import Jsonb
    with _conn() as c:
        c.execute(
            "UPDATE jobs SET status='complete', recommendation=%s, result=%s, "
            "completed_at=now() WHERE id=%s AND status IN ('pending','running')",
            (recommendation, Jsonb(result), job_id),
        )
        c.commit()

def mark_failed(job_id: str, *, error: str) -> None:
    """Transition any non-terminal state -> failed."""
    with _conn() as c:
        c.execute(
            "UPDATE jobs SET status='failed', error=%s, completed_at=now() "
            "WHERE id=%s AND status IN ('pending','running')",
            (error, job_id),
        )
        c.commit()
```

- [ ] **Step 4: Run the tests — expect pass**

Make sure `NEON_DATABASE_URL` is exported in your shell or `.env` is loaded.

```bash
pytest tests/test_db.py
```

Expected: 6 passes.

- [ ] **Step 5: Commit**

```bash
cd ..
git add agent/lib/db.py agent/tests/test_db.py
git commit -m "feat(agent): db.py with idempotent status transitions + tests"
```

---

## Task 13: Implement `agent/lib/llm.py`

**Files:**
- Create: `agent/lib/llm.py`
- Create: `agent/lib/prompts.py`
- Create: `agent/tests/test_llm.py`

- [ ] **Step 1: Write the test**

`agent/tests/test_llm.py`:

```python
import json
import pytest
from pydantic import ValidationError
from lib.llm import Analysis, Signal, parse_response

def test_analysis_validates_buy_hold_sell():
    a = Analysis(recommendation="buy", summary="strong fundamentals", signals=[])
    assert a.recommendation == "buy"

def test_analysis_rejects_invalid_recommendation():
    with pytest.raises(ValidationError):
        Analysis(recommendation="strong-buy", summary="x", signals=[])

def test_analysis_accepts_signals():
    a = Analysis(
        recommendation="hold",
        summary="mixed",
        signals=[Signal(label="P/E", evidence="32, above average", source="https://example.com/aapl")],
    )
    assert len(a.signals) == 1
    assert a.signals[0].source == "https://example.com/aapl"

def test_parse_response_extracts_json():
    payload = json.dumps({
        "recommendation": "sell",
        "summary": "declining margins",
        "signals": [{"label": "margin", "evidence": "down 4pp YoY", "source": None}],
    })
    a = parse_response(payload)
    assert a.recommendation == "sell"

def test_parse_response_rejects_malformed():
    with pytest.raises(ValueError):
        parse_response("not json")
```

- [ ] **Step 2: Run — expect failure**

```bash
pytest tests/test_llm.py
```

Expected: ImportError.

- [ ] **Step 3: Write `agent/lib/prompts.py`**

```python
SYSTEM_PROMPT = """\
You are a financial analysis assistant. Given a single US-listed stock ticker,
research recent news, fundamentals, and analyst sentiment using the web_search
tool, then output ONLY a JSON object matching this schema:

{
  "recommendation": "buy" | "hold" | "sell",
  "summary": "<2-3 sentence plain-English summary>",
  "signals": [
    {"label": "<short label>", "evidence": "<one sentence>", "source": "<URL or null>"}
  ]
}

Provide 3 to 5 signals. Cite source URLs whenever possible. Output JSON ONLY
with no surrounding markdown, no commentary, no preamble. This is not financial
advice and your output will be shown to the user with a clear demo disclaimer.
"""

def user_prompt(ticker: str) -> str:
    return f"Analyze ticker: {ticker}. Output JSON only."
```

- [ ] **Step 4: Write `agent/lib/llm.py`**

```python
import json
import os
from typing import Protocol
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from openai import OpenAI, APIError, RateLimitError, APIConnectionError
from opentelemetry import trace
from .prompts import SYSTEM_PROMPT, user_prompt

class Signal(BaseModel):
    label: str
    evidence: str
    source: str | None = None

class Analysis(BaseModel):
    recommendation: str = Field(pattern="^(buy|hold|sell)$")
    summary: str
    signals: list[Signal]

class LLMClient(Protocol):
    def analyze(self, ticker: str) -> Analysis: ...

def parse_response(raw: str) -> Analysis:
    """Strip optional markdown fences, parse JSON, validate."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        # remove leading "json\n" if present
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM did not return valid JSON: {e}") from e
    return Analysis(**data)

class OpenAIClient:
    def __init__(self, model: str = "gpt-4.1-mini"):
        self._client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self._model = model

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=16),
        retry=retry_if_exception_type((RateLimitError, APIConnectionError)),
        reraise=True,
    )
    def analyze(self, ticker: str) -> Analysis:
        tracer = trace.get_tracer("stock-agent")
        with tracer.start_as_current_span("llm.analyze") as span:
            span.set_attribute("model", self._model)
            resp = self._client.responses.create(
                model=self._model,
                input=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt(ticker)},
                ],
                tools=[{"type": "web_search"}],
            )
            text = resp.output_text  # convenience aggregator on the Responses API
            usage = getattr(resp, "usage", None)
            if usage:
                span.set_attribute("tokens_in", getattr(usage, "input_tokens", 0))
                span.set_attribute("tokens_out", getattr(usage, "output_tokens", 0))
            return parse_response(text)

def run_analysis(ticker: str) -> dict:
    client: LLMClient = OpenAIClient()
    return client.analyze(ticker).model_dump()
```

- [ ] **Step 5: Run tests — expect pass**

```bash
pytest tests/test_llm.py
```

Expected: 5 passes.

- [ ] **Step 6: Commit**

```bash
cd ..
git add agent/lib/llm.py agent/lib/prompts.py agent/tests/test_llm.py
git commit -m "feat(agent): llm client with web_search + pydantic Analysis schema + retries"
```

---

## Task 14: Implement `agent/lib/observability.py` (OTel core, no exporters)

**Files:**
- Create: `agent/lib/observability.py`
- Create: `agent/tests/test_observability.py`

- [ ] **Step 1: Write the test**

`agent/tests/test_observability.py`:

```python
import os
import pytest
from opentelemetry import trace
from lib.observability import init_observability, record_error, flush_observability

def test_init_is_idempotent(monkeypatch):
    monkeypatch.setenv("JOB_ID", "job-1")
    init_observability(job_id="job-1")
    init_observability(job_id="job-1")   # second call must not raise

def test_record_error_marks_span(monkeypatch):
    monkeypatch.setenv("JOB_ID", "job-2")
    init_observability(job_id="job-2")
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("t") as span:
        record_error(span, ValueError("nope"))
        # OpenTelemetry doesn't expose recorded status post-hoc through stable API,
        # but the call must not raise.
    flush_observability(timeout_s=1.0)

def test_flush_without_exporters_is_no_op(monkeypatch):
    monkeypatch.setenv("JOB_ID", "job-3")
    init_observability(job_id="job-3")
    flush_observability(timeout_s=1.0)
```

- [ ] **Step 2: Run — expect failure**

```bash
pytest tests/test_observability.py
```

Expected: ImportError.

- [ ] **Step 3: Write the module**

`agent/lib/observability.py`:

```python
import os
from opentelemetry import trace, propagate, context as ot_context
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import SpanContext, NonRecordingSpan, set_span_in_context
from opentelemetry.trace.status import Status, StatusCode

_initialized = False
_sentry_inited = False
_dd_inited = False

def init_observability(job_id: str) -> None:
    """Initialize OTel and any configured exporters (Sentry/Datadog).
    Idempotent — safe to call multiple times."""
    global _initialized, _sentry_inited, _dd_inited
    if _initialized:
        return

    resource = Resource.create({
        "service.name": "stock-agent",
        "deployment.environment": os.environ.get("DD_ENV", "development"),
        "job.id": job_id,
    })
    provider = TracerProvider(resource=resource)

    # Always log spans to stdout in addition to any exporters (Daytona captures stdout).
    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    # Sentry exporter — wired in Task 18
    # Datadog exporter — wired in Task 19

    trace.set_tracer_provider(provider)

    # Continue the W3C trace from the parent (NextJS) if TRACEPARENT was passed.
    traceparent = os.environ.get("TRACEPARENT")
    if traceparent:
        carrier = {"traceparent": traceparent}
        ctx = propagate.extract(carrier)
        # Activate it so spans we start are children of the parent.
        ot_context.attach(ctx)

    _initialized = True

def record_error(span, exc: BaseException) -> None:
    """Vendor-neutral: record the exception on the span and mark it ERROR."""
    span.record_exception(exc)
    span.set_status(Status(StatusCode.ERROR, str(exc)))

def flush_observability(timeout_s: float = 5.0) -> None:
    """Drain all active exporters. MUST run before the VM is deleted."""
    tp = trace.get_tracer_provider()
    if hasattr(tp, "shutdown"):
        try:
            tp.shutdown()
        except Exception:
            pass
    # Sentry / Datadog flush wired in Tasks 18 / 19.
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/test_observability.py
```

Expected: 3 passes.

- [ ] **Step 5: Commit**

```bash
cd ..
git add agent/lib/observability.py agent/tests/test_observability.py
git commit -m "feat(agent): OTel scaffold with idempotent init and flush"
```

---

## Task 15: Implement `agent/lib/self_delete.py`

**Files:**
- Create: `agent/lib/self_delete.py`
- Create: `agent/tests/test_self_delete.py`

- [ ] **Step 1: Write the test**

`agent/tests/test_self_delete.py`:

```python
from unittest.mock import patch, MagicMock
import httpx
from lib.self_delete import self_delete

def test_self_delete_calls_daytona_api(monkeypatch):
    monkeypatch.setenv("DAYTONA_API_KEY", "dt-test")
    monkeypatch.setenv("DAYTONA_SANDBOX_ID", "sb-abc")
    monkeypatch.setenv("DAYTONA_API_URL", "https://api.daytona.test")
    fake = MagicMock(status_code=200)
    with patch("httpx.delete", return_value=fake) as mock_del:
        self_delete()
        mock_del.assert_called_once()
        url, kwargs = mock_del.call_args.args[0], mock_del.call_args.kwargs
        assert "sb-abc" in url
        assert kwargs["headers"]["Authorization"] == "Bearer dt-test"

def test_self_delete_swallows_network_error(monkeypatch):
    monkeypatch.setenv("DAYTONA_API_KEY", "dt-test")
    monkeypatch.setenv("DAYTONA_SANDBOX_ID", "sb-abc")
    with patch("httpx.delete", side_effect=httpx.ConnectError("boom")):
        # Must not raise — autoDeleteInterval will reclaim the sandbox.
        self_delete()

def test_self_delete_no_op_when_sandbox_id_unset(monkeypatch):
    monkeypatch.delenv("DAYTONA_SANDBOX_ID", raising=False)
    with patch("httpx.delete") as mock_del:
        self_delete()
        mock_del.assert_not_called()
```

- [ ] **Step 2: Run — expect failure**

```bash
pytest tests/test_self_delete.py
```

- [ ] **Step 3: Write the module**

`agent/lib/self_delete.py`:

```python
import os
import httpx

def self_delete() -> None:
    """DELETE this sandbox via the Daytona REST API. Never raises.
    Safety net: Daytona's autoDeleteInterval reclaims the sandbox if this fails."""
    sandbox_id = os.environ.get("DAYTONA_SANDBOX_ID")
    api_key = os.environ.get("DAYTONA_API_KEY")
    if not sandbox_id or not api_key:
        return
    base = os.environ.get("DAYTONA_API_URL", "https://app.daytona.io/api")
    try:
        httpx.delete(
            f"{base}/sandbox/{sandbox_id}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
    except Exception:
        # Intentionally swallow — autoDeleteInterval is the safety net.
        pass
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/test_self_delete.py
```

Expected: 3 passes.

- [ ] **Step 5: Commit**

```bash
cd ..
git add agent/lib/self_delete.py agent/tests/test_self_delete.py
git commit -m "feat(agent): self_delete that never raises"
```

---

## Task 16: Implement `agent/agent.py` (the entrypoint)

**Files:**
- Create: `agent/agent.py`
- Create: `agent/tests/test_agent.py`

- [ ] **Step 1: Write the integration test (uses real Neon, stubs the LLM)**

`agent/tests/test_agent.py`:

```python
import os
import uuid
import pytest
import psycopg
from unittest.mock import patch
from lib.llm import Analysis, Signal

@pytest.fixture
def neon_url():
    url = os.environ.get("NEON_DATABASE_URL")
    if not url:
        pytest.skip("NEON_DATABASE_URL not set")
    return url

@pytest.fixture
def fresh_job(neon_url):
    job_id = str(uuid.uuid4())
    with psycopg.connect(neon_url) as conn:
        conn.execute("INSERT INTO jobs (id, ticker, status) VALUES (%s, %s, 'pending')", (job_id, "AAPL"))
        conn.commit()
    yield job_id
    with psycopg.connect(neon_url) as conn:
        conn.execute("DELETE FROM jobs WHERE id = %s", (job_id,))
        conn.commit()

FAKE_ANALYSIS = Analysis(
    recommendation="buy",
    summary="strong",
    signals=[Signal(label="rev", evidence="up 10%", source=None)],
)

def test_main_happy_path(neon_url, fresh_job, monkeypatch):
    monkeypatch.setenv("JOB_ID", fresh_job)
    monkeypatch.setenv("NEON_DATABASE_URL", neon_url)

    with patch("lib.llm.OpenAIClient.analyze", return_value=FAKE_ANALYSIS), \
         patch("lib.self_delete.self_delete"):
        import importlib
        import agent
        importlib.reload(agent)
        agent.main()

    with psycopg.connect(neon_url) as conn:
        row = conn.execute(
            "SELECT status, recommendation, result FROM jobs WHERE id=%s", (fresh_job,)
        ).fetchone()
    assert row[0] == "complete"
    assert row[1] == "buy"
    assert row[2]["summary"] == "strong"

def test_main_idempotency_when_already_complete(neon_url, fresh_job, monkeypatch):
    """If the row is no longer 'pending', the agent must exit without writing."""
    with psycopg.connect(neon_url) as conn:
        conn.execute(
            "UPDATE jobs SET status='complete', recommendation='hold', "
            "result='{\"summary\":\"x\",\"signals\":[]}'::jsonb WHERE id=%s",
            (fresh_job,),
        )
        conn.commit()

    monkeypatch.setenv("JOB_ID", fresh_job)
    monkeypatch.setenv("NEON_DATABASE_URL", neon_url)

    analyze = patch("lib.llm.OpenAIClient.analyze")
    with analyze as m, patch("lib.self_delete.self_delete"):
        import importlib, agent
        importlib.reload(agent)
        agent.main()
        m.assert_not_called()

def test_main_writes_failed_on_llm_error(neon_url, fresh_job, monkeypatch):
    monkeypatch.setenv("JOB_ID", fresh_job)
    monkeypatch.setenv("NEON_DATABASE_URL", neon_url)

    with patch("lib.llm.OpenAIClient.analyze", side_effect=RuntimeError("LLM blew up")), \
         patch("lib.self_delete.self_delete"):
        import importlib, agent
        importlib.reload(agent)
        with pytest.raises(RuntimeError):
            agent.main()

    with psycopg.connect(neon_url) as conn:
        row = conn.execute("SELECT status, error FROM jobs WHERE id=%s", (fresh_job,)).fetchone()
    assert row[0] == "failed"
    assert "LLM blew up" in row[1]
```

- [ ] **Step 2: Run — expect failure**

```bash
pytest tests/test_agent.py
```

- [ ] **Step 3: Write `agent/agent.py`**

```python
import os
import sys
import traceback
from opentelemetry import trace
from lib.observability import init_observability, flush_observability, record_error
from lib.db import get_job, mark_running, mark_complete, mark_failed
from lib.llm import run_analysis
from lib.self_delete import self_delete

JOB_ID = os.environ.get("JOB_ID", "")

def main() -> None:
    if not JOB_ID:
        print("JOB_ID not set", file=sys.stderr)
        sys.exit(2)

    init_observability(job_id=JOB_ID)
    tracer = trace.get_tracer("stock-agent")

    with tracer.start_as_current_span("agent.run") as span:
        span.set_attribute("job_id", JOB_ID)
        try:
            job = get_job(JOB_ID)
            if job is None or job["status"] != "pending":
                # Idempotency guard
                print(f"job {JOB_ID} not pending (status={job and job['status']}); exiting", file=sys.stderr)
                return
            span.set_attribute("ticker", job["ticker"])

            mark_running(JOB_ID)
            result = run_analysis(ticker=job["ticker"])
            mark_complete(JOB_ID, recommendation=result["recommendation"], result=result)
            span.set_attribute("final_status", "complete")
        except Exception as e:
            record_error(span, e)
            mark_failed(JOB_ID, error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
            span.set_attribute("final_status", "failed")
            raise
        finally:
            flush_observability()
            try:
                self_delete()
            except Exception:
                pass

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/test_agent.py
```

Expected: 3 passes.

- [ ] **Step 5: End-to-end local smoke (without Daytona)**

Insert a pending row manually, then run the agent against it.

```bash
# In a Python shell or psql:
# INSERT INTO jobs (ticker) VALUES ('AAPL') RETURNING id;
# Note the returned id.

export JOB_ID=<that-uuid>
export NEON_DATABASE_URL=...
export OPENAI_API_KEY=...
python agent.py
```

Expected: the agent runs, calls OpenAI, writes the result, and exits. Check the row:

```bash
psql $NEON_DATABASE_URL -c "SELECT status, recommendation, result FROM jobs WHERE id = '<that-uuid>'"
```

- [ ] **Step 6: Commit**

```bash
cd ..
git add agent/agent.py agent/tests/test_agent.py
git commit -m "feat(agent): main entrypoint with idempotency, flush, self-delete"
```

---

## Task 17: Build and publish the Daytona snapshot

**Files:**
- Create: `scripts/build_snapshot.sh`
- Create: `Makefile`

- [ ] **Step 1: Write the build script**

`scripts/build_snapshot.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Build and publish the Daytona snapshot.
# Requires the Daytona CLI installed and authenticated:
#   https://www.daytona.io/docs/getting-started/installation/

cd "$(dirname "$0")/.."

echo "Building stock-agent image..."
docker build -t stock-agent:latest ./agent

echo "Publishing snapshot to Daytona..."
daytona snapshot push stock-agent:latest --name stock-agent:latest

echo "Done."
```

```bash
chmod +x scripts/build_snapshot.sh
```

(On Windows, use Git Bash or WSL to run the script.)

- [ ] **Step 2: Write the Makefile**

```makefile
.PHONY: dev test seed snapshot smoke clean

dev:
	pnpm dev

test:
	pnpm test
	cd agent && .venv/bin/pytest

seed:
	pnpm exec tsx scripts/apply_migration.ts

snapshot:
	./scripts/build_snapshot.sh

smoke:
	./scripts/smoke.sh
```

- [ ] **Step 3: Run the snapshot build**

```bash
make snapshot
```

Expected:
1. Docker builds the image (~1-2 minutes the first time).
2. Daytona CLI uploads it; outputs a confirmation.

Verify with:
```bash
daytona snapshot list
```

The snapshot named `stock-agent:latest` should appear.

- [ ] **Step 4: Commit**

```bash
git add scripts/build_snapshot.sh Makefile
git commit -m "feat(snapshot): build and publish Daytona snapshot via Makefile"
```

---

## Task 18: Wire the Sentry exporter into both NextJS and the Python agent

**Files:**
- Modify: `lib/observability/otel.ts` (NextJS side)
- Create: `lib/observability/exporters/sentry.ts` (NextJS side)
- Create: `sentry.server.config.ts`, `sentry.client.config.ts`, `sentry.edge.config.ts` (NextJS root)
- Modify: `agent/lib/observability.py` (Python side)

- [ ] **Step 1: Install Sentry**

```bash
pnpm add @sentry/nextjs
```

- [ ] **Step 2: Write the Sentry config files (NextJS)**

`sentry.server.config.ts`:

```typescript
import * as Sentry from "@sentry/nextjs";

const dsn = process.env.SENTRY_DSN_NEXTJS;
if (dsn) {
  Sentry.init({
    dsn,
    tracesSampleRate: 1.0,
    environment: process.env.DD_ENV ?? process.env.NODE_ENV ?? "development",
  });
}
```

`sentry.client.config.ts`:

```typescript
import * as Sentry from "@sentry/nextjs";

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN ?? process.env.SENTRY_DSN_NEXTJS;
if (dsn) {
  Sentry.init({
    dsn,
    tracesSampleRate: 1.0,
    environment: process.env.NODE_ENV,
  });
}
```

`sentry.edge.config.ts`:

```typescript
import * as Sentry from "@sentry/nextjs";

const dsn = process.env.SENTRY_DSN_NEXTJS;
if (dsn) {
  Sentry.init({
    dsn,
    tracesSampleRate: 1.0,
  });
}
```

Sentry's NextJS SDK v8+ integrates with OpenTelemetry automatically — spans we create with the OTel API are picked up by Sentry's exporter without any further wiring.

- [ ] **Step 3: Update `lib/observability/exporters/sentry.ts` (boot probe)**

`lib/observability/exporters/sentry.ts`:

```typescript
// Active only when SENTRY_DSN_NEXTJS is set. Initialization is handled by the
// sentry.{server,client,edge}.config.ts files at framework boot — this module
// is a marker for explicit readability of the exporters/ directory.
export const sentryEnabled = !!process.env.SENTRY_DSN_NEXTJS;
```

- [ ] **Step 4: Add Sentry to the Python agent**

Modify `agent/lib/observability.py`:

Insert into `init_observability`, after the line `trace.set_tracer_provider(provider)` and before the TRACEPARENT block:

```python
    # === Sentry exporter ===
    # Sentry Python SDK v2+ integrates with OTel via SentrySpanProcessor +
    # SentryPropagator — spans created on the OTel TracerProvider are forwarded
    # to Sentry automatically. No application code touches sentry_sdk directly.
    dsn = os.environ.get("SENTRY_DSN_AGENT")
    if dsn:
        import sentry_sdk
        from sentry_sdk.integrations.opentelemetry import SentrySpanProcessor, SentryPropagator
        sentry_sdk.init(
            dsn=dsn,
            traces_sample_rate=1.0,
            environment=os.environ.get("DD_ENV", "development"),
        )
        provider.add_span_processor(SentrySpanProcessor())
        propagate.set_global_textmap(SentryPropagator())
        global _sentry_inited
        _sentry_inited = True
```

Modify `flush_observability` to also flush Sentry:

```python
def flush_observability(timeout_s: float = 5.0) -> None:
    """Drain all active exporters. MUST run before the VM is deleted."""
    tp = trace.get_tracer_provider()
    if hasattr(tp, "shutdown"):
        try:
            tp.shutdown()
        except Exception:
            pass

    if _sentry_inited:
        try:
            import sentry_sdk
            sentry_sdk.flush(timeout=timeout_s)
        except Exception:
            pass
```

- [ ] **Step 5: Add a Python test for the Sentry path**

Append to `agent/tests/test_observability.py`:

```python
def test_init_with_sentry_dsn_does_not_crash(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN_AGENT", "https://public@o0.ingest.sentry.io/0")
    monkeypatch.setenv("JOB_ID", "job-sentry")
    # Force module re-import so init runs fresh
    import importlib, lib.observability as o
    importlib.reload(o)
    o.init_observability(job_id="job-sentry")
    o.flush_observability(timeout_s=1.0)
```

- [ ] **Step 6: Run all Python tests — expect pass**

```bash
cd agent
pytest
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
cd ..
git add .
git commit -m "feat(observability): Sentry exporter wiring (both NextJS and agent)"
```

---

## Task 19: Wire the Datadog exporter into both NextJS and the Python agent

**Files:**
- Create: `lib/observability/exporters/datadog.ts`
- Create: `instrumentation.ts` (NextJS root — hooks into NextJS boot)
- Modify: `agent/lib/observability.py`

- [ ] **Step 1: Install dd-trace**

```bash
pnpm add dd-trace
```

- [ ] **Step 2: Write the Datadog exporter (NextJS)**

`lib/observability/exporters/datadog.ts`:

```typescript
export function initDatadogIfEnabled(): boolean {
  if (!process.env.DD_API_KEY) return false;
  // dd-trace must be required (CJS) before any instrumented module.
  // The instrumentation.ts hook calls this at framework boot.
  const tracer = require("dd-trace").init({
    service: process.env.DD_SERVICE ?? "stock-agent-frontend",
    env: process.env.DD_ENV ?? process.env.NODE_ENV ?? "development",
    logInjection: true,
  });
  return !!tracer;
}
```

- [ ] **Step 3: Wire it through NextJS's instrumentation hook**

`instrumentation.ts` (at the project root):

```typescript
export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    const { initDatadogIfEnabled } = await import("./lib/observability/exporters/datadog");
    initDatadogIfEnabled();
  }
}
```

NextJS automatically picks up a top-level `instrumentation.ts` file when `experimental.instrumentationHook` is enabled. In NextJS 15 it's on by default.

- [ ] **Step 4: Update the Python observability module**

Modify `agent/lib/observability.py` `init_observability`, inserting after the Sentry block:

```python
    # === Datadog exporter ===
    dd_key = os.environ.get("DD_API_KEY")
    if dd_key:
        import ddtrace
        ddtrace.config.service = os.environ.get("DD_SERVICE", "stock-agent")
        ddtrace.config.env = os.environ.get("DD_ENV", "development")
        # ddtrace can run as an OTel-compatible exporter for an existing TracerProvider.
        # The simplest, most-supported wiring is to let ddtrace install its own tracer
        # alongside OTel; both will receive spans through the OTel API thanks to
        # ddtrace's OTel bridge (enabled via DD_TRACE_OTEL_ENABLED).
        os.environ.setdefault("DD_TRACE_OTEL_ENABLED", "true")
        ddtrace.patch_all(httpx=True, psycopg=True, openai=True, logging=True)
        global _dd_inited
        _dd_inited = True
```

Modify `flush_observability` to also flush ddtrace:

```python
    if _dd_inited:
        try:
            import ddtrace
            ddtrace.tracer.shutdown(timeout=timeout_s)
        except Exception:
            pass
```

- [ ] **Step 5: Add a Python test for the Datadog path**

Append to `agent/tests/test_observability.py`:

```python
def test_init_with_dd_api_key_does_not_crash(monkeypatch):
    monkeypatch.setenv("DD_API_KEY", "dd-test-key")
    monkeypatch.setenv("DD_SITE", "datadoghq.com")
    monkeypatch.setenv("JOB_ID", "job-dd")
    import importlib, lib.observability as o
    importlib.reload(o)
    o.init_observability(job_id="job-dd")
    o.flush_observability(timeout_s=1.0)

def test_init_with_both_vendors_does_not_crash(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN_AGENT", "https://public@o0.ingest.sentry.io/0")
    monkeypatch.setenv("DD_API_KEY", "dd-test-key")
    monkeypatch.setenv("JOB_ID", "job-both")
    import importlib, lib.observability as o
    importlib.reload(o)
    o.init_observability(job_id="job-both")
    o.flush_observability(timeout_s=1.0)
```

- [ ] **Step 6: Run Python tests**

```bash
cd agent
pytest tests/test_observability.py
```

Expected: 5 passes.

- [ ] **Step 7: Commit**

```bash
cd ..
git add .
git commit -m "feat(observability): Datadog exporter wiring (both NextJS and agent)"
```

---

## Task 20: Write the `/api/cleanup` route + `/admin` page

**Files:**
- Create: `app/api/cleanup/route.ts`
- Create: `app/admin/page.tsx`
- Create: `tests/api.cleanup.test.ts`

- [ ] **Step 1: Write the test**

`tests/api.cleanup.test.ts`:

```typescript
import { describe, it, expect, vi } from "vitest";
import { POST } from "@/app/api/cleanup/route";

const updateMock = vi.fn(async () => ({ rowCount: 2 }));
vi.mock("@/lib/db/client", () => ({
  db: {
    update: () => ({ set: () => ({ where: () => ({ returning: () => Promise.resolve([{ id: "a" }, { id: "b" }]) }) }) }),
  },
  jobs: { id: "id", status: "status", startedAt: "started_at" },
}));

describe("POST /api/cleanup", () => {
  it("returns the count of swept rows", async () => {
    const res = await POST(new Request("http://localhost/api/cleanup", { method: "POST" }));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.swept).toBe(2);
  });
});
```

- [ ] **Step 2: Run — expect failure**

```bash
pnpm test tests/api.cleanup.test.ts
```

- [ ] **Step 3: Write the cleanup route**

`app/api/cleanup/route.ts`:

```typescript
import { and, eq, lt, sql } from "drizzle-orm";
import { db, jobs } from "@/lib/db/client";
import { traced, addAttrs } from "@/lib/observability/api";

export async function POST(_req: Request): Promise<Response> {
  return traced("api.cleanup.post", undefined, async (span) => {
    const tenMinAgo = new Date(Date.now() - 10 * 60 * 1000);
    const swept = await db
      .update(jobs)
      .set({ status: "failed", error: "timeout", completedAt: sql`now()` })
      .where(and(eq(jobs.status, "running"), lt(jobs.startedAt, tenMinAgo)))
      .returning({ id: jobs.id });
    addAttrs(span, { swept: swept.length });
    return Response.json({ swept: swept.length });
  });
}
```

- [ ] **Step 4: Run — expect pass**

```bash
pnpm test tests/api.cleanup.test.ts
```

- [ ] **Step 5: Write the admin page**

`app/admin/page.tsx`:

```tsx
import { desc } from "drizzle-orm";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { db, jobs } from "@/lib/db/client";

export const dynamic = "force-dynamic";

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  pending: "outline",
  running: "secondary",
  complete: "default",
  failed: "destructive",
};

export default async function AdminPage() {
  const rows = await db.select().from(jobs).orderBy(desc(jobs.createdAt)).limit(50);
  const durationSec = (r: typeof rows[number]): number | null => {
    if (!r.completedAt) return null;
    return Math.round((r.completedAt.getTime() - r.createdAt.getTime()) / 1000);
  };

  return (
    <main className="p-8 max-w-6xl mx-auto space-y-4">
      <h1 className="text-2xl font-bold">Admin · Recent jobs</h1>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-slate-500 border-b">
            <th className="py-2">id</th>
            <th>ticker</th>
            <th>status</th>
            <th>rec</th>
            <th>dur (s)</th>
            <th>created</th>
            <th>error</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-b">
              <td className="py-1">
                <Link href={`/jobs/${r.id}`} className="font-mono text-xs text-blue-700">{r.id.slice(0, 8)}</Link>
              </td>
              <td className="font-mono">{r.ticker}</td>
              <td><Badge variant={STATUS_VARIANT[r.status]}>{r.status}</Badge></td>
              <td>{r.recommendation ?? ""}</td>
              <td>{durationSec(r) ?? ""}</td>
              <td className="text-xs text-slate-500">{r.createdAt.toISOString()}</td>
              <td className="text-xs text-red-600 truncate max-w-xs">{r.error?.slice(0, 80) ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
```

- [ ] **Step 6: Verify the admin page in the browser**

```bash
pnpm dev
```

Open http://localhost:3000/admin — should show the table with whatever rows you have.

- [ ] **Step 7: Commit**

```bash
git add .
git commit -m "feat: cleanup endpoint and admin page"
```

---

## Task 21: End-to-end smoke test

**Files:**
- Create: `scripts/smoke.sh`

- [ ] **Step 1: Ensure the snapshot is up to date**

```bash
make snapshot
```

- [ ] **Step 2: Write the smoke script**

`scripts/smoke.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

# End-to-end smoke: submits a ticker via the live NextJS dev server,
# waits for the row to complete, prints the result.

TICKER="${1:-AAPL}"
BASE="${BASE:-http://localhost:3000}"

echo "Submitting $TICKER..."
JOB=$(curl -s -X POST "$BASE/api/jobs" \
  -H 'content-type: application/json' \
  -d "{\"ticker\":\"$TICKER\"}" | jq -r .jobId)
echo "Job id: $JOB"

echo "Polling..."
for i in $(seq 1 60); do
  RESP=$(curl -s "$BASE/api/status/$JOB")
  STATUS=$(echo "$RESP" | jq -r .status)
  printf "  [%02d] status=%s\n" "$i" "$STATUS"
  if [[ "$STATUS" == "complete" || "$STATUS" == "failed" ]]; then
    echo "$RESP" | jq .
    exit 0
  fi
  sleep 3
done

echo "Timed out waiting for $JOB"
exit 1
```

```bash
chmod +x scripts/smoke.sh
```

- [ ] **Step 3: Run the dev server in one terminal**

```bash
pnpm dev
```

- [ ] **Step 4: Run the smoke in another terminal**

```bash
./scripts/smoke.sh AAPL
```

Expected: status progresses `pending → running → complete` over ~30–90 seconds. Final JSON shows `recommendation`, `result.summary`, and `result.signals`.

- [ ] **Step 5: Verify in the browser**

Refresh http://localhost:3000/admin — the `AAPL` row should be `complete` with a duration and a recommendation. Click into `/jobs/<id>` — the detail page shows the summary and signals.

- [ ] **Step 6: Commit**

```bash
git add scripts/smoke.sh
git commit -m "test: end-to-end smoke script"
```

---

## Task 22: Comprehensive README with full configuration and HOW-TOs

**Goal:** README.md is the single doorway into the project. A new engineer with zero context must be able to clone the repo, get to a working end-to-end run, switch observability backends, and debug common failures using only the README. Link out to the spec and plan for deeper architecture detail.

**Files:**
- Modify: `README.md`

The README must cover (use these as required sections):

1. **What this is** — 2-3 sentences, with the demo disclaimer.
2. **Architecture at a glance** — ASCII diagram + lifecycle.
3. **Prerequisites** — exact versions for Node, pnpm, Python, Docker; what accounts to create (Neon, Daytona, OpenAI; optional Sentry / Datadog) and how.
4. **Quickstart** — minimum steps from clone to first run.
5. **Configuration reference** — every env var explained: required vs optional, source, example value, what breaks if missing.
6. **HOW-TO: Provision Neon** — create project, get connection string, apply migrations.
7. **HOW-TO: Provision Daytona** — get API key, install CLI, build and publish the snapshot, verify it appears in `daytona snapshot list`.
8. **HOW-TO: Get an OpenAI key** — and which models / tools the demo uses.
9. **HOW-TO: Enable Sentry only** — what to set, what you'll see, how to verify.
10. **HOW-TO: Enable Datadog only** — what to set, what you'll see, how to verify.
11. **HOW-TO: Enable both** — same instrumentation lights up in both vendors.
12. **HOW-TO: Run with no observability backend** — confirm the demo still works; `jobs` table is the audit trail.
13. **Running the app** — `pnpm dev`, what URLs to open, how to submit a ticker.
14. **Running the tests** — NextJS (vitest), Python agent (pytest), what requires `NEON_DATABASE_URL`, what runs offline.
15. **Running the end-to-end smoke** — `scripts/smoke.sh`.
16. **Operating the demo** — `/admin` page, `/api/cleanup` for stuck rows, where to find sandbox logs in the Daytona dashboard.
17. **Troubleshooting** — at minimum these scenarios, each with symptom → cause → fix:
   - "Submit returns 500 with spawn_failed"
   - "Job stuck in `pending` forever"
   - "Job stuck in `running` forever"
   - "LLM returns invalid JSON"
   - "Sentry / Datadog showing nothing"
   - "Sandbox not self-deleting"
   - "Local Neon migration fails"
18. **What's out of scope (intentional YAGNI)** — link to spec section 11.
19. **Project layout** — one-line description of each top-level directory.
20. **Where to dig deeper** — links to the spec and plan.

- [ ] **Step 1: Replace `README.md` with the comprehensive version**

````markdown
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
| Node.js | 20+ | NextJS 15 runtime |
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
| `DAYTONA_API_KEY` | Daytona dashboard → API Keys | `dt_abc…` | Spawn fails → 500 on submit |
| `DAYTONA_TARGET` | Daytona dashboard | `us` | Region defaults may misroute the spawn |
| `NEON_DATABASE_URL` | Neon dashboard → Connection string | `postgresql://user:pass@ep-…neon.tech/neondb` | DB calls fail everywhere |
| `OPENAI_API_KEY` | OpenAI dashboard → API Keys | `sk-proj-…` | Agent crashes when it tries to call the LLM |

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

In another:
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
├── db/migrations/        SQL migrations applied by scripts/apply_migration.ts
├── scripts/              build_snapshot.sh, apply_migration.ts, smoke.sh
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
````

- [ ] **Step 2: Sanity-check that every cross-reference in the README still resolves**

```powershell
# Files referenced in the README must exist:
Test-Path .env.example
Test-Path Makefile
Test-Path scripts/build_snapshot.sh
Test-Path scripts/apply_migration.ts
Test-Path scripts/smoke.sh
Test-Path docs/superpowers/specs/2026-06-22-daytona-stock-agent-design.md
Test-Path docs/superpowers/plans/2026-06-22-daytona-stock-agent.md
```

Every check must return `True`. If any is `False`, either the file is missing (fix the upstream task) or the README references the wrong path (fix the README).

- [ ] **Step 3: Verify the README renders cleanly**

Open `README.md` on GitHub (push to a branch if needed) or in a markdown previewer. Check:
- All section headings appear in the TOC.
- The ASCII architecture diagram renders monospace.
- All code blocks have language tags.
- All internal links resolve.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs(readme): comprehensive setup, configuration, HOW-TOs, and troubleshooting"
```

---

## Done

You should now have:

- A NextJS app on http://localhost:3000 with a working submit form and job detail page.
- A `jobs` table in Neon recording every submission with full state and metadata.
- A Daytona snapshot named `stock-agent:latest` that runs the agent on boot.
- A Python agent that reads its job from Neon, runs an OpenAI analysis with web search, writes the result back, and self-deletes.
- OpenTelemetry instrumentation on both sides that exports to Sentry, Datadog, both, or neither — purely env-var-driven.
- A smoke test that exercises the whole loop.
- Tests on both sides that don't depend on real cloud services.

### Verification checklist

- [ ] `pnpm test` is green.
- [ ] `cd agent && pytest` is green.
- [ ] `./scripts/smoke.sh AAPL` completes with a non-null `recommendation`.
- [ ] With `SENTRY_DSN_*` set only, a deliberate `mark_failed` shows up in Sentry.
- [ ] With `DD_API_KEY` set only, the same run shows up in Datadog APM as one cross-cloud trace.
- [ ] With both set, the same trace appears in both vendors.
- [ ] With neither set, the demo still works end-to-end (the `jobs` table is the audit trail).
