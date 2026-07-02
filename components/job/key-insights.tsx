import { mapSignalsToInsights, type RawSignal } from "@/lib/job/map-insights";

const ICON_BG: Record<string, string> = {
  psychology: "bg-af-primary-container text-af-primary-fixed",
  trending_up: "bg-af-secondary-container text-af-on-secondary-container",
  warning: "bg-af-error-container text-af-on-error-container",
  groups: "bg-af-surface-container text-af-on-surface",
};

export function KeyInsights({ signals, lastUpdatedLabel }: { signals: RawSignal[] | null; lastUpdatedLabel: string }) {
  const insights = mapSignalsToInsights(signals);

  return (
    <section className="space-y-6">
      <div className="flex items-center justify-between">
        <h4 className="text-2xl font-semibold text-af-on-surface">Key Insights</h4>
        <span className="text-sm text-af-on-surface-variant">Last updated: {lastUpdatedLabel}</span>
      </div>
      {insights.length === 0 ? (
        <p className="text-sm text-af-on-surface-variant">No insights yet.</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {insights.map((s, i) => (
            <div
              key={i}
              className="bg-af-surface-container-lowest p-6 rounded-xl border border-af-outline-variant flex flex-col justify-between h-full"
            >
              <div className="space-y-4">
                <div className={`w-12 h-12 rounded-lg flex items-center justify-center ${ICON_BG[s.icon]}`}>
                  <span className="material-symbols-outlined">{s.icon}</span>
                </div>
                <h5 className="text-sm font-semibold text-af-on-surface uppercase">{s.label}</h5>
                <p className="text-sm text-af-on-surface-variant leading-relaxed">{s.evidence}</p>
              </div>
              {s.sourceHref && (
                <div className="mt-6 pt-4 border-t border-af-outline-variant">
                  <a
                    href={s.sourceHref}
                    target="_blank"
                    rel="noreferrer"
                    className="text-af-secondary text-[12px] font-medium flex items-center gap-1 hover:underline"
                  >
                    Source
                    <span className="material-symbols-outlined text-[14px]">open_in_new</span>
                  </a>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
