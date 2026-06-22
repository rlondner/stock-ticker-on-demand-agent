import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { desc, eq } from "drizzle-orm";
import { db, jobs } from "@/lib/db/client";

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  pending: "outline",
  running: "secondary",
  complete: "default",
  failed: "destructive",
};

export async function JobsList() {
  const rows = await db
    .select()
    .from(jobs)
    .where(eq(jobs.userId, "demo-user"))
    .orderBy(desc(jobs.createdAt))
    .limit(20);

  if (rows.length === 0) return <p className="text-sm text-slate-500">No jobs yet.</p>;

  return (
    <ul className="space-y-1">
      {rows.map((j) => (
        <li key={j.id}>
          <Link href={`/jobs/${j.id}`} className="flex items-center gap-3 p-2 rounded hover:bg-slate-50">
            <span className="font-mono w-16">{j.ticker}</span>
            <Badge variant={STATUS_VARIANT[j.status] ?? "outline"}>{j.status}</Badge>
            {j.recommendation && <Badge variant="default">{j.recommendation.toUpperCase()}</Badge>}
            <span className="text-xs text-slate-500 ml-auto">{j.createdAt.toISOString()}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
