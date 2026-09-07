import { describe, it, expect, vi } from "vitest";
import { submitAnalysis } from "@/lib/analyze/submit-analysis";

function makeFetch(status: number, body: unknown): typeof fetch {
  return vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }) as unknown as Response);
}

describe("submitAnalysis", () => {
  it("validates the ticker before hitting the network", async () => {
    const fetchSpy = vi.fn();
    const pushSpy = vi.fn();
    const result = await submitAnalysis({
      ticker: "aaaaaa", // >5 chars — invalid
      fetchImpl: fetchSpy as unknown as typeof fetch,
      push: pushSpy,
    });
    expect(result).toEqual({ ok: false, error: expect.stringMatching(/1[–-]5 uppercase/) });
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(pushSpy).not.toHaveBeenCalled();
  });

  it("posts the uppercased ticker and pushes to /jobs/[id] on 200", async () => {
    const fetchImpl = makeFetch(200, { jobId: "job-1" });
    const push = vi.fn();
    const result = await submitAnalysis({ ticker: "aapl", fetchImpl, push });
    expect(fetchImpl).toHaveBeenCalledWith("/api/jobs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ticker: "AAPL" }),
    });
    expect(push).toHaveBeenCalledWith("/jobs/job-1");
    expect(result).toEqual({ ok: true, jobId: "job-1" });
  });

  it("returns the server error on 400 and does NOT navigate", async () => {
    const fetchImpl = makeFetch(400, { error: "ticker must be 1-5 uppercase letters" });
    const push = vi.fn();
    const result = await submitAnalysis({ ticker: "AAPL", fetchImpl, push });
    expect(push).not.toHaveBeenCalled();
    expect(result).toEqual({ ok: false, error: "ticker must be 1-5 uppercase letters" });
  });

  it("on 500 with jobId, returns the error AND navigates to the failed job", async () => {
    const fetchImpl = makeFetch(500, { error: "spawn_failed", jobId: "job-x" });
    const push = vi.fn();
    const result = await submitAnalysis({ ticker: "AAPL", fetchImpl, push });
    expect(push).toHaveBeenCalledWith("/jobs/job-x");
    expect(result).toEqual({ ok: false, error: "spawn_failed", jobId: "job-x" });
  });

  it("on 500 without jobId, returns the error and stays on the form", async () => {
    const fetchImpl = makeFetch(500, { error: "internal" });
    const push = vi.fn();
    const result = await submitAnalysis({ ticker: "AAPL", fetchImpl, push });
    expect(push).not.toHaveBeenCalled();
    expect(result).toEqual({ ok: false, error: "internal" });
  });

  it("handles a fetch reject as 'Submit failed'", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new Error("network");
    }) as unknown as typeof fetch;
    const push = vi.fn();
    const result = await submitAnalysis({ ticker: "AAPL", fetchImpl, push });
    expect(push).not.toHaveBeenCalled();
    expect(result).toEqual({ ok: false, error: "Submit failed" });
  });

  it("omits notify fields from the POST body when no channel is selected", async () => {
    const fetchImpl = makeFetch(200, { jobId: "job-1" });
    const push = vi.fn();
    await submitAnalysis({ ticker: "AAPL", fetchImpl, push });
    const body = JSON.parse((fetchImpl as any).mock.calls[0][1].body);
    expect(body.notifyChannel).toBeUndefined();
    expect(body.notifyDestination).toBeUndefined();
  });

  it("includes notify fields in the POST body when a channel is selected", async () => {
    const fetchImpl = makeFetch(200, { jobId: "job-1" });
    const push = vi.fn();
    await submitAnalysis({ ticker: "AAPL", notifyChannel: "slack", notifyDestination: "#analysts", fetchImpl, push });
    const body = JSON.parse((fetchImpl as any).mock.calls[0][1].body);
    expect(body.notifyChannel).toBe("slack");
    expect(body.notifyDestination).toBe("#analysts");
  });
});
