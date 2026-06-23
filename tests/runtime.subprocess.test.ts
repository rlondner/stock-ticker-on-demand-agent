import { describe, it, expect, vi, beforeEach } from "vitest";
import { trace } from "@opentelemetry/api";
import { BasicTracerProvider } from "@opentelemetry/sdk-trace-base";

const spawnMock = vi.fn();
const unrefMock = vi.fn();
const existsSyncMock = vi.fn();
const mkdirSyncMock = vi.fn();
const openSyncMock = vi.fn(() => 42);

vi.mock("node:child_process", () => ({ spawn: spawnMock }));
vi.mock("node:fs", () => ({
  existsSync: existsSyncMock,
  mkdirSync: mkdirSyncMock,
  openSync: openSyncMock,
}));

trace.setGlobalTracerProvider(new BasicTracerProvider());

describe("spawnAnalysisSubprocess", () => {
  beforeEach(() => {
    process.env.NEON_DATABASE_URL = "postgresql://test";
    process.env.OPENAI_API_KEY = "sk-test";
    delete process.env.OPENAI_API_URL;
    delete process.env.OPENAI_MODEL;
    delete process.env.SENTRY_DSN_AGENT;
    delete process.env.DD_API_KEY;
    delete process.env.DAYTONA_API_KEY;
    spawnMock.mockReset();
    spawnMock.mockReturnValue({ unref: unrefMock, pid: 9999 });
    existsSyncMock.mockReset().mockReturnValue(true);
    mkdirSyncMock.mockReset();
    openSyncMock.mockClear();
    unrefMock.mockClear();
  });

  it("returns 'local-<jobId>' and spawns the agent with the required env", async () => {
    const { spawnAnalysisSubprocess } = await import("@/lib/runtime/subprocess");
    const span = trace.getTracer("t").startSpan("p");
    const id = await spawnAnalysisSubprocess("job-abc", span);
    span.end();
    expect(id).toBe("local-job-abc");

    expect(spawnMock).toHaveBeenCalledTimes(1);
    const [pythonPath, argv, opts] = spawnMock.mock.calls[0] as [string, string[], any];
    expect(pythonPath).toMatch(/agent[\\/]\.venv[\\/](Scripts[\\/]python\.exe|bin[\\/]python)$/);
    expect(argv).toEqual(["agent.py"]);
    expect(opts.cwd).toMatch(/[\\/]agent$/);
    expect(opts.detached).toBe(true);
    expect(opts.stdio).toEqual(["ignore", 42, 42]);
    expect(opts.env.JOB_ID).toBe("job-abc");
    expect(opts.env.NEON_DATABASE_URL).toBe("postgresql://test");
    expect(opts.env.OPENAI_API_KEY).toBe("sk-test");
    expect(opts.env.TRACEPARENT).toMatch(/^00-/);
    expect(opts.env.DAYTONA_API_KEY).toBeUndefined();
    expect(unrefMock).toHaveBeenCalledTimes(1);
  });

  it("forwards OPENAI_API_URL, OPENAI_MODEL, SENTRY_DSN_AGENT only when set", async () => {
    process.env.OPENAI_API_URL = "https://proxy.example.com/v1";
    process.env.OPENAI_MODEL = "gpt-4.1";
    process.env.SENTRY_DSN_AGENT = "https://x@sentry.io/1";
    const { spawnAnalysisSubprocess } = await import("@/lib/runtime/subprocess");
    const span = trace.getTracer("t").startSpan("p");
    await spawnAnalysisSubprocess("job-fwd", span);
    span.end();
    const opts = spawnMock.mock.calls.at(-1)![2];
    expect(opts.env.OPENAI_API_URL).toBe("https://proxy.example.com/v1");
    expect(opts.env.OPENAI_MODEL).toBe("gpt-4.1");
    expect(opts.env.SENTRY_DSN_AGENT).toBe("https://x@sentry.io/1");
  });

  it("forwards the Datadog block when DD_API_KEY is set", async () => {
    process.env.DD_API_KEY = "dd-key";
    const { spawnAnalysisSubprocess } = await import("@/lib/runtime/subprocess");
    const span = trace.getTracer("t").startSpan("p");
    await spawnAnalysisSubprocess("job-dd", span);
    span.end();
    const opts = spawnMock.mock.calls.at(-1)![2];
    expect(opts.env.DD_API_KEY).toBe("dd-key");
    expect(opts.env.DD_SERVICE).toBe("stock-agent");
    expect(opts.env.DD_SITE).toBe("datadoghq.com");
  });

  it("never forwards DAYTONA_API_KEY", async () => {
    process.env.DAYTONA_API_KEY = "dt-key";
    const { spawnAnalysisSubprocess } = await import("@/lib/runtime/subprocess");
    const span = trace.getTracer("t").startSpan("p");
    await spawnAnalysisSubprocess("job-no-dt", span);
    span.end();
    const opts = spawnMock.mock.calls.at(-1)![2];
    expect(opts.env.DAYTONA_API_KEY).toBeUndefined();
  });

  it("creates agent/.runs/ and opens a per-job log file", async () => {
    const { spawnAnalysisSubprocess } = await import("@/lib/runtime/subprocess");
    const span = trace.getTracer("t").startSpan("p");
    await spawnAnalysisSubprocess("job-log", span);
    span.end();
    expect(mkdirSyncMock).toHaveBeenCalledWith(
      expect.stringMatching(/agent[\\/]\.runs$/),
      { recursive: true },
    );
    expect(openSyncMock).toHaveBeenCalledWith(
      expect.stringMatching(/agent[\\/]\.runs[\\/]job-log\.log$/),
      "a",
    );
  });

  it("throws a clear error when the venv Python is missing", async () => {
    existsSyncMock.mockReturnValue(false);
    const { spawnAnalysisSubprocess } = await import("@/lib/runtime/subprocess");
    const span = trace.getTracer("t").startSpan("p");
    await expect(spawnAnalysisSubprocess("job-no-venv", span)).rejects.toThrow(
      /agent venv not found/i,
    );
    span.end();
  });
});
