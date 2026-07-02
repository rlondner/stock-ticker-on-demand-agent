import { describe, it, expect } from "vitest";
import { statusPillProps } from "@/lib/ui/status-pill";

describe("statusPillProps", () => {
  it("maps pending to a neutral pill", () => {
    expect(statusPillProps("pending")).toEqual({
      label: "Pending",
      className: "bg-af-surface-container-high text-af-on-surface-variant",
    });
  });

  it("maps running to the green secondary pill", () => {
    expect(statusPillProps("running")).toEqual({
      label: "Running",
      className: "bg-af-secondary-container text-af-on-secondary-container",
    });
  });

  it("maps complete to the primary-container dark pill", () => {
    expect(statusPillProps("complete")).toEqual({
      label: "Complete",
      className: "bg-af-primary-container text-af-on-primary",
    });
  });

  it("maps failed to the error-container pill", () => {
    expect(statusPillProps("failed")).toEqual({
      label: "Failed",
      className: "bg-af-error-container text-af-on-error-container",
    });
  });

  it("throws on an unknown status", () => {
    // @ts-expect-error — deliberately invalid
    expect(() => statusPillProps("weird")).toThrow(/unknown status/i);
  });
});
