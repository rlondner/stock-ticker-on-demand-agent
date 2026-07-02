export function Welcome() {
  return (
    <section className="col-span-12 mb-8">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <p className="text-sm font-semibold text-af-on-surface-variant uppercase tracking-widest mb-1">
            Equity Research Terminal
          </p>
          <h2 className="text-5xl font-bold text-af-on-surface tracking-tight">Market Overview</h2>
        </div>
        <div className="flex gap-4">
          <div className="px-6 py-4 bg-af-surface-container-lowest border border-af-outline-variant rounded-xl">
            <p className="text-sm text-af-on-surface-variant">Active Portfolios</p>
            <p className="text-2xl font-semibold text-af-on-surface">
              12 <span className="text-af-secondary text-sm">▲ 4.2%</span>
            </p>
          </div>
          <div className="px-6 py-4 bg-af-surface-container-lowest border border-af-outline-variant rounded-xl">
            <p className="text-sm text-af-on-surface-variant">Weekly Volume</p>
            <p className="text-2xl font-semibold text-af-on-surface">
              $1.2M <span className="text-af-error text-sm">▼ 1.8%</span>
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
