import { notifyPillProps } from "@/lib/ui/notify-pill";
import type { NotifyChannel } from "@/lib/db/schema";

export function NotifyPill({ channel, notifiedAt }: { channel: NotifyChannel | null; notifiedAt: string | null }) {
  const props = notifyPillProps(channel, notifiedAt);
  if (!props) return null;
  return (
    <span className={`inline-block px-3 py-1 rounded-full text-[12px] font-medium ${props.className}`}>
      {props.label}
    </span>
  );
}
