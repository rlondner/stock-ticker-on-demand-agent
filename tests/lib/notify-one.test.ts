import { describe, it, expect, vi, beforeEach } from "vitest";

const execFileMock = vi.fn((_cmd: string, _args: string[], _opts: unknown, cb: (err: Error | null) => void) => cb(null));

vi.mock("node:child_process", () => ({ execFile: execFileMock }));

describe("sendCompletionNotification", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    process.env.ONE_SECRET = "sk_test";
    process.env.ONE_SLACK_CONNECTION_KEY = "conn-slack";
    process.env.ONE_SLACK_SEND_ACTION_ID = "action-slack";
    process.env.ONE_GMAIL_CONNECTION_KEY = "conn-gmail";
    process.env.ONE_GMAIL_SEND_ACTION_ID = "action-gmail";
  });

  it("builds a slack payload and invokes the CLI with the slack action/connection", async () => {
    const { sendCompletionNotification } = await import("@/lib/notify/one");
    await sendCompletionNotification({
      ticker: "AAPL", recommendation: "buy", summary: "Strong quarter.",
      notifyChannel: "slack", notifyDestination: "#analysts",
    });
    const call = execFileMock.mock.calls[0];
    expect(call[0]).toBe("npx");
    expect(call[1]).toEqual(expect.arrayContaining([
      "--no-install", "@withone/cli", "actions", "execute", "slack", "action-slack", "conn-slack",
    ]));
    const dArgIndex = (call[1] as string[]).indexOf("-d");
    const payload = JSON.parse((call[1] as string[])[dArgIndex + 1]);
    expect(payload.channel).toBe("#analysts");
    expect(payload.text).toContain("AAPL");
    expect(payload.text).toContain("buy");
  });

  it("builds a gmail payload and invokes the CLI with the gmail action/connection", async () => {
    const { sendCompletionNotification } = await import("@/lib/notify/one");
    await sendCompletionNotification({
      ticker: "MDB", recommendation: "hold", summary: "Mixed signals.",
      notifyChannel: "gmail", notifyDestination: "jane@example.com",
    });
    const call = execFileMock.mock.calls[0];
    expect(call[1]).toEqual(expect.arrayContaining([
      "actions", "execute", "gmail", "action-gmail", "conn-gmail",
    ]));
    const dArgIndex = (call[1] as string[]).indexOf("-d");
    const payload = JSON.parse((call[1] as string[])[dArgIndex + 1]);
    expect(payload.to).toBe("jane@example.com");
    expect(payload.subject).toContain("MDB");
    expect(payload.body).toContain("hold");
  });

  it("never throws when the CLI call fails", async () => {
    execFileMock.mockImplementationOnce((_cmd, _args, _opts, cb) => cb(new Error("boom")));
    const { sendCompletionNotification } = await import("@/lib/notify/one");
    await expect(sendCompletionNotification({
      ticker: "AAPL", recommendation: "buy", summary: "x",
      notifyChannel: "slack", notifyDestination: "#analysts",
    })).resolves.toBeUndefined();
  });

  it("never throws when the connection/action env vars are missing", async () => {
    delete process.env.ONE_SLACK_CONNECTION_KEY;
    const { sendCompletionNotification } = await import("@/lib/notify/one");
    await expect(sendCompletionNotification({
      ticker: "AAPL", recommendation: "buy", summary: "x",
      notifyChannel: "slack", notifyDestination: "#analysts",
    })).resolves.toBeUndefined();
    expect(execFileMock).not.toHaveBeenCalled();
  });
});
