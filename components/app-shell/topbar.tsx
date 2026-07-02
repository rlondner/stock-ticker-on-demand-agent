export function Topbar() {
  return (
    <header className="sticky top-0 z-10 bg-af-surface-container-lowest border-b border-af-outline-variant px-4 h-16 flex justify-between items-center w-full max-w-af-max mx-auto">
      <div className="flex items-center gap-8">
        <span className="text-2xl font-extrabold text-af-on-surface tracking-tight">AlphaFlow</span>
        <nav className="hidden lg:flex items-center gap-6">
          <span className="text-af-on-surface font-bold border-b-2 border-af-primary pb-1 text-sm">
            Dashboard
          </span>
          {["Market", "Portfolio", "Watchlist", "Alerts"].map((tab) => (
            <button
              key={tab}
              type="button"
              className="text-af-on-surface-variant pb-1 text-sm hover:text-af-on-surface transition-colors"
            >
              {tab}
            </button>
          ))}
        </nav>
      </div>
      <div className="flex items-center gap-6">
        <div className="relative">
          <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-af-on-surface-variant pointer-events-none">
            search
          </span>
          <input
            type="text"
            placeholder="Analyze tickers (e.g. NVDA)..."
            disabled
            className="pl-10 pr-4 py-2 bg-af-surface-container-low border border-af-outline-variant rounded-full text-sm w-64 outline-none cursor-not-allowed"
          />
        </div>
        <div className="flex items-center gap-4">
          <button type="button" className="text-af-on-surface-variant hover:text-af-on-surface transition-colors">
            <span className="material-symbols-outlined">notifications</span>
          </button>
          <button type="button" className="text-af-on-surface-variant hover:text-af-on-surface transition-colors">
            <span className="material-symbols-outlined">settings</span>
          </button>
          <div className="w-8 h-8 rounded-full bg-af-surface-container-high border border-af-outline-variant" aria-hidden />
        </div>
      </div>
    </header>
  );
}
