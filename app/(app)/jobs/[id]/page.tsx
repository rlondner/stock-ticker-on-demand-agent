import { notFound } from "next/navigation";
import { eq } from "drizzle-orm";
import { db, jobs } from "@/lib/db/client";
import { JobLivePoller } from "@/components/job/job-live-poller";
import type { SerializedJob } from "@/lib/job/types";

export const dynamic = "force-dynamic";

export default async function JobPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const rows = await db.select().from(jobs).where(eq(jobs.id, id)).limit(1);
  if (rows.length === 0) notFound();
  const row = rows[0];
  const initial: SerializedJob = {
    id: row.id,
    ticker: row.ticker,
    status: row.status as SerializedJob["status"],
    recommendation: row.recommendation as SerializedJob["recommendation"],
    result: (row.result as SerializedJob["result"]) ?? null,
    error: row.error ?? null,
    sandboxId: row.sandboxId ?? null,
    depth: row.depth as SerializedJob["depth"],
    createdAt: row.createdAt.toISOString(),
    startedAt: row.startedAt ? row.startedAt.toISOString() : null,
    completedAt: row.completedAt ? row.completedAt.toISOString() : null,
  };
  return <JobLivePoller initialJob={initial} />;
}
