import { describe, it, expect, vi } from "vitest";
import { POST } from "@/app/api/cleanup/route";

const updateMock = vi.fn(async () => ({ rowCount: 2 }));
vi.mock("@/lib/db/client", () => ({
  db: {
    update: () => ({ set: () => ({ where: () => ({ returning: () => Promise.resolve([{ id: "a" }, { id: "b" }]) }) }) }),
  },
  jobs: { id: "id", status: "status", startedAt: "started_at" },
}));

describe("POST /api/cleanup", () => {
  it("returns the count of swept rows", async () => {
    const res = await POST(new Request("http://localhost/api/cleanup", { method: "POST" }));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.swept).toBe(2);
  });
});
