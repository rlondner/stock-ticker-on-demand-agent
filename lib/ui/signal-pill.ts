export type Recommendation = "buy" | "hold" | "sell";

export function signalPillProps(
  recommendation: Recommendation | null,
): { label: string; className: string } | null {
  if (recommendation === null) return null;
  switch (recommendation) {
    case "buy":
      return { label: "BUY", className: "bg-af-signal-buy text-white" };
    case "hold":
      return { label: "HOLD", className: "bg-af-signal-hold text-white" };
    case "sell":
      return { label: "SELL", className: "bg-af-signal-sell text-white" };
  }
}
