import { describe, it, expect } from "vitest";
import { signalPillProps } from "@/lib/ui/signal-pill";

describe("signalPillProps", () => {
  it("maps buy to green BUY pill", () => {
    expect(signalPillProps("buy")).toEqual({
      label: "BUY",
      className: "bg-af-signal-buy text-white",
    });
  });

  it("maps hold to amber HOLD pill", () => {
    expect(signalPillProps("hold")).toEqual({
      label: "HOLD",
      className: "bg-af-signal-hold text-white",
    });
  });

  it("maps sell to red SELL pill", () => {
    expect(signalPillProps("sell")).toEqual({
      label: "SELL",
      className: "bg-af-signal-sell text-white",
    });
  });

  it("returns null when no recommendation", () => {
    expect(signalPillProps(null)).toBeNull();
  });
});
