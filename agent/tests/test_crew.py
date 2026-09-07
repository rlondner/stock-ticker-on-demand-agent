from unittest.mock import MagicMock, patch
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


def test_run_crew_analysis_returns_thesis_plus_snapshot(monkeypatch):
    monkeypatch.setattr(crew, "fetch_snapshot", lambda ticker: _fake_snapshot())
    fake_crew_instance = MagicMock()
    fake_crew_instance.kickoff.return_value = MagicMock(raw=None)
    monkeypatch.setattr(crew, "_build_crew", lambda ticker, snapshot, sandbox_id, depth: fake_crew_instance)
    monkeypatch.setattr(crew, "_extract_thesis_dict", lambda crew_output: _fake_thesis_dict())

    out = crew.run_crew_analysis("MDB", depth="deep", sandbox_id="sb-1")

    assert out["recommendation"] == "buy"
    assert out["researcher_findings"][0]["claim"] == "r"
    assert out["snapshot"]["currency"] == "USD"
    fake_crew_instance.kickoff.assert_called_once()


def test_run_crew_analysis_validates_against_thesis_schema(monkeypatch):
    monkeypatch.setattr(crew, "fetch_snapshot", lambda ticker: None)
    bad_dict = _fake_thesis_dict()
    bad_dict["recommendation"] = "strong-buy"  # invalid enum value
    fake_crew_instance = MagicMock()
    fake_crew_instance.kickoff.return_value = MagicMock(raw=None)
    monkeypatch.setattr(crew, "_build_crew", lambda ticker, snapshot, sandbox_id, depth: fake_crew_instance)
    monkeypatch.setattr(crew, "_extract_thesis_dict", lambda crew_output: bad_dict)

    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        crew.run_crew_analysis("MDB", depth="deep", sandbox_id="sb-1")


def test_max_execution_seconds_reads_env_per_depth(monkeypatch):
    monkeypatch.setenv("CREW_MAX_EXECUTION_S_DEEP", "800")
    monkeypatch.setenv("CREW_MAX_EXECUTION_S_FULL", "1400")
    assert crew._max_execution_seconds("deep") == 800
    assert crew._max_execution_seconds("full") == 1400


def test_max_execution_seconds_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("CREW_MAX_EXECUTION_S_DEEP", raising=False)
    assert crew._max_execution_seconds("deep") == 780
