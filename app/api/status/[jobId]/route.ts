import { and, eq, isNull } from "drizzle-orm";
import { db, jobs } from "@/lib/db/client";
import { traced, addAttrs } from "@/lib/observability/api";
import { sendCompletionNotification } from "@/lib/notify/one";

type Ctx = { params: Promise<{ jobId: string }> };

export async function GET(_req: Request, ctx: Ctx): Promise<Response> {
  const { jobId } = await ctx.params;
  return traced("api.status.get", { job_id: jobId }, async (span) => {
    const rows = await db.select().from(jobs).where(eq(jobs.id, jobId)).limit(1);
    if (rows.length === 0) {
      addAttrs(span, { outcome: "not_found" });
      return Response.json({ error: "not_found" }, { status: 404 });
    }
    let row = rows[0];
    addAttrs(span, { status: row.status });

    if (row.status === "complete" && row.notifyChannel && row.notifyDestination && !row.notifiedAt) {
      const notifyChannel = row.notifyChannel as "slack" | "gmail";
      const notifyDestination = row.notifyDestination;
      const claimed = await db
        .update(jobs)
        .set({ notifiedAt: new Date() })
        .where(and(eq(jobs.id, jobId), isNull(jobs.notifiedAt)))
        .returning({ id: jobs.id });
      if (claimed.length > 0) {
        const claimedAt = new Date();
        row = { ...row, notifiedAt: claimedAt };
        addAttrs(span, { notify_claimed: true });
        try {
          await sendCompletionNotification({
            ticker: row.ticker,
            recommendation: row.recommendation,
            summary: (row.result as { summary?: string } | null)?.summary,
            notifyChannel,
            notifyDestination,
          });
        } catch {
          // sendCompletionNotification already swallows its own errors and
          // never rejects; this catch is a last-resort guard so a future
          // change there can never break the status endpoint.
        }
      }
    }

    return Response.json(row);
  });
}
