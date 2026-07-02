import os
import uuid
import pytest
import psycopg
from unittest.mock import patch
from lib.llm import Analysis, Signal
from lib.finance import Snapshot

@pytest.fixture
def neon_url():
    url = os.environ.get("NEON_DATABASE_URL")
    if not url:
        pytest.skip("NEON_DATABASE_URL not set")
    return url

@pytest.fixture
def fresh_job(neon_url):
    job_id = str(uuid.uuid4())
    with psycopg.connect(neon_url) as conn:
        conn.execute("INSERT INTO jobs (id, ticker, status) VALUES (%s, %s, 'pending')", (job_id, "AAPL"))
        conn.commit()
    yield job_id
    with psycopg.connect(neon_url) as conn:
        conn.execute("DELETE FROM jobs WHERE id = %s", (job_id,))
        conn.commit()

FAKE_ANALYSIS = Analysis(
    recommendation="buy",
    summary="strong",
    signals=[Signal(label="rev", evidence="up 10%", source=None)],
)

def test_main_happy_path(neon_url, fresh_job, monkeypatch):
    monkeypatch.setenv("JOB_ID", fresh_job)
    monkeypatch.setenv("NEON_DATABASE_URL", neon_url)

    with patch("lib.llm.OpenAIClient.analyze", return_value=FAKE_ANALYSIS), \
         patch("lib.self_delete.self_delete"):
        import importlib
        import agent
        importlib.reload(agent)
        agent.main()

    with psycopg.connect(neon_url) as conn:
        row = conn.execute(
            "SELECT status, recommendation, result FROM jobs WHERE id=%s", (fresh_job,)
        ).fetchone()
    assert row[0] == "complete"
    assert row[1] == "buy"
    assert row[2]["summary"] == "strong"

def test_main_idempotency_when_already_complete(neon_url, fresh_job, monkeypatch):
    """If the row is no longer 'pending', the agent must exit without writing."""
    with psycopg.connect(neon_url) as conn:
        conn.execute(
            "UPDATE jobs SET status='complete', recommendation='hold', "
            "result='{\"summary\":\"x\",\"signals\":[]}'::jsonb WHERE id=%s",
            (fresh_job,),
        )
        conn.commit()

    monkeypatch.setenv("JOB_ID", fresh_job)
    monkeypatch.setenv("NEON_DATABASE_URL", neon_url)

    analyze = patch("lib.llm.OpenAIClient.analyze")
    with analyze as m, patch("lib.self_delete.self_delete"):
        import importlib, agent
        importlib.reload(agent)
        agent.main()
        m.assert_not_called()

def test_main_writes_failed_on_llm_error(neon_url, fresh_job, monkeypatch):
    monkeypatch.setenv("JOB_ID", fresh_job)
    monkeypatch.setenv("NEON_DATABASE_URL", neon_url)

    with patch("lib.llm.OpenAIClient.analyze", side_effect=RuntimeError("LLM blew up")), \
         patch("lib.llm.fetch_snapshot", return_value=None), \
         patch("lib.self_delete.self_delete"):
        import importlib, agent
        importlib.reload(agent)
        with pytest.raises(RuntimeError):
            agent.main()

    with psycopg.connect(neon_url) as conn:
        row = conn.execute("SELECT status, error FROM jobs WHERE id=%s", (fresh_job,)).fetchone()
    assert row[0] == "failed"
    assert "LLM blew up" in row[1]


def _fake_snapshot() -> Snapshot:
    return Snapshot(
        company_name="MongoDB, Inc.",
        close=342.15,
        previous_close=346.44,
        change_pct=-1.24,
        currency="USD",
        as_of="2026-07-02T12:00:00Z",
    )


def test_main_persists_snapshot_when_fetch_succeeds(neon_url, fresh_job, monkeypatch):
    monkeypatch.setenv("JOB_ID", fresh_job)
    monkeypatch.setenv("NEON_DATABASE_URL", neon_url)

    with patch("lib.llm.OpenAIClient.analyze", return_value=FAKE_ANALYSIS), \
         patch("lib.llm.fetch_snapshot", return_value=_fake_snapshot()), \
         patch("lib.self_delete.self_delete"):
        import importlib
        import agent
        importlib.reload(agent)
        agent.main()

    with psycopg.connect(neon_url) as conn:
        row = conn.execute(
            "SELECT status, result FROM jobs WHERE id=%s", (fresh_job,)
        ).fetchone()
    assert row[0] == "complete"
    assert row[1]["summary"] == "strong"
    assert row[1]["snapshot"]["company_name"] == "MongoDB, Inc."
    assert row[1]["snapshot"]["close"] == 342.15
    assert row[1]["snapshot"]["change_pct"] == -1.24


def test_main_persists_none_snapshot_when_fetch_fails(neon_url, fresh_job, monkeypatch):
    """Best-effort: LLM still runs, result.snapshot is None, job completes."""
    monkeypatch.setenv("JOB_ID", fresh_job)
    monkeypatch.setenv("NEON_DATABASE_URL", neon_url)

    with patch("lib.llm.OpenAIClient.analyze", return_value=FAKE_ANALYSIS), \
         patch("lib.llm.fetch_snapshot", return_value=None), \
         patch("lib.self_delete.self_delete"):
        import importlib
        import agent
        importlib.reload(agent)
        agent.main()

    with psycopg.connect(neon_url) as conn:
        row = conn.execute(
            "SELECT status, result FROM jobs WHERE id=%s", (fresh_job,)
        ).fetchone()
    assert row[0] == "complete"
    assert row[1]["snapshot"] is None
