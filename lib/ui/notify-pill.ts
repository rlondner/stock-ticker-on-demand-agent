import type { NotifyChannel } from "@/lib/db/schema";

export function notifyPillProps(
  channel: NotifyChannel | null,
  notifiedAt: string | null,
): { label: string; className: string } | null {
  if (!channel || !notifiedAt) return null;
  const label = channel === "slack" ? "Notified via Slack" : "Notified via Gmail";
  return { label, className: "bg-af-secondary-container text-af-on-secondary-container" };
}
