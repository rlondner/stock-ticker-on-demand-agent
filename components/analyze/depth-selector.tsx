"use client";

const DEPTHS = [
  { key: "quick", icon: "speed", label: "Quick Scan", eta: "~2 mins" },
  { key: "deep", icon: "query_stats", label: "Deep Dive", eta: "~8 mins" },
  { key: "full", icon: "description", label: "Full Report", eta: "~20 mins" },
] as const;

export type DepthKey = (typeof DEPTHS)[number]["key"];

export function DepthSelector({ value, onChange }: { value: DepthKey; onChange: (key: DepthKey) => void }) {
  return (
    <div className="space-y-2">
      <label className="text-sm font-semibold text-af-on-surface">Analysis Depth</label>
      <div className="grid grid-cols-3 gap-4">
        {DEPTHS.map((d) => {
          const isSelected = value === d.key;
          return (
            <button
              key={d.key}
              type="button"
              onClick={() => onChange(d.key)}
              className={`flex flex-col items-center gap-2 p-6 border-2 rounded-xl text-center transition-all ${
                isSelected
                  ? "border-af-primary bg-af-surface-container-low"
                  : "border-af-outline-variant hover:border-af-primary"
              }`}
            >
              <span
                className={`material-symbols-outlined ${
                  isSelected ? "text-af-on-surface" : "text-af-on-surface-variant"
                }`}
                style={{ fontVariationSettings: isSelected ? "'FILL' 1" : "'FILL' 0" }}
              >
                {d.icon}
              </span>
              <span className={`text-sm font-semibold ${isSelected ? "text-af-on-surface" : "text-af-on-surface-variant"}`}>
                {d.label}
              </span>
              <span className="text-[10px] text-af-on-surface-variant">{d.eta}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
