import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { trace } from "@opentelemetry/api";
import { BasicTracerProvider } from "@opentelemetry/sdk-trace-base";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { eq } from "drizzle-orm";

const haveSecrets = !!process.env.NEON_DATABASE_URL && !!process.env.OPENAI_API_KEY;

// Minimal OpenAI Responses-API payload. The Python SDK's response parser is
// fairly forgiving — it requires `output_text` (or the nested `output[].content`
// shape) plus core fields. If a future SDK version tightens this, expand here.
const ANALYSIS_JSON = JSON.stringify({
  recommendation: "hold",
  summary: "deterministic test fixture",
  signals: [{ label: "test-signal", evidence: "fixture only", source: null }],
});

const FAKE_RESPONSE = {
  id: "resp_test_fixture",
  object: "response",
  created_at: 1_000_000_000,
  status: "completed",
  model: "gpt-4.1-mini",
  output: [
    {
      type: "message",
      id: "msg_test",
      status: "completed",
      role: "assistant",
      content: [{ type: "output_text", text: ANALYSIS_JSON, annotations: [] }],
    },
  ],
  output_text: ANALYSIS_JSON,
  usage: { input_tokens: 1, output_tokens: 1, total_tokens: 2 },
};

let server: http.Server | undefined;
let serverUrl = "";

beforeAll(async () => {
  trace.setGlobalTracerProvider(new BasicTracerProvider());
  if (!haveSecrets) return;

  server = http.createServer((_req, res) => {
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(FAKE_RESPONSE));
  });
  await new Promise<void>((resolve) => server!.listen(0, "127.0.0.1", resolve));
  const addr = server!.address();
  if (typeof addr === "object" && addr) {
    serverUrl = `http://127.0.0.1:${addr.port}/v1`;
  }
});

afterAll(async () => {
  if (server) await new Promise<void>((r) => server!.close(() => r()));
});

describe.skipIf(!haveSecrets)("subprocess runner integration", () => {
  it("runs the real Python agent end-to-end and marks the job complete", async () => {
    const origUrl = process.env.OPENAI_API_URL;
    const origRuntime = process.env.AGENT_RUNTIME;
    process.env.OPENAI_API_URL = serverUrl;
    process.env.AGENT_RUNTIME = "subprocess";

    const { db, jobs } = await import("@/lib/db/client");
    const { spawnAnalysisSubprocess } = await import("@/lib/runtime/subprocess");

    const [{ id: jobId }] = await db
      .insert(jobs)
      .values({ ticker: "TEST" })
      .returning({ id: jobs.id });

    try {
      const span = trace.getTracer("integration").startSpan("p");
      const sandboxId = await spawnAnalysisSubprocess(jobId, "quick", span);
      span.end();
      expect(sandboxId).toBe(`local-${jobId}`);

      const logPath = path.resolve(process.cwd(), "agent", ".runs", `${jobId}.log`);
      expect(fs.existsSync(logPath)).toBe(true);

      const deadline = Date.now() + 30_000;
      let status = "pending";
      let row: any;
      while (Date.now() < deadline) {
        const rows = await db.select().from(jobs).where(eq(jobs.id, jobId));
        row = rows[0];
        status = row?.status ?? "pending";
        if (status === "complete" || status === "failed") break;
        await new Promise((r) => setTimeout(r, 500));
      }

      expect(status, `final status; error=${row?.error}`).toBe("complete");
      expect(["buy", "hold", "sell"]).toContain(row.recommendation);
    } finally {
      // Restore env-var mutations + cleanup the row.
      if (origUrl === undefined) delete process.env.OPENAI_API_URL;
      else process.env.OPENAI_API_URL = origUrl;
      if (origRuntime === undefined) delete process.env.AGENT_RUNTIME;
      else process.env.AGENT_RUNTIME = origRuntime;
      await db.delete(jobs).where(eq(jobs.id, jobId));
    }
  }, 60_000);
});
