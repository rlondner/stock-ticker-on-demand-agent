import { describe, it, expect, vi, beforeEach, beforeAll } from "vitest";
import { trace } from "@opentelemetry/api";
import { BasicTracerProvider } from "@opentelemetry/sdk-trace-base";

const createSessionMock = vi.fn(async (_id: string) => {});
const executeSessionCommandMock = vi.fn(async () => ({ cmdId: "cmd-1" }));
const createMock = vi.fn(async () => ({
  id: "sb-12345",
  process: {
    createSession: createSessionMock,
    executeSessionCommand: executeSessionCommandMock,
  },
}));

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
    delete process.env.OPENAI_API_URL;
    delete process.env.OPENAI_MODEL;
    delete process.env.SENTRY_DSN_AGENT;
    delete process.env.DD_API_KEY;
    delete process.env.DD_TRACE_ENABLED;
    delete process.env.DD_EXPORTER;
    delete process.env.DD_OTLP_ENDPOINT;
    createMock.mockClear();
    createSessionMock.mockClear();
    executeSessionCommandMock.mockClear();
  });

  it("kicks off python /app/agent.py in a background session", async () => {
    const { spawnAnalysisSandbox } = await import("@/lib/daytona");
    const span = trace.getTracer("t").startSpan("p");
    await spawnAnalysisSandbox("job-kick", span);
    span.end();
    expect(createSessionMock).toHaveBeenCalledWith("agent-job-kick");
    expect(executeSessionCommandMock).toHaveBeenCalledWith("agent-job-kick", {
      command: "python /app/agent.py",
      runAsync: true,
    });
  });

  it("returns the sandbox id and passes JOB_ID + TRACEPARENT", async () => {
    const { spawnAnalysisSandbox } = await import("@/lib/daytona");
    const span = trace.getTracer("t").startSpan("parent");
    const id = await spawnAnalysisSandbox("job-abc", span);
    span.end();
    expect(id).toBe("sb-12345");
    const call = createMock.mock.calls[0][0] as any;
    expect(call.snapshot).toBe("stock-agent:v1");
    expect(call.envVars.JOB_ID).toBe("job-abc");
    expect(call.envVars.TRACEPARENT).toMatch(/^00-/);
    expect(call.envVars.OPENAI_API_URL).toBeUndefined();
    expect(call.envVars.OPENAI_MODEL).toBeUndefined();
    expect(call.envVars.SENTRY_DSN_AGENT).toBeUndefined();
    expect(call.envVars.DD_API_KEY).toBeUndefined();
  });

  it("forwards OPENAI_API_URL only when set", async () => {
    process.env.OPENAI_API_URL = "https://my-proxy.example.com/v1";
    const { spawnAnalysisSandbox } = await import("@/lib/daytona");
    const span = trace.getTracer("t").startSpan("p");
    await spawnAnalysisSandbox("job-url", span);
    span.end();
    const call = createMock.mock.calls.at(-1)![0] as any;
    expect(call.envVars.OPENAI_API_URL).toBe("https://my-proxy.example.com/v1");
  });

  it("forwards OPENAI_MODEL only when set", async () => {
    process.env.OPENAI_MODEL = "gpt-4.1";
    const { spawnAnalysisSandbox } = await import("@/lib/daytona");
    const span = trace.getTracer("t").startSpan("p");
    await spawnAnalysisSandbox("job-model", span);
    span.end();
    const call = createMock.mock.calls.at(-1)![0] as any;
    expect(call.envVars.OPENAI_MODEL).toBe("gpt-4.1");
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

  it("forwards DD_TRACE_ENABLED only when set", async () => {
    process.env.DD_TRACE_ENABLED = "false";
    const { spawnAnalysisSandbox } = await import("@/lib/daytona");
    const span = trace.getTracer("t").startSpan("p");
    await spawnAnalysisSandbox("job-dd-disabled", span);
    span.end();
    const call = createMock.mock.calls.at(-1)![0] as any;
    expect(call.envVars.DD_TRACE_ENABLED).toBe("false");
  });

  it("forwards DD_EXPORTER and DD_OTLP_ENDPOINT only when set", async () => {
    process.env.DD_EXPORTER = "otlp";
    process.env.DD_OTLP_ENDPOINT = "https://trace.agent.datadoghq.com/v1/traces";
    const { spawnAnalysisSandbox } = await import("@/lib/daytona");
    const span = trace.getTracer("t").startSpan("p");
    await spawnAnalysisSandbox("job-dd-otlp", span);
    span.end();
    const call = createMock.mock.calls.at(-1)![0] as any;
    expect(call.envVars.DD_EXPORTER).toBe("otlp");
    expect(call.envVars.DD_OTLP_ENDPOINT).toBe("https://trace.agent.datadoghq.com/v1/traces");
  });
});
