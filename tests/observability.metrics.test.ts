import { describe, it, expect, vi, beforeEach, afterAll } from "vitest";

// sentryIncr uses a lazy CJS require() which bypasses vi.mock ESM interception.
// We spy on the real @sentry/nextjs module object at the property level instead.
// This only works because require() returns the same cached module instance.
import * as SentryNextjs from "@sentry/nextjs";

// Set SENTRY_DSN_NEXTJS before first initMetrics() call so sentryEnabled=true.
process.env.SENTRY_DSN_NEXTJS = "https://test@sentry.io/123";

import { initMetrics, jobsSubmitted, buildJobAttrs } from "@/lib/observability/metrics";

afterAll(() => {
  delete process.env.SENTRY_DSN_NEXTJS;
});

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

  it("jobsSubmitted calls Sentry metrics.count with attributes (not increment/tags)", () => {
    // initMetrics() was called above with SENTRY_DSN_NEXTJS set, so sentryEnabled=true.
    // Spy on the real @sentry/nextjs.metrics.count (same object the CJS require returns).
    const spy = vi.spyOn(SentryNextjs.metrics, "count");
    try {
      initMetrics(); // idempotent
      jobsSubmitted("accepted", "AAPL");
      expect(spy).toHaveBeenCalledWith(
        "jobs.submitted",
        1,
        { attributes: { outcome: "accepted", ticker: "AAPL" } },
      );
    } finally {
      spy.mockRestore();
    }
  });
});
