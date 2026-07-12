# Thesis Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the agent's cited bull/bear `Thesis` on the analysis page (Investment Thesis block with confidence + grounding badges, Bull|Bear columns, Key Risks), replacing the dead `KeyInsights`/`signals` path.

**Architecture:** Pure formatting helpers in `lib/ui/thesis.ts` (unit-tested, node-env vitest) + a thin `InvestmentThesis` component that delegates all mapping to them. The stale `signals`/`RawSignal`/`map-insights` code is removed.

**Tech Stack:** Next.js / React / TypeScript, vitest (node env, pure-logic tests — no React-render harness).

## Global Constraints

- `ThesisPoint = { claim: string; evidence: string; source_url: string | null }`.
- `result` shape (after Task 2): `{ recommendation?, confidence?, summary?, bull_case?: ThesisPoint[], bear_case?: ThesisPoint[], key_risks?: ThesisPoint[], grounding?, snapshot? } | null` — `signals` removed.
- Grounding badge mapping (verbatim): `researched`→`{label:"Web-researched", tone:"up"}`, `limited`→`{label:"Limited research", tone:"neutral"}`, `snapshot_only`→`{label:"Snapshot only", tone:"muted"}`, unknown/null→`null`.
- Confidence formatting: `low`→"Low", `medium`→"Medium", `high`→"High", unknown/null→`null`.
- `safeSourceHref` returns the URL only for `http:`/`https:`, else `null`.
- Layout: header row (confidence + grounding badges) → Bull | Bear two-column grid → Key Risks full-width. Bull accent `text-af-secondary`, Bear `text-af-error`, Risks `text-af-signal-hold`. Empty section → "None provided."
- Tests are node-env vitest of pure helpers only (match `tests/components/*`); no React-render tests, no new deps.
- `StockHeader` and `RawLLMResponse` are NOT changed.
- Verification target: `npx tsc --noEmit` yields NO NEW type errors (7 pre-existing errors in `lib/runtime/subprocess.ts` + `tests/daytona.test.ts` are unrelated and remain); `npm run test` passes.

---

### Task 1: Types + pure `lib/ui/thesis.ts` helpers

**Files:**
- Modify: `lib/job/types.ts`
- Create: `lib/ui/thesis.ts`
- Create: `tests/components/thesis.test.ts`

**Interfaces:**
- Produces:
  - `ThesisPoint` (type) in `lib/job/types.ts`.
  - `formatConfidence(c: string | null | undefined): string | null`
  - `formatGrounding(g: string | null | undefined): { label: string; tone: "up"|"neutral"|"muted" } | null`
  - `safeSourceHref(url: string | null | undefined): string | null`

- [ ] **Step 1: Write the failing tests**

Create `tests/components/thesis.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { formatConfidence, formatGrounding, safeSourceHref } from "@/lib/ui/thesis";

describe("formatConfidence", () => {
  it("title-cases the known levels", () => {
    expect(formatConfidence("low")).toBe("Low");
    expect(formatConfidence("medium")).toBe("Medium");
    expect(formatConfidence("high")).toBe("High");
  });
  it("returns null for null/unknown", () => {
    expect(formatConfidence(null)).toBeNull();
    expect(formatConfidence("bogus")).toBeNull();
  });
});

describe("formatGrounding", () => {
  it("maps each level to label + tone", () => {
    expect(formatGrounding("researched")).toEqual({ label: "Web-researched", tone: "up" });
    expect(formatGrounding("limited")).toEqual({ label: "Limited research", tone: "neutral" });
    expect(formatGrounding("snapshot_only")).toEqual({ label: "Snapshot only", tone: "muted" });
  });
  it("returns null for null/unknown", () => {
    expect(formatGrounding(null)).toBeNull();
    expect(formatGrounding("x")).toBeNull();
  });
});

describe("safeSourceHref", () => {
  it("passes through http and https", () => {
    expect(safeSourceHref("https://x.test/a")).toBe("https://x.test/a");
    expect(safeSourceHref("http://x.test/b")).toBe("http://x.test/b");
  });
  it("rejects non-http, malformed, empty, and null", () => {
    expect(safeSourceHref("ftp://x/y")).toBeNull();
    expect(safeSourceHref("javascript:alert(1)")).toBeNull();
    expect(safeSourceHref("not a url")).toBeNull();
    expect(safeSourceHref("")).toBeNull();
    expect(safeSourceHref(null)).toBeNull();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npx vitest run tests/components/thesis.test.ts`
Expected: FAIL — cannot resolve `@/lib/ui/thesis`.

- [ ] **Step 3: Implement `lib/ui/thesis.ts`**

```typescript
export function formatConfidence(c: string | null | undefined): string | null {
  const map: Record<string, string> = { low: "Low", medium: "Medium", high: "High" };
  return c ? (map[c] ?? null) : null;
}

export type GroundingBadge = { label: string; tone: "up" | "neutral" | "muted" };

export function formatGrounding(g: string | null | undefined): GroundingBadge | null {
  switch (g) {
    case "researched":
      return { label: "Web-researched", tone: "up" };
    case "limited":
      return { label: "Limited research", tone: "neutral" };
    case "snapshot_only":
      return { label: "Snapshot only", tone: "muted" };
    default:
      return null;
  }
}

export function safeSourceHref(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.protocol === "http:" || u.protocol === "https:" ? u.toString() : null;
  } catch {
    return null;
  }
}
```

- [ ] **Step 4: Add `ThesisPoint` + the thesis fields to the `result` type**

In `lib/job/types.ts`, add the exported type (near the top, after the imports):

```typescript
export type ThesisPoint = { claim: string; evidence: string; source_url: string | null };
```

Replace the `result` object in `SerializedJob` with (KEEP `signals` for now — it is removed in Task 2 so `key-insights.tsx` keeps compiling this task):

```typescript
  result: {
    recommendation?: Recommendation;
    confidence?: string;
    summary?: string;
    bull_case?: ThesisPoint[];
    bear_case?: ThesisPoint[];
    key_risks?: ThesisPoint[];
    grounding?: string;
    signals?: RawSignal[];
    snapshot?: Snapshot | null;
  } | null;
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `npx vitest run tests/components/thesis.test.ts`
Expected: PASS (all cases). Also confirm no new type errors introduced by the type edit:

Run: `npx tsc --noEmit 2>&1 | grep -c "error TS"`
Expected: `7` (the pre-existing errors only; the additive type change introduces none).

- [ ] **Step 6: Commit**

```bash
git add lib/ui/thesis.ts tests/components/thesis.test.ts lib/job/types.ts
git commit -m "feat(web): add thesis type + pure thesis formatting helpers"
```

---

### Task 2: `InvestmentThesis` component + wiring + remove dead signals code

**Files:**
- Create: `components/job/investment-thesis.tsx`
- Modify: `components/job/job-live-poller.tsx`
- Modify: `lib/job/types.ts`
- Delete: `components/job/key-insights.tsx`
- Delete: `lib/job/map-insights.ts`
- Delete: `tests/components/map-insights.test.ts`

**Interfaces:**
- Consumes: `ThesisPoint` type; `formatConfidence`/`formatGrounding`/`safeSourceHref` (Task 1).

- [ ] **Step 1: Create `components/job/investment-thesis.tsx`**

```tsx
import type { SerializedJob, ThesisPoint } from "@/lib/job/types";
import { formatConfidence, formatGrounding, safeSourceHref } from "@/lib/ui/thesis";

const GROUNDING_TONE: Record<string, string> = {
  up: "text-af-secondary",
  neutral: "text-af-signal-hold",
  muted: "text-af-on-surface-variant",
};

function ThesisPointItem({ point }: { point: ThesisPoint }) {
  const href = safeSourceHref(point.source_url);
  return (
    <li className="space-y-1">
      <p className="text-sm font-semibold text-af-on-surface">{point.claim}</p>
      <p className="text-sm text-af-on-surface-variant leading-relaxed">{point.evidence}</p>
      {href && (
        <a
          href={href}
          target="_blank"
          rel="noreferrer"
          className="text-af-secondary text-[12px] font-medium inline-flex items-center gap-1 hover:underline"
        >
          Source
          <span className="material-symbols-outlined text-[14px]">open_in_new</span>
        </a>
      )}
    </li>
  );
}

function ThesisSection({ title, points, accent }: { title: string; points: ThesisPoint[]; accent: string }) {
  return (
    <div className="bg-af-surface-container-lowest p-6 rounded-xl border border-af-outline-variant">
      <h5 className={`text-sm font-semibold uppercase mb-4 ${accent}`}>{title}</h5>
      {points.length === 0 ? (
        <p className="text-sm text-af-on-surface-variant">None provided.</p>
      ) : (
        <ul className="space-y-4">
          {points.map((p, i) => (
            <ThesisPointItem key={i} point={p} />
          ))}
        </ul>
      )}
    </div>
  );
}

export function InvestmentThesis({
  result,
  lastUpdatedLabel,
}: {
  result: SerializedJob["result"];
  lastUpdatedLabel: string;
}) {
  const confidence = formatConfidence(result?.confidence ?? null);
  const grounding = formatGrounding(result?.grounding ?? null);
  const bull = result?.bull_case ?? [];
  const bear = result?.bear_case ?? [];
  const risks = result?.key_risks ?? [];

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h4 className="text-2xl font-semibold text-af-on-surface">Investment Thesis</h4>
          {confidence && (
            <span className="text-[12px] font-medium text-af-on-surface-variant border border-af-outline-variant rounded-full px-3 py-1">
              Confidence: {confidence}
            </span>
          )}
          {grounding && (
            <span
              className={`text-[12px] font-medium border border-af-outline-variant rounded-full px-3 py-1 ${GROUNDING_TONE[grounding.tone]}`}
            >
              {grounding.label}
            </span>
          )}
        </div>
        <span className="text-sm text-af-on-surface-variant">Last updated: {lastUpdatedLabel}</span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <ThesisSection title="Bull Case" points={bull} accent="text-af-secondary" />
        <ThesisSection title="Bear Case" points={bear} accent="text-af-error" />
      </div>
      <ThesisSection title="Key Risks" points={risks} accent="text-af-signal-hold" />
    </section>
  );
}
```

- [ ] **Step 2: Swap the component in the poller**

In `components/job/job-live-poller.tsx`, change the import line
`import { KeyInsights } from "./key-insights";` to:

```tsx
import { InvestmentThesis } from "./investment-thesis";
```

And replace the usage line
`<KeyInsights signals={job.result?.signals ?? null} lastUpdatedLabel={lastUpdatedLabel} />`
with:

```tsx
          <InvestmentThesis result={job.result ?? null} lastUpdatedLabel={lastUpdatedLabel} />
```

- [ ] **Step 3: Remove `signals`/`RawSignal` from the type**

In `lib/job/types.ts`, delete the line `    signals?: RawSignal[];` from the `result`
object, and delete the import line `import type { RawSignal } from "@/lib/job/map-insights";`.

- [ ] **Step 4: Delete the dead files**

```bash
git rm components/job/key-insights.tsx lib/job/map-insights.ts tests/components/map-insights.test.ts
```

- [ ] **Step 5: Verify no dead references remain**

Run: `grep -rn "map-insights\|KeyInsights\|RawSignal\|mapSignalsToInsights" lib app components tests --include=*.ts --include=*.tsx`
Expected: no output.

- [ ] **Step 6: Type-check and run the full Node suite**

Run: `npx tsc --noEmit 2>&1 | grep -c "error TS"`
Expected: `7` (only the pre-existing `subprocess.ts`/`daytona.test.ts` errors; the thesis work adds none).

Run: `npm run test`
Expected: PASS (all vitest suites; `thesis.test.ts` present, `map-insights.test.ts` gone).

- [ ] **Step 7: Commit**

```bash
git add components/job/investment-thesis.tsx components/job/job-live-poller.tsx lib/job/types.ts
git commit -m "feat(web): render the investment thesis; remove dead signals path"
```

---

## Self-Review

**Spec coverage:**
- `ThesisPoint` + `result` type update (drop `signals`) → Task 1 Step 4 (add) + Task 2 Step 3 (remove `signals`/`RawSignal`). ✓
- Pure helpers `formatConfidence`/`formatGrounding`/`safeSourceHref` + tests → Task 1. ✓
- Grounding tones + confidence labels verbatim → Task 1 Step 3 + tests. ✓
- Layout: header badges → Bull|Bear grid → Key Risks; accents; "None provided" empty state → Task 2 Step 1. ✓
- Point renders claim+evidence+optional source link via `safeSourceHref`; null url → no link → Task 2 Step 1 `ThesisPointItem`. ✓
- Poller swap → Task 2 Step 2. ✓
- Delete `key-insights.tsx`/`map-insights.ts`/`map-insights.test.ts` + grep gate → Task 2 Steps 4–5. ✓
- `StockHeader`/`RawLLMResponse` untouched → not in any task. ✓
- Node-env pure-helper tests only, no React render → Task 1. ✓
- tsc "no NEW errors" + full suite → Task 1 Step 5 + Task 2 Step 6. ✓

**Placeholder scan:** No TBD/TODO; complete code in every code step. ✓

**Type consistency:** `ThesisPoint`, `formatConfidence`, `formatGrounding` (returns `{label, tone}`), `safeSourceHref`, and `GROUNDING_TONE` keys (`up`/`neutral`/`muted`) defined in Task 1 and consumed with matching shapes in Task 2's component. `result` field names (`confidence`, `grounding`, `bull_case`, `bear_case`, `key_risks`) match between the type (Task 1) and the component (Task 2). ✓
