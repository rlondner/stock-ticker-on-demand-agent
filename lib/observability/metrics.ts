import { MeterProvider, PeriodicExportingMetricReader, type MetricReader } from "@opentelemetry/sdk-metrics";
import { metrics as otelMetrics, type Counter } from "@opentelemetry/api";

let provider: MeterProvider | undefined;
let jobsSubmittedCounter: Counter | undefined;
let sentryEnabled = false;

function metricsEndpoint(tracesEndpoint: string): string {
  const override = process.env.DD_OTLP_METRICS_ENDPOINT;
  if (override) return override;
  if (tracesEndpoint.endsWith("/v1/traces")) {
    return tracesEndpoint.slice(0, -"/v1/traces".length) + "/v1/metrics";
  }
  return tracesEndpoint;
}

export function buildJobAttrs(outcome: string, ticker: string): Record<string, string> {
  return { outcome, ticker };
}

export function initMetrics(opts?: { readers?: MetricReader[] }): void {
  if (provider) return;
  try {
    const readers: MetricReader[] = [...(opts?.readers ?? [])];

    const ddKey = process.env.DD_API_KEY;
    const ddDisabled = (process.env.DD_TRACE_ENABLED ?? "").trim().toLowerCase() === "false";
    const ddExporter = (process.env.DD_EXPORTER ?? "agent").trim().toLowerCase();
    const otlpEndpoint = process.env.DD_OTLP_ENDPOINT;
    if (ddKey && !ddDisabled && ddExporter === "otlp" && otlpEndpoint) {
      // Lazy require keeps the OTLP exporter out of edge/browser bundles.
      const { OTLPMetricExporter } = require("@opentelemetry/exporter-metrics-otlp-http");
      readers.push(new PeriodicExportingMetricReader({
        exporter: new OTLPMetricExporter({
          url: metricsEndpoint(otlpEndpoint),
          headers: { "DD-API-KEY": ddKey },
        }),
      }));
    }

    provider = new MeterProvider({ readers });
    otelMetrics.setGlobalMeterProvider(provider);
    const meter = provider.getMeter("stock-agent-frontend");
    jobsSubmittedCounter = meter.createCounter("jobs.submitted");
    sentryEnabled = !!process.env.SENTRY_DSN_NEXTJS;
  } catch {
    /* metrics init must never throw to caller */
  }
}

function sentryIncr(key: string, value: number, tags: Record<string, string>): void {
  if (!sentryEnabled) return;
  try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const Sentry = require("@sentry/nextjs");
    Sentry?.metrics?.count?.(key, value, { attributes: tags });
  } catch {
    /* metrics must never break a request */
  }
}

export function jobsSubmitted(outcome: string, ticker: string): void {
  const attrs = buildJobAttrs(outcome, ticker);
  try {
    jobsSubmittedCounter?.add(1, attrs);
  } catch {
    /* no-op */
  }
  sentryIncr("jobs.submitted", 1, attrs);
}

export async function forceFlushMetrics(): Promise<void> {
  try {
    await provider?.forceFlush();
  } catch {
    /* no-op */
  }
}
