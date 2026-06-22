import { and, eq, lt, sql } from "drizzle-orm";
import { db, jobs } from "@/lib/db/client";
import { traced, addAttrs } from "@/lib/observability/api";

export async function POST(_req: Request): Promise<Response> {
  return traced("api.cleanup.post", undefined, async (span) => {
    const tenMinAgo = new Date(Date.now() - 10 * 60 * 1000);
    const swept = await db
      .update(jobs)
      .set({ status: "failed", error: "timeout", completedAt: sql`now()` })
      .where(and(eq(jobs.status, "running"), lt(jobs.startedAt, tenMinAgo)))
      .returning({ id: jobs.id });
    addAttrs(span, { swept: swept.length });
    return Response.json({ swept: swept.length });
  });
}
