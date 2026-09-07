export type SubmitResult =
  | { ok: true; jobId: string }
  | { ok: false; error: string; jobId?: string };

export type SubmitParams = {
  ticker: string;
  notifyChannel?: "slack" | "gmail";
  notifyDestination?: string;
  fetchImpl?: typeof fetch;
  push: (path: string) => void;
};

const TICKER_RE = /^[A-Z]{1,5}$/;

export async function submitAnalysis({ ticker, notifyChannel, notifyDestination, fetchImpl, push }: SubmitParams): Promise<SubmitResult> {
  const doFetch: typeof fetch = fetchImpl ?? fetch;
  const value = ticker.trim().toUpperCase();
  if (!TICKER_RE.test(value)) {
    return { ok: false, error: "Ticker must be 1–5 uppercase letters." };
  }

  const body: Record<string, string> = { ticker: value };
  if (notifyChannel) {
    body.notifyChannel = notifyChannel;
    if (notifyDestination) body.notifyDestination = notifyDestination;
  }

  let res: Response;
  try {
    res = await doFetch("/api/jobs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    return { ok: false, error: "Submit failed" };
  }

  const resBody = (await res.json().catch(() => ({}))) as { jobId?: string; error?: string };

  if (res.ok && resBody.jobId) {
    push(`/jobs/${resBody.jobId}`);
    return { ok: true, jobId: resBody.jobId };
  }

  // Non-2xx. If the server still returned a jobId (spawn failure path — see
  // /api/jobs/route.ts D9), route the user to the failed job so they can
  // inspect the error card.
  if (resBody.jobId) {
    push(`/jobs/${resBody.jobId}`);
    return { ok: false, error: resBody.error ?? "Submit failed", jobId: resBody.jobId };
  }
  return { ok: false, error: resBody.error ?? "Submit failed" };
}
