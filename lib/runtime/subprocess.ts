import type { Span } from "@opentelemetry/api";

export async function spawnAnalysisSubprocess(_jobId: string, _parentSpan: Span): Promise<string> {
  throw new Error("not implemented yet");
}
