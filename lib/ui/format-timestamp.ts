const MOCK_FMT = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  year: "numeric",
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
  timeZoneName: "short",
});

/** Format like the AlphaFlow mock: "Jun 14, 2024 · 09:12:04 EST". */
export function formatMockTimestamp(date: Date): string {
  const parts = MOCK_FMT.formatToParts(date);
  const p = (t: string) => parts.find((x) => x.type === t)?.value ?? "";
  const month = p("month");
  const day = p("day");
  const year = p("year");
  const hour = p("hour");
  const minute = p("minute");
  const second = p("second");
  const tz = p("timeZoneName");
  return `${month} ${day}, ${year} · ${hour}:${minute}:${second} ${tz}`;
}

const COMPACT_FMT = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  year: "numeric",
  month: "short",
  day: "2-digit",
});

/** Format like "Oct 24, 2023" — no time component. */
export function formatCompactDate(date: Date): string {
  return COMPACT_FMT.format(date);
}
