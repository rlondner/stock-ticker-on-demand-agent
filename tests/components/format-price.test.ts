import { describe, it, expect } from "vitest";
import { formatPrice, formatChangePct } from "@/lib/ui/format-price";

describe("formatPrice", () => {
  it("formats a positive USD number with symbol + 2 decimals", () => {
    expect(formatPrice(342.15, "USD")).toBe("$342.15");
  });

  it("formats zero", () => {
    expect(formatPrice(0, "USD")).toBe("$0.00");
  });

  it("respects the currency argument", () => {
    // Intl.NumberFormat in Node outputs "€1,234.50" for EUR/en-US.
    expect(formatPrice(1234.5, "EUR")).toMatch(/€\s?1,234\.50/);
  });

  it("returns em-dash for null", () => {
    expect(formatPrice(null, "USD")).toBe("—");
  });
});

describe("formatChangePct", () => {
  it("formats a positive change with plus sign and up tone", () => {
    expect(formatChangePct(2.4)).toEqual({ text: "+2.40%", tone: "up" });
  });

  it("formats a negative change with sign preserved and down tone", () => {
    expect(formatChangePct(-1.24)).toEqual({ text: "-1.24%", tone: "down" });
  });

  it("treats zero as up (neutral or up, not down)", () => {
    expect(formatChangePct(0)).toEqual({ text: "+0.00%", tone: "up" });
  });

  it("returns em-dash + neutral for null", () => {
    expect(formatChangePct(null)).toEqual({ text: "—", tone: "neutral" });
  });
});
