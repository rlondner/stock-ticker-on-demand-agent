export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    const { initDatadogIfEnabled } = await import("./lib/observability/exporters/datadog");
    initDatadogIfEnabled();
    const { initOtel } = await import("./lib/observability/otel");
    initOtel();
  }
}
