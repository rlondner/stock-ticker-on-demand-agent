"use client";
import { useEffect, useState } from "react";
import { StockHeader } from "./stock-header";
import { KeyInsights } from "./key-insights";
import { RevenueDistribution } from "./revenue-distribution";
import { AnalystSentiment } from "./analyst-sentiment";
import { formatCompactDate } from "@/lib/ui/format-timestamp";
import type { SerializedJob } from "@/lib/job/types";

export function JobLivePoller({ initialJob }: { initialJob: SerializedJob }) {
  const [job, setJob] = useState<SerializedJob>(initialJob);

  useEffect(() => {
    if (job.status === "complete" || job.status === "failed") return;
    const id = setInterval(async () => {
      const res = await fetch(`/api/status/${job.id}`);
      if (!res.ok) return;
      const next: SerializedJob = await res.json();
      setJob(next);
      if (next.status === "complete" || next.status === "failed") clearInterval(id);
    }, 2500);
    return () => clearInterval(id);
  }, [job.id, job.status]);

  const elapsedSeconds = Math.round(
    ((job.completedAt ? new Date(job.completedAt).getTime() : Date.now()) -
      new Date(job.createdAt).getTime()) /
      1000,
  );

  const lastUpdatedLabel = job.completedAt
    ? formatCompactDate(new Date(job.completedAt))
    : "Just now";

  return (
    <div className="space-y-8">
      <StockHeader
        ticker={job.ticker}
        status={job.status}
        recommendation={job.recommendation}
        summary={job.result?.summary ?? null}
      />

      {(job.status === "pending" || job.status === "running") && (
        <>
          <p className="text-sm text-af-on-surface-variant">
            Sandbox {job.sandboxId ?? "spawning…"} · {elapsedSeconds}s elapsed
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            {Array.from({ length: 4 }, (_, i) => (
              <div key={i} className="bg-af-surface-container-low animate-pulse rounded-xl h-56" />
            ))}
          </div>
          <div className="grid grid-cols-12 gap-6">
            <div className="col-span-12 lg:col-span-8 bg-af-surface-container-low animate-pulse rounded-xl h-96" />
            <div className="col-span-12 lg:col-span-4 bg-af-surface-container-low animate-pulse rounded-xl h-96" />
          </div>
        </>
      )}

      {job.status === "failed" && (
        <div className="bg-af-error-container rounded-xl p-6">
          <pre className="text-xs whitespace-pre-wrap text-af-on-error-container">{job.error}</pre>
        </div>
      )}

      {job.status === "complete" && (
        <>
          <KeyInsights signals={job.result?.signals ?? null} lastUpdatedLabel={lastUpdatedLabel} />
          <section className="grid grid-cols-12 gap-6">
            <RevenueDistribution />
            <AnalystSentiment />
          </section>
        </>
      )}
    </div>
  );
}
