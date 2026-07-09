import { describe, it, expect, vi, beforeEach } from "vitest";

const incr = vi.fn();
vi.mock("@sentry/nextjs", () => ({ metrics: { increment: incr, distribution: vi.fn() } }));

import { initMetrics, jobsSubmitted, buildJobAttrs } from "@/lib/observability/metrics";

describe("node metrics facade", () => {
  beforeEach(() => vi.clearAllMocks());

  it("buildJobAttrs includes outcome and ticker but never job_id", () => {
    const attrs = buildJobAttrs("accepted", "AAPL");
    expect(attrs).toEqual({ outcome: "accepted", ticker: "AAPL" });
    expect("job_id" in attrs).toBe(false);
  });

  it("jobsSubmitted does not throw before/after init", () => {
    expect(() => jobsSubmitted("rejected", "AAPL")).not.toThrow();
    initMetrics();
    expect(() => jobsSubmitted("accepted", "AAPL")).not.toThrow();
  });
});
