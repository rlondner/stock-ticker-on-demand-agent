"use client";

const SUGGESTED = [
  { ticker: "NVDA", icon: "trending_up" },
  { ticker: "AAPL", icon: "trending_up" },
  { ticker: "MSFT", icon: "trending_up" },
  { ticker: "TSLA", icon: "history" },
  { ticker: "AMD", icon: "history" },
] as const;

export function SuggestedTickers({ onPick }: { onPick: (ticker: string) => void }) {
  return (
    <div className="space-y-2">
      <p className="text-[12px] text-af-on-surface-variant">Suggested Tickers</p>
      <div className="flex flex-wrap gap-2">
        {SUGGESTED.map((s) => (
          <button
            key={s.ticker}
            type="button"
            onClick={() => onPick(s.ticker)}
            className="px-4 py-1 border border-af-outline-variant rounded-full text-sm font-semibold text-af-on-surface-variant transition-all flex items-center gap-1 hover:border-af-on-surface hover:bg-af-surface-container-low"
          >
            <span className="material-symbols-outlined text-[16px]">{s.icon}</span>
            {s.ticker}
          </button>
        ))}
      </div>
    </div>
  );
}
