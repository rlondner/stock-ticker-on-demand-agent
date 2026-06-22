import { describe, it, expect, vi, beforeEach, beforeAll } from "vitest";
import { trace } from "@opentelemetry/api";
import { BasicTracerProvider } from "@opentelemetry/sdk-trace-base";

const createMock = vi.fn(async () => ({ id: "sb-12345" }));

vi.mock("@daytonaio/sdk", () => ({
  Daytona: vi.fn(function (this: any) {
    this.create = createMock;
  }),
}));

beforeAll(() => {
  // Register a real tracer provider so startSpan returns a recording span
  // whose context can be injected via the W3C propagator.
  const provider = new BasicTracerProvider();
  trace.setGlobalTracerProvider(provider);
});

describe("spawnAnalysisSandbox", () => {
  beforeEach(() => {
    process.env.DAYTONA_API_KEY = "dt-test";
    process.env.NEON_DATABASE_URL = "postgresql://test";
    process.env.OPENAI_API_KEY = "sk-test";
    delete process.env.SENTRY_DSN_AGENT;
    delete process.env.DD_API_KEY;
    createMock.mockClear();
  });

  it("returns the sandbox id and passes JOB_ID + TRACEPARENT", async () => {
    const { spawnAnalysisSandbox } = await import("@/lib/daytona");
    const span = trace.getTracer("t").startSpan("parent");
    const id = await spawnAnalysisSandbox("job-abc", span);
    span.end();
    expect(id).toBe("sb-12345");
    const call = createMock.mock.calls[0][0] as any;
    expect(call.snapshot).toBe("stock-agent:latest");
    expect(call.envVars.JOB_ID).toBe("job-abc");
    expect(call.envVars.TRACEPARENT).toMatch(/^00-/);
    expect(call.envVars.SENTRY_DSN_AGENT).toBeUndefined();
    expect(call.envVars.DD_API_KEY).toBeUndefined();
  });

  it("forwards Sentry DSN only when set", async () => {
    process.env.SENTRY_DSN_AGENT = "https://x@sentry.io/1";
    const { spawnAnalysisSandbox } = await import("@/lib/daytona");
    const span = trace.getTracer("t").startSpan("p");
    await spawnAnalysisSandbox("job-2", span);
    span.end();
    const call = createMock.mock.calls.at(-1)![0] as any;
    expect(call.envVars.SENTRY_DSN_AGENT).toBe("https://x@sentry.io/1");
  });

  it("forwards Datadog block only when DD_API_KEY is set", async () => {
    process.env.DD_API_KEY = "dd-key";
    const { spawnAnalysisSandbox } = await import("@/lib/daytona");
    const span = trace.getTracer("t").startSpan("p");
    await spawnAnalysisSandbox("job-3", span);
    span.end();
    const call = createMock.mock.calls.at(-1)![0] as any;
    expect(call.envVars.DD_API_KEY).toBe("dd-key");
    expect(call.envVars.DD_SERVICE).toBe("stock-agent");
    expect(call.envVars.DD_SITE).toBe("datadoghq.com");
  });
});
