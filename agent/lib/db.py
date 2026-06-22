import os
from typing import Any
import psycopg
from psycopg.rows import dict_row

def _conn():
    url = os.environ["NEON_DATABASE_URL"]
    return psycopg.connect(url, row_factory=dict_row)

def get_job(job_id: str) -> dict[str, Any] | None:
    with _conn() as c:
        cur = c.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
        return cur.fetchone()

def mark_running(job_id: str) -> None:
    """Transition pending -> running. No-op if status is terminal."""
    with _conn() as c:
        c.execute(
            "UPDATE jobs SET status='running', started_at=now() "
            "WHERE id=%s AND status='pending'",
            (job_id,),
        )
        c.commit()

def mark_complete(job_id: str, *, recommendation: str, result: dict) -> None:
    """Transition running -> complete. Only writes if status is pending or running."""
    from psycopg.types.json import Jsonb
    with _conn() as c:
        c.execute(
            "UPDATE jobs SET status='complete', recommendation=%s, result=%s, "
            "completed_at=now() WHERE id=%s AND status IN ('pending','running')",
            (recommendation, Jsonb(result), job_id),
        )
        c.commit()

def mark_failed(job_id: str, *, error: str) -> None:
    """Transition any non-terminal state -> failed."""
    with _conn() as c:
        c.execute(
            "UPDATE jobs SET status='failed', error=%s, completed_at=now() "
            "WHERE id=%s AND status IN ('pending','running')",
            (error, job_id),
        )
        c.commit()
