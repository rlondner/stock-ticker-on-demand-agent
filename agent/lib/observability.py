import logging
import os
import socket
from opentelemetry import trace, propagate, context as ot_context
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace.status import Status, StatusCode
from .otlp_target import resolve_otlp_target

_stdlib_logger = logging.getLogger("stock-agent")

_initialized = False
_sentry_inited = False
_dd_inited = False
_otlp_traces_inited = False
_logger_provider = None


def get_host() -> str:
    """Actual OS hostname of the machine executing the agent. On a Daytona
    sandbox this returns the sandbox's assigned hostname; on your workstation
    it returns your local hostname."""
    return socket.gethostname()

def init_observability(job_id: str) -> None:
    """Initialize OTel and any configured exporters (Sentry/Datadog).
    Idempotent - safe to call multiple times."""
    global _initialized, _sentry_inited, _dd_inited, _otlp_traces_inited
    if _initialized:
        return

    resource = Resource.create({
        "service.name": "stock-agent",
        "deployment.environment": os.environ.get("DD_ENV", "development"),
        "job.id": job_id,
        "host.name": get_host(),
    })
    provider = TracerProvider(resource=resource)

    # Always log spans to stdout in addition to any exporters (Daytona captures stdout).
    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)

    # Metrics: share the same Resource; OTLP metric export is gated identically
    # to the OTLP trace path (see lib/metrics.init_metrics).
    from lib.metrics import init_metrics
    init_metrics(resource)

    # === Sentry exporter ===
    # Sentry Python SDK v2+ integrates with OTel via SentrySpanProcessor +
    # SentryPropagator — spans created on the OTel TracerProvider are forwarded
    # to Sentry automatically. No application code touches sentry_sdk directly.
    dsn = os.environ.get("SENTRY_DSN_AGENT")
    if dsn:
        import sentry_sdk
        from sentry_sdk.integrations.opentelemetry import SentrySpanProcessor, SentryPropagator
        sentry_sdk.init(
            dsn=dsn,
            traces_sample_rate=1.0,
            environment=os.environ.get("DD_ENV", "development"),
            _experiments={"enable_logs": True},
        )
        sentry_sdk.set_tag("host", get_host())
        provider.add_span_processor(SentrySpanProcessor())
        propagate.set_global_textmap(SentryPropagator())
        global _sentry_inited
        _sentry_inited = True

    # === Datadog / OTLP trace exporter ===
    # DD_EXPORTER picks how traces reach Datadog:
    #   'agent' (opt-in): ddtrace.patch_all → ships to a local Datadog Agent on
    #     localhost:8126. Auto-instruments httpx/psycopg/openai/logging. Requires
    #     DD_API_KEY and an Agent reachable from this process. Set
    #     DD_TRACE_ENABLED=false to short-circuit when no Agent is running.
    #   'otlp' (default): OTLP-HTTP exporter driven by resolve_otlp_target("traces").
    #     No Agent needed (good for Daytona sandboxes). OTel-native auto-instrumentation
    #     (httpx/psycopg/openai) is activated when available.
    dd_disabled = os.environ.get("DD_TRACE_ENABLED", "").strip().lower() == "false"
    dd_exporter = (os.environ.get("DD_EXPORTER") or "otlp").strip().lower()
    if dd_exporter not in ("agent", "otlp"):
        raise ValueError(
            f"DD_EXPORTER={dd_exporter!r} is not valid; expected 'agent' or 'otlp'"
        )
    if dd_exporter == "agent" and os.environ.get("DD_API_KEY") and not dd_disabled:
        import ddtrace
        ddtrace.config.service = os.environ.get("DD_SERVICE", "stock-agent")
        ddtrace.config.env = os.environ.get("DD_ENV", "development")
        os.environ.setdefault("DD_TRACE_OTEL_ENABLED", "true")
        ddtrace.patch_all(httpx=True, psycopg=True, openai=True, logging=True)
        global _dd_inited
        _dd_inited = True
    else:
        # Intentional OTLP-default path: covers both dd_exporter=="otlp" and the
        # degenerate agent-mode case (missing DD_API_KEY or DD_TRACE_ENABLED=false).
        # resolve_otlp_target returns None when unconfigured → no exporter installed,
        # but _install_trace_instrumentors() still runs harmlessly.
        _trace_target = resolve_otlp_target("traces")
        if _trace_target is not None:
            endpoint, headers = _trace_target
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
                endpoint=endpoint, headers=headers,
            )))
            global _otlp_traces_inited
            _otlp_traces_inited = True
        _install_trace_instrumentors()

    # Logs: OTel LoggerProvider bridged from stdlib; OTLP export via resolver.
    try:
        from opentelemetry.sdk._logs import LoggerProvider
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        global _logger_provider
        _logger_provider = LoggerProvider(resource=resource)
        _log_target = resolve_otlp_target("logs")
        if _log_target is not None:
            endpoint, headers = _log_target
            from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
            _logger_provider.add_log_record_processor(BatchLogRecordProcessor(
                OTLPLogExporter(endpoint=endpoint, headers=headers),
            ))
        _install_log_bridge(_logger_provider)
    except Exception:
        pass

    # Continue the W3C trace from the parent (NextJS) if TRACEPARENT was passed.
    traceparent = os.environ.get("TRACEPARENT")
    if traceparent:
        carrier = {"traceparent": traceparent}
        ctx = propagate.extract(carrier)
        ot_context.attach(ctx)

    _initialized = True

def record_error(span, exc: BaseException) -> None:
    """Vendor-neutral: record the exception on the span and mark it ERROR."""
    span.record_exception(exc)
    span.set_status(Status(StatusCode.ERROR, str(exc)))


def _dd_site() -> str:
    return os.environ.get("DD_SITE", "datadoghq.com").strip() or "datadoghq.com"


def _dd_enabled() -> bool:
    if not os.environ.get("DD_API_KEY"):
        return False
    return os.environ.get("DD_TRACE_ENABLED", "").strip().lower() != "false"


def _dd_common_tags() -> list[str]:
    tags = [
        f"env:{os.environ.get('DD_ENV', 'development')}",
        f"service:{os.environ.get('DD_SERVICE', 'stock-agent')}",
        f"host:{get_host()}",
    ]
    job_id = os.environ.get("JOB_ID")
    if job_id:
        tags.append(f"job_id:{job_id}")
    return tags


def _install_trace_instrumentors() -> None:
    """Activate OTel-native auto-instrumentation for outbound HTTP, Postgres, and
    OpenAI against the current TracerProvider (used in OTLP mode, where ddtrace's
    patch_all is not active). Each is guarded independently."""
    for mod_path, cls_name in (
        ("opentelemetry.instrumentation.httpx", "HTTPXClientInstrumentor"),
        ("opentelemetry.instrumentation.psycopg", "PsycopgInstrumentor"),
        ("opentelemetry.instrumentation.openai", "OpenAIInstrumentor"),
    ):
        try:
            mod = __import__(mod_path, fromlist=[cls_name])
            getattr(mod, cls_name)().instrument()
        except Exception:
            pass


def _install_log_bridge(logger_provider) -> None:
    """Route stdlib logs emitted through `_stdlib_logger` into an OTel
    LoggerProvider so they reach the OTLP log exporter. Idempotent."""
    from opentelemetry.sdk._logs import LoggingHandler
    for h in list(_stdlib_logger.handlers):
        if isinstance(h, LoggingHandler):
            return
    handler = LoggingHandler(level=logging.DEBUG, logger_provider=logger_provider)
    _stdlib_logger.addHandler(handler)
    _stdlib_logger.setLevel(logging.DEBUG)


def emit_log(level: str, message: str, **attributes) -> None:
    """Emit a structured log to stdlib (always), Sentry Logs (when
    SENTRY_DSN_AGENT is set), and the OTel LoggerProvider (which exports via
    OTLP when a logs target is configured).

    Every log carries the dynamic OS hostname so origin is visible in each
    backend's UI without joining to trace tags.

    level: 'trace' | 'debug' | 'info' | 'warn' | 'error' | 'fatal'
    """
    attributes.setdefault("host", get_host())

    stdlib_level = {
        "trace": logging.DEBUG, "debug": logging.DEBUG, "info": logging.INFO,
        "warn": logging.WARNING, "error": logging.ERROR, "fatal": logging.CRITICAL,
    }.get(level, logging.INFO)
    _stdlib_logger.log(stdlib_level, "%s %s", message, attributes)

    if _sentry_inited:
        try:
            import sentry_sdk
            fn = getattr(sentry_sdk.logger, level, None)
            if fn:
                fn(message, **attributes)
        except Exception:
            pass


# Backward-compat alias for existing callers.
sentry_log = emit_log

def flush_observability(timeout_s: float = 5.0) -> None:
    """Drain all active exporters. MUST run before the VM is deleted."""
    tp = trace.get_tracer_provider()
    if hasattr(tp, "shutdown"):
        try:
            tp.shutdown()
        except Exception:
            pass

    try:
        from lib.metrics import flush_metrics
        flush_metrics(timeout_s=timeout_s)
    except Exception:
        pass

    if _logger_provider is not None:
        try:
            _logger_provider.force_flush(timeout_millis=int(timeout_s * 1000))
        except Exception:
            pass

    if _sentry_inited:
        try:
            import sentry_sdk
            sentry_sdk.flush(timeout=timeout_s)
        except Exception:
            pass

    if _dd_inited:
        try:
            import ddtrace
            ddtrace.tracer.shutdown(timeout=timeout_s)
        except Exception:
            pass
