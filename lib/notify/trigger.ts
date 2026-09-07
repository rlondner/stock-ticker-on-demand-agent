import { and, eq, isNull } from "drizzle-orm";
import { db, jobs } from "@/lib/db/client";
import type { Span } from "@opentelemetry/api";
import { addAttrs } from "@/lib/observability/api";
import { sendCompletionNotification } from "@/lib/notify/one";

type JobRow = typeof jobs.$inferSelect;

/**
 * Atomically claims the "send the completion notification" job for a row
 * (via a conditional UPDATE ... WHERE notified_at IS NULL) and, if the claim
 * succeeds, sends the notification through the One CLI.
 *
 * Safe to call from multiple sites (e.g. both the status-poll route and the
 * server-rendered job page) and multiple times concurrently for the same
 * job id — only the caller that wins the atomic claim will ever send.
 *
 * `span`, if provided, gets `notify_claimed` and `notify_sent` attributes
 * recorded for when this app's OTel tracer is actually initialized and
 * exported. As of this writing, no OTel tracer provider is registered
 * anywhere in this app (nobody calls `initOtel()`) — a pre-existing,
 * app-wide gap unrelated to this feature — so these attributes are not
 * currently visible in any backend. They're recorded anyway for
 * forward-compatibility once that app-wide gap is fixed.
 */
export async function triggerCompletionNotificationIfDue(
  jobId: string,
  row: JobRow,
  span?: Span,
): Promise<JobRow> {
  if (!(row.status === "complete" && row.notifyChannel && row.notifyDestination && !row.notifiedAt)) {
    return row;
  }

  const notifyChannel = row.notifyChannel as "slack" | "gmail";
  const notifyDestination = row.notifyDestination;
  const claimed = await db
    .update(jobs)
    .set({ notifiedAt: new Date() })
    .where(and(eq(jobs.id, jobId), isNull(jobs.notifiedAt)))
    .returning({ id: jobs.id });

  if (claimed.length === 0) {
    return row;
  }

  const claimedAt = new Date();
  const updatedRow = { ...row, notifiedAt: claimedAt };
  if (span) addAttrs(span, { notify_claimed: true });

  let sent = false;
  try {
    sent = await sendCompletionNotification({
      ticker: row.ticker,
      recommendation: row.recommendation,
      summary: (row.result as { summary?: string } | null)?.summary,
      notifyChannel,
      notifyDestination,
    });
  } catch {
    // sendCompletionNotification already swallows its own errors and
    // never rejects; this catch is a last-resort guard so a future
    // change there can never break callers.
    sent = false;
  }
  if (span) addAttrs(span, { notify_sent: sent });

  return updatedRow;
}
