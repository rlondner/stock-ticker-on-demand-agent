import json
from unittest.mock import MagicMock

import lib.crew as crew
from lib.llm import Thesis, ThesisPoint


def _fake_snapshot():
    from lib.finance import Snapshot
    return Snapshot(currency="USD", as_of="2026-09-07T00:00:00Z")


def _fake_thesis_dict():
    return {
        "recommendation": "buy", "confidence": "medium", "summary": "s",
        "bull_case": [{"claim": "c", "evidence": "e", "source_url": None}],
        "bear_case": [], "key_risks": [],
        "researcher_findings": [{"claim": "r", "evidence": "re", "source_url": "https://x.test"}],
        "fundamentals_analysis": [{"claim": "f", "evidence": "fe", "source_url": None}],
        "risk_analysis": [{"claim": "k", "evidence": "ke", "source_url": None}],
    }


def _fake_crew_instance(thesis_dict=None):
    fake_crew_instance = MagicMock()
    fake_crew_instance.kickoff.return_value = MagicMock(raw=json.dumps(thesis_dict or _fake_thesis_dict()))
    return fake_crew_instance


def test_run_crew_analysis_returns_thesis_plus_snapshot(monkeypatch):
    monkeypatch.setenv("YOUDOTCOM_API_KEY", "ydc-test")
    monkeypatch.setattr(crew, "fetch_snapshot", lambda ticker: _fake_snapshot())
    fake_crew_instance = _fake_crew_instance()
    monkeypatch.setattr(crew, "_build_crew", lambda ticker, snapshot, sandbox_id, depth: fake_crew_instance)

    out = crew.run_crew_analysis("MDB", depth="deep", sandbox_id="sb-1")

    assert out["recommendation"] == "buy"
    assert out["researcher_findings"][0]["claim"] == "r"
    assert out["snapshot"]["currency"] == "USD"
    fake_crew_instance.kickoff.assert_called_once()


def test_run_crew_analysis_validates_against_thesis_schema(monkeypatch):
    monkeypatch.setenv("YOUDOTCOM_API_KEY", "ydc-test")
    monkeypatch.setattr(crew, "fetch_snapshot", lambda ticker: None)
    bad_dict = _fake_thesis_dict()
    bad_dict["recommendation"] = "strong-buy"  # invalid enum value
    fake_crew_instance = _fake_crew_instance(bad_dict)
    monkeypatch.setattr(crew, "_build_crew", lambda ticker, snapshot, sandbox_id, depth: fake_crew_instance)

    import pytest
    with pytest.raises(ValueError):
        crew.run_crew_analysis("MDB", depth="deep", sandbox_id="sb-1")


def test_run_crew_analysis_raises_without_youdotcom_api_key(monkeypatch):
    """Finding 1: no gating meant deep/full jobs silently ran with every
    You.com call 401ing. run_crew_analysis must fail fast before building the
    crew so agent.py's existing except/mark_failed path marks the job failed
    with an honest error instead of producing fabricated-looking research."""
    monkeypatch.delenv("YOUDOTCOM_API_KEY", raising=False)
    built = []
    monkeypatch.setattr(crew, "_build_crew", lambda *a, **kw: built.append(1))

    import pytest
    with pytest.raises(RuntimeError, match="YOUDOTCOM_API_KEY"):
        crew.run_crew_analysis("MDB", depth="deep", sandbox_id="sb-1")
    assert built == []  # never got far enough to build the crew


def test_run_crew_analysis_sets_grounding_researched_when_citation_present(monkeypatch):
    """Finding 2 (round 2): the crew path must engine-set grounding via the
    shared _grounding() helper (same one llm.py's quick tier uses), not
    hardcode 'researched' unconditionally. When at least one bull/bear/risk
    point carries a source_url, grounding should be 'researched'."""
    monkeypatch.setenv("YOUDOTCOM_API_KEY", "ydc-test")
    monkeypatch.setattr(crew, "fetch_snapshot", lambda ticker: None)
    thesis_dict = _fake_thesis_dict()
    thesis_dict["bull_case"] = [{"claim": "c", "evidence": "e", "source_url": "https://x.test"}]
    fake_crew_instance = _fake_crew_instance(thesis_dict)
    monkeypatch.setattr(crew, "_build_crew", lambda ticker, snapshot, sandbox_id, depth: fake_crew_instance)

    out = crew.run_crew_analysis("MDB", depth="deep", sandbox_id="sb-1")

    assert out["grounding"] == "researched"


def test_run_crew_analysis_sets_grounding_limited_when_no_citations(monkeypatch):
    """Finding 2 (round 2): if the crew completes but every You.com call
    inside it failed (rate limit, network blip, etc.), no bull_case/bear_case/
    key_risks point will carry a source_url even though tools were available
    and the API key was set. The engine must not report 'researched' in that
    case -- it should degrade to 'limited', mirroring llm.py's _grounding()."""
    monkeypatch.setenv("YOUDOTCOM_API_KEY", "ydc-test")
    monkeypatch.setattr(crew, "fetch_snapshot", lambda ticker: None)
    thesis_dict = _fake_thesis_dict()
    thesis_dict["bull_case"] = [{"claim": "c", "evidence": "e", "source_url": None}]
    thesis_dict["bear_case"] = []
    thesis_dict["key_risks"] = []
    fake_crew_instance = _fake_crew_instance(thesis_dict)
    monkeypatch.setattr(crew, "_build_crew", lambda ticker, snapshot, sandbox_id, depth: fake_crew_instance)

    out = crew.run_crew_analysis("MDB", depth="deep", sandbox_id="sb-1")

    assert out["grounding"] == "limited"


def test_run_crew_analysis_records_duration_metric_on_success(monkeypatch):
    """Finding 3: crew.run duration must be recorded via metrics.record_crew_run_duration,
    following the same span + duration pattern llm.py uses for llm.analyze."""
    monkeypatch.setenv("YOUDOTCOM_API_KEY", "ydc-test")
    monkeypatch.setattr(crew, "fetch_snapshot", lambda ticker: None)
    fake_crew_instance = _fake_crew_instance()
    monkeypatch.setattr(crew, "_build_crew", lambda ticker, snapshot, sandbox_id, depth: fake_crew_instance)

    seen = []
    monkeypatch.setattr(
        crew.metrics, "record_crew_run_duration",
        lambda final_status, ticker, depth, duration_ms: seen.append((final_status, ticker, depth)),
    )

    crew.run_crew_analysis("MDB", depth="deep", sandbox_id="sb-1")

    assert seen == [("complete", "MDB", "deep")]


def test_run_crew_analysis_records_duration_metric_on_failure(monkeypatch):
    """The duration metric must still fire (with final_status='failed') when
    kickoff() raises, via the finally block."""
    monkeypatch.setenv("YOUDOTCOM_API_KEY", "ydc-test")
    monkeypatch.setattr(crew, "fetch_snapshot", lambda ticker: None)
    fake_crew_instance = MagicMock()
    fake_crew_instance.kickoff.side_effect = RuntimeError("boom")
    monkeypatch.setattr(crew, "_build_crew", lambda ticker, snapshot, sandbox_id, depth: fake_crew_instance)

    seen = []
    monkeypatch.setattr(
        crew.metrics, "record_crew_run_duration",
        lambda final_status, ticker, depth, duration_ms: seen.append((final_status, ticker, depth)),
    )

    import pytest
    with pytest.raises(RuntimeError, match="boom"):
        crew.run_crew_analysis("MDB", depth="deep", sandbox_id="sb-1")

    assert seen == [("failed", "MDB", "deep")]


def test_max_execution_seconds_reads_env_per_depth(monkeypatch):
    monkeypatch.setenv("CREW_MAX_EXECUTION_S_DEEP", "800")
    monkeypatch.setenv("CREW_MAX_EXECUTION_S_FULL", "1400")
    assert crew._max_execution_seconds("deep") == 800
    assert crew._max_execution_seconds("full") == 1400


def test_max_execution_seconds_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("CREW_MAX_EXECUTION_S_DEEP", raising=False)
    assert crew._max_execution_seconds("deep") == 780


def test_build_crew_divides_max_execution_time_across_four_agents(monkeypatch):
    """Regression guard: _build_crew must divide the per-tier execution budget
    across all 4 agents (not pass the full budget to each), since that
    division is what keeps the crew within the sandbox's auto-delete budget."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("CREW_MAX_EXECUTION_S_DEEP", "800")
    crew_instance = crew._build_crew("MDB", None, "sb-1", "deep")
    expected = 800 // 4
    assert len(crew_instance.agents) == 4
    for agent in crew_instance.agents:
        assert agent.max_execution_time == expected


def test_build_crew_risk_analyst_has_earnings_tool(monkeypatch):
    """Finding 8: the design spec's tool table gives the Risk Analyst
    youdotcom_search, youdotcom_news, AND get_earnings; the implementation
    previously only wired the first two."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    crew_instance = crew._build_crew("MDB", None, "sb-1", "deep")
    risk_agent = crew_instance.agents[2]
    assert risk_agent.role == "Risk Analyst"
    tool_names = {t.name for t in risk_agent.tools}
    assert "get_earnings" in tool_names
