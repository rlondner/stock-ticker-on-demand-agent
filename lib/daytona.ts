import type { Span } from "@opentelemetry/api";

// Real implementation lands in Task 8. For now this stub lets the API route
// be tested independently.
export async function spawnAnalysisSandbox(_jobId: string, _parentSpan: Span): Promise<string> {
  return "sb-stub";
}
