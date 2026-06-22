import { trace, SpanStatusCode, type Span } from "@opentelemetry/api";

const tracer = trace.getTracer("stock-agent-frontend");

export async function traced<T>(
  name: string,
  attrs: Record<string, string | number | boolean> | undefined,
  fn: (span: Span) => Promise<T>,
): Promise<T> {
  return tracer.startActiveSpan(name, async (span) => {
    if (attrs) for (const [k, v] of Object.entries(attrs)) span.setAttribute(k, v);
    try {
      return await fn(span);
    } catch (e) {
      recordError(span, e);
      throw e;
    } finally {
      span.end();
    }
  });
}

export function recordError(span: Span, e: unknown): void {
  const err = e instanceof Error ? e : new Error(String(e));
  span.recordException(err);
  span.setStatus({ code: SpanStatusCode.ERROR, message: err.message });
}

export function addAttrs(span: Span, attrs: Record<string, string | number | boolean>): void {
  for (const [k, v] of Object.entries(attrs)) span.setAttribute(k, v);
}
