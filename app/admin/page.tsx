import { desc } from "drizzle-orm";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { db, jobs } from "@/lib/db/client";

export const dynamic = "force-dynamic";

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  pending: "outline",
  running: "secondary",
  complete: "default",
  failed: "destructive",
};

export default async function AdminPage() {
  const rows = await db.select().from(jobs).orderBy(desc(jobs.createdAt)).limit(50);
  const durationSec = (r: typeof rows[number]): number | null => {
    if (!r.completedAt) return null;
    return Math.round((r.completedAt.getTime() - r.createdAt.getTime()) / 1000);
  };

  return (
    <main className="p-8 max-w-6xl mx-auto space-y-4">
      <h1 className="text-2xl font-bold">Admin · Recent jobs</h1>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-slate-500 border-b">
            <th className="py-2">id</th>
            <th>ticker</th>
            <th>status</th>
            <th>rec</th>
            <th>dur (s)</th>
            <th>created</th>
            <th>error</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-b">
              <td className="py-1">
                <Link href={`/jobs/${r.id}`} className="font-mono text-xs text-blue-700">{r.id.slice(0, 8)}</Link>
              </td>
              <td className="font-mono">{r.ticker}</td>
              <td><Badge variant={STATUS_VARIANT[r.status]}>{r.status}</Badge></td>
              <td>{r.recommendation ?? ""}</td>
              <td>{durationSec(r) ?? ""}</td>
              <td className="text-xs text-slate-500">{r.createdAt.toISOString()}</td>
              <td className="text-xs text-red-600 truncate max-w-xs">{r.error?.slice(0, 80) ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
