import { context, propagation, trace, type Span } from "@opentelemetry/api";
import { W3CTraceContextPropagator } from "@opentelemetry/core";

let _propagatorReady = false;
function ensurePropagator(): void {
  if (_propagatorReady) return;
  propagation.setGlobalPropagator(new W3CTraceContextPropagator());
  _propagatorReady = true;
}

export function injectTraceparent(parentSpan: Span): string {
  ensurePropagator();
  const carrier: Record<string, string> = {};
  propagation.inject(trace.setSpan(context.active(), parentSpan), carrier);
  return carrier.traceparent ?? "";
}

export function forwardIfSet(k: string): Record<string, string> {
  return process.env[k] ? { [k]: process.env[k]! } : {};
}

export function datadogBlockIfEnabled(): Record<string, string> {
  if (!process.env.DD_API_KEY) return {};
  return {
    DD_API_KEY: process.env.DD_API_KEY,
    DD_SITE: process.env.DD_SITE ?? "datadoghq.com",
    DD_SERVICE: "stock-agent",
    DD_ENV: process.env.DD_ENV ?? process.env.NODE_ENV ?? "development",
  };
}
