import { describe, it, expect, vi, beforeEach } from "vitest";
import { POST } from "@/app/api/cleanup/route";

// autoDeleteIntervalFor defaults: quick=600s, deep=900s, full=1500s.
// Sweep threshold = autoDeleteIntervalFor(depth) + 90s grace.
//   quick: 690s, deep: 990s, full: 1590s
const QUICK_THRESHOLD_S = 600 + 90;
const DEEP_THRESHOLD_S = 900 + 90;
const FULL_THRESHOLD_S = 1500 + 90;

let selectRows: Array<{ id: string; depth: string; startedAt: Date | null }> = [];
const updateMock = vi.fn((_arg: unknown) => ({}));
let returningIds: Array<{ id: string }> = [];

vi.mock("@/lib/db/client", () => ({
  db: {
    select: () => ({
      from: () => ({
        where: () => Promise.resolve(selectRows),
      }),
    }),
    update: (arg: unknown) => {
      updateMock(arg);
      return {
        set: () => ({
          where: () => ({
            returning: () => Promise.resolve(returningIds),
          }),
        }),
      };
    },
  },
  jobs: { id: "id", status: "status", startedAt: "started_at", depth: "depth" },
}));

function ago(seconds: number): Date {
  return new Date(Date.now() - seconds * 1000);
}

beforeEach(() => {
  selectRows = [];
  returningIds = [];
  updateMock.mockClear();
});

describe("POST /api/cleanup", () => {
  it("sweeps a quick job stuck past its own threshold", async () => {
    selectRows = [{ id: "q1", depth: "quick", startedAt: ago(QUICK_THRESHOLD_S + 5) }];
    returningIds = [{ id: "q1" }];

    const res = await POST(new Request("http://localhost/api/cleanup", { method: "POST" }));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.swept).toBe(1);
  });

  it("does NOT sweep a deep job only 5 minutes into running (below deep's ~990s threshold)", async () => {
    selectRows = [{ id: "d1", depth: "deep", startedAt: ago(5 * 60) }];

    const res = await POST(new Request("http://localhost/api/cleanup", { method: "POST" }));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.swept).toBe(0);
    expect(updateMock).not.toHaveBeenCalled();
  });

  it("sweeps a deep job past its actual threshold (~990s)", async () => {
    selectRows = [{ id: "d2", depth: "deep", startedAt: ago(DEEP_THRESHOLD_S + 5) }];
    returningIds = [{ id: "d2" }];

    const res = await POST(new Request("http://localhost/api/cleanup", { method: "POST" }));
    const body = await res.json();
    expect(body.swept).toBe(1);
  });

  it("does NOT sweep a full job still within its ~1590s threshold", async () => {
    selectRows = [{ id: "f1", depth: "full", startedAt: ago(20 * 60) }]; // 1200s < 1590s

    const res = await POST(new Request("http://localhost/api/cleanup", { method: "POST" }));
    const body = await res.json();
    expect(body.swept).toBe(0);
    expect(updateMock).not.toHaveBeenCalled();
  });

  it("sweeps a full job past its actual threshold (~1590s)", async () => {
    selectRows = [{ id: "f2", depth: "full", startedAt: ago(FULL_THRESHOLD_S + 5) }];
    returningIds = [{ id: "f2" }];

    const res = await POST(new Request("http://localhost/api/cleanup", { method: "POST" }));
    const body = await res.json();
    expect(body.swept).toBe(1);
  });

  it("returns 0 swept when there are no running jobs", async () => {
    selectRows = [];

    const res = await POST(new Request("http://localhost/api/cleanup", { method: "POST" }));
    const body = await res.json();
    expect(body.swept).toBe(0);
    expect(updateMock).not.toHaveBeenCalled();
  });
});
