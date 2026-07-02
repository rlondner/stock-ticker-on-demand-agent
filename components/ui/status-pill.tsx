import { statusPillProps, type JobStatus } from "@/lib/ui/status-pill";

export function StatusPill({ status }: { status: JobStatus }) {
  const { label, className } = statusPillProps(status);
  return (
    <span className={`inline-block px-3 py-1 rounded-full text-[12px] font-medium ${className}`}>
      {label}
    </span>
  );
}
