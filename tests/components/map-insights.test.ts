import { describe, it, expect } from "vitest";
import { mapSignalsToInsights } from "@/lib/job/map-insights";

describe("mapSignalsToInsights", () => {
  it("returns [] for an empty input", () => {
    expect(mapSignalsToInsights([])).toEqual([]);
  });

  it("returns [] for null input (missing signals array)", () => {
    expect(mapSignalsToInsights(null)).toEqual([]);
  });

  it("cycles through the four icon names by index", () => {
    const signals = [
      { label: "s1", evidence: "e1", source: null },
      { label: "s2", evidence: "e2", source: null },
      { label: "s3", evidence: "e3", source: null },
      { label: "s4", evidence: "e4", source: null },
    ];
    const out = mapSignalsToInsights(signals);
    expect(out.map((s) => s.icon)).toEqual(["psychology", "trending_up", "warning", "groups"]);
  });

  it("renders label uppercase", () => {
    const out = mapSignalsToInsights([{ label: "AI Momentum", evidence: "e", source: null }]);
    expect(out[0].label).toBe("AI MOMENTUM");
  });

  it("keeps the source when it parses as an http(s) URL", () => {
    const out = mapSignalsToInsights([{ label: "s", evidence: "e", source: "https://example.com/q3-call" }]);
    expect(out[0].sourceHref).toBe("https://example.com/q3-call");
  });

  it("drops the source when it is not a URL", () => {
    const out = mapSignalsToInsights([{ label: "s", evidence: "e", source: "Q3 Earnings Call" }]);
    expect(out[0].sourceHref).toBeNull();
  });

  it("drops the source when it is null", () => {
    const out = mapSignalsToInsights([{ label: "s", evidence: "e", source: null }]);
    expect(out[0].sourceHref).toBeNull();
  });

  it("wraps around after 4 signals (5th uses psychology again)", () => {
    const signals = Array.from({ length: 5 }, (_, i) => ({
      label: `s${i}`,
      evidence: `e${i}`,
      source: null,
    }));
    const out = mapSignalsToInsights(signals);
    expect(out[4].icon).toBe("psychology");
  });
});
