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

  it("formats neutral as Neutral", () => {
    expect(formatConsensus("neutral")).toBe("Neutral");
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
