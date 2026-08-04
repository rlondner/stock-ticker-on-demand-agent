export function formatConfidence(c: string | null | undefined): string | null {
  const map: Record<string, string> = { low: "Low", medium: "Medium", high: "High" };
  return c ? (map[c] ?? null) : null;
}

export type GroundingBadge = { label: string; tone: "up" | "neutral" | "muted" };

export function formatGrounding(g: string | null | undefined): GroundingBadge | null {
  switch (g) {
    case "researched":
      return { label: "Web-researched", tone: "up" };
    case "limited":
      return { label: "Limited research", tone: "neutral" };
    case "snapshot_only":
      return { label: "Snapshot only", tone: "muted" };
    default:
      return null;
  }
}

export function safeSourceHref(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.protocol === "http:" || u.protocol === "https:" ? u.toString() : null;
  } catch {
    return null;
  }
}
