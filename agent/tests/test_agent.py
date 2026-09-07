import os
import uuid
import pytest
import psycopg
from unittest.mock import patch
from lib.llm import Thesis, ThesisPoint
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

FAKE_ANALYSIS = Thesis(
    recommendation="buy",
    confidence="medium",
    summary="strong",
    bull_case=[ThesisPoint(claim="rev", evidence="up 10%", source_url=None)],
    bear_case=[ThesisPoint(claim="risk", evidence="competition", source_url=None)],
    key_risks=[ThesisPoint(claim="macro", evidence="rates rising", source_url=None)],
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


def test_agent_run_uses_llmobs_workflow_span(monkeypatch):
    import contextlib, importlib, agent as agent_module

    calls = {"workflow": [], "annotate": []}

    @contextlib.contextmanager
    def fake_workflow_span(name, session_id=None):
        calls["workflow"].append((name, session_id))
        yield "WORKFLOW_SPAN"

    def fake_annotate(span, **kw):
        calls["annotate"].append((span, kw))

    importlib.reload(agent_module)
    monkeypatch.setattr(agent_module.llmobs, "workflow_span", fake_workflow_span)
    monkeypatch.setattr(agent_module.llmobs, "annotate", fake_annotate)
    monkeypatch.setattr(agent_module, "get_job",
                        lambda job_id: {"ticker": "AAPL", "status": "pending", "sandbox_id": None})
    monkeypatch.setattr(agent_module, "mark_running", lambda job_id: None)
    monkeypatch.setattr(agent_module, "mark_complete", lambda job_id, recommendation, result: None)
    monkeypatch.setattr(agent_module, "run_analysis", lambda ticker: {"recommendation": "buy"})
    monkeypatch.setattr(agent_module, "self_delete", lambda sandbox_id=None: None)
    monkeypatch.setattr(agent_module, "init_observability", lambda **kw: None)
    monkeypatch.setattr(agent_module, "flush_observability", lambda *a, **kw: None)
    monkeypatch.setattr(agent_module._metrics, "record_job_completed", lambda *a, **kw: None)
    monkeypatch.setattr(agent_module._metrics, "record_agent_run_duration", lambda *a, **kw: None)
    monkeypatch.setattr(agent_module, "JOB_ID", "job-llmobs-wf")

    agent_module.main()

    assert calls["workflow"] == [("agent.run", "job-llmobs-wf")]
    assert any(span == "WORKFLOW_SPAN" for span, _ in calls["annotate"])


def test_flush_and_self_delete_run_after_workflow_span_exits(monkeypatch):
    """Regression test for the final-review finding: flush_observability() and
    self_delete() must run AFTER the llmobs.workflow_span() context manager has
    fully exited (i.e. after the workflow span — which carries session_id,
    input/output data, and final_status — has closed), not from inside its
    with-block's finally. Otherwise the explicit pre-teardown flush races
    sandbox teardown via ddtrace's atexit hook instead of covering that span."""
    import contextlib, importlib, agent as agent_module

    events = []

    @contextlib.contextmanager
    def fake_workflow_span(name, session_id=None):
        events.append("workflow_span.enter")
        yield "WORKFLOW_SPAN"
        events.append("workflow_span.exit")

    def fake_flush_observability(*a, **kw):
        events.append("flush_observability")

    def fake_self_delete(sandbox_id=None):
        events.append("self_delete")

    importlib.reload(agent_module)
    monkeypatch.setattr(agent_module.llmobs, "workflow_span", fake_workflow_span)
    monkeypatch.setattr(agent_module.llmobs, "annotate", lambda *a, **kw: None)
    monkeypatch.setattr(agent_module, "get_job",
                        lambda job_id: {"ticker": "AAPL", "status": "pending", "sandbox_id": None})
    monkeypatch.setattr(agent_module, "mark_running", lambda job_id: None)
    monkeypatch.setattr(agent_module, "mark_complete", lambda job_id, recommendation, result: None)
    monkeypatch.setattr(agent_module, "run_analysis", lambda ticker: {"recommendation": "buy"})
    monkeypatch.setattr(agent_module, "self_delete", fake_self_delete)
    monkeypatch.setattr(agent_module, "init_observability", lambda **kw: None)
    monkeypatch.setattr(agent_module, "flush_observability", fake_flush_observability)
    monkeypatch.setattr(agent_module._metrics, "record_job_completed", lambda *a, **kw: None)
    monkeypatch.setattr(agent_module._metrics, "record_agent_run_duration", lambda *a, **kw: None)
    monkeypatch.setattr(agent_module, "JOB_ID", "job-flush-order")

    agent_module.main()

    assert events == [
        "workflow_span.enter",
        "workflow_span.exit",
        "flush_observability",
        "self_delete",
    ], events
