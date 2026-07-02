import { StatusPill } from "@/components/ui/status-pill";
import { SignalPill } from "@/components/ui/signal-pill";
import type { JobStatus } from "@/lib/ui/status-pill";
import type { Recommendation } from "@/lib/ui/signal-pill";
import type { Snapshot } from "@/lib/job/types";
import { formatPrice, formatChangePct } from "@/lib/ui/format-price";

type Props = {
  ticker: string;
  status: JobStatus;
  recommendation: Recommendation | null;
  summary: string | null;
  snapshot: Snapshot | null;
};

const TONE_CLASS = {
  up: "text-af-secondary",
  down: "text-af-error",
  neutral: "text-af-on-surface-variant",
} as const;

export function StockHeader({ ticker, status, recommendation, summary, snapshot }: Props) {
  const displayName = snapshot?.company_name ?? ticker;
  const currency = snapshot?.currency ?? "USD";
  const priceText = formatPrice(snapshot?.close ?? null, currency);
  const change = formatChangePct(snapshot?.change_pct ?? null);

  return (
    <section className="flex flex-col md:flex-row md:items-end justify-between gap-6 bg-af-surface-container-lowest p-8 rounded-xl border border-af-outline-variant">
      <div className="space-y-2">
        <div className="flex items-center gap-4">
          <h2 className="text-5xl font-bold text-af-on-surface tracking-tight">{ticker}</h2>
          <StatusPill status={status} />
          <SignalPill recommendation={recommendation} />
        </div>
        <div>
          <h3 className="text-2xl font-semibold text-af-on-surface">{displayName}</h3>
          {summary && (
            <p className="text-af-on-surface-variant text-base max-w-2xl mt-4">{summary}</p>
          )}
        </div>
      </div>
      <div className="flex flex-col items-end gap-2">
        <div className="text-right">
          <p className="text-[12px] text-af-on-surface-variant uppercase tracking-wider">Current Price</p>
          <p className="text-3xl font-semibold text-af-on-surface">
            {priceText}{" "}
            <span className={`text-sm font-medium ${TONE_CLASS[change.tone]}`}>{change.text}</span>
          </p>
        </div>
      </div>
    </section>
  );
}
