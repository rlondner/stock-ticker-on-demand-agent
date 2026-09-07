"""Datadog Agent (LLM) Observability instrumentation. Thin wrappers around
ddtrace.llmobs so every call site can use them unconditionally: they gate on
whether LLMObs is enabled and never raise, so telemetry can never break an
agent run. This runs alongside (not instead of) the OTel spans set up in
observability.py — it's an additional signal feeding Datadog's dedicated LLM
Observability UI, not a replacement for the unified OTel/Sentry/Datadog-APM
pipeline."""
import contextlib
import os
import sys

_llmobs_inited = False


def _exit_span(cm, exc_type, exc_value, tb) -> bool:
    """Call cm.__exit__ with the given exception info, swallowing any
    exception __exit__ itself raises (telemetry teardown must never break
    the caller). Returns whether __exit__ asked to suppress the exception,
    exactly like a native `with` statement would (False if __exit__ raised
    or returned a falsy value)."""
    try:
        return bool(cm.__exit__(exc_type, exc_value, tb))
    except Exception:
        return False


def init_llmobs() -> bool:
    """Enable ddtrace's LLM Observability SDK in agentless mode (Daytona
    sandboxes have no local Datadog Agent). Gated on DD_API_KEY and the
    independent DD_LLMOBS_ENABLED kill switch (this is the one signal that
    ships full prompt/completion text). Idempotent-ish: safe to call once per
    process; returns whether LLMObs ended up enabled. Never raises."""
    global _llmobs_inited
    if not os.environ.get("DD_API_KEY"):
        return False
    if os.environ.get("DD_LLMOBS_ENABLED", "").strip().lower() == "false":
        return False
    try:
        from ddtrace.llmobs import LLMObs
        LLMObs.enable(
            ml_app="stock-agent",
            agentless_enabled=True,
            api_key=os.environ["DD_API_KEY"],
            site=os.environ.get("DD_SITE", "datadoghq.com"),
            env=os.environ.get("DD_ENV", "development"),
            service=os.environ.get("DD_SERVICE", "stock-agent"),
        )
    except Exception:
        return False
    _llmobs_inited = True
    return True


def llmobs_enabled() -> bool:
    return _llmobs_inited


@contextlib.contextmanager
def workflow_span(name: str, session_id: str | None = None):
    """Top-level span for one job. Set session_id here only — it propagates
    to child agent/llm/tool spans in the same trace automatically."""
    if not _llmobs_inited:
        yield None
        return
    from ddtrace.llmobs import LLMObs
    try:
        cm = LLMObs.workflow(name=name, session_id=session_id)
        span = cm.__enter__()
    except Exception:
        yield None
        return
    try:
        yield span
    except BaseException:
        exc_type, exc_value, tb = sys.exc_info()
        if not _exit_span(cm, exc_type, exc_value, tb):
            raise
    else:
        _exit_span(cm, None, None, None)


@contextlib.contextmanager
def agent_span(name: str):
    """Span for one tool-use loop (one run_agent_loop() call)."""
    if not _llmobs_inited:
        yield None
        return
    from ddtrace.llmobs import LLMObs
    try:
        cm = LLMObs.agent(name=name)
        span = cm.__enter__()
    except Exception:
        yield None
        return
    try:
        yield span
    except BaseException:
        exc_type, exc_value, tb = sys.exc_info()
        if not _exit_span(cm, exc_type, exc_value, tb):
            raise
    else:
        _exit_span(cm, None, None, None)


@contextlib.contextmanager
def llm_span(name: str, model_name: str):
    """Span for one actual model API call."""
    if not _llmobs_inited:
        yield None
        return
    from ddtrace.llmobs import LLMObs
    try:
        cm = LLMObs.llm(name=name, model_name=model_name)
        span = cm.__enter__()
    except Exception:
        yield None
        return
    try:
        yield span
    except BaseException:
        exc_type, exc_value, tb = sys.exc_info()
        if not _exit_span(cm, exc_type, exc_value, tb):
            raise
    else:
        _exit_span(cm, None, None, None)


@contextlib.contextmanager
def tool_span(name: str):
    """Span for one tool dispatch (a function-tool call or the hosted web_search)."""
    if not _llmobs_inited:
        yield None
        return
    from ddtrace.llmobs import LLMObs
    try:
        cm = LLMObs.tool(name=name)
        span = cm.__enter__()
    except Exception:
        yield None
        return
    try:
        yield span
    except BaseException:
        exc_type, exc_value, tb = sys.exc_info()
        if not _exit_span(cm, exc_type, exc_value, tb):
            raise
    else:
        _exit_span(cm, None, None, None)


def annotate(span, **kwargs) -> None:
    """Attach input/output/metadata/metrics to an LLMObs span. No-op if span
    is None (LLMObs disabled). Never raises — an annotation failure must not
    break the agent run."""
    if span is None:
        return
    try:
        from ddtrace.llmobs import LLMObs
        LLMObs.annotate(span, **kwargs)
    except Exception:
        pass


def flush_llmobs(timeout_s: float = 5.0) -> None:
    """Drain the LLMObs writer. MUST run before the Daytona sandbox
    self-deletes. No-op if LLMObs was never enabled."""
    if not _llmobs_inited:
        return
    try:
        from ddtrace.llmobs import LLMObs
        LLMObs.flush()
    except Exception:
        pass
