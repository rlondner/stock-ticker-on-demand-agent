import { z } from "zod";
import { eq } from "drizzle-orm";
import { db, jobs } from "@/lib/db/client";
import { spawnAnalysisSandbox } from "@/lib/daytona";
import { traced, addAttrs, recordError } from "@/lib/observability/api";

const Body = z.object({
  ticker: z.string().regex(/^[A-Z]{1,5}$/, "ticker must be 1-5 uppercase letters"),
});

export async function POST(req: Request): Promise<Response> {
  return traced("api.jobs.post", { route: "POST /api/jobs" }, async (span) => {
    let parsed: z.infer<typeof Body>;
    try {
      parsed = Body.parse(await req.json());
    } catch (e) {
      addAttrs(span, { outcome: "rejected" });
      const msg = e instanceof z.ZodError ? e.issues[0]?.message ?? "invalid" : "invalid";
      return Response.json({ error: msg }, { status: 400 });
    }

    const [{ id: jobId }] = await db
      .insert(jobs)
      .values({ ticker: parsed.ticker })
      .returning({ id: jobs.id });
    addAttrs(span, { job_id: jobId, ticker: parsed.ticker });

    try {
      const sandboxId = await spawnAnalysisSandbox(jobId, span);
      await db.update(jobs).set({ sandboxId }).where(eq(jobs.id, jobId));
      addAttrs(span, { sandbox_id: sandboxId, outcome: "accepted" });
      return Response.json({ jobId });
    } catch (e) {
      recordError(span, e);
      await db
        .update(jobs)
        .set({ status: "failed", error: `sandbox_spawn_failed: ${e instanceof Error ? e.message : e}` })
        .where(eq(jobs.id, jobId));
      return Response.json({ error: "spawn_failed", jobId }, { status: 500 });
    }
  });
}
