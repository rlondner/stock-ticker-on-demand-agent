export function MarketRiskCard() {
  return (
    <div className="bg-af-surface-container-lowest border border-af-outline-variant rounded-xl p-6 flex flex-col">
      <div className="flex justify-between items-center mb-4">
        <h4 className="text-sm font-semibold text-af-on-surface">Market Risk</h4>
        <span className="material-symbols-outlined text-af-error">warning</span>
      </div>
      <p className="text-sm text-af-on-surface-variant mb-4">
        Exposure to geopolitical tensions in energy sectors has increased significantly this morning.
      </p>
      <button
        type="button"
        className="mt-auto text-af-on-surface font-semibold text-sm flex items-center gap-1 hover:gap-2 transition-all"
      >
        View Report <span className="material-symbols-outlined text-sm">arrow_forward</span>
      </button>
    </div>
  );
}
