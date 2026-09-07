import contextlib
from unittest.mock import MagicMock
import lib.llmobs as llmobs


def test_init_llmobs_noop_without_api_key(monkeypatch):
    monkeypatch.delenv("DD_API_KEY", raising=False)
    monkeypatch.setattr(llmobs, "_llmobs_inited", False)
    assert llmobs.init_llmobs() is False
    assert llmobs.llmobs_enabled() is False


def test_init_llmobs_noop_when_flag_false(monkeypatch):
    monkeypatch.setenv("DD_API_KEY", "dd-test-key")
    monkeypatch.setenv("DD_LLMOBS_ENABLED", "false")
    monkeypatch.setattr(llmobs, "_llmobs_inited", False)
    assert llmobs.init_llmobs() is False
    assert llmobs.llmobs_enabled() is False


def test_init_llmobs_enables_when_configured(monkeypatch):
    monkeypatch.setenv("DD_API_KEY", "dd-test-key")
    monkeypatch.setenv("DD_SITE", "datadoghq.eu")
    monkeypatch.setenv("DD_ENV", "staging")
    monkeypatch.setenv("DD_SERVICE", "stock-agent-test")
    monkeypatch.delenv("DD_LLMOBS_ENABLED", raising=False)
    monkeypatch.setattr(llmobs, "_llmobs_inited", False)

    calls = []
    fake_llmobs = MagicMock()
    fake_llmobs.enable.side_effect = lambda **kw: calls.append(kw)
    import ddtrace.llmobs as ddllmobs
    monkeypatch.setattr(ddllmobs, "LLMObs", fake_llmobs)

    assert llmobs.init_llmobs() is True
    assert llmobs.llmobs_enabled() is True
    assert calls == [{
        "ml_app": "stock-agent",
        "agentless_enabled": True,
        "api_key": "dd-test-key",
        "site": "datadoghq.eu",
        "env": "staging",
        "service": "stock-agent-test",
    }]


def test_init_llmobs_handles_enable_exception(monkeypatch):
    monkeypatch.setenv("DD_API_KEY", "dd-test-key")
    monkeypatch.setattr(llmobs, "_llmobs_inited", False)

    fake_llmobs = MagicMock()
    fake_llmobs.enable.side_effect = RuntimeError("boom")
    import ddtrace.llmobs as ddllmobs
    monkeypatch.setattr(ddllmobs, "LLMObs", fake_llmobs)

    assert llmobs.init_llmobs() is False
    assert llmobs.llmobs_enabled() is False


def test_workflow_span_yields_none_when_disabled(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", False)
    with llmobs.workflow_span("agent.run", session_id="job-1") as span:
        assert span is None


def test_agent_span_yields_none_when_disabled(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", False)
    with llmobs.agent_span("llm.analyze") as span:
        assert span is None


def test_llm_span_yields_none_when_disabled(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", False)
    with llmobs.llm_span("llm.call", "gpt-4.1-mini") as span:
        assert span is None


def test_tool_span_yields_none_when_disabled(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", False)
    with llmobs.tool_span("tool.get_financials") as span:
        assert span is None


def _fake_cm(sentinel):
    @contextlib.contextmanager
    def _cm(**kwargs):
        _cm.calls.append(kwargs)
        yield sentinel
    _cm.calls = []
    return _cm


def test_workflow_span_delegates_to_llmobs_when_enabled(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", True)
    fake_workflow = _fake_cm("SPAN")
    fake_llmobs = MagicMock(workflow=fake_workflow)
    import ddtrace.llmobs as ddllmobs
    monkeypatch.setattr(ddllmobs, "LLMObs", fake_llmobs)

    with llmobs.workflow_span("agent.run", session_id="job-1") as span:
        assert span == "SPAN"
    assert fake_workflow.calls == [{"name": "agent.run", "session_id": "job-1"}]


def test_agent_span_delegates_to_llmobs_when_enabled(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", True)
    fake_agent = _fake_cm("SPAN")
    fake_llmobs = MagicMock(agent=fake_agent)
    import ddtrace.llmobs as ddllmobs
    monkeypatch.setattr(ddllmobs, "LLMObs", fake_llmobs)

    with llmobs.agent_span("llm.analyze") as span:
        assert span == "SPAN"
    assert fake_agent.calls == [{"name": "llm.analyze"}]


def test_llm_span_delegates_to_llmobs_when_enabled(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", True)
    fake_llm = _fake_cm("SPAN")
    fake_llmobs = MagicMock(llm=fake_llm)
    import ddtrace.llmobs as ddllmobs
    monkeypatch.setattr(ddllmobs, "LLMObs", fake_llmobs)

    with llmobs.llm_span("llm.call", "gpt-4.1-mini") as span:
        assert span == "SPAN"
    assert fake_llm.calls == [{"name": "llm.call", "model_name": "gpt-4.1-mini"}]


def test_tool_span_delegates_to_llmobs_when_enabled(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", True)
    fake_tool = _fake_cm("SPAN")
    fake_llmobs = MagicMock(tool=fake_tool)
    import ddtrace.llmobs as ddllmobs
    monkeypatch.setattr(ddllmobs, "LLMObs", fake_llmobs)

    with llmobs.tool_span("tool.get_financials") as span:
        assert span == "SPAN"
    assert fake_tool.calls == [{"name": "tool.get_financials"}]


def test_annotate_noop_when_span_none():
    llmobs.annotate(None, input_data="x", output_data="y")  # must not raise


def test_annotate_calls_llmobs_annotate_with_kwargs(monkeypatch):
    fake_llmobs = MagicMock()
    import ddtrace.llmobs as ddllmobs
    monkeypatch.setattr(ddllmobs, "LLMObs", fake_llmobs)

    llmobs.annotate("SPAN", input_data="x", output_data="y", metrics={"input_tokens": 1})
    fake_llmobs.annotate.assert_called_once_with(
        "SPAN", input_data="x", output_data="y", metrics={"input_tokens": 1}
    )


def test_annotate_swallows_exception(monkeypatch):
    fake_llmobs = MagicMock()
    fake_llmobs.annotate.side_effect = RuntimeError("boom")
    import ddtrace.llmobs as ddllmobs
    monkeypatch.setattr(ddllmobs, "LLMObs", fake_llmobs)

    llmobs.annotate("SPAN", input_data="x")  # must not raise


def test_flush_llmobs_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", False)
    llmobs.flush_llmobs(timeout_s=1.0)  # must not raise, must not import ddtrace


def test_flush_llmobs_calls_llmobs_flush_when_enabled(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", True)
    fake_llmobs = MagicMock()
    import ddtrace.llmobs as ddllmobs
    monkeypatch.setattr(ddllmobs, "LLMObs", fake_llmobs)

    llmobs.flush_llmobs(timeout_s=1.0)
    fake_llmobs.flush.assert_called_once()


def test_flush_llmobs_swallows_exception(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", True)
    fake_llmobs = MagicMock()
    fake_llmobs.flush.side_effect = RuntimeError("boom")
    import ddtrace.llmobs as ddllmobs
    monkeypatch.setattr(ddllmobs, "LLMObs", fake_llmobs)

    llmobs.flush_llmobs(timeout_s=1.0)  # must not raise
