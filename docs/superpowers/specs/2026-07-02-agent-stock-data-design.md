# Agent stock-data enrichment — design

**Date:** 2026-07-02
**Related:** [2026-06-22 Daytona stock agent](./2026-06-22-daytona-stock-agent-design.md), [2026-07-02 UX refactor](./2026-07-02-ux-refactor-design.md)

## Problem

The Done page mockup (`designs/analysis_done.html`) shows the ticker, the **company name** (`MongoDB, Inc.`), the **latest close price** (`$342.15`), the **change vs previous close** (`-1.24%`), and a company-specific summary. The current `StockHeader` hardcodes the price and change (per spec-D10) and echoes the ticker in the H3 slot because "no company-name lookup" exists.

We can't close that gap by giving the LLM a `web_search` tool: the current model in this environment is **Gemma-family (no reliable web search or tool-use)**, called through the OpenAI-compatible chat.completions path (`OPENAI_USE_RESPONSES_API=false`). Any dynamic ticker data has to come from a deterministic source before the LLM runs.

## Non-goals

- Making the Home dashboard cards (`Welcome`, `AiSentimentCard`, `TopGainersCard`, `MarketRiskCard`) dynamic. They're market-level, not per-ticker.
- Making the Done-page `AnalystSentiment` bento card dynamic. yfinance exposes `recommendationKey` (one string) and `numberOfAnalystOpinions` (one int), which don't cleanly map to the design's `BUY 62% / HOLD 31% / SELL 7%` split. Left for follow-up.
- Making the Done-page `RevenueDistribution` card dynamic. Company-specific segmentation isn't in yfinance's free surface.
- Backfilling snapshots into `jobs.result` for jobs that completed before this change. StockHeader's null-guards make old jobs continue to render correctly.
- Adding a second refresh path in Next.js. Snapshot is captured once, at analysis time, and frozen with the job.

## Architecture

```
┌───────────────────┐   fetch_snapshot(ticker)   ┌────────────────┐
│  agent/agent.py   │ ──────────────────────────▶│ agent/lib/     │
│  (unchanged flow) │◀───────────Snapshot────────│   finance.py   │
└─────────┬─────────┘                            └────────────────┘
          │                                              │
          │ run_analysis(ticker)                         │ yfinance.Ticker(...)
          ▼                                              ▼
┌───────────────────┐   snapshot in user prompt  ┌────────────────┐
│ agent/lib/llm.py  │ ──────────────────────────▶│ OpenAI-compat  │
│                   │◀────────── JSON ────────── │ (Gemma via     │
└─────────┬─────────┘                            │  chat compls)  │
          │                                      └────────────────┘
          │ result = {...llm, snapshot}
          ▼
┌───────────────────┐   jobs.result JSONB
│  Neon Postgres    │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐   SerializedJob.result.snapshot
│  Next.js Done     │  StockHeader renders company name,
│  page + poller    │  close, change_pct, currency.
└───────────────────┘
```

## Snapshot data shape

One pydantic model in `agent/lib/finance.py`, mirrored one-for-one in `lib/job/types.ts`.

```python
class Snapshot(BaseModel):
    company_name: str | None                     # yfinance info['longName']
    sector: str | None                           # info['sector']
    industry: str | None                         # info['industry']
    close: float | None                          # info['regularMarketPrice'] or last row of history
    previous_close: float | None                 # info['regularMarketPreviousClose']
    change_pct: float | None                     # derived: (close - prev) / prev * 100, rounded 2dp
    market_cap: int | None                       # info['marketCap']
    fifty_two_week_high: float | None            # info['fiftyTwoWeekHigh']
    fifty_two_week_low: float | None             # info['fiftyTwoWeekLow']
    average_volume: int | None                   # info['averageVolume']
    analyst_recommendation: str | None           # info['recommendationKey'], normalized to lowercase
    analyst_opinion_count: int | None            # info['numberOfAnalystOpinions']
    business_summary: str | None                 # info['longBusinessSummary'] — LLM context only
    currency: str                                # info['currency'] or 'USD'
    as_of: str                                   # ISO timestamp of fetch (UTC)
```

Every scalar is nullable except `currency` and `as_of`. `change_pct` is `None` if either `close` or `previous_close` is missing.

## `agent/lib/finance.py`

- Single public function: `fetch_snapshot(ticker: str) -> Snapshot | None`.
- Uses `yfinance.Ticker(ticker)` for both `info` and (if `regularMarketPrice` is absent) `history(period="5d")` to backfill close/previous_close from the OHLCV frame.
- Wrapped in `tenacity.retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4), retry=retry_if_exception_type(Exception))`. Any exception is caught, retried, and on final failure the function returns `None` (does not raise).
- Emits one `snapshot.fetched` log with the compact snapshot on success, or one `snapshot.missing` log with `reason` (`"empty_info"` / `"exception"`) and the exception type on failure. Log payloads never include `business_summary` (too long).
- Adds span attributes on the current OTEL span (whichever the caller sits inside): `snapshot.fetched: bool`, `snapshot.ticker: str`, plus (on success) `snapshot.close: float | None`, `snapshot.change_pct: float | None`. Never puts `business_summary` on the span.

## `agent/lib/prompts.py` rewrite

**New `SYSTEM_PROMPT`:**

```
You are a financial analysis assistant. You will receive a single
US-listed stock ticker and a compact set of facts about the company.
Use those facts as ground truth: do not invent prices, company names,
market caps, or other numbers.

Output ONLY a JSON object matching this schema:

{
  "recommendation": "buy" | "hold" | "sell",
  "summary": "<2-3 sentence plain-English take that references the
              company name and, if available, the price move>",
  "signals": [
    {"label": "<short label>",
     "evidence": "<one sentence>",
     "source": "<URL or null>"}
  ]
}

Provide 3 to 5 signals. Set "source" to null when you cannot cite a
specific URL (you do not have web access). Do not include markdown,
commentary, or preamble around the JSON. This is not financial advice
and the output will be shown to the user with a demo disclaimer.
```

**New `user_prompt(ticker: str, snapshot: Snapshot | None) -> str`:**

- If `snapshot is None`:
  ```
  Ticker: MDB
  (No live facts available for this ticker. Base your take on general
   knowledge and be explicit that some data is unavailable.)
  Task: Output JSON only.
  ```
- If `snapshot` is provided, format each present field as a bullet under a `Facts:` block. `None` fields are omitted (not shown as "N/A"). `business_summary` is truncated to ~800 chars if it exceeds that.

## `agent/lib/llm.py` — `run_analysis`

```python
def run_analysis(ticker: str) -> dict:
    snapshot = fetch_snapshot(ticker)      # None on best-effort failure
    client: LLMClient = OpenAIClient()
    analysis = client.analyze(ticker, snapshot=snapshot)
    return {
        **analysis.model_dump(),
        "snapshot": snapshot.model_dump() if snapshot else None,
    }
```

`OpenAIClient.analyze` gains one keyword arg (`snapshot: Snapshot | None = None`) and passes it through to `user_prompt`. The retry decorator, empty-response handling, and observability instrumentation are unchanged.

`agent/agent.py` needs no code changes: `run_analysis` already returns a dict that `mark_complete` persists straight into `jobs.result` as JSONB.

## Failure handling (contract)

| Failure                             | Behavior                                                                                         |
| ----------------------------------- | ------------------------------------------------------------------------------------------------ |
| Invalid / delisted ticker           | `fetch_snapshot` returns `None`. LLM runs with the "no facts" user prompt. Job completes.        |
| yfinance network / 5xx              | Retried 3× with backoff. Final failure → `None`. LLM runs. Job completes.                        |
| yfinance returns partial `info`     | Snapshot returned with the missing scalars set to `None`. `change_pct` is `None` if either close is missing. |
| LLM error (unchanged)               | Existing tenacity + `EmptyLLMResponseError` handling in `llm.py`.                                |
| Both snapshot and LLM fail          | Existing agent flow marks the job as `failed`. Only the LLM failure branch can produce this.     |

## Persisted schema

`jobs.result` (already `jsonb`) gains an optional top-level `snapshot` object matching the Snapshot shape above. Existing rows have `undefined` there; StockHeader's null-guards render them the same as `null`.

No migration needed.

## Frontend consumption

**`lib/job/types.ts`:**

```ts
export type Snapshot = {
  company_name: string | null;
  sector: string | null;
  industry: string | null;
  close: number | null;
  previous_close: number | null;
  change_pct: number | null;
  market_cap: number | null;
  fifty_two_week_high: number | null;
  fifty_two_week_low: number | null;
  average_volume: number | null;
  // yfinance returns lowercased strings like "buy", "hold", "sell",
  // "strong_buy", "strong_sell", "underperform", "outperform".
  // Kept as `string | null` so we don't have to churn this union when
  // Yahoo adds a new bucket.
  analyst_recommendation: string | null;
  analyst_opinion_count: number | null;
  business_summary: string | null;
  currency: string;
  as_of: string;
};

export type SerializedJob = {
  // ... existing fields ...
  result: {
    summary?: string;
    signals?: RawSignal[];
    snapshot?: Snapshot | null;
  } | null;
};
```

**`app/(app)/jobs/[id]/page.tsx`:** reads `row.result?.snapshot ?? null` and threads it through `SerializedJob` into `JobLivePoller`. No new server function.

**`components/job/job-live-poller.tsx`:** forwards `snapshot` from `initialJob.result.snapshot` on first render, and from each polled response afterward.

**`components/job/stock-header.tsx`:** targeted rewrite. Deletes the Spec-D10 hardcoded `$342.15 / -1.24%` and the ticker-echoed H3.

- `<h2>` — still the ticker.
- `<h3>` — `snapshot?.company_name ?? ticker`.
- Summary `<p>` — unchanged (from `result.summary`).
- Right block "CURRENT PRICE" — `formatPrice(snapshot?.close ?? null, snapshot?.currency ?? "USD")`; change `%` uses `formatChangePct(snapshot?.change_pct ?? null)`. Class is `text-af-error` when the number is negative, `text-af-secondary` when positive, `text-af-on-surface-variant` when null.

**`lib/ui/format-price.ts` — new file, two pure functions:**

- `formatPrice(n: number | null, currency: string): string` — `null` → `"—"`. Otherwise `new Intl.NumberFormat("en-US", { style: "currency", currency }).format(n)`.
- `formatChangePct(n: number | null): { text: string; tone: "up" | "down" | "neutral" }` — `null` → `{ text: "—", tone: "neutral" }`. Otherwise `{ text: "${n >= 0 ? "+" : ""}${n.toFixed(2)}%", tone: n < 0 ? "down" : "up" }`.

Untouched: `Welcome`, `AiSentimentCard`, `TopGainersCard`, `MarketRiskCard`, `RecentActivity` on Home. `KeyInsights`, `RevenueDistribution`, `AnalystSentiment` on Done.

## Observability

- New span attributes on `agent.run` (via finance.py setting them on the current span):
  - `snapshot.fetched: bool`
  - `snapshot.ticker: str`
  - `snapshot.close: float` (only when present)
  - `snapshot.change_pct: float` (only when present)
- New structured logs:
  - `snapshot.fetched` — `ticker`, `company_name`, `close`, `previous_close`, `change_pct`, `currency`. No `business_summary`.
  - `snapshot.missing` — `ticker`, `reason` (`"empty_info"` or `"exception"`), `exception_type` when applicable.
- Existing `llm.*` metrics and logs unchanged.

## Testing

**Python — new files under `agent/tests/`:**

- `test_finance.py`:
  1. Happy path — mock `yfinance.Ticker` returning a filled `info` dict + 5-day history frame; assert every Snapshot field, including 2dp `change_pct` derivation.
  2. Partial data — `regularMarketPrice` missing but `history` populated → `close` filled from history, `change_pct` derived correctly.
  3. Network failure — mock raises on every attempt → `fetch_snapshot` returns `None`, `snapshot.missing` log emitted once.
  4. Delisted ticker — `info` returns the tell-tale minimal payload Yahoo uses for unknowns → `fetch_snapshot` returns `None`.

- `test_prompts.py`:
  1. `user_prompt("MDB", snapshot=<full>)` → contains `"MongoDB, Inc."`, `"$342.15"`, `"-1.24%"`, `"Technology"`; `business_summary` is truncated at ~800 chars.
  2. `user_prompt("MDB", snapshot=None)` → mentions ticker only, no numbers, contains the "no live facts" phrasing.

**Python — extend existing `test_agent.py`:**

- Extend the end-to-end test to inject a stub `fetch_snapshot` that returns a filled Snapshot; assert `result["snapshot"]["company_name"] == "MongoDB, Inc."`. Second variant: stub returns `None`; assert `result["snapshot"] is None` and the job still marks `complete`.

**Python — extend `test_observability.py`:**

- One new test asserting `snapshot.fetched=True` + `snapshot.close` + `snapshot.change_pct` span attributes on success, and `snapshot.missing` log event on failure.

**TypeScript — new files under `tests/components/`:**

- `format-price.test.ts` — `formatPrice(342.15, "USD")` → `"$342.15"`; `formatPrice(null, "USD")` → `"—"`; `formatChangePct(-1.24)` → `{ text: "-1.24%", tone: "down" }`; `formatChangePct(2.4)` → `{ text: "+2.40%", tone: "up" }`; `formatChangePct(null)` → `{ text: "—", tone: "neutral" }`.
- `stock-header.test.tsx` — snapshot present: company name in H3, price + change render, negative % has `text-af-error`. Snapshot null: ticker echoed in H3, price/change render as `—` with neutral class.

## Dependencies

- **Python:** add `yfinance>=0.2.40` to `agent/requirements.txt`. Pulls in `pandas`, `numpy`, `beautifulsoup4`, `requests` transitively — all already common on the sandbox image; verify sandbox startup cost is still acceptable when the plan runs.
- **TypeScript:** none.
- **DB migration:** none — `jobs.result` is `jsonb`.

## Rollout order (for the implementation plan)

1. Add `yfinance` dep, `agent/lib/finance.py`, `test_finance.py`. Ship independently, verify sandbox still boots.
2. Rewrite `prompts.py`, extend `llm.py`, add `test_prompts.py`, extend `test_agent.py` + `test_observability.py`.
3. Update `lib/job/types.ts`, add `lib/ui/format-price.ts` + tests, rewrite `components/job/stock-header.tsx` + tests, thread `snapshot` through `JobLivePoller` and the job page.
4. Manual end-to-end sanity check: fresh analysis via `/analyze` for a known ticker (e.g. `AAPL`) → Done page shows real company name, real close, real `%` — matching the design mockup.

## Open questions

None gating implementation. Follow-up work explicitly flagged as out of scope:

- Making `AnalystSentiment` card dynamic — needs a derivation strategy from yfinance's single-string `recommendationKey` (or a second data source).
- Refreshing the header price on view instead of freezing at analysis time.
- Backfilling snapshots into existing completed jobs.
