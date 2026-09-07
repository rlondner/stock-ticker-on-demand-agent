import { z } from "zod";
import { eq } from "drizzle-orm";
import { db, jobs } from "@/lib/db/client";
import { spawnAgent } from "@/lib/runtime";
import { traced, addAttrs, recordError } from "@/lib/observability/api";
import { jobsSubmitted } from "@/lib/observability/metrics";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const SLACK_DEST_RE = /^[#@][\w-]+$/;

const Body = z.object({
  ticker: z.string().regex(/^[A-Z]{1,5}$/, "ticker must be 1-5 uppercase letters"),
  notifyChannel: z.enum(["slack", "gmail"]).optional(),
  notifyDestination: z.string().optional(),
})
  .refine((b) => !b.notifyChannel || !!b.notifyDestination, {
    message: "notifyDestination is required when notifyChannel is set",
    path: ["notifyDestination"],
  })
  .refine((b) => b.notifyChannel !== "gmail" || !b.notifyDestination || EMAIL_RE.test(b.notifyDestination), {
    message: "notifyDestination must be a valid email address for gmail",
    path: ["notifyDestination"],
  })
  .refine((b) => b.notifyChannel !== "slack" || !b.notifyDestination || SLACK_DEST_RE.test(b.notifyDestination), {
    message: "notifyDestination must start with # (channel) or @ (user) for slack",
    path: ["notifyDestination"],
  });

export async function POST(req: Request): Promise<Response> {
  return traced("api.jobs.post", { route: "POST /api/jobs" }, async (span) => {
    let parsed: z.infer<typeof Body>;
    try {
      parsed = Body.parse(await req.json());
    } catch (e) {
      addAttrs(span, { outcome: "rejected" });
      jobsSubmitted("rejected", "unknown");
      const msg = e instanceof z.ZodError ? e.issues[0]?.message ?? "invalid" : "invalid";
      return Response.json({ error: msg }, { status: 400 });
    }

    if (parsed.notifyChannel && !process.env.ONE_SECRET) {
      addAttrs(span, { outcome: "rejected" });
      jobsSubmitted("rejected", parsed.ticker);
      return Response.json({ error: "notifications are not configured on this server" }, { status: 400 });
    }

    const [{ id: jobId }] = await db
      .insert(jobs)
      .values({ ticker: parsed.ticker, notifyChannel: parsed.notifyChannel, notifyDestination: parsed.notifyDestination })
      .returning({ id: jobs.id });
    addAttrs(span, { job_id: jobId, ticker: parsed.ticker });

    try {
      const sandboxId = await spawnAgent(jobId, span);
      await db.update(jobs).set({ sandboxId }).where(eq(jobs.id, jobId));
      addAttrs(span, { sandbox_id: sandboxId, outcome: "accepted" });
      jobsSubmitted("accepted", parsed.ticker);
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
