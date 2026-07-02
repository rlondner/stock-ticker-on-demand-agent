import os from "node:os";

export function initDatadogIfEnabled(): boolean {
  if (!process.env.DD_API_KEY) return false;
  // dd-trace ships to a local Datadog Agent on localhost:8126 by default.
  // Set DD_TRACE_ENABLED=false in .env when running locally without an Agent
  // to silence the "failed to send, dropping N traces" warnings.
  if ((process.env.DD_TRACE_ENABLED ?? "").trim().toLowerCase() === "false") return false;
  const tracer = require("dd-trace").init({
    service: process.env.DD_SERVICE ?? "stock-agent-frontend",
    env: process.env.DD_ENV ?? process.env.NODE_ENV ?? "development",
    logInjection: true,
  });
  return !!tracer;
}

function ddEnabled(): boolean {
  if (!process.env.DD_API_KEY) return false;
  return (process.env.DD_TRACE_ENABLED ?? "").trim().toLowerCase() !== "false";
}

function ddSite(): string {
  return (process.env.DD_SITE ?? "").trim() || "datadoghq.com";
}

function commonTags(extra?: Record<string, string | number>): string[] {
  const tags = [
    `env:${process.env.DD_ENV ?? process.env.NODE_ENV ?? "development"}`,
    `service:${process.env.DD_SERVICE ?? "stock-agent-frontend"}`,
    `host:${os.hostname()}`,
  ];
  if (extra) for (const [k, v] of Object.entries(extra)) tags.push(`${k}:${v}`);
  return tags;
}

/**
 * Fire-and-forget POST to Datadog's HTTP log intake. Never awaited — the
 * request handler shouldn't wait on telemetry.
 */
export function ddLog(
  level: "debug" | "info" | "warn" | "error",
  message: string,
  attributes: Record<string, string | number | boolean> = {},
): void {
  if (!ddEnabled()) return;
  const payload = {
    ddsource: "nodejs",
    service: process.env.DD_SERVICE ?? "stock-agent-frontend",
    hostname: os.hostname(),
    status: level,
    message,
    ddtags: commonTags().join(","),
    ...attributes,
  };
  void fetch(`https://http-intake.logs.${ddSite()}/api/v2/logs`, {
    method: "POST",
    headers: {
      "DD-API-KEY": process.env.DD_API_KEY!,
      "Content-Type": "application/json",
    },
    body: JSON.stringify([payload]),
  }).catch(() => {});
}

/**
 * Fire-and-forget POST of a single gauge point to Datadog's v2 metrics
 * intake. (Sentry sunset custom metrics in Oct 2024, so this is DD-only —
 * on the Sentry side the equivalent lives as a span attribute.)
 */
export function ddMetric(
  name: string,
  value: number,
  tags: Record<string, string | number> = {},
): void {
  if (!ddEnabled()) return;
  const payload = {
    series: [{
      metric: name,
      type: 3,
      points: [{ timestamp: Math.floor(Date.now() / 1000), value }],
      tags: commonTags(tags),
      resources: [{ type: "host", name: os.hostname() }],
    }],
  };
  void fetch(`https://api.${ddSite()}/api/v2/series`, {
    method: "POST",
    headers: {
      "DD-API-KEY": process.env.DD_API_KEY!,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  }).catch(() => {});
}
