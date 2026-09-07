import { describe, it, expect, vi, beforeEach } from "vitest";

const sendMock = vi.fn(async () => {});
vi.mock("@/lib/notify/one", () => ({ sendCompletionNotification: sendMock }));

const baseRow = {
  id: "job-1", ticker: "AAPL", status: "complete", recommendation: "buy",
  result: { summary: "s" }, sandboxId: "sb-1",
  createdAt: new Date(), startedAt: new Date(), completedAt: new Date(),
  error: null, notifyChannel: "slack" as const, notifyDestination: "#analysts",
  notifiedAt: null as Date | null,
};

type NotifyRow = Omit<typeof baseRow, "notifyChannel" | "notifyDestination"> & {
  notifyChannel: "slack" | "gmail" | null;
  notifyDestination: string | null;
};

function mockDb(row: NotifyRow, claimSucceeds: boolean) {
  const limit = vi.fn(async () => [row]);
  const whereSelect = vi.fn(() => ({ limit }));
  const from = vi.fn(() => ({ where: whereSelect }));
  const select = vi.fn(() => ({ from }));

  const returning = vi.fn(async () => (claimSucceeds ? [{ id: row.id }] : []));
  const whereUpdate = vi.fn(() => ({ returning }));
  const set = vi.fn(() => ({ where: whereUpdate }));
  const update = vi.fn(() => ({ set }));

  return { db: { select, update }, jobs: { id: "id", status: "status", notifiedAt: "notifiedAt" }, __select: select, __update: update };
}

describe("GET /api/status/[jobId] notification trigger", () => {
  beforeEach(() => vi.clearAllMocks());

  it("sends the notification and returns notifiedAt when the job just completed", async () => {
    vi.resetModules();
    vi.doMock("@/lib/db/client", () => mockDb(baseRow, true));
    const { GET } = await import("@/app/api/status/[jobId]/route");
    const res = await GET(new Request("http://localhost"), { params: Promise.resolve({ jobId: "job-1" }) });
    const body = await res.json();
    expect(sendMock).toHaveBeenCalledTimes(1);
    expect(body.notifiedAt).toBeTruthy();
  });

  it("does not send when notifyChannel is null", async () => {
    vi.resetModules();
    vi.doMock("@/lib/db/client", () => mockDb({ ...baseRow, notifyChannel: null, notifyDestination: null }, true));
    const { GET } = await import("@/app/api/status/[jobId]/route");
    await GET(new Request("http://localhost"), { params: Promise.resolve({ jobId: "job-1" }) });
    expect(sendMock).not.toHaveBeenCalled();
  });

  it("does not send when notifiedAt is already set", async () => {
    vi.resetModules();
    vi.doMock("@/lib/db/client", () => mockDb({ ...baseRow, notifiedAt: new Date() }, true));
    const { GET } = await import("@/app/api/status/[jobId]/route");
    await GET(new Request("http://localhost"), { params: Promise.resolve({ jobId: "job-1" }) });
    expect(sendMock).not.toHaveBeenCalled();
  });

  it("does not send when status is not complete", async () => {
    vi.resetModules();
    vi.doMock("@/lib/db/client", () => mockDb({ ...baseRow, status: "running" }, true));
    const { GET } = await import("@/app/api/status/[jobId]/route");
    await GET(new Request("http://localhost"), { params: Promise.resolve({ jobId: "job-1" }) });
    expect(sendMock).not.toHaveBeenCalled();
  });

  it("does not send when the atomic claim loses the race (already claimed by a concurrent poll)", async () => {
    vi.resetModules();
    vi.doMock("@/lib/db/client", () => mockDb(baseRow, false));
    const { GET } = await import("@/app/api/status/[jobId]/route");
    await GET(new Request("http://localhost"), { params: Promise.resolve({ jobId: "job-1" }) });
    expect(sendMock).not.toHaveBeenCalled();
  });

  it("still returns 200 with the job data when the notification call rejects", async () => {
    vi.resetModules();
    sendMock.mockRejectedValueOnce(new Error("cli failed"));
    vi.doMock("@/lib/db/client", () => mockDb(baseRow, true));
    const { GET } = await import("@/app/api/status/[jobId]/route");
    const res = await GET(new Request("http://localhost"), { params: Promise.resolve({ jobId: "job-1" }) });
    expect(res.status).toBe(200);
  });
});
