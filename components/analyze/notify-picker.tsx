"use client";

export type NotifyChannelOption = "none" | "slack" | "gmail";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const SLACK_DEST_RE = /^[#@][\w-]+$/;

export function validateDestination(channel: NotifyChannelOption, destination: string): string | null {
  if (channel === "none") return null;
  if (!destination) return "Destination is required.";
  if (channel === "gmail" && !EMAIL_RE.test(destination)) return "Enter a valid email address.";
  if (channel === "slack" && !SLACK_DEST_RE.test(destination)) return "Slack destination must start with # or @.";
  return null;
}

export function NotifyPicker({
  channel, destination, onChannelChange, onDestinationChange,
}: {
  channel: NotifyChannelOption;
  destination: string;
  onChannelChange: (c: NotifyChannelOption) => void;
  onDestinationChange: (d: string) => void;
}) {
  return (
    <div className="space-y-2">
      <label className="text-sm font-semibold text-af-on-surface">Notify me when done</label>
      <div className="flex gap-3">
        <select
          value={channel}
          onChange={(e) => onChannelChange(e.target.value as NotifyChannelOption)}
          className="border border-af-outline-variant rounded-lg px-3 py-2 text-sm bg-af-surface-container-lowest text-af-on-surface"
        >
          <option value="none">None</option>
          <option value="slack">Slack</option>
          <option value="gmail">Gmail</option>
        </select>
        {channel !== "none" && (
          <input
            type="text"
            value={destination}
            onChange={(e) => onDestinationChange(e.target.value)}
            placeholder={channel === "slack" ? "#analysts" : "you@company.com"}
            className="flex-1 border border-af-outline-variant rounded-lg px-3 py-2 text-sm bg-af-surface-container-lowest text-af-on-surface"
          />
        )}
      </div>
    </div>
  );
}
