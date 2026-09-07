import { describe, it, expect, vi, beforeEach } from "vitest";

const sendMock = vi.fn(async () => true);
vi.mock("@/lib/notify/one", () => ({ sendCompletionNotification: sendMock }));

const baseRow = {
  id: "job-1", userId: "user-1", ticker: "AAPL", status: "complete", recommendation: "buy",
  result: { summary: "s" }, sandboxId: "sb-1",
  createdAt: new Date(), startedAt: new Date(), completedAt: new Date(),
  error: null, notifyChannel: "slack" as const, notifyDestination: "#analysts",
  notifiedAt: null as Date | null,
};

type NotifyRow = Omit<typeof baseRow, "notifyChannel" | "notifyDestination"> & {
  notifyChannel: "slack" | "gmail" | null;
  notifyDestination: string | null;
};

/**
 * A stateful update mock: the first call to `.returning()` succeeds (as a
 * real atomic `UPDATE ... WHERE notified_at IS NULL` would for whichever
 * caller wins the race), and every subsequent call returns an empty array
 * (as it would once `notified_at` has actually been persisted).
 */
function mockDbStatefulClaim(row: NotifyRow) {
  const limit = vi.fn(async () => [row]);
  const whereSelect = vi.fn(() => ({ limit }));
  const from = vi.fn(() => ({ where: whereSelect }));
  const select = vi.fn(() => ({ from }));

  let claimCount = 0;
  const returning = vi.fn(async () => {
    claimCount += 1;
    return claimCount === 1 ? [{ id: row.id }] : [];
  });
  const whereUpdate = vi.fn(() => ({ returning }));
  const set = vi.fn(() => ({ where: whereUpdate }));
  const update = vi.fn(() => ({ set }));

  return { db: { select, update }, jobs: { id: "id", status: "status", notifiedAt: "notifiedAt" } };
}

describe("triggerCompletionNotificationIfDue idempotency", () => {
  beforeEach(() => vi.clearAllMocks());

  it("sends exactly once across two sequential calls for the same job id (claim-then-send fires once)", async () => {
    vi.resetModules();
    vi.doMock("@/lib/db/client", () => mockDbStatefulClaim(baseRow));
    const { triggerCompletionNotificationIfDue } = await import("@/lib/notify/trigger");

    const firstResult = await triggerCompletionNotificationIfDue("job-1", baseRow);
    // Second call simulates a later poll/page-load reading the same
    // (stale, pre-claim) row — the atomic claim inside the helper is what
    // must prevent a double-send, not the caller re-reading fresh state.
    const secondResult = await triggerCompletionNotificationIfDue("job-1", baseRow);

    expect(sendMock).toHaveBeenCalledTimes(1);
    expect(firstResult.notifiedAt).toBeTruthy();
    expect(secondResult.notifiedAt).toBeNull();
  });

  it("does not send when the atomic claim loses the race on a single call", async () => {
    vi.resetModules();
    const limit = vi.fn(async () => [baseRow]);
    const whereSelect = vi.fn(() => ({ limit }));
    const from = vi.fn(() => ({ where: whereSelect }));
    const select = vi.fn(() => ({ from }));
    const returning = vi.fn(async () => []);
    const whereUpdate = vi.fn(() => ({ returning }));
    const set = vi.fn(() => ({ where: whereUpdate }));
    const update = vi.fn(() => ({ set }));
    vi.doMock("@/lib/db/client", () => ({
      db: { select, update },
      jobs: { id: "id", status: "status", notifiedAt: "notifiedAt" },
    }));
    const { triggerCompletionNotificationIfDue } = await import("@/lib/notify/trigger");

    const result = await triggerCompletionNotificationIfDue("job-1", baseRow);

    expect(sendMock).not.toHaveBeenCalled();
    expect(result.notifiedAt).toBeNull();
  });
});
