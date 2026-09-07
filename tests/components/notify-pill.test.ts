import { describe, it, expect } from "vitest";
import { notifyPillProps } from "@/lib/ui/notify-pill";

describe("notifyPillProps", () => {
  it("returns null when notifiedAt is null", () => {
    expect(notifyPillProps("slack", null)).toBeNull();
  });

  it("returns null when channel is null", () => {
    expect(notifyPillProps(null, "2026-09-07T00:00:00Z")).toBeNull();
  });

  it("returns a Slack label when notified via slack", () => {
    const props = notifyPillProps("slack", "2026-09-07T00:00:00Z");
    expect(props?.label).toBe("Notified via Slack");
  });

  it("returns a Gmail label when notified via gmail", () => {
    const props = notifyPillProps("gmail", "2026-09-07T00:00:00Z");
    expect(props?.label).toBe("Notified via Gmail");
  });
});
