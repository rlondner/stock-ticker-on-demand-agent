import { describe, it, expect } from "vitest";
import { formatConfidence, formatGrounding, safeSourceHref } from "@/lib/ui/thesis";

describe("formatConfidence", () => {
  it("title-cases the known levels", () => {
    expect(formatConfidence("low")).toBe("Low");
    expect(formatConfidence("medium")).toBe("Medium");
    expect(formatConfidence("high")).toBe("High");
  });
  it("returns null for null/unknown", () => {
    expect(formatConfidence(null)).toBeNull();
    expect(formatConfidence("bogus")).toBeNull();
  });
});

describe("formatGrounding", () => {
  it("maps each level to label + tone", () => {
    expect(formatGrounding("researched")).toEqual({ label: "Web-researched", tone: "up" });
    expect(formatGrounding("limited")).toEqual({ label: "Limited research", tone: "neutral" });
    expect(formatGrounding("snapshot_only")).toEqual({ label: "Snapshot only", tone: "muted" });
  });
  it("returns null for null/unknown", () => {
    expect(formatGrounding(null)).toBeNull();
    expect(formatGrounding("x")).toBeNull();
  });
});

describe("safeSourceHref", () => {
  it("passes through http and https", () => {
    expect(safeSourceHref("https://x.test/a")).toBe("https://x.test/a");
    expect(safeSourceHref("http://x.test/b")).toBe("http://x.test/b");
  });
  it("rejects non-http, malformed, empty, and null", () => {
    expect(safeSourceHref("ftp://x/y")).toBeNull();
    expect(safeSourceHref("javascript:alert(1)")).toBeNull();
    expect(safeSourceHref("not a url")).toBeNull();
    expect(safeSourceHref("")).toBeNull();
    expect(safeSourceHref(null)).toBeNull();
  });
});
