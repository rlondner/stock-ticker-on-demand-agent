export function initDatadogIfEnabled(): boolean {
  if (!process.env.DD_API_KEY) return false;
  const tracer = require("dd-trace").init({
    service: process.env.DD_SERVICE ?? "stock-agent-frontend",
    env: process.env.DD_ENV ?? process.env.NODE_ENV ?? "development",
    logInjection: true,
  });
  return !!tracer;
}
