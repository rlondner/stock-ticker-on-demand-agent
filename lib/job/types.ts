import type { JobStatus } from "@/lib/ui/status-pill";
import type { Recommendation } from "@/lib/ui/signal-pill";
import type { NotifyChannel } from "@/lib/db/schema";

export type ThesisPoint = { claim: string; evidence: string; source_url: string | null };

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
  // "strong_buy", "strong_sell", "underperform", "outperform". Kept as
  // `string | null` so we don't churn this union when Yahoo adds a bucket.
  analyst_recommendation: string | null;
  analyst_opinion_count: number | null;
  business_summary: string | null;
  analyst_distribution: {
    strong_buy: number;
    buy: number;
    hold: number;
    sell: number;
    strong_sell: number;
  } | null;
  currency: string;
  as_of: string;
};

export type SerializedJob = {
  id: string;
  ticker: string;
  status: JobStatus;
  recommendation: Recommendation | null;
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
  error: string | null;
  sandboxId: string | null;
  createdAt: string; // ISO
  startedAt: string | null; // ISO
  completedAt: string | null; // ISO
  notifyChannel: NotifyChannel | null;
  notifyDestination: string | null;
  notifiedAt: string | null; // ISO
};
