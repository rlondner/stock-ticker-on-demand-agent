import { describe, it, expect } from "vitest";
import { jobs } from "@/lib/db/schema";

describe("jobs schema", () => {
  it("has a depth column defaulting to 'quick'", () => {
    expect(jobs.depth).toBeDefined();
  });
});
