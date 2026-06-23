import type { Span } from "@opentelemetry/api";
import { spawnAnalysisSandbox } from "@/lib/daytona";
import { spawnAnalysisSubprocess } from "@/lib/runtime/subprocess";

export async function spawnAgent(jobId: string, parentSpan: Span): Promise<string> {
  const runtime = process.env.AGENT_RUNTIME ?? "daytona";
  switch (runtime) {
    case "daytona":
      return spawnAnalysisSandbox(jobId, parentSpan);
    case "subprocess":
      return spawnAnalysisSubprocess(jobId, parentSpan);
    default:
      throw new Error(`unknown AGENT_RUNTIME=${runtime} (expected 'daytona' or 'subprocess')`);
  }
}
