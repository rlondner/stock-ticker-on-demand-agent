"use client";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";

type Job = {
  id: string;
  ticker: string;
  status: "pending" | "running" | "complete" | "failed";
  recommendation: "buy" | "hold" | "sell" | null;
  result: { summary?: string; signals?: Array<{ label: string; evidence: string; source: string | null }> } | null;
  error: string | null;
  sandboxId: string | null;
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
};

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  pending: "outline",
  running: "secondary",
  complete: "default",
  failed: "destructive",
};

export function JobDetail({ initialJob }: { initialJob: Job }) {
  const [job, setJob] = useState(initialJob);

  useEffect(() => {
    if (job.status === "complete" || job.status === "failed") return;
    const id = setInterval(async () => {
      const res = await fetch(`/api/status/${job.id}`);
      if (!res.ok) return;
      const next: Job = await res.json();
      setJob(next);
      if (next.status === "complete" || next.status === "failed") clearInterval(id);
    }, 2500);
    return () => clearInterval(id);
  }, [job.id, job.status]);

  const elapsedMs = job.completedAt
    ? new Date(job.completedAt).getTime() - new Date(job.createdAt).getTime()
    : Date.now() - new Date(job.createdAt).getTime();

  return (
    <div className="space-y-6">
      <div className="flex items-baseline gap-3">
        <h1 className="text-2xl font-mono">{job.ticker}</h1>
        <Badge variant={STATUS_VARIANT[job.status]}>{job.status}</Badge>
        {job.recommendation && (
          <Badge variant="default" className="text-base">{job.recommendation.toUpperCase()}</Badge>
        )}
      </div>

      {(job.status === "pending" || job.status === "running") && (
        <p className="text-sm text-slate-500">
          Sandbox {job.sandboxId ?? "spawning…"} · {Math.round(elapsedMs / 1000)}s elapsed
        </p>
      )}

      {job.status === "failed" && job.error && (
        <Card className="p-4 border-red-300 bg-red-50">
          <pre className="text-xs whitespace-pre-wrap">{job.error}</pre>
        </Card>
      )}

      {job.status === "complete" && job.result && (
        <>
          <p>{job.result.summary}</p>
          <ul className="space-y-2">
            {(job.result.signals ?? []).map((s, i) => (
              <li key={i} className="text-sm">
                <strong>{s.label}:</strong> {s.evidence}
                {s.source && <> · <a href={s.source} className="text-blue-600 underline" target="_blank" rel="noreferrer">source</a></>}
              </li>
            ))}
          </ul>
          <p className="text-xs text-slate-400">Completed in {Math.round(elapsedMs / 1000)}s · Demo only — not financial advice.</p>
        </>
      )}
    </div>
  );
}
