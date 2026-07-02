type Row = { label: string; pct: number; color: string; textColor: string };

const ROWS: Row[] = [
  { label: "BUY RECOMMENDATION", pct: 62, color: "bg-af-secondary", textColor: "text-af-secondary" },
  { label: "HOLD RECOMMENDATION", pct: 31, color: "bg-af-signal-hold", textColor: "text-af-signal-hold" },
  { label: "SELL RECOMMENDATION", pct: 7, color: "bg-af-error", textColor: "text-af-error" },
];

export function AnalystSentiment() {
  return (
    <div className="col-span-12 lg:col-span-4 bg-af-surface-container-lowest p-8 rounded-xl border border-af-outline-variant">
      <h4 className="text-2xl font-semibold text-af-on-surface mb-8">Analyst Sentiment</h4>
      <div className="space-y-6">
        {ROWS.map((r) => (
          <div key={r.label}>
            <div className={`flex justify-between text-[12px] mb-2 font-medium ${r.textColor}`}>
              <span>{r.label}</span>
              <span>{r.pct}%</span>
            </div>
            <div className="w-full h-2 bg-af-surface-container-low rounded-full overflow-hidden">
              <div className={`h-full ${r.color}`} style={{ width: `${r.pct}%` }} />
            </div>
          </div>
        ))}
      </div>
      <div className="mt-8 p-4 bg-af-surface-container-low rounded-lg">
        <p className="text-sm italic text-af-on-surface">
          &ldquo;The expansion of Atlas into multi-cloud environments provides a unique moat that hyperscalers struggle to replicate.&rdquo;
        </p>
        <p className="text-[12px] font-medium text-af-on-surface-variant mt-2">— Tier 1 Investment Bank</p>
      </div>
    </div>
  );
}
