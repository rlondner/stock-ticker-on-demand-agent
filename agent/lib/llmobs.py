"""Datadog Agent (LLM) Observability instrumentation. Thin wrappers around
ddtrace.llmobs so every call site can use them unconditionally: they gate on
whether LLMObs is enabled and never raise, so telemetry can never break an
agent run. This runs alongside (not instead of) the OTel spans set up in
observability.py — it's an additional signal feeding Datadog's dedicated LLM
Observability UI, not a replacement for the unified OTel/Sentry/Datadog-APM
pipeline."""
import contextlib
import os

_llmobs_inited = False


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
    with LLMObs.workflow(name=name, session_id=session_id) as span:
        yield span


@contextlib.contextmanager
def agent_span(name: str):
    """Span for one tool-use loop (one run_agent_loop() call)."""
    if not _llmobs_inited:
        yield None
        return
    from ddtrace.llmobs import LLMObs
    with LLMObs.agent(name=name) as span:
        yield span


@contextlib.contextmanager
def llm_span(name: str, model_name: str):
    """Span for one actual model API call."""
    if not _llmobs_inited:
        yield None
        return
    from ddtrace.llmobs import LLMObs
    with LLMObs.llm(name=name, model_name=model_name) as span:
        yield span


@contextlib.contextmanager
def tool_span(name: str):
    """Span for one tool dispatch (a function-tool call or the hosted web_search)."""
    if not _llmobs_inited:
        yield None
        return
    from ddtrace.llmobs import LLMObs
    with LLMObs.tool(name=name) as span:
        yield span


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
