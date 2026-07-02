export function formatPrice(n: number | null, currency: string): string {
  if (n === null) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
  }).format(n);
}

export type ChangeTone = "up" | "down" | "neutral";

export function formatChangePct(
  n: number | null,
): { text: string; tone: ChangeTone } {
  if (n === null) return { text: "—", tone: "neutral" };
  const sign = n >= 0 ? "+" : "";
  const text = `${sign}${n.toFixed(2)}%`;
  const tone: ChangeTone = n < 0 ? "down" : "up";
  return { text, tone };
}
