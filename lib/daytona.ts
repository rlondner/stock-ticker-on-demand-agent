import os from "node:os";
import { Daytona } from "@daytonaio/sdk";
import { type Span } from "@opentelemetry/api";
import * as Sentry from "@sentry/nextjs";
import { injectTraceparent, forwardIfSet, datadogBlockIfEnabled } from "./runtime/env";
import { ddLog, ddMetric } from "./observability/exporters/datadog";

let _dt: Daytona | undefined;
function client(): Daytona {
  if (!_dt) {
    const apiKey = process.env.DAYTONA_API_KEY;
    if (!apiKey) throw new Error("DAYTONA_API_KEY is not set");
    _dt = new Daytona({ apiKey });
  }
  return _dt;
}

export async function spawnAnalysisSandbox(jobId: string, parentSpan: Span): Promise<string> {
  const env: Record<string, string> = {
    JOB_ID: jobId,
    NEON_DATABASE_URL: process.env.NEON_DATABASE_URL!,
    OPENAI_API_KEY: process.env.OPENAI_API_KEY!,
    DAYTONA_API_KEY: process.env.DAYTONA_API_KEY!,
    TRACEPARENT: injectTraceparent(parentSpan),
    ...forwardIfSet("OPENAI_API_URL"),
    ...forwardIfSet("OPENAI_MODEL"),
    ...forwardIfSet("OPENAI_USE_RESPONSES_API"),
    ...forwardIfSet("SENTRY_DSN_AGENT"),
    ...forwardIfSet("DD_TRACE_ENABLED"),
    ...forwardIfSet("DD_EXPORTER"),
    ...forwardIfSet("DD_OTLP_ENDPOINT"),
    ...datadogBlockIfEnabled(),
  };

  Sentry.logger?.info?.("daytona.spawn.requested", {
    host: os.hostname(),
    job_id: jobId,
    snapshot: "stock-agent:v1",
    target: process.env.DAYTONA_TARGET,
  });
  ddLog("info", "daytona.spawn.requested", {
    job_id: jobId,
    snapshot: "stock-agent:v1",
    target: process.env.DAYTONA_TARGET ?? "",
  });

  const startedAt = Date.now();
  const sandbox = await client().create({
    snapshot: "stock-agent:v1",
    envVars: env,
    autoStopInterval: 0,
    autoDeleteInterval: 600,
  });
  const durationMs = Date.now() - startedAt;

  // Daytona doesn't auto-run the image's Dockerfile CMD — the sandbox boots
  // idle so the SDK can attach. Kick off the agent explicitly in a background
  // session so this call returns to the caller immediately.
  const sessionId = `agent-${jobId}`;
  await sandbox.process.createSession(sessionId);
  await sandbox.process.executeSessionCommand(sessionId, {
    command: "python /app/agent.py",
    runAsync: true,
  });

  parentSpan.setAttribute("host", os.hostname());
  parentSpan.setAttribute("daytona.spawn.duration_ms", durationMs);
  parentSpan.setAttribute("daytona.sandbox_id", sandbox.id);

  Sentry.logger?.info?.("daytona.spawn.completed", {
    host: os.hostname(),
    job_id: jobId,
    sandbox_id: sandbox.id,
    duration_ms: durationMs,
  });
  ddLog("info", "daytona.spawn.completed", {
    job_id: jobId,
    sandbox_id: sandbox.id,
    duration_ms: durationMs,
  });
  ddMetric("daytona.spawn.duration_ms", durationMs, { sandbox_id: sandbox.id });

  return sandbox.id;
}
