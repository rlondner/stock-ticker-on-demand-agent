import type { Snapshot } from "@/lib/job/types";
import { analystPanelModel } from "@/lib/ui/analyst-sentiment";

const BAR_COLOR: Record<string, string> = {
  BUY: "bg-af-secondary",
  HOLD: "bg-af-signal-hold",
  SELL: "bg-af-error",
};
const BAR_TEXT: Record<string, string> = {
  BUY: "text-af-secondary",
  HOLD: "text-af-signal-hold",
  SELL: "text-af-error",
};

export function AnalystSentiment({ snapshot }: { snapshot: Snapshot | null }) {
  const model = analystPanelModel(snapshot);
  return (
    <div className="col-span-12 lg:col-span-4 bg-af-surface-container-lowest p-8 rounded-xl border border-af-outline-variant">
      <h4 className="text-2xl font-semibold text-af-on-surface mb-8">Analyst Sentiment</h4>

      {model.kind === "bars" && (
        <>
          <div className="space-y-6">
            {model.bars.map((b) => (
              <div key={b.label}>
                <div className={`flex justify-between text-[12px] mb-2 font-medium ${BAR_TEXT[b.label]}`}>
                  <span>{b.label} RECOMMENDATION</span>
                  <span>{b.pct}%</span>
                </div>
                <div className="w-full h-2 bg-af-surface-container-low rounded-full overflow-hidden">
                  <div className={`h-full ${BAR_COLOR[b.label]}`} style={{ width: `${b.pct}%` }} />
                </div>
              </div>
            ))}
          </div>
          <p className="mt-8 text-[12px] font-medium text-af-on-surface-variant">
            Based on {model.total} analyst {model.total === 1 ? "rating" : "ratings"}
          </p>
        </>
      )}

      {model.kind === "consensus" && (
        <div className="mt-2">
          <p className="text-3xl font-semibold text-af-on-surface">{model.label}</p>
          {model.count !== null && (
            <p className="text-[12px] font-medium text-af-on-surface-variant mt-2">
              Consensus across {model.count} {model.count === 1 ? "analyst" : "analysts"}
            </p>
          )}
        </div>
      )}

      {model.kind === "unavailable" && (
        <p className="text-sm text-af-on-surface-variant">Analyst data unavailable</p>
      )}
    </div>
  );
}
