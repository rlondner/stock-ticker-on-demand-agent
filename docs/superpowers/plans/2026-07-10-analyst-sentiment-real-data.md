# Analyst Sentiment Real Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded Analyst Sentiment panel with the real yfinance analyst-recommendation distribution, fetched by the agent, tracked as a snapshot metric, fed to the LLM prompt, and rendered (3 bars with consensus fallback).

**Architecture:** The agent fetches `Ticker.recommendations` (5-bucket counts), stores them on `Snapshot.analyst_distribution`, feeds them into the LLM prompt, and tracks the field in the completeness metrics. The frontend derives the panel via a pure `analystPanelModel` helper (tested) and renders it in a thin component.

**Tech Stack:** Python (pydantic, yfinance, opentelemetry) + Next.js/TypeScript. Tests: pytest (agent), vitest node-env pure-function tests (frontend).

## Global Constraints

- yfinance accessor: `Ticker.recommendations` → rows with keys `period, strongBuy, buy, hold, sell, strongSell`; the current distribution is the row where `period == "0m"` (verify against installed yfinance 1.5.1).
- `AnalystDistribution` fields (snake_case): `strong_buy, buy, hold, sell, strong_sell` (all `int`).
- Distribution fetch is best-effort and MUST NEVER raise or fail the snapshot; returns `None` on exception / missing frame / no `0m` row / all-zero.
- `analyst_distribution` is added to `_SNAPSHOT_KEY_FIELDS` (now 13 fields); `completeness` is out of 13 and `field_missing{field=analyst_distribution}` fires when absent.
- Panel renders 3 collapsed bars: **BUY** = `strong_buy + buy`, **HOLD** = `hold`, **SELL** = `sell + strong_sell`, each `pct = round(count / total * 100)`, `total` = sum of all five.
- Empty state → consensus fallback: formatted `analyst_recommendation` + `analyst_opinion_count` "N analysts"; if both absent → "Analyst data unavailable". The hardcoded quote is removed.
- Frontend logic lives in pure helpers (`lib/ui/analyst-sentiment.ts`) tested in node-env vitest (no React-render tests — matches the existing `tests/components/*` pattern).
- Agent tests use the venv: `agent/.venv/bin/python -m pytest ...`.

---

### Task 1: Agent — fetch + store + track the analyst distribution

**Files:**
- Modify: `agent/lib/finance.py`
- Modify: `agent/tests/test_finance.py`

**Interfaces:**
- Produces:
  - `class AnalystDistribution(BaseModel)` with `strong_buy, buy, hold, sell, strong_sell: int`.
  - `Snapshot.analyst_distribution: AnalystDistribution | None`.
  - `_fetch_recommendation_distribution(ticker_obj) -> AnalystDistribution | None`.

- [ ] **Step 1: Write the failing tests**

Add to `agent/tests/test_finance.py`:

```python
from unittest.mock import PropertyMock


def _fake_recs(records):
    m = MagicMock()
    m.to_dict.return_value = records
    return m


def test_fetch_recommendation_distribution_reads_0m_row():
    from lib import finance
    recs = _fake_recs([
        {"period": "0m", "strongBuy": 12, "buy": 8, "hold": 5, "sell": 1, "strongSell": 0},
        {"period": "-1m", "strongBuy": 10, "buy": 9, "hold": 6, "sell": 2, "strongSell": 1},
    ])
    t = MagicMock()
    t.recommendations = recs
    d = finance._fetch_recommendation_distribution(t)
    assert (d.strong_buy, d.buy, d.hold, d.sell, d.strong_sell) == (12, 8, 5, 1, 0)


def test_fetch_recommendation_distribution_none_when_no_0m_row():
    from lib import finance
    t = MagicMock()
    t.recommendations = _fake_recs([{"period": "-1m", "strongBuy": 1, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0}])
    assert finance._fetch_recommendation_distribution(t) is None


def test_fetch_recommendation_distribution_none_on_all_zero():
    from lib import finance
    t = MagicMock()
    t.recommendations = _fake_recs([{"period": "0m", "strongBuy": 0, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0}])
    assert finance._fetch_recommendation_distribution(t) is None


def test_fetch_recommendation_distribution_none_on_exception():
    from lib import finance
    t = MagicMock()
    type(t).recommendations = PropertyMock(side_effect=RuntimeError("boom"))
    assert finance._fetch_recommendation_distribution(t) is None


def test_fetch_snapshot_attaches_analyst_distribution():
    from lib import finance
    fake_ticker = MagicMock()
    fake_ticker.info = dict(_HAPPY_INFO)
    fake_ticker.recommendations = _fake_recs([
        {"period": "0m", "strongBuy": 12, "buy": 8, "hold": 5, "sell": 1, "strongSell": 0},
    ])
    with patch.object(finance, "yfinance") as yf:
        yf.Ticker.return_value = fake_ticker
        s = finance.fetch_snapshot("MDB")
    assert s.analyst_distribution is not None
    assert s.analyst_distribution.strong_buy == 12
    assert s.analyst_distribution.strong_sell == 0
```

Also, update the TWO existing metric tests to account for the new 13th field:

In `test_fetch_snapshot_emits_success_metrics`, add a recommendations mock so all 13 fields populate, and change the completeness expectation:

```python
def test_fetch_snapshot_emits_success_metrics(monkeypatch):
    from lib import finance
    calls = _spy_snapshot_metrics(monkeypatch)
    fake_ticker = MagicMock()
    fake_ticker.info = dict(_HAPPY_INFO)
    fake_ticker.recommendations = _fake_recs([
        {"period": "0m", "strongBuy": 12, "buy": 8, "hold": 5, "sell": 1, "strongSell": 0},
    ])
    with patch.object(finance, "yfinance") as yf:
        yf.Ticker.return_value = fake_ticker
        finance.fetch_snapshot("MDB")
    assert calls["fetch"] == [("success", "MDB")]
    assert calls["backfilled"] == []
    assert calls["field_missing"] == []
    assert calls["completeness"] == [13]
```

In `test_fetch_snapshot_emits_field_missing_and_completeness_for_partial`, the minimal ticker has no recommendations, so `analyst_distribution` is now also missing — update the expected set and completeness:

```python
    assert set(calls["field_missing"]) == {
        "industry", "close", "previous_close", "market_cap",
        "fifty_two_week_high", "fifty_two_week_low", "average_volume",
        "analyst_recommendation", "analyst_opinion_count", "business_summary",
        "analyst_distribution",
    }
    assert calls["completeness"] == [2]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd agent && .venv/bin/python -m pytest tests/test_finance.py -v`
Expected: FAIL — `AttributeError: module 'lib.finance' has no attribute '_fetch_recommendation_distribution'`, and the two updated metric tests fail on `analyst_distribution`/completeness.

- [ ] **Step 3: Add the `AnalystDistribution` model + `Snapshot` field + key-field entry**

In `agent/lib/finance.py`, add the `analyst_distribution` entry to `_SNAPSHOT_KEY_FIELDS` (append after `"business_summary"`):

```python
_SNAPSHOT_KEY_FIELDS = (
    "company_name", "sector", "industry", "close", "previous_close", "market_cap",
    "fifty_two_week_high", "fifty_two_week_low", "average_volume",
    "analyst_recommendation", "analyst_opinion_count", "business_summary",
    "analyst_distribution",
)
```

Add the submodel just above `class Snapshot`:

```python
class AnalystDistribution(BaseModel):
    strong_buy: int
    buy: int
    hold: int
    sell: int
    strong_sell: int
```

Add the field to `Snapshot` (after `business_summary`):

```python
    analyst_distribution: AnalystDistribution | None = None
```

- [ ] **Step 4: Add `_fetch_recommendation_distribution`**

Add this helper in `agent/lib/finance.py` (place it near `_backfill_from_history`):

```python
def _fetch_recommendation_distribution(ticker_obj) -> AnalystDistribution | None:
    """Best-effort current-month analyst distribution from yfinance's
    `recommendations` frame (period '0m'). Never raises; returns None on any
    failure, a missing/empty frame, no '0m' row, or an all-zero row."""
    try:
        df = ticker_obj.recommendations
        if df is None:
            return None
        row = None
        for rec in df.to_dict("records"):
            if str(rec.get("period")) == "0m":
                row = rec
                break
        if row is None:
            return None
        dist = AnalystDistribution(
            strong_buy=int(row.get("strongBuy") or 0),
            buy=int(row.get("buy") or 0),
            hold=int(row.get("hold") or 0),
            sell=int(row.get("sell") or 0),
            strong_sell=int(row.get("strongSell") or 0),
        )
        if (dist.strong_buy + dist.buy + dist.hold + dist.sell + dist.strong_sell) == 0:
            return None
        return dist
    except Exception:
        return None
```

- [ ] **Step 5: Wire it into `_fetch_snapshot_once`**

In `_fetch_snapshot_once`, right after `snap = _snapshot_from_info(info)`, add:

```python
    dist = _fetch_recommendation_distribution(t)
    if dist is not None:
        snap = snap.model_copy(update={"analyst_distribution": dist})
```

(Leave the existing backfill block below unchanged; the `(snap, backfilled)` return is unaffected.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd agent && .venv/bin/python -m pytest tests/test_finance.py -v`
Expected: PASS — new distribution tests + the two updated metric tests + all other existing finance tests.

- [ ] **Step 7: Commit**

```bash
git add agent/lib/finance.py agent/tests/test_finance.py
git commit -m "feat(agent): fetch + store + track the analyst recommendation distribution"
```

---

### Task 2: Agent — feed the distribution into the LLM prompt

**Files:**
- Modify: `agent/lib/prompts.py`
- Modify: `agent/tests/test_prompts.py`

**Interfaces:**
- Consumes: `Snapshot.analyst_distribution` (Task 1).

- [ ] **Step 1: Write the failing tests**

Add to `agent/tests/test_prompts.py`:

```python
from lib.finance import AnalystDistribution


def test_user_prompt_includes_analyst_ratings_when_distribution_present():
    dist = AnalystDistribution(strong_buy=12, buy=8, hold=5, sell=1, strong_sell=0)
    p = user_prompt("MDB", snapshot=_snap(analyst_distribution=dist))
    assert "Analyst ratings:" in p
    assert "12 strong buy" in p
    assert "8 buy" in p
    assert "5 hold" in p
    assert "1 sell" in p
    assert "0 strong sell" in p


def test_user_prompt_omits_analyst_ratings_when_no_distribution():
    p = user_prompt("MDB", snapshot=_snap(analyst_distribution=None))
    assert "Analyst ratings:" not in p
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd agent && .venv/bin/python -m pytest tests/test_prompts.py -k analyst_ratings -v`
Expected: FAIL — the "Analyst ratings:" line is not emitted yet.

- [ ] **Step 3: Emit the distribution line in `_format_facts`**

In `agent/lib/prompts.py`, in `_format_facts`, add after the `if snapshot.analyst_recommendation:` block (and before the `business_summary` block):

```python
    if snapshot.analyst_distribution:
        d = snapshot.analyst_distribution
        lines.append(
            f"- Analyst ratings: {d.strong_buy} strong buy, {d.buy} buy, "
            f"{d.hold} hold, {d.sell} sell, {d.strong_sell} strong sell"
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd agent && .venv/bin/python -m pytest tests/test_prompts.py -v`
Expected: PASS (new tests + existing prompt tests).

- [ ] **Step 5: Commit**

```bash
git add agent/lib/prompts.py agent/tests/test_prompts.py
git commit -m "feat(agent): feed analyst distribution into the LLM prompt facts"
```

---

### Task 3: Frontend — Snapshot type + pure panel helper

**Files:**
- Modify: `lib/job/types.ts`
- Create: `lib/ui/analyst-sentiment.ts`
- Create: `tests/components/analyst-sentiment.test.ts`

**Interfaces:**
- Produces:
  - `toAnalystBars(d) -> { bars: {label, pct}[]; total } | null`
  - `formatConsensus(rec: string | null) -> string | null`
  - `analystPanelModel(snapshot) -> AnalystPanel` (discriminated union `bars` | `consensus` | `unavailable`)

- [ ] **Step 1: Add `analyst_distribution` to the `Snapshot` type**

In `lib/job/types.ts`, add to the `Snapshot` type (after `business_summary`):

```typescript
  analyst_distribution: {
    strong_buy: number;
    buy: number;
    hold: number;
    sell: number;
    strong_sell: number;
  } | null;
```

- [ ] **Step 2: Write the failing tests**

Create `tests/components/analyst-sentiment.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { toAnalystBars, formatConsensus, analystPanelModel } from "@/lib/ui/analyst-sentiment";
import type { Snapshot } from "@/lib/job/types";

const DIST = { strong_buy: 12, buy: 8, hold: 5, sell: 1, strong_sell: 4 };

function snap(overrides: Partial<Snapshot>): Snapshot {
  return {
    company_name: null, sector: null, industry: null, close: null, previous_close: null,
    change_pct: null, market_cap: null, fifty_two_week_high: null, fifty_two_week_low: null,
    average_volume: null, analyst_recommendation: null, analyst_opinion_count: null,
    business_summary: null, analyst_distribution: null, currency: "USD", as_of: "x",
    ...overrides,
  };
}

describe("toAnalystBars", () => {
  it("collapses 5 buckets into 3 bars with percentages", () => {
    // buy=20, hold=5, sell=5, total=30 -> 67/17/17 (rounded)
    const r = toAnalystBars(DIST)!;
    expect(r.total).toBe(30);
    expect(r.bars).toEqual([
      { label: "BUY", pct: 67 },
      { label: "HOLD", pct: 17 },
      { label: "SELL", pct: 17 },
    ]);
  });

  it("returns null for null input or zero total", () => {
    expect(toAnalystBars(null)).toBeNull();
    expect(toAnalystBars({ strong_buy: 0, buy: 0, hold: 0, sell: 0, strong_sell: 0 })).toBeNull();
  });
});

describe("formatConsensus", () => {
  it("maps known keys and title-cases unknowns", () => {
    expect(formatConsensus("strong_buy")).toBe("Strong Buy");
    expect(formatConsensus("buy")).toBe("Buy");
    expect(formatConsensus("underperform")).toBe("Underperform");
    expect(formatConsensus(null)).toBeNull();
  });
});

describe("analystPanelModel", () => {
  it("returns bars when a distribution is present", () => {
    const m = analystPanelModel(snap({ analyst_distribution: DIST }));
    expect(m.kind).toBe("bars");
  });

  it("falls back to consensus when there is no distribution", () => {
    const m = analystPanelModel(snap({ analyst_recommendation: "buy", analyst_opinion_count: 34 }));
    expect(m).toEqual({ kind: "consensus", label: "Buy", count: 34 });
  });

  it("returns unavailable when nothing is present", () => {
    expect(analystPanelModel(snap({})).kind).toBe("unavailable");
    expect(analystPanelModel(null).kind).toBe("unavailable");
  });
});
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `npx vitest run tests/components/analyst-sentiment.test.ts`
Expected: FAIL — cannot resolve `@/lib/ui/analyst-sentiment`.

- [ ] **Step 4: Implement `lib/ui/analyst-sentiment.ts`**

Create `lib/ui/analyst-sentiment.ts`:

```typescript
import type { Snapshot } from "@/lib/job/types";

export type AnalystBar = { label: "BUY" | "HOLD" | "SELL"; pct: number };
type Distribution = NonNullable<Snapshot["analyst_distribution"]>;

export function toAnalystBars(d: Distribution | null): { bars: AnalystBar[]; total: number } | null {
  if (!d) return null;
  const buy = d.strong_buy + d.buy;
  const hold = d.hold;
  const sell = d.sell + d.strong_sell;
  const total = buy + hold + sell;
  if (total <= 0) return null;
  const pct = (n: number) => Math.round((n / total) * 100);
  return {
    total,
    bars: [
      { label: "BUY", pct: pct(buy) },
      { label: "HOLD", pct: pct(hold) },
      { label: "SELL", pct: pct(sell) },
    ],
  };
}

const CONSENSUS_LABELS: Record<string, string> = {
  strong_buy: "Strong Buy",
  buy: "Buy",
  outperform: "Outperform",
  hold: "Hold",
  neutral: "Hold",
  underperform: "Underperform",
  sell: "Sell",
  strong_sell: "Strong Sell",
};

export function formatConsensus(rec: string | null): string | null {
  if (!rec) return null;
  return (
    CONSENSUS_LABELS[rec] ??
    rec.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

export type AnalystPanel =
  | { kind: "bars"; bars: AnalystBar[]; total: number }
  | { kind: "consensus"; label: string; count: number | null }
  | { kind: "unavailable" };

export function analystPanelModel(snapshot: Snapshot | null): AnalystPanel {
  const bars = toAnalystBars(snapshot?.analyst_distribution ?? null);
  if (bars) return { kind: "bars", bars: bars.bars, total: bars.total };
  const label = formatConsensus(snapshot?.analyst_recommendation ?? null);
  if (label) return { kind: "consensus", label, count: snapshot?.analyst_opinion_count ?? null };
  return { kind: "unavailable" };
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `npx vitest run tests/components/analyst-sentiment.test.ts`
Expected: PASS (all cases).

- [ ] **Step 6: Commit**

```bash
git add lib/job/types.ts lib/ui/analyst-sentiment.ts tests/components/analyst-sentiment.test.ts
git commit -m "feat(web): add analyst_distribution type + pure analyst-panel helper"
```

---

### Task 4: Frontend — render the panel + wire the poller

**Files:**
- Modify: `components/job/analyst-sentiment.tsx`
- Modify: `components/job/job-live-poller.tsx`

**Interfaces:**
- Consumes: `analystPanelModel` (Task 3); `Snapshot` type (Task 3).

- [ ] **Step 1: Rewrite `analyst-sentiment.tsx` to render the real model**

Replace the entire contents of `components/job/analyst-sentiment.tsx` with:

```tsx
import type { Snapshot } from "@/lib/job/types";
import { analystPanelModel } from "@/lib/ui/analyst-sentiment";

const BAR_COLOR: Record<string, string> = {
  BUY: "bg-af-secondary",
  HOLD: "bg-af-signal-hold",
  SELL: "bg-af-error",
};
const BAR_TEXT: Record<string, string> = {
  BUY: "text-af-secondary",
  HOLD: "text-af-signal-hold",
  SELL: "text-af-error",
};

export function AnalystSentiment({ snapshot }: { snapshot: Snapshot | null }) {
  const model = analystPanelModel(snapshot);
  return (
    <div className="col-span-12 lg:col-span-4 bg-af-surface-container-lowest p-8 rounded-xl border border-af-outline-variant">
      <h4 className="text-2xl font-semibold text-af-on-surface mb-8">Analyst Sentiment</h4>

      {model.kind === "bars" && (
        <>
          <div className="space-y-6">
            {model.bars.map((b) => (
              <div key={b.label}>
                <div className={`flex justify-between text-[12px] mb-2 font-medium ${BAR_TEXT[b.label]}`}>
                  <span>{b.label} RECOMMENDATION</span>
                  <span>{b.pct}%</span>
                </div>
                <div className="w-full h-2 bg-af-surface-container-low rounded-full overflow-hidden">
                  <div className={`h-full ${BAR_COLOR[b.label]}`} style={{ width: `${b.pct}%` }} />
                </div>
              </div>
            ))}
          </div>
          <p className="mt-8 text-[12px] font-medium text-af-on-surface-variant">
            Based on {model.total} analyst {model.total === 1 ? "rating" : "ratings"}
          </p>
        </>
      )}

      {model.kind === "consensus" && (
        <div className="mt-2">
          <p className="text-3xl font-semibold text-af-on-surface">{model.label}</p>
          {model.count !== null && (
            <p className="text-[12px] font-medium text-af-on-surface-variant mt-2">
              Consensus across {model.count} {model.count === 1 ? "analyst" : "analysts"}
            </p>
          )}
        </div>
      )}

      {model.kind === "unavailable" && (
        <p className="text-sm text-af-on-surface-variant">Analyst data unavailable</p>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Pass the snapshot from the poller**

In `components/job/job-live-poller.tsx`, change the `<AnalystSentiment />` usage to:

```tsx
            <AnalystSentiment snapshot={job.result?.snapshot ?? null} />
```

- [ ] **Step 3: Type-check and run the full Node suite**

Run: `npx tsc --noEmit && npm run test`
Expected: no type errors; all vitest suites pass (including `analyst-sentiment.test.ts`).

- [ ] **Step 4: Run the full Python suite (sanity)**

Run: `cd agent && .venv/bin/python -m pytest -q`
Expected: PASS (all agent tests; DB tests skip without `NEON_DATABASE_URL`).

- [ ] **Step 5: Commit**

```bash
git add components/job/analyst-sentiment.tsx components/job/job-live-poller.tsx
git commit -m "feat(web): render real analyst sentiment with consensus fallback"
```

---

## Self-Review

**Spec coverage:**
- Fetch 5-bucket distribution (`Ticker.recommendations`, `0m` row), guarded/never-raises → Task 1 Step 4. ✓
- `AnalystDistribution` submodel + `Snapshot` field → Task 1 Step 3. ✓
- Attach in `_fetch_snapshot_once` without changing `(snap, backfilled)` → Task 1 Step 5. ✓
- Metric: `analyst_distribution` as 13th key field; completeness /13; field_missing when absent → Task 1 Step 3 + updated tests Step 1. ✓
- LLM prompt "Analyst ratings:" line → Task 2. ✓
- Frontend `Snapshot` type + pure `analystPanelModel`/`toAnalystBars`/`formatConsensus` → Task 3. ✓
- 3-bar collapse (BUY=strong_buy+buy, SELL=sell+strong_sell), % of total → Task 3 `toAnalystBars`. ✓
- Consensus fallback + "unavailable"; quote removed → Task 3 `analystPanelModel` + Task 4 component. ✓
- Poller passes snapshot → Task 4 Step 2. ✓
- Pure-helper tests in node-env vitest (no React render) → Task 3. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✓

**Type consistency:** `AnalystDistribution(strong_buy, buy, hold, sell, strong_sell: int)` defined Task 1, consumed by the prompt (Task 2) and mirrored by the TS `Snapshot.analyst_distribution` shape (Task 3). `analystPanelModel(snapshot) -> AnalystPanel` defined Task 3, consumed by the component (Task 4). `toAnalystBars` bar labels `"BUY"|"HOLD"|"SELL"` match the component's `BAR_COLOR`/`BAR_TEXT` keys. ✓
