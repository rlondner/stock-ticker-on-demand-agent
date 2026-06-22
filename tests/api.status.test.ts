import { describe, it, expect, vi, beforeEach } from "vitest";
import { GET } from "@/app/api/status/[jobId]/route";

const fakeRow = {
  id: "11111111-1111-1111-1111-111111111111",
  ticker: "AAPL",
  status: "complete",
  recommendation: "buy",
  result: { summary: "test", signals: [] },
  sandboxId: "sb-x",
  createdAt: new Date("2026-06-22T10:00:00Z"),
  startedAt: new Date("2026-06-22T10:00:05Z"),
  completedAt: new Date("2026-06-22T10:00:50Z"),
  error: null,
};

vi.mock("@/lib/db/client", () => {
  const limit = vi.fn(async () => [fakeRow]);
  const where = vi.fn(() => ({ limit }));
  const from = vi.fn(() => ({ where }));
  const select = vi.fn(() => ({ from }));
  return { db: { select }, jobs: { id: "id" }, __limit: limit };
});

describe("GET /api/status/[jobId]", () => {
  beforeEach(() => vi.clearAllMocks());

  it("returns the job row", async () => {
    const res = await GET(new Request("http://localhost"), { params: Promise.resolve({ jobId: fakeRow.id }) });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.id).toBe(fakeRow.id);
    expect(body.status).toBe("complete");
    expect(body.recommendation).toBe("buy");
  });

  it("returns 404 when job not found", async () => {
    const dbMod = await import("@/lib/db/client") as any;
    dbMod.__limit.mockResolvedValueOnce([]);
    const res = await GET(new Request("http://localhost"), { params: Promise.resolve({ jobId: "00000000-0000-0000-0000-000000000000" }) });
    expect(res.status).toBe(404);
  });
});
