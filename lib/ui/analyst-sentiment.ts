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
