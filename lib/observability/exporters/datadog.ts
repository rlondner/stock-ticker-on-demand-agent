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
