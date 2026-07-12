# Design: Render the investment thesis (sub-project 3 of the LLM re-architecture)

**Date:** 2026-07-12
**Status:** Approved (design), pending implementation plan
**Scope:** Next.js frontend only. Render the cited bull/bear `Thesis` the agent
now produces, replacing the empty `KeyInsights` panel and closing the interim
gap left by sub-project 1.

## Background

Sub-project 1 switched the agent's LLM step from a flat `Analysis` (with
`signals`) to a cited `Thesis` (`recommendation`, `confidence`, `summary`,
`bull_case`, `bear_case`, `key_risks`, `grounding`). The frontend was left
unchanged, so:

- `lib/job/types.ts`'s `SerializedJob.result` still declares the stale
  `{ summary?, signals?, snapshot? }` shape.
- `components/job/key-insights.tsx` reads `result.signals` (now absent) and
  renders empty.

This sub-project updates the frontend types and rendering to show the thesis.
No agent/backend changes (that shipped in sub-project 1); no metrics
(sub-project 4).

## Data (already produced by the agent)

`result` is `thesis.model_dump()` + `snapshot`:
`{ recommendation, confidence, summary, bull_case: ThesisPoint[],
bear_case: ThesisPoint[], key_risks: ThesisPoint[], grounding, snapshot }`
where `ThesisPoint = { claim, evidence, source_url }` (`source_url` is a real
URL for web-researched claims, `null` for snapshot-grounded ones), `confidence`
∈ `low|medium|high`, `grounding` ∈ `researched|limited|snapshot_only`.

## Layout (on job `complete`)

Replace the `KeyInsights` panel with an **Investment Thesis** block:

1. **Header row:** "Investment Thesis" heading + a **Confidence** badge
   (Low/Medium/High) + a **grounding** badge, colour-toned:
   - `researched` → "Web-researched" (positive/green tone)
   - `limited` → "Limited research" (amber/hold tone)
   - `snapshot_only` → "Snapshot only" (muted/neutral tone)
2. **Bull | Bear:** two side-by-side columns — bull green-toned, bear red-toned —
   each a list of points.
3. **Key Risks:** a full-width amber-toned section below.

Each **point** renders `claim` (bold) + `evidence`, and a "Source ↗" link when
`source_url` is a valid http(s) URL (reusing the existing card/source-link
pattern). Snapshot-grounded points (`source_url` null) render no link. An empty
section renders a muted "None provided."

`StockHeader` (ticker/price/recommendation/summary) and `RawLLMResponse` are
unchanged. The recommendation badge continues to come from the top-level
`SerializedJob.recommendation` column.

## Components & helpers (repo convention: pure helpers + thin components)

### `lib/job/types.ts`
- Add `export type ThesisPoint = { claim: string; evidence: string; source_url: string | null };`
- Update `SerializedJob.result` to:
  ```ts
  result: {
    recommendation?: Recommendation;
    confidence?: string;
    summary?: string;
    bull_case?: ThesisPoint[];
    bear_case?: ThesisPoint[];
    key_risks?: ThesisPoint[];
    grounding?: string;
    snapshot?: Snapshot | null;
  } | null;
  ```
- Drop the now-stale `import type { RawSignal } from "@/lib/job/map-insights"`.

### `lib/ui/thesis.ts` (new, pure, unit-tested)
- `formatConfidence(c: string | null): string | null` — `low|medium|high` →
  "Low"/"Medium"/"High"; unknown/null → null.
- `formatGrounding(g: string | null): { label: string; tone: "up"|"neutral"|"muted" } | null`
  — `researched` → `{ "Web-researched", "up" }`; `limited` →
  `{ "Limited research", "neutral" }`; `snapshot_only` → `{ "Snapshot only",
  "muted" }`; unknown/null → null.
- `safeSourceHref(url: string | null): string | null` — returns the URL only for
  `http:`/`https:`, else null (mirrors the existing `parseHttpUrl` in
  `map-insights.ts`, which is being removed).

### `components/job/investment-thesis.tsx` (new, thin)
- Props: `{ result: SerializedJob["result"]; lastUpdatedLabel: string }`.
- Renders the header row (confidence + grounding badges via the helpers), the
  Bull | Bear two-column grid, and the Key Risks section. A small internal
  `ThesisSection`/point renderer maps each `ThesisPoint` to claim + evidence +
  optional source link. All formatting/tone decisions come from
  `lib/ui/thesis.ts`; the component contains no parsing/mapping logic.
- Tone tokens reuse existing design tokens (`af-secondary` for bull, `af-error`
  for bear, `af-signal-hold`/amber for risks), consistent with the codebase.

### `components/job/job-live-poller.tsx`
- Replace `<KeyInsights signals={job.result?.signals ?? null} lastUpdatedLabel={lastUpdatedLabel} />`
  with `<InvestmentThesis result={job.result ?? null} lastUpdatedLabel={lastUpdatedLabel} />`
  and update the import.

## Cleanup (dead after the Thesis switch)

- Delete `components/job/key-insights.tsx`.
- Delete `lib/job/map-insights.ts` and `tests/components/map-insights.test.ts`
  (the `signals`/`RawSignal`/`mapSignalsToInsights` path no longer exists).
- Confirm no remaining imports of `map-insights`, `KeyInsights`, `RawSignal`, or
  `mapSignalsToInsights` (grep gate in the plan).

## Error / edge handling

- `result` null or missing thesis arrays → sections render "None provided"; the
  block never throws. `StockHeader`/`RawLLMResponse` still render.
- Non-http/malformed `source_url` → no link (via `safeSourceHref`).
- Older jobs whose `result` lacks thesis fields degrade to the "None provided"
  sections (the raw dump still shows whatever is stored).

## Testing (node-env vitest, no React render — matches `tests/components/*`)

`tests/components/thesis.test.ts` covering the pure helpers:
- `formatConfidence`: each of low/medium/high → title-case; null/unknown → null.
- `formatGrounding`: each of the three levels → correct `{ label, tone }`;
  null/unknown → null.
- `safeSourceHref`: an https URL passes through; an `ftp:`/`javascript:`/empty/
  null value → null.

Component wiring is verified by `npx tsc --noEmit` (no new type errors) and the
full `npm run test` suite (which must stay green after the `map-insights` test is
removed).

## Out of scope

- Any agent/schema/backend change (shipped in sub-project 1).
- Per-tool / loop metrics (sub-project 4).
- No new React-render test harness (the repo tests pure logic, not rendered
  components).

## Risks

- The pre-existing 7 `tsc` errors in `lib/runtime/subprocess.ts` +
  `tests/daytona.test.ts` are unrelated; the plan asserts "no NEW type errors,"
  not zero.
