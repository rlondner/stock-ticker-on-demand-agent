import type { JobStatus } from "@/lib/ui/status-pill";
import type { Recommendation } from "@/lib/ui/signal-pill";
import type { RawSignal } from "@/lib/job/map-insights";

export type SerializedJob = {
  id: string;
  ticker: string;
  status: JobStatus;
  recommendation: Recommendation | null;
  result: { summary?: string; signals?: RawSignal[] } | null;
  error: string | null;
  sandboxId: string | null;
  createdAt: string; // ISO
  startedAt: string | null; // ISO
  completedAt: string | null; // ISO
};
