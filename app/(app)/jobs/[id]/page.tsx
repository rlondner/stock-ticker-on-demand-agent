import { notFound } from "next/navigation";
import { eq } from "drizzle-orm";
import { db, jobs } from "@/lib/db/client";
import { JobDetail } from "@/components/job-detail";

export const dynamic = "force-dynamic";

export default async function JobPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const rows = await db.select().from(jobs).where(eq(jobs.id, id)).limit(1);
  if (rows.length === 0) notFound();
  const row = rows[0];
  const initial = {
    ...row,
    createdAt: row.createdAt.toISOString(),
    startedAt: row.startedAt ? row.startedAt.toISOString() : null,
    completedAt: row.completedAt ? row.completedAt.toISOString() : null,
  };
  return (
    <main className="p-8 max-w-3xl mx-auto">
      <JobDetail initialJob={initial as any} />
    </main>
  );
}
