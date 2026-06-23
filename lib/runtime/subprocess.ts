import { spawn } from "node:child_process";
import { existsSync, mkdirSync, openSync } from "node:fs";
import path from "node:path";
import type { Span } from "@opentelemetry/api";
import { injectTraceparent, forwardIfSet, datadogBlockIfEnabled } from "./env";

function resolvePythonPath(): string {
  const repoRoot = process.cwd();
  const isWindows = process.platform === "win32";
  const rel = isWindows
    ? path.join("agent", ".venv", "Scripts", "python.exe")
    : path.join("agent", ".venv", "bin", "python");
  return path.join(repoRoot, rel);
}

export async function spawnAnalysisSubprocess(
  jobId: string,
  parentSpan: Span,
): Promise<string> {
  const pythonPath = resolvePythonPath();
  if (!existsSync(pythonPath)) {
    throw new Error(
      `agent venv not found at ${pythonPath} — run \`pip install -r agent/requirements.txt\` in agent/.venv`,
    );
  }

  const repoRoot = process.cwd();
  const agentDir = path.join(repoRoot, "agent");
  const runsDir = path.join(agentDir, ".runs");
  mkdirSync(runsDir, { recursive: true });
  const logPath = path.join(runsDir, `${jobId}.log`);
  const logFd = openSync(logPath, "a");

  const env: Record<string, string> = {
    ...process.env as Record<string, string>,
    JOB_ID: jobId,
    NEON_DATABASE_URL: process.env.NEON_DATABASE_URL!,
    OPENAI_API_KEY: process.env.OPENAI_API_KEY!,
    TRACEPARENT: injectTraceparent(parentSpan),
    ...forwardIfSet("OPENAI_API_URL"),
    ...forwardIfSet("OPENAI_MODEL"),
    ...forwardIfSet("SENTRY_DSN_AGENT"),
    ...datadogBlockIfEnabled(),
  };
  // Never forward Daytona credentials into a local subprocess.
  delete env.DAYTONA_API_KEY;

  const child = spawn(pythonPath, ["agent.py"], {
    cwd: agentDir,
    env,
    stdio: ["ignore", logFd, logFd],
    detached: true,
  });
  child.unref();

  return `local-${jobId}`;
}
