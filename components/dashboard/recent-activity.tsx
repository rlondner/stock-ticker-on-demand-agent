import Link from "next/link";
import { desc, eq, sql } from "drizzle-orm";
import { db, jobs } from "@/lib/db/client";
import { StatusPill } from "@/components/ui/status-pill";
import { SignalPill } from "@/components/ui/signal-pill";
import { formatMockTimestamp } from "@/lib/ui/format-timestamp";
import type { JobStatus } from "@/lib/ui/status-pill";
import type { Recommendation } from "@/lib/ui/signal-pill";

const PAGE_SIZE = 10;

export async function RecentActivity() {
  const rows = await db
    .select({
      id: jobs.id,
      ticker: jobs.ticker,
      status: jobs.status,
      recommendation: jobs.recommendation,
      createdAt: jobs.createdAt,
    })
    .from(jobs)
    .where(eq(jobs.userId, "demo-user"))
    .orderBy(desc(jobs.createdAt))
    .limit(PAGE_SIZE);

  const totalRows = await db
    .select({ count: sql<number>`count(*)::int` })
    .from(jobs)
    .where(eq(jobs.userId, "demo-user"));
  const total = totalRows[0]?.count ?? rows.length;

  return (
    <section className="col-span-12">
      <div className="bg-af-surface-container-lowest border border-af-outline-variant rounded-xl overflow-hidden">
        <div className="px-8 py-6 border-b border-af-outline-variant">
          <h3 className="text-2xl font-semibold text-af-on-surface">Recent Activity</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-af-surface-container-low">
                <th className="px-8 py-4 text-[12px] font-semibold text-af-on-surface-variant uppercase tracking-wider">Ticker</th>
                <th className="px-8 py-4 text-[12px] font-semibold text-af-on-surface-variant uppercase tracking-wider">Analysis Status</th>
                <th className="px-8 py-4 text-[12px] font-semibold text-af-on-surface-variant uppercase tracking-wider">Signal</th>
                <th className="px-8 py-4 text-[12px] font-semibold text-af-on-surface-variant uppercase tracking-wider">Timestamp</th>
                <th className="px-8 py-4 text-[12px] font-semibold text-af-on-surface-variant uppercase tracking-wider text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-af-outline-variant">
              {rows.length === 0 && (
                <tr>
                  <td className="px-8 py-8 text-af-on-surface-variant text-sm" colSpan={5}>
                    No analyses yet. Click &quot;New Analysis&quot; to start.
                  </td>
                </tr>
              )}
              {rows.map((r) => (
                <tr key={r.id} className="hover:bg-af-surface-container-low transition-colors">
                  <td className="px-8 py-6">
                    <Link href={`/jobs/${r.id}`} className="flex items-center gap-4">
                      <div className="w-8 h-8 rounded bg-af-surface-container-high flex items-center justify-center font-bold text-af-on-surface">
                        {r.ticker.charAt(0)}
                      </div>
                      <span className="font-bold text-af-on-surface">{r.ticker}</span>
                    </Link>
                  </td>
                  <td className="px-8 py-6">
                    <StatusPill status={r.status as JobStatus} />
                  </td>
                  <td className="px-8 py-6">
                    <SignalPill recommendation={r.recommendation as Recommendation | null} />
                  </td>
                  <td className="px-8 py-6 text-sm text-af-on-surface-variant">
                    {formatMockTimestamp(r.createdAt)}
                  </td>
                  <td className="px-8 py-6 text-right">
                    <button
                      type="button"
                      aria-label="row actions"
                      className="p-2 text-af-on-surface-variant hover:text-af-on-surface rounded-full hover:bg-af-surface-container transition-all"
                    >
                      <span className="material-symbols-outlined">more_vert</span>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="px-8 py-4 bg-af-surface-container-low flex items-center justify-between">
          <p className="text-[12px] text-af-on-surface-variant">
            Showing {rows.length} of {total} analysis jobs
          </p>
          <div className="flex gap-2">
            <button type="button" aria-label="previous page" className="p-1 text-af-on-surface-variant hover:text-af-on-surface">
              <span className="material-symbols-outlined">chevron_left</span>
            </button>
            <button type="button" aria-label="next page" className="p-1 text-af-on-surface-variant hover:text-af-on-surface">
              <span className="material-symbols-outlined">chevron_right</span>
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
