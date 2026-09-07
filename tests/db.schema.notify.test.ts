import { describe, it, expect } from "vitest";
import { jobs } from "@/lib/db/schema";

describe("jobs notify columns", () => {
  it("has notifyChannel, notifyDestination, and notifiedAt columns", () => {
    expect(jobs.notifyChannel).toBeDefined();
    expect(jobs.notifyDestination).toBeDefined();
    expect(jobs.notifiedAt).toBeDefined();
  });
});
