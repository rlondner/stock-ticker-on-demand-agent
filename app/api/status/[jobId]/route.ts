import { eq } from "drizzle-orm";
import { db, jobs } from "@/lib/db/client";
import { traced, addAttrs } from "@/lib/observability/api";
import { triggerCompletionNotificationIfDue } from "@/lib/notify/trigger";

type Ctx = { params: Promise<{ jobId: string }> };

export async function GET(_req: Request, ctx: Ctx): Promise<Response> {
  const { jobId } = await ctx.params;
  return traced("api.status.get", { job_id: jobId }, async (span) => {
    const rows = await db.select().from(jobs).where(eq(jobs.id, jobId)).limit(1);
    if (rows.length === 0) {
      addAttrs(span, { outcome: "not_found" });
      return Response.json({ error: "not_found" }, { status: 404 });
    }
    addAttrs(span, { status: rows[0].status });
    const row = await triggerCompletionNotificationIfDue(jobId, rows[0], span);

    return Response.json(row);
  });
}
