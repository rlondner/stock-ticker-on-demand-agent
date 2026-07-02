export type JobStatus = "pending" | "running" | "complete" | "failed";

export function statusPillProps(status: JobStatus): { label: string; className: string } {
  switch (status) {
    case "pending":
      return { label: "Pending", className: "bg-af-surface-container-high text-af-on-surface-variant" };
    case "running":
      return { label: "Running", className: "bg-af-secondary-container text-af-on-secondary-container" };
    case "complete":
      return { label: "Complete", className: "bg-af-primary-container text-af-on-primary" };
    case "failed":
      return { label: "Failed", className: "bg-af-error-container text-af-on-error-container" };
    default: {
      const _exhaustive: never = status;
      throw new Error(`unknown status: ${String(_exhaustive)}`);
    }
  }
}
