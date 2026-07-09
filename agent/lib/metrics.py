"""Metrics facade: records each metric once into an OTel Meter (exported via a
periodic OTLP reader) and mirrors it to Sentry's native metrics API. Every path
is guarded so a metrics failure never propagates. No-ops when unconfigured.

job_id is intentionally never used as an attribute (unbounded cardinality)."""
import os
import time
from contextvars import ContextVar

_meter = None
_meter_provider = None
_instruments: dict = {}
_sentry_metrics_enabled = False
_current_ticker: ContextVar[str] = ContextVar("current_ticker", default="unknown")
_http_starts: dict = {}


def _metrics_endpoint(traces_endpoint: str) -> str:
    """Derive the OTLP metrics URL from the OTLP traces URL. Explicit override
    via DD_OTLP_METRICS_ENDPOINT wins."""
    override = os.environ.get("DD_OTLP_METRICS_ENDPOINT")
    if override:
        return override
    if traces_endpoint.endswith("/v1/traces"):
        return traces_endpoint[: -len("/v1/traces")] + "/v1/metrics"
    return traces_endpoint


def init_metrics(resource, extra_readers=None) -> None:
    """Build a MeterProvider with an OTLP metric reader when configured, plus any
    extra_readers (used by tests). Idempotent + safe when nothing is configured."""
    global _meter, _meter_provider, _instruments, _sentry_metrics_enabled
    if _meter is not None:
        return
    from opentelemetry import metrics as ot_metrics
    from opentelemetry.sdk.metrics import MeterProvider

    readers = list(extra_readers or [])

    dd_key = os.environ.get("DD_API_KEY")
    dd_disabled = os.environ.get("DD_TRACE_ENABLED", "").strip().lower() == "false"
    dd_exporter = (os.environ.get("DD_EXPORTER") or "agent").strip().lower()
    otlp_endpoint = os.environ.get("DD_OTLP_ENDPOINT")
    if dd_key and not dd_disabled and dd_exporter == "otlp" and otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        readers.append(PeriodicExportingMetricReader(OTLPMetricExporter(
            endpoint=_metrics_endpoint(otlp_endpoint),
            headers={"DD-API-KEY": dd_key},
        )))

    _meter_provider = MeterProvider(resource=resource, metric_readers=readers)
    try:
        ot_metrics.set_meter_provider(_meter_provider)
    except Exception:
        pass
    _meter = _meter_provider.get_meter("stock-agent")

    _instruments = {
        "jobs_completed": _meter.create_counter("jobs.completed"),
        "agent_run_duration_ms": _meter.create_histogram("agent.run.duration_ms", unit="ms"),
        "llm_tokens_in": _meter.create_histogram("llm.tokens_in"),
        "llm_tokens_out": _meter.create_histogram("llm.tokens_out"),
        "llm_calls": _meter.create_counter("llm.calls"),
        "llm_empty_response": _meter.create_counter("llm.empty_response"),
        "http_requests": _meter.create_counter("agent.http.requests"),
        "http_duration_ms": _meter.create_histogram("agent.http.duration_ms", unit="ms"),
    }

    _sentry_metrics_enabled = bool(os.environ.get("SENTRY_DSN_AGENT"))


def set_current_ticker(ticker: str) -> None:
    _current_ticker.set(ticker or "unknown")


def flush_metrics(timeout_s: float = 5.0) -> None:
    if _meter_provider is None:
        return
    try:
        _meter_provider.force_flush(timeout_millis=int(timeout_s * 1000))
    except Exception:
        pass


# --- Sentry mirror (guarded; resilient to SDK API differences) ---
def _sentry_incr(key, value, tags):
    if not _sentry_metrics_enabled:
        return
    try:
        import sentry_sdk
        m = getattr(sentry_sdk, "metrics", None)
        if m and hasattr(m, "count"):
            m.count(key, value, attributes=tags)
    except Exception:
        pass


def _sentry_dist(key, value, tags):
    if not _sentry_metrics_enabled:
        return
    try:
        import sentry_sdk
        m = getattr(sentry_sdk, "metrics", None)
        if m and hasattr(m, "distribution"):
            m.distribution(key, value, attributes=tags)
    except Exception:
        pass


def _add(instr_key, value, attrs):
    if _meter is None:
        return
    try:
        instr = _instruments.get(instr_key)
        if instr is not None:
            instr.add(value, attrs)
    except Exception:
        pass


def _hist(instr_key, value, attrs):
    if _meter is None:
        return
    try:
        instr = _instruments.get(instr_key)
        if instr is not None:
            instr.record(value, attrs)
    except Exception:
        pass


# --- Public emit functions ---
def record_job_completed(final_status: str, ticker: str) -> None:
    attrs = {"final_status": final_status, "ticker": ticker}
    _add("jobs_completed", 1, attrs)
    _sentry_incr("jobs.completed", 1, attrs)


def record_agent_run_duration(final_status: str, ticker: str, duration_ms: float) -> None:
    attrs = {"final_status": final_status, "ticker": ticker}
    _hist("agent_run_duration_ms", duration_ms, attrs)
    _sentry_dist("agent.run.duration_ms", duration_ms, attrs)


def record_llm_tokens(model: str, api: str, tokens_in: int, tokens_out: int, ticker: str) -> None:
    attrs = {"model": model, "api": api, "ticker": ticker}
    _hist("llm_tokens_in", tokens_in, attrs)
    _hist("llm_tokens_out", tokens_out, attrs)
    _sentry_dist("llm.tokens_in", tokens_in, attrs)
    _sentry_dist("llm.tokens_out", tokens_out, attrs)


def record_llm_call(model: str, api: str, outcome: str, ticker: str) -> None:
    attrs = {"model": model, "api": api, "outcome": outcome, "ticker": ticker}
    _add("llm_calls", 1, attrs)
    _sentry_incr("llm.calls", 1, attrs)


def record_llm_empty_response(model: str, api: str, ticker: str) -> None:
    attrs = {"model": model, "api": api, "ticker": ticker}
    _add("llm_empty_response", 1, attrs)
    _sentry_incr("llm.empty_response", 1, attrs)


def record_http_request(host: str, status_code: int, duration_ms: float, ticker: str) -> None:
    count_attrs = {"host": host, "status_code": status_code, "ticker": ticker}
    dur_attrs = {"host": host, "ticker": ticker}
    _add("http_requests", 1, count_attrs)
    _hist("http_duration_ms", duration_ms, dur_attrs)
    _sentry_incr("agent.http.requests", 1, count_attrs)
    _sentry_dist("agent.http.duration_ms", duration_ms, dur_attrs)


# --- httpx event hooks + instrumented client factory ---
def _on_request(request) -> None:
    _http_starts[id(request)] = time.monotonic()


def _on_response(response) -> None:
    start = _http_starts.pop(id(response.request), None)
    dur_ms = (time.monotonic() - start) * 1000 if start is not None else 0.0
    try:
        host = response.request.url.host
    except Exception:
        host = "unknown"
    record_http_request(host=host, status_code=response.status_code,
                        duration_ms=dur_ms, ticker=_current_ticker.get())


def build_httpx_client():
    """An httpx.Client whose event hooks emit agent.http.* metrics. Pass to the
    OpenAI client so all outbound OpenAI HTTP calls are measured."""
    import httpx
    return httpx.Client(event_hooks={"request": [_on_request], "response": [_on_response]})
