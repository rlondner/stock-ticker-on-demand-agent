"use client";
import { useEffect, useState } from "react";
import { StockHeader } from "./stock-header";
import { InvestmentThesis } from "./investment-thesis";
import { RawLLMResponse } from "./raw-llm-response";
import { AnalystSentiment } from "./analyst-sentiment";
import { formatCompactDate } from "@/lib/ui/format-timestamp";
import type { SerializedJob } from "@/lib/job/types";

export function JobLivePoller({ initialJob }: { initialJob: SerializedJob }) {
  const [job, setJob] = useState<SerializedJob>(initialJob);
  const [nowMs, setNowMs] = useState<number>(() => Date.now());

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

  useEffect(() => {
    if (job.status !== "pending" && job.status !== "running") return;
    const id = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(id);
  }, [job.status]);

  const endMs = job.completedAt ? new Date(job.completedAt).getTime() : nowMs;
  const elapsedSeconds = Math.round(
    (endMs - new Date(job.createdAt).getTime()) / 1000,
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
        snapshot={job.result?.snapshot ?? null}
        notifyChannel={job.notifyChannel}
        notifiedAt={job.notifiedAt}
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
          <InvestmentThesis result={job.result ?? null} lastUpdatedLabel={lastUpdatedLabel} />
          <section className="grid grid-cols-12 gap-6">
            <RawLLMResponse result={job.result} />
            <AnalystSentiment snapshot={job.result?.snapshot ?? null} />
          </section>
        </>
      )}
    </div>
  );
}
