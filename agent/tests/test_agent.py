import os
import uuid
import pytest
import psycopg
from unittest.mock import patch
from lib.llm import Analysis, Signal

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

def test_agent_records_completion_metrics(monkeypatch):
    monkeypatch.setenv("JOB_ID", "job-x")
    import importlib, agent as agent_module, lib.metrics as mtr
    importlib.reload(mtr)
    calls = {}
    monkeypatch.setattr(mtr, "record_job_completed",
                        lambda final_status, ticker: calls.setdefault("completed", (final_status, ticker)))
    monkeypatch.setattr(mtr, "record_agent_run_duration",
                        lambda final_status, ticker, duration_ms: calls.setdefault("duration", (final_status, ticker)))
    monkeypatch.setattr(agent_module, "get_job", lambda job_id: {"ticker": "AAPL", "status": "pending", "sandbox_id": None})
    monkeypatch.setattr(agent_module, "mark_running", lambda job_id: None)
    monkeypatch.setattr(agent_module, "mark_complete", lambda job_id, recommendation, result: None)
    monkeypatch.setattr(agent_module, "run_analysis", lambda ticker: {"recommendation": "buy"})
    monkeypatch.setattr(agent_module, "self_delete", lambda sandbox_id=None: None)
    monkeypatch.setattr(agent_module, "init_observability", lambda **kw: None)
    monkeypatch.setattr(agent_module, "flush_observability", lambda *a, **kw: None)

    monkeypatch.setattr(agent_module, "JOB_ID", "job-x")
    agent_module.main()
    assert calls["completed"] == ("complete", "AAPL")
    assert calls["duration"][0] == "complete"

def test_main_writes_failed_on_llm_error(neon_url, fresh_job, monkeypatch):
    monkeypatch.setenv("JOB_ID", fresh_job)
    monkeypatch.setenv("NEON_DATABASE_URL", neon_url)

    with patch("lib.llm.OpenAIClient.analyze", side_effect=RuntimeError("LLM blew up")), \
         patch("lib.self_delete.self_delete"):
        import importlib, agent
        importlib.reload(agent)
        with pytest.raises(RuntimeError):
            agent.main()

    with psycopg.connect(neon_url) as conn:
        row = conn.execute("SELECT status, error FROM jobs WHERE id=%s", (fresh_job,)).fetchone()
    assert row[0] == "failed"
    assert "LLM blew up" in row[1]
