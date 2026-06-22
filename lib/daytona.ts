import { Daytona } from "@daytonaio/sdk";
import { context, propagation, trace, type Span } from "@opentelemetry/api";
import { W3CTraceContextPropagator } from "@opentelemetry/core";

// Ensure a W3C trace-context propagator is registered so traceparent can be
// injected into the sandbox env even when the NodeSDK hasn't been started
// (e.g. in unit tests). NodeSDK installs the same propagator by default, so
// calling this in production is a harmless re-registration.
let _propagatorReady = false;
function ensurePropagator(): void {
  if (_propagatorReady) return;
  propagation.setGlobalPropagator(new W3CTraceContextPropagator());
  _propagatorReady = true;
}

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
  ensurePropagator();
  const carrier: Record<string, string> = {};
  propagation.inject(trace.setSpan(context.active(), parentSpan), carrier);

  const env: Record<string, string> = {
    JOB_ID: jobId,
    NEON_DATABASE_URL: process.env.NEON_DATABASE_URL!,
    OPENAI_API_KEY: process.env.OPENAI_API_KEY!,
    DAYTONA_API_KEY: process.env.DAYTONA_API_KEY!,
    TRACEPARENT: carrier.traceparent ?? "",
    ...forwardIfSet("SENTRY_DSN_AGENT"),
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

function forwardIfSet(k: string): Record<string, string> {
  return process.env[k] ? { [k]: process.env[k]! } : {};
}

function datadogBlockIfEnabled(): Record<string, string> {
  if (!process.env.DD_API_KEY) return {};
  return {
    DD_API_KEY: process.env.DD_API_KEY,
    DD_SITE: process.env.DD_SITE ?? "datadoghq.com",
    DD_SERVICE: "stock-agent",
    DD_ENV: process.env.DD_ENV ?? process.env.NODE_ENV ?? "development",
  };
}
