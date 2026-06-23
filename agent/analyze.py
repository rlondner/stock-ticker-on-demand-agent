"""Standalone driver: insert a pending job row, then run the agent in-process.

Usage:
    python analyze.py <TICKER> [--no-wait]

Loads env vars from <repo>/.env automatically (shell vars take precedence).
NEON_DATABASE_URL and OPENAI_API_KEY must be present in either.
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from lib.db import _conn

REPO_ROOT = Path(__file__).resolve().parent.parent
DOTENV_PATH = REPO_ROOT / ".env"

TICKER_RE = re.compile(r"^[A-Z]{1,5}$")


def insert_pending(ticker: str) -> str:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO jobs (ticker) VALUES (%s) RETURNING id::text",
            (ticker,),
        )
        row = cur.fetchone()
        c.commit()
        return row["id"]


def poll_until_terminal(job_id: str, timeout_s: float = 180.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        with _conn() as c:
            cur = c.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
            row = cur.fetchone()
        if row and row["status"] in ("complete", "failed"):
            return row
        time.sleep(1.0)
    raise TimeoutError(f"job {job_id} did not reach a terminal state in {timeout_s}s")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the stock agent locally against a fresh job row.")
    parser.add_argument("ticker", help="1-5 uppercase letters, e.g. AAPL")
    parser.add_argument("--no-wait", action="store_true", help="exit immediately after agent.main() returns")
    args = parser.parse_args()

    # Load env vars from <repo>/.env. override=False means existing shell vars win.
    load_dotenv(DOTENV_PATH, override=False)

    ticker = args.ticker.strip()
    if not TICKER_RE.match(ticker):
        print(f"invalid ticker {ticker!r}: must match {TICKER_RE.pattern}", file=sys.stderr)
        return 2

    if "NEON_DATABASE_URL" not in os.environ:
        print(f"NEON_DATABASE_URL not found in environment or {DOTENV_PATH}", file=sys.stderr)
        return 2
    if "OPENAI_API_KEY" not in os.environ:
        print(f"OPENAI_API_KEY not found in environment or {DOTENV_PATH}", file=sys.stderr)
        return 2

    job_id = insert_pending(ticker)
    print(f"inserted job {job_id} (ticker={ticker})", file=sys.stderr)

    # IMPORTANT: agent.py reads JOB_ID into a module-level constant at import time
    # (agent.py:10), so the env var MUST be set BEFORE the import. Defer the import.
    os.environ["JOB_ID"] = job_id
    os.environ.setdefault("DAYTONA_SANDBOX_ID", f"local-{job_id}")

    import agent as agent_module  # deferred — see comment above

    try:
        agent_module.main()
    except Exception as e:
        print(f"agent.main() raised: {e}", file=sys.stderr)

    if args.no_wait:
        return 0

    row = poll_until_terminal(job_id)
    payload = {
        "id": str(row["id"]),
        "ticker": row["ticker"],
        "status": row["status"],
        "recommendation": row["recommendation"],
        "result": row["result"],
        "error": row["error"],
    }
    print(json.dumps(payload, indent=2, default=str))
    return 0 if row["status"] == "complete" else 1


if __name__ == "__main__":
    sys.exit(main())
