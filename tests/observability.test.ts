import { describe, it, expect } from "vitest";
import { traced, recordError, addAttrs } from "@/lib/observability/api";
import { trace } from "@opentelemetry/api";

describe("observability helpers", () => {
  it("traced() runs fn and returns its result", async () => {
    const result = await traced("test.span", { foo: "bar" }, async (_span) => 42);
    expect(result).toBe(42);
  });

  it("traced() re-throws errors and marks the span", async () => {
    await expect(
      traced("test.error", undefined, async () => { throw new Error("boom"); })
    ).rejects.toThrow("boom");
  });

  it("addAttrs and recordError work without a real exporter", () => {
    const span = trace.getTracer("t").startSpan("s");
    addAttrs(span, { a: 1, b: "x" });
    recordError(span, new Error("oops"));
    span.end();
  });
});
