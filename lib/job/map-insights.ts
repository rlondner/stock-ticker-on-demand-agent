export type RawSignal = { label: string; evidence: string; source: string | null };

export type Insight = {
  icon: "psychology" | "trending_up" | "warning" | "groups";
  label: string;
  evidence: string;
  sourceHref: string | null;
};

const ICONS = ["psychology", "trending_up", "warning", "groups"] as const;

function parseHttpUrl(s: string | null): string | null {
  if (!s) return null;
  try {
    const u = new URL(s);
    return u.protocol === "http:" || u.protocol === "https:" ? u.toString() : null;
  } catch {
    return null;
  }
}

export function mapSignalsToInsights(signals: RawSignal[] | null | undefined): Insight[] {
  if (!signals) return [];
  return signals.map((s, i) => ({
    icon: ICONS[i % ICONS.length],
    label: s.label.toUpperCase(),
    evidence: s.evidence,
    sourceHref: parseHttpUrl(s.source),
  }));
}
