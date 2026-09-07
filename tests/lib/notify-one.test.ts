import { describe, it, expect, vi, beforeEach } from "vitest";

const execFileMock = vi.fn((_cmd: string, _args: string[], _opts: unknown, cb: (err: Error | null) => void) => cb(null));
const sentryWarnMock = vi.fn();
const ddLogMock = vi.fn();

vi.mock("node:child_process", () => ({ execFile: execFileMock }));
vi.mock("@sentry/nextjs", () => ({ logger: { warn: sentryWarnMock } }));
vi.mock("@/lib/observability/exporters/datadog", () => ({ ddLog: ddLogMock }));

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
    const result = await sendCompletionNotification({
      ticker: "AAPL", recommendation: "buy", summary: "Strong quarter.",
      notifyChannel: "slack", notifyDestination: "#analysts",
    });
    expect(result).toBe(true);
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
    const result = await sendCompletionNotification({
      ticker: "MDB", recommendation: "hold", summary: "Mixed signals.",
      notifyChannel: "gmail", notifyDestination: "jane@example.com",
    });
    expect(result).toBe(true);
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

  it("invokes execFile with a timeout so a hung CLI process can't hang callers forever", async () => {
    const { sendCompletionNotification } = await import("@/lib/notify/one");
    await sendCompletionNotification({
      ticker: "AAPL", recommendation: "buy", summary: "Strong quarter.",
      notifyChannel: "slack", notifyDestination: "#analysts",
    });
    const call = execFileMock.mock.calls[0];
    const opts = call[2] as Record<string, unknown>;
    expect(opts).toEqual(expect.objectContaining({ timeout: 10_000, killSignal: "SIGKILL" }));
  });

  it("never throws when the CLI call fails, and resolves false", async () => {
    execFileMock.mockImplementationOnce((_cmd, _args, _opts, cb) => cb(new Error("boom")));
    const { sendCompletionNotification } = await import("@/lib/notify/one");
    await expect(sendCompletionNotification({
      ticker: "AAPL", recommendation: "buy", summary: "x",
      notifyChannel: "slack", notifyDestination: "#analysts",
    })).resolves.toBe(false);
  });

  it("never throws when the connection/action env vars are missing, and resolves false", async () => {
    delete process.env.ONE_SLACK_CONNECTION_KEY;
    const { sendCompletionNotification } = await import("@/lib/notify/one");
    await expect(sendCompletionNotification({
      ticker: "AAPL", recommendation: "buy", summary: "x",
      notifyChannel: "slack", notifyDestination: "#analysts",
    })).resolves.toBe(false);
    expect(execFileMock).not.toHaveBeenCalled();
  });

  it("never logs the raw error message, connection key, action id, or payload when the CLI call fails", async () => {
    const fakeConnectionKey = "conn-slack";
    const fakeActionId = "action-slack";
    const fakePayloadFragment = "#super-secret-analysts-channel";
    const leakyMessage =
      `Command failed: npx --no-install @withone/cli actions execute slack ${fakeActionId} ${fakeConnectionKey} ` +
      `-d {"channel":"${fakePayloadFragment}","text":"AAPL analysis complete"}\nstderr: boom`;
    execFileMock.mockImplementationOnce((_cmd, _args, _opts, cb) => cb(new Error(leakyMessage)));

    const { sendCompletionNotification } = await import("@/lib/notify/one");
    const result = await sendCompletionNotification({
      ticker: "AAPL", recommendation: "buy", summary: "x",
      notifyChannel: "slack", notifyDestination: fakePayloadFragment,
    });

    expect(result).toBe(false);

    const allLoggedArgs = [...sentryWarnMock.mock.calls, ...ddLogMock.mock.calls]
      .map((args) => JSON.stringify(args));
    expect(allLoggedArgs.length).toBeGreaterThan(0);
    for (const logged of allLoggedArgs) {
      expect(logged).not.toContain(fakeConnectionKey);
      expect(logged).not.toContain(fakeActionId);
      expect(logged).not.toContain(fakePayloadFragment);
      expect(logged).not.toContain(leakyMessage);
    }
  });
});
