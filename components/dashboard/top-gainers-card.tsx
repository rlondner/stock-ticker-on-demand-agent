const GAINERS = [
  { ticker: "TSLA", pct: "+12.4%" },
  { ticker: "NVDA", pct: "+8.2%" },
  { ticker: "PLTR", pct: "+7.1%" },
];

export function TopGainersCard() {
  return (
    <div className="bg-af-surface-container-lowest border border-af-outline-variant rounded-xl p-6 flex flex-col">
      <div className="flex justify-between items-center mb-4">
        <h4 className="text-sm font-semibold text-af-on-surface">Top Gainers</h4>
        <span className="material-symbols-outlined text-af-secondary">trending_up</span>
      </div>
      <div className="space-y-2">
        {GAINERS.map((g) => (
          <div key={g.ticker} className="flex justify-between items-center text-sm">
            <span className="font-bold">{g.ticker}</span>
            <span className="text-af-secondary font-medium">{g.pct}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
