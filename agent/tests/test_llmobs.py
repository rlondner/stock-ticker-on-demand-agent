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


def test_workflow_span_yields_none_when_llmobs_raises_on_open(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", True)
    fake_llmobs = MagicMock()
    fake_llmobs.workflow.side_effect = RuntimeError("boom")
    import ddtrace.llmobs as ddllmobs
    monkeypatch.setattr(ddllmobs, "LLMObs", fake_llmobs)

    with llmobs.workflow_span("agent.run", session_id="job-1") as span:
        assert span is None  # must not raise


def test_agent_span_yields_none_when_llmobs_raises_on_open(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", True)
    fake_llmobs = MagicMock()
    fake_llmobs.agent.side_effect = RuntimeError("boom")
    import ddtrace.llmobs as ddllmobs
    monkeypatch.setattr(ddllmobs, "LLMObs", fake_llmobs)

    with llmobs.agent_span("llm.analyze") as span:
        assert span is None  # must not raise


def test_llm_span_yields_none_when_llmobs_raises_on_open(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", True)
    fake_llmobs = MagicMock()
    fake_llmobs.llm.side_effect = RuntimeError("boom")
    import ddtrace.llmobs as ddllmobs
    monkeypatch.setattr(ddllmobs, "LLMObs", fake_llmobs)

    with llmobs.llm_span("llm.call", "gpt-4.1-mini") as span:
        assert span is None  # must not raise


def test_tool_span_yields_none_when_llmobs_raises_on_open(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", True)
    fake_llmobs = MagicMock()
    fake_llmobs.tool.side_effect = RuntimeError("boom")
    import ddtrace.llmobs as ddllmobs
    monkeypatch.setattr(ddllmobs, "LLMObs", fake_llmobs)

    with llmobs.tool_span("tool.get_financials") as span:
        assert span is None  # must not raise


def _fake_cm_direct(sentinel):
    """A MagicMock-based fake context manager with directly controllable
    __enter__/__exit__, so tests can assert on the exact exception info
    __exit__ was called with."""
    fake_cm = MagicMock()
    fake_cm.__enter__ = MagicMock(return_value=sentinel)
    fake_cm.__exit__ = MagicMock(return_value=False)
    return fake_cm


def _install_fake_cm(monkeypatch, attr_name, fake_cm):
    fake_llmobs = MagicMock()
    setattr(fake_llmobs, attr_name, MagicMock(return_value=fake_cm))
    import ddtrace.llmobs as ddllmobs
    monkeypatch.setattr(ddllmobs, "LLMObs", fake_llmobs)


# (span_context_manager_factory, LLMObs attribute name to mock)
_SPAN_CASES = [
    (lambda: llmobs.workflow_span("agent.run", session_id="job-1"), "workflow"),
    (lambda: llmobs.agent_span("llm.analyze"), "agent"),
    (lambda: llmobs.llm_span("llm.call", "gpt-4.1-mini"), "llm"),
    (lambda: llmobs.tool_span("tool.get_financials"), "tool"),
]


def test_workflow_span_propagates_body_exception_and_forwards_exc_info(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", True)
    fake_cm = _fake_cm_direct("SPAN")
    _install_fake_cm(monkeypatch, "workflow", fake_cm)

    class Boom(RuntimeError):
        pass

    raised = None
    try:
        with llmobs.workflow_span("agent.run", session_id="job-1") as span:
            assert span == "SPAN"
            raise Boom("body failed")
    except Boom as e:
        raised = e
    assert raised is not None, "the body's exception must propagate to the caller"

    fake_cm.__exit__.assert_called_once()
    exc_type, exc_value, tb = fake_cm.__exit__.call_args.args
    assert exc_type is Boom
    assert isinstance(exc_value, Boom)
    assert tb is not None


def test_agent_span_propagates_body_exception_and_forwards_exc_info(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", True)
    fake_cm = _fake_cm_direct("SPAN")
    _install_fake_cm(monkeypatch, "agent", fake_cm)

    class Boom(RuntimeError):
        pass

    raised = None
    try:
        with llmobs.agent_span("llm.analyze") as span:
            assert span == "SPAN"
            raise Boom("body failed")
    except Boom as e:
        raised = e
    assert raised is not None

    fake_cm.__exit__.assert_called_once()
    exc_type, exc_value, tb = fake_cm.__exit__.call_args.args
    assert exc_type is Boom
    assert isinstance(exc_value, Boom)
    assert tb is not None


def test_llm_span_propagates_body_exception_and_forwards_exc_info(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", True)
    fake_cm = _fake_cm_direct("SPAN")
    _install_fake_cm(monkeypatch, "llm", fake_cm)

    class Boom(RuntimeError):
        pass

    raised = None
    try:
        with llmobs.llm_span("llm.call", "gpt-4.1-mini") as span:
            assert span == "SPAN"
            raise Boom("body failed")
    except Boom as e:
        raised = e
    assert raised is not None

    fake_cm.__exit__.assert_called_once()
    exc_type, exc_value, tb = fake_cm.__exit__.call_args.args
    assert exc_type is Boom
    assert isinstance(exc_value, Boom)
    assert tb is not None


def test_tool_span_propagates_body_exception_and_forwards_exc_info(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", True)
    fake_cm = _fake_cm_direct("SPAN")
    _install_fake_cm(monkeypatch, "tool", fake_cm)

    class Boom(RuntimeError):
        pass

    raised = None
    try:
        with llmobs.tool_span("tool.get_financials") as span:
            assert span == "SPAN"
            raise Boom("body failed")
    except Boom as e:
        raised = e
    assert raised is not None

    fake_cm.__exit__.assert_called_once()
    exc_type, exc_value, tb = fake_cm.__exit__.call_args.args
    assert exc_type is Boom
    assert isinstance(exc_value, Boom)
    assert tb is not None


def test_workflow_span_swallows_exit_failure_on_normal_exit(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", True)
    fake_cm = _fake_cm_direct("SPAN")
    fake_cm.__exit__.side_effect = RuntimeError("exit boom")
    _install_fake_cm(monkeypatch, "workflow", fake_cm)

    with llmobs.workflow_span("agent.run", session_id="job-1") as span:
        assert span == "SPAN"
    # must not raise


def test_agent_span_swallows_exit_failure_on_normal_exit(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", True)
    fake_cm = _fake_cm_direct("SPAN")
    fake_cm.__exit__.side_effect = RuntimeError("exit boom")
    _install_fake_cm(monkeypatch, "agent", fake_cm)

    with llmobs.agent_span("llm.analyze") as span:
        assert span == "SPAN"
    # must not raise


def test_llm_span_swallows_exit_failure_on_normal_exit(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", True)
    fake_cm = _fake_cm_direct("SPAN")
    fake_cm.__exit__.side_effect = RuntimeError("exit boom")
    _install_fake_cm(monkeypatch, "llm", fake_cm)

    with llmobs.llm_span("llm.call", "gpt-4.1-mini") as span:
        assert span == "SPAN"
    # must not raise


def test_tool_span_swallows_exit_failure_on_normal_exit(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", True)
    fake_cm = _fake_cm_direct("SPAN")
    fake_cm.__exit__.side_effect = RuntimeError("exit boom")
    _install_fake_cm(monkeypatch, "tool", fake_cm)

    with llmobs.tool_span("tool.get_financials") as span:
        assert span == "SPAN"
    # must not raise


def test_workflow_span_preserves_original_exception_when_exit_also_raises(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", True)
    fake_cm = _fake_cm_direct("SPAN")
    fake_cm.__exit__.side_effect = RuntimeError("exit boom")
    _install_fake_cm(monkeypatch, "workflow", fake_cm)

    class Original(RuntimeError):
        pass

    raised = None
    try:
        with llmobs.workflow_span("agent.run", session_id="job-1") as span:
            raise Original("original failure")
    except Exception as e:
        raised = e
    assert isinstance(raised, Original), "the original exception must win, not the exit failure"


def test_agent_span_preserves_original_exception_when_exit_also_raises(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", True)
    fake_cm = _fake_cm_direct("SPAN")
    fake_cm.__exit__.side_effect = RuntimeError("exit boom")
    _install_fake_cm(monkeypatch, "agent", fake_cm)

    class Original(RuntimeError):
        pass

    raised = None
    try:
        with llmobs.agent_span("llm.analyze") as span:
            raise Original("original failure")
    except Exception as e:
        raised = e
    assert isinstance(raised, Original)


def test_llm_span_preserves_original_exception_when_exit_also_raises(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", True)
    fake_cm = _fake_cm_direct("SPAN")
    fake_cm.__exit__.side_effect = RuntimeError("exit boom")
    _install_fake_cm(monkeypatch, "llm", fake_cm)

    class Original(RuntimeError):
        pass

    raised = None
    try:
        with llmobs.llm_span("llm.call", "gpt-4.1-mini") as span:
            raise Original("original failure")
    except Exception as e:
        raised = e
    assert isinstance(raised, Original)


def test_tool_span_preserves_original_exception_when_exit_also_raises(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", True)
    fake_cm = _fake_cm_direct("SPAN")
    fake_cm.__exit__.side_effect = RuntimeError("exit boom")
    _install_fake_cm(monkeypatch, "tool", fake_cm)

    class Original(RuntimeError):
        pass

    raised = None
    try:
        with llmobs.tool_span("tool.get_financials") as span:
            raise Original("original failure")
    except Exception as e:
        raised = e
    assert isinstance(raised, Original)


def test_workflow_span_respects_exit_suppress_true(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", True)
    fake_cm = _fake_cm_direct("SPAN")
    fake_cm.__exit__.return_value = True  # ask to suppress, like a native `with`
    _install_fake_cm(monkeypatch, "workflow", fake_cm)

    with llmobs.workflow_span("agent.run", session_id="job-1") as span:
        raise RuntimeError("should be suppressed")
    # must not raise: __exit__ returning True suppresses the exception
