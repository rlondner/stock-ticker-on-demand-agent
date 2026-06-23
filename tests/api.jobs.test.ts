import { describe, it, expect, vi, beforeEach } from "vitest";
import { POST } from "@/app/api/jobs/route";

vi.mock("@/lib/runtime", () => ({
  spawnAgent: vi.fn(async (jobId: string) => `sb-${jobId.slice(0, 8)}`),
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
  beforeEach(() => vi.clearAllMocks());

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
});
