import { describe, it, expect, vi, beforeEach } from "vitest";

const initDatadogMock = vi.fn(() => true);
const initOtelMock = vi.fn();

vi.mock("@/lib/observability/exporters/datadog", () => ({
  initDatadogIfEnabled: initDatadogMock,
}));
vi.mock("@/lib/observability/otel", () => ({
  initOtel: initOtelMock,
}));

describe("instrumentation register()", () => {
  beforeEach(() => {
    initDatadogMock.mockClear();
    initOtelMock.mockClear();
  });

  it("initializes both Datadog and OTel on the nodejs runtime", async () => {
    process.env.NEXT_RUNTIME = "nodejs";
    const { register } = await import("@/instrumentation");
    await register();
    expect(initDatadogMock).toHaveBeenCalledTimes(1);
    expect(initOtelMock).toHaveBeenCalledTimes(1);
  });

  it("does nothing on non-nodejs runtimes", async () => {
    process.env.NEXT_RUNTIME = "edge";
    const { register } = await import("@/instrumentation");
    await register();
    expect(initDatadogMock).not.toHaveBeenCalled();
    expect(initOtelMock).not.toHaveBeenCalled();
  });
});
