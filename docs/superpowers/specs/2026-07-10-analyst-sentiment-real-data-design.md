# Design: Wire Analyst Sentiment panel to real yfinance data

**Date:** 2026-07-10
**Status:** Approved (design), pending implementation plan
**Scope:** Agent (`agent/`) + Next.js frontend. Replace the hardcoded
"Analyst Sentiment" panel with the real yfinance analyst-recommendation
distribution, fetched by the agent, fed to both the UI and the LLM prompt.

## Background

`components/job/analyst-sentiment.tsx` is currently rendered with **no props**
and is **entirely hardcoded**: static `62% / 31% / 7%` buy/hold/sell bars and a
canned "Tier 1 Investment Bank" quote. It ignores the real analyst data — even
though the agent already fetches `analyst_recommendation` (consensus label) and
`analyst_opinion_count`, and yfinance can supply the full per-bucket distribution.

yfinance 1.5.1 exposes `Ticker.recommendations` — a DataFrame with columns
`period, strongBuy, buy, hold, sell, strongSell`. The current-month distribution
is the row where `period == "0m"`. This is a **separate call** from the `.info`
dict the snapshot already reads.

## Decisions (from brainstorming)

- Fetch the real 5-bucket distribution and **store all 5 counts**.
- Render **3 bars**: Buy (`strong_buy + buy`) / Hold / Sell (`sell + strong_sell`),
  normalized to % of total — matching the current layout.
- **Remove** the hardcoded analyst quote (no data source).
- Empty state → **fall back to consensus**: show `analyst_recommendation` +
  "N analysts" if present; else "Analyst data unavailable".
- Track `analyst_distribution` as a snapshot-metric field (completeness → /13).
- **Feed the distribution into the LLM prompt** as an additional ground-truth fact.

## Data model — agent (`agent/lib/finance.py`)

- New Pydantic submodel:
  ```python
  class AnalystDistribution(BaseModel):
      strong_buy: int
      buy: int
      hold: int
      sell: int
      strong_sell: int
  ```
- `Snapshot` gains `analyst_distribution: AnalystDistribution | None = None`.
- New guarded helper `_fetch_recommendation_distribution(ticker_obj) -> AnalystDistribution | None`:
  reads `ticker_obj.recommendations`, selects the `period == "0m"` row, extracts the
  five counts as `int`. Returns `None` on any exception, empty/missing frame, or an
  all-zero row. **Never raises** (wrapped in try/except like `_backfill_from_history`).
- `_fetch_snapshot_once` calls it after `_snapshot_from_info(info)` and attaches the
  result via `model_copy(update={"analyst_distribution": dist})`. The `(snapshot,
  backfilled)` return shape is unchanged; distribution fetch failure does not affect
  `backfilled` and does not fail the snapshot.

## Metrics (extends the shipped snapshot metrics)

- Add `"analyst_distribution"` to `_SNAPSHOT_KEY_FIELDS` (now 13 fields). Effect:
  `agent.snapshot.field_missing{field=analyst_distribution}` fires when it is `None`,
  and `agent.snapshot.completeness` is measured out of 13.
- Update the metric tests: the fully-populated case expects `completeness == 13`; the
  partial case's expected `field_missing` set includes `analyst_distribution`.

## LLM prompt (`agent/lib/prompts.py`)

- In `_format_facts`, when `snapshot.analyst_distribution` is present, add a line
  after the existing "Analyst consensus" line:
  ```
  - Analyst ratings: {strong_buy} strong buy, {buy} buy, {hold} hold, {sell} sell, {strong_sell} strong sell
  ```
  The `SYSTEM_PROMPT` already instructs the model to treat facts as ground truth, so
  no system-prompt change is needed. This gives the model the distribution to reason
  over (it currently only sees the single consensus label).

## Frontend

- `lib/job/types.ts`: add `analyst_distribution` to the `Snapshot` type —
  `{ strong_buy: number; buy: number; hold: number; sell: number; strong_sell: number } | null`.
- New pure helper `lib/ui/analyst-sentiment.ts` (mirrors `lib/ui/format-price.ts` etc.):
  `toAnalystBars(distribution)` → returns `{ bars: {label, pct}[]; total: number } | null`.
  Collapses to 3 buckets (Buy = strong_buy+buy, Hold, Sell = sell+strong_sell),
  computes each `pct = round(count / total * 100)`, `total` = sum of all five counts.
  Returns `null` when the distribution is absent or `total == 0`.
- `components/job/analyst-sentiment.tsx`: change signature to accept a `snapshot`
  prop and render:
  - `toAnalystBars(snapshot.analyst_distribution)` non-null → the 3 real bars + "N analysts";
  - else → consensus fallback: `analyst_recommendation` (formatted for display, e.g.
    `strong_buy` → "Strong Buy") + `analyst_opinion_count` "N analysts"; if both absent
    → "Analyst data unavailable".
  - Remove the hardcoded `ROWS` and the quote block.
- `components/job/job-live-poller.tsx`: pass
  `snapshot={job.result?.snapshot ?? null}` to `<AnalystSentiment>`.

Existing plumbing (`snapshot.model_dump()` → `result` jsonb → status API →
`SerializedJob.result.snapshot`) carries the new field with no changes.

## Error handling

- Distribution fetch is best-effort and guarded; a failure leaves
  `analyst_distribution = None`, the panel falls back to consensus, and the snapshot /
  price flow is unaffected.
- `toAnalystBars` guards `total == 0` (division) and a `null` distribution, returning
  `null` so the component takes the fallback path.

## Testing (TDD)

- **Agent** (`agent/tests/test_finance.py`): `_fetch_recommendation_distribution` with a
  mocked `recommendations` DataFrame containing a `0m` row → the five counts; empty
  frame / missing `0m` / exception / all-zero → `None`; `fetch_snapshot` attaches the
  distribution onto the returned `Snapshot`.
- **Metrics** (`agent/tests/test_finance.py` / `test_metrics.py`): completeness counts
  out of 13; a snapshot lacking the distribution emits
  `field_missing(field="analyst_distribution")`.
- **Prompt** (`agent/tests/test_prompts.py`): a snapshot with a distribution renders the
  "Analyst ratings:" line; without one, the line is absent.
- **Frontend**: `toAnalystBars` unit tests (5 counts → 3 bars + %, total, zero-total →
  null, null input → null); a vitest component test asserting the bars render with a
  distribution and the consensus fallback renders without.

## Out of scope

- No change to the 3-bar visual layout (same design, real data).
- No new fetch beyond `Ticker.recommendations`; no historical (`-1m`/`-2m`) periods —
  only the current `0m` distribution.

## Risks

- yfinance's `recommendations` shape has changed across versions; the helper is written
  against 1.5.1's `period/strongBuy/buy/hold/sell/strongSell` columns and is fully
  guarded, so a future shape change degrades to the consensus fallback rather than
  breaking the fetch. The plan verifies the accessor against the installed version.
- Adding a 13th key field shifts `completeness` denominators in any existing dashboard;
  documented in the metric change.
