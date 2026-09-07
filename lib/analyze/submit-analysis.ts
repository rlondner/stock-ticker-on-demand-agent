export type SubmitResult =
  | { ok: true; jobId: string }
  | { ok: false; error: string; jobId?: string };

export type Depth = "quick" | "deep" | "full";

export type SubmitParams = {
  ticker: string;
  depth?: Depth;
  fetchImpl?: typeof fetch;
  push: (path: string) => void;
};

const TICKER_RE = /^[A-Z]{1,5}$/;

export async function submitAnalysis({ ticker, depth = "quick", fetchImpl, push }: SubmitParams): Promise<SubmitResult> {
  const doFetch: typeof fetch = fetchImpl ?? fetch;
  const value = ticker.trim().toUpperCase();
  if (!TICKER_RE.test(value)) {
    return { ok: false, error: "Ticker must be 1–5 uppercase letters." };
  }

  let res: Response;
  try {
    res = await doFetch("/api/jobs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ticker: value, depth }),
    });
  } catch {
    return { ok: false, error: "Submit failed" };
  }

  const body = (await res.json().catch(() => ({}))) as { jobId?: string; error?: string };

  if (res.ok && body.jobId) {
    push(`/jobs/${body.jobId}`);
    return { ok: true, jobId: body.jobId };
  }

  // Non-2xx. If the server still returned a jobId (spawn failure path — see
  // /api/jobs/route.ts D9), route the user to the failed job so they can
  // inspect the error card.
  if (body.jobId) {
    push(`/jobs/${body.jobId}`);
    return { ok: false, error: body.error ?? "Submit failed", jobId: body.jobId };
  }
  return { ok: false, error: body.error ?? "Submit failed" };
}
