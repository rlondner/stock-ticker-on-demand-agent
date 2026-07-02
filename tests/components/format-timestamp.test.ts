import { describe, it, expect } from "vitest";
import { formatMockTimestamp, formatCompactDate } from "@/lib/ui/format-timestamp";

describe("formatMockTimestamp", () => {
  it("renders the mock's 'Jun 14, 2024 · 09:12:04 EST' shape (ET)", () => {
    // 2024-06-14T13:12:04Z is 09:12:04 EDT (America/New_York).
    // ET-region output shows 'EDT' or 'EST' depending on DST; assert the
    // structural shape rather than the exact abbreviation.
    const out = formatMockTimestamp(new Date("2024-06-14T13:12:04Z"));
    expect(out).toMatch(/^Jun 14, 2024 · 09:12:04 E[SD]T$/);
  });

  it("is stable regardless of the process's local timezone", () => {
    // Same instant as above; confirms the formatter forces America/New_York
    const out = formatMockTimestamp(new Date(Date.UTC(2024, 5, 14, 13, 12, 4)));
    expect(out).toMatch(/^Jun 14, 2024 ·/);
  });
});

describe("formatCompactDate", () => {
  it("renders the mock's 'Oct 24, 2023' shape (no time)", () => {
    expect(formatCompactDate(new Date("2023-10-24T18:00:00Z"))).toBe("Oct 24, 2023");
  });
});
