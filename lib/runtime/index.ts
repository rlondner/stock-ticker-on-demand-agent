import type { Span } from "@opentelemetry/api";
import type { Depth } from "@/lib/db/schema";
import { spawnAnalysisSandbox } from "@/lib/daytona";
import { spawnAnalysisSubprocess } from "@/lib/runtime/subprocess";

export async function spawnAgent(jobId: string, depth: Depth, parentSpan: Span): Promise<string> {
  const runtime = process.env.AGENT_RUNTIME ?? "daytona";
  switch (runtime) {
    case "daytona":
      return spawnAnalysisSandbox(jobId, depth, parentSpan);
    case "subprocess":
      return spawnAnalysisSubprocess(jobId, depth, parentSpan);
    default:
      throw new Error(`unknown AGENT_RUNTIME=${runtime} (expected 'daytona' or 'subprocess')`);
  }
}
