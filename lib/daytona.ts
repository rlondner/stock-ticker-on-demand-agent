import { Daytona } from "@daytonaio/sdk";
import { type Span } from "@opentelemetry/api";
import { injectTraceparent, forwardIfSet, datadogBlockIfEnabled } from "./runtime/env";

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
    ...datadogBlockIfEnabled(),
  };

  const sandbox = await client().create({
    snapshot: "stock-agent:latest",
    envVars: env,
    autoStopInterval: 0,
    autoDeleteInterval: 600,
  });
  return sandbox.id;
}
