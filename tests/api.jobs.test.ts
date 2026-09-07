import { describe, it, expect, vi, beforeEach } from "vitest";
import { POST } from "@/app/api/jobs/route";

vi.mock("@/lib/runtime", () => ({
  spawnAgent: vi.fn(async (jobId: string) => `sb-${jobId.slice(0, 8)}`),
}));

vi.mock("@/lib/observability/metrics", () => ({
  jobsSubmitted: vi.fn(),
}));

vi.mock("@/lib/db/client", () => {
  const rows: Array<{ id: string; ticker: string; status: string; sandbox_id?: string }> = [];
  const insertReturning = vi.fn(async (data: { ticker: string }) => {
    const id = crypto.randomUUID();
    const row = { id, ticker: data.ticker, status: "pending" };
    rows.push(row);
    return [{ id }];
  });
  return {
    db: {
      insert: () => ({ values: (v: any) => ({ returning: () => insertReturning(v) }) }),
      update: () => ({ set: () => ({ where: () => Promise.resolve() }) }),
    },
    jobs: {},
    __rows: rows,
  };
});

function req(body: unknown): Request {
  return new Request("http://localhost/api/jobs", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("POST /api/jobs", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    delete process.env.ONE_SECRET;
  });

  it("rejects an empty ticker with 400", async () => {
    const res = await POST(req({ ticker: "" }));
    expect(res.status).toBe(400);
  });

  it("rejects a malformed ticker with 400", async () => {
    const res = await POST(req({ ticker: "foo!" }));
    expect(res.status).toBe(400);
  });

  it("accepts a valid ticker and returns jobId", async () => {
    const res = await POST(req({ ticker: "AAPL" }));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.jobId).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("emits jobs.submitted on accept and reject", async () => {
    const { jobsSubmitted } = await import("@/lib/observability/metrics");
    await POST(req({ ticker: "AAPL" }));
    await POST(req({ ticker: "" }));
    expect(jobsSubmitted).toHaveBeenCalledWith("accepted", "AAPL");
    expect(jobsSubmitted).toHaveBeenCalledWith("rejected", "unknown");
  });

  it("accepts a valid slack notify config", async () => {
    process.env.ONE_SECRET = "sk_test";
    const res = await POST(req({ ticker: "AAPL", notifyChannel: "slack", notifyDestination: "#analysts" }));
    expect(res.status).toBe(200);
  });

  it("accepts a valid gmail notify config", async () => {
    process.env.ONE_SECRET = "sk_test";
    const res = await POST(req({ ticker: "AAPL", notifyChannel: "gmail", notifyDestination: "jane@example.com" }));
    expect(res.status).toBe(200);
  });

  it("rejects notifyChannel without a destination", async () => {
    process.env.ONE_SECRET = "sk_test";
    const res = await POST(req({ ticker: "AAPL", notifyChannel: "slack" }));
    expect(res.status).toBe(400);
  });

  it("rejects a malformed gmail destination", async () => {
    process.env.ONE_SECRET = "sk_test";
    const res = await POST(req({ ticker: "AAPL", notifyChannel: "gmail", notifyDestination: "not-an-email" }));
    expect(res.status).toBe(400);
  });

  it("rejects a malformed slack destination", async () => {
    process.env.ONE_SECRET = "sk_test";
    const res = await POST(req({ ticker: "AAPL", notifyChannel: "slack", notifyDestination: "general" }));
    expect(res.status).toBe(400);
  });

  it("rejects a notify request when ONE_SECRET is unset", async () => {
    delete process.env.ONE_SECRET;
    const res = await POST(req({ ticker: "AAPL", notifyChannel: "slack", notifyDestination: "#analysts" }));
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toMatch(/not configured/);
  });

  it("accepts a plain submit with no notify fields regardless of ONE_SECRET", async () => {
    delete process.env.ONE_SECRET;
    const res = await POST(req({ ticker: "AAPL" }));
    expect(res.status).toBe(200);
  });
});
