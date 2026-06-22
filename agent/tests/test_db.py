import os
import uuid
import pytest
import psycopg

@pytest.fixture
def neon_url():
    url = os.environ.get("NEON_DATABASE_URL")
    if not url:
        pytest.skip("NEON_DATABASE_URL not set — skipping integration test")
    return url

@pytest.fixture
def fresh_job(neon_url):
    """Inserts a fresh pending job and returns its id; cleans up after."""
    job_id = str(uuid.uuid4())
    with psycopg.connect(neon_url) as conn:
        conn.execute(
            "INSERT INTO jobs (id, ticker, status) VALUES (%s, %s, 'pending')",
            (job_id, "TEST"),
        )
        conn.commit()
    yield job_id
    with psycopg.connect(neon_url) as conn:
        conn.execute("DELETE FROM jobs WHERE id = %s", (job_id,))
        conn.commit()

def test_get_job_returns_row(neon_url, fresh_job, monkeypatch):
    monkeypatch.setenv("NEON_DATABASE_URL", neon_url)
    from lib.db import get_job
    row = get_job(fresh_job)
    assert row is not None
    assert row["ticker"] == "TEST"
    assert row["status"] == "pending"

def test_get_job_returns_none_for_missing(neon_url, monkeypatch):
    monkeypatch.setenv("NEON_DATABASE_URL", neon_url)
    from lib.db import get_job
    assert get_job("00000000-0000-0000-0000-000000000000") is None

def test_mark_running_transitions_from_pending(neon_url, fresh_job, monkeypatch):
    monkeypatch.setenv("NEON_DATABASE_URL", neon_url)
    from lib.db import mark_running, get_job
    mark_running(fresh_job)
    row = get_job(fresh_job)
    assert row["status"] == "running"
    assert row["started_at"] is not None

def test_mark_running_does_not_overwrite_terminal(neon_url, fresh_job, monkeypatch):
    monkeypatch.setenv("NEON_DATABASE_URL", neon_url)
    from lib.db import mark_running, mark_complete, get_job
    mark_running(fresh_job)
    mark_complete(fresh_job, recommendation="buy", result={"summary": "ok"})
    mark_running(fresh_job)
    row = get_job(fresh_job)
    assert row["status"] == "complete"

def test_mark_complete_sets_result_and_recommendation(neon_url, fresh_job, monkeypatch):
    monkeypatch.setenv("NEON_DATABASE_URL", neon_url)
    from lib.db import mark_running, mark_complete, get_job
    mark_running(fresh_job)
    mark_complete(fresh_job, recommendation="hold", result={"summary": "neutral", "signals": []})
    row = get_job(fresh_job)
    assert row["status"] == "complete"
    assert row["recommendation"] == "hold"
    assert row["result"]["summary"] == "neutral"
    assert row["completed_at"] is not None

def test_mark_failed_writes_error(neon_url, fresh_job, monkeypatch):
    monkeypatch.setenv("NEON_DATABASE_URL", neon_url)
    from lib.db import mark_failed, get_job
    mark_failed(fresh_job, error="ValueError: nope")
    row = get_job(fresh_job)
    assert row["status"] == "failed"
    assert "ValueError" in row["error"]
