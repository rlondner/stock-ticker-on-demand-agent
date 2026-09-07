import { and, eq, inArray, sql } from "drizzle-orm";
import { db, jobs } from "@/lib/db/client";
import type { Depth } from "@/lib/db/schema";
import { autoDeleteIntervalFor } from "@/lib/daytona";
import { traced, addAttrs } from "@/lib/observability/api";

// A job should only be swept once its sandbox is GUARANTEED to be gone --
// i.e. the sweep threshold per tier must be at or above that tier's Daytona
// autoDeleteInterval, with margin. Sweeping earlier doesn't recover a truly
// stuck sandbox, it preempts a healthy one: the pre-existing flat 10min
// threshold routinely killed deep (~8min)/full (~20min) jobs still legitimately
// running, and because mark_complete's SQL guard is
// `WHERE id=%s AND status IN ('pending','running')`, a swept-to-`failed` row
// is never updated when the crew later succeeds -- the real result is
// silently discarded.
const SWEEP_GRACE_S = 90;

function sweepThresholdMs(depth: Depth): number {
  return (autoDeleteIntervalFor(depth) + SWEEP_GRACE_S) * 1000;
}

export async function POST(_req: Request): Promise<Response> {
  return traced("api.cleanup.post", undefined, async (span) => {
    const candidates = await db
      .select({ id: jobs.id, depth: jobs.depth, startedAt: jobs.startedAt })
      .from(jobs)
      .where(eq(jobs.status, "running"));

    const now = Date.now();
    const staleIds = candidates
      .filter((job) => {
        if (!job.startedAt) return false;
        const depth = (job.depth as Depth) ?? "quick";
        const age = now - new Date(job.startedAt).getTime();
        return age > sweepThresholdMs(depth);
      })
      .map((job) => job.id);

    if (staleIds.length === 0) {
      addAttrs(span, { swept: 0 });
      return Response.json({ swept: 0 });
    }

    const swept = await db
      .update(jobs)
      .set({ status: "failed", error: "timeout", completedAt: sql`now()` })
      .where(and(eq(jobs.status, "running"), inArray(jobs.id, staleIds)))
      .returning({ id: jobs.id });
    addAttrs(span, { swept: swept.length });
    return Response.json({ swept: swept.length });
  });
}
