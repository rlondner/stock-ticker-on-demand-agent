import { describe, it, expect, vi, beforeEach } from "vitest";
import { trace } from "@opentelemetry/api";
import { BasicTracerProvider } from "@opentelemetry/sdk-trace-base";

const daytonaMock = vi.fn(async () => "sb-from-daytona");
const subprocessMock = vi.fn(async () => "local-from-subprocess");

vi.mock("@/lib/daytona", () => ({ spawnAnalysisSandbox: daytonaMock }));
vi.mock("@/lib/runtime/subprocess", () => ({ spawnAnalysisSubprocess: subprocessMock }));

trace.setGlobalTracerProvider(new BasicTracerProvider());

describe("spawnAgent dispatcher", () => {
  beforeEach(() => {
    delete process.env.AGENT_RUNTIME;
    daytonaMock.mockClear();
    subprocessMock.mockClear();
  });

  it("defaults to daytona when AGENT_RUNTIME is unset", async () => {
    const { spawnAgent } = await import("@/lib/runtime");
    const span = trace.getTracer("t").startSpan("p");
    const id = await spawnAgent("job-1", "quick", span);
    span.end();
    expect(daytonaMock).toHaveBeenCalledWith("job-1", "quick", span);
    expect(subprocessMock).not.toHaveBeenCalled();
    expect(id).toBe("sb-from-daytona");
  });

  it("dispatches to daytona when AGENT_RUNTIME=daytona", async () => {
    process.env.AGENT_RUNTIME = "daytona";
    const { spawnAgent } = await import("@/lib/runtime");
    const span = trace.getTracer("t").startSpan("p");
    await spawnAgent("job-2", "quick", span);
    span.end();
    expect(daytonaMock).toHaveBeenCalledWith("job-2", "quick", span);
    expect(subprocessMock).not.toHaveBeenCalled();
  });

  it("dispatches to subprocess when AGENT_RUNTIME=subprocess", async () => {
    process.env.AGENT_RUNTIME = "subprocess";
    const { spawnAgent } = await import("@/lib/runtime");
    const span = trace.getTracer("t").startSpan("p");
    const id = await spawnAgent("job-3", "quick", span);
    span.end();
    expect(subprocessMock).toHaveBeenCalledWith("job-3", "quick", span);
    expect(daytonaMock).not.toHaveBeenCalled();
    expect(id).toBe("local-from-subprocess");
  });

  it("throws on unknown AGENT_RUNTIME value", async () => {
    process.env.AGENT_RUNTIME = "kubernetes";
    const { spawnAgent } = await import("@/lib/runtime");
    const span = trace.getTracer("t").startSpan("p");
    await expect(spawnAgent("job-4", "quick", span)).rejects.toThrow(/unknown AGENT_RUNTIME/i);
    span.end();
  });
});
