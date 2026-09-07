import { execFile as execFileCb } from "node:child_process";
import { promisify } from "node:util";
import * as Sentry from "@sentry/nextjs";
import { ddLog } from "../observability/exporters/datadog";

const execFile = promisify(execFileCb);

type NotifyJob = {
  ticker: string;
  recommendation: string | null;
  summary: string | undefined;
  notifyChannel: "slack" | "gmail";
  notifyDestination: string;
};

function buildPayload(job: NotifyJob): Record<string, string> {
  const rec = job.recommendation ?? "unknown";
  const summary = job.summary ?? "";
  if (job.notifyChannel === "slack") {
    return {
      channel: job.notifyDestination,
      text: `*${job.ticker}* analysis complete — recommendation: *${rec}*\n${summary}`,
    };
  }
  return {
    to: job.notifyDestination,
    subject: `${job.ticker} analysis complete (${rec})`,
    body: `${job.ticker} analysis complete — recommendation: ${rec}\n${summary}`,
  };
}

function credentialsFor(channel: "slack" | "gmail"): { connectionKey: string; actionId: string } | null {
  const prefix = channel === "slack" ? "ONE_SLACK" : "ONE_GMAIL";
  const connectionKey = process.env[`${prefix}_CONNECTION_KEY`];
  const actionId = process.env[`${prefix}_SEND_ACTION_ID`];
  if (!connectionKey || !actionId) return null;
  return { connectionKey, actionId };
}

export async function sendCompletionNotification(job: NotifyJob): Promise<boolean> {
  const creds = credentialsFor(job.notifyChannel);
  if (!creds || !process.env.ONE_SECRET) {
    ddLog("warn", "notify.one.skipped", { channel: job.notifyChannel, reason: "missing_credentials" });
    return false;
  }
  const payload = buildPayload(job);
  try {
    await execFile("npx", [
      "--no-install", "@withone/cli", "actions", "execute",
      job.notifyChannel, creds.actionId, creds.connectionKey,
      "-d", JSON.stringify(payload), "--agent",
    ], { env: { ...process.env } });
    ddLog("info", "notify.one.sent", { channel: job.notifyChannel, ticker: job.ticker });
    return true;
  } catch {
    // Never log the raw error/argv here: execFile's rejection message is
    // "Command failed: <file> <all args joined>\n<stderr>", and the args
    // include the connection key, action id, and the full JSON payload
    // (which can contain a recipient email). Log a fixed-shape, safe
    // summary instead so nothing sensitive reaches any logging backend.
    const failure = { channel: job.notifyChannel, ticker: job.ticker, failed: true };
    Sentry.logger?.warn?.("notify.one.failed", failure);
    ddLog("warn", "notify.one.failed", failure);
    return false;
  }
}
