import logging
import os
import socket
from opentelemetry import trace, propagate, context as ot_context
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace.status import Status, StatusCode

_stdlib_logger = logging.getLogger("stock-agent")

_initialized = False
_sentry_inited = False
_dd_inited = False
_dd_otlp_inited = False


def get_host() -> str:
    """Actual OS hostname of the machine executing the agent. On a Daytona
    sandbox this returns the sandbox's assigned hostname; on your workstation
    it returns your local hostname."""
    return socket.gethostname()

def init_observability(job_id: str) -> None:
    """Initialize OTel and any configured exporters (Sentry/Datadog).
    Idempotent - safe to call multiple times."""
    global _initialized, _sentry_inited, _dd_inited, _dd_otlp_inited
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

    # === Datadog exporter ===
    # DD_EXPORTER picks how traces reach Datadog:
    #   'agent' (default): ddtrace.patch_all → ships to a local Datadog Agent on
    #     localhost:8126. Auto-instruments httpx/psycopg/openai/logging. Requires
    #     an Agent reachable from this process. Set DD_TRACE_ENABLED=false to
    #     short-circuit when no Agent is running.
    #   'otlp': OTLP-HTTP exporter ships spans directly to Datadog's intake.
    #     No Agent needed (good for Daytona sandboxes). Only the explicit OTel
    #     spans we create get shipped — no auto-instrumented HTTP/DB/OpenAI spans.
    #     Requires DD_OTLP_ENDPOINT (the exact intake URL from Datadog's docs)
    #     and DD_API_KEY.
    dd_key = os.environ.get("DD_API_KEY")
    dd_disabled = os.environ.get("DD_TRACE_ENABLED", "").strip().lower() == "false"
    dd_exporter = (os.environ.get("DD_EXPORTER") or "agent").strip().lower()
    if dd_exporter not in ("agent", "otlp"):
        raise ValueError(
            f"DD_EXPORTER={dd_exporter!r} is not valid; expected 'agent' or 'otlp'"
        )
    if dd_key and not dd_disabled:
        if dd_exporter == "agent":
            import ddtrace
            ddtrace.config.service = os.environ.get("DD_SERVICE", "stock-agent")
            ddtrace.config.env = os.environ.get("DD_ENV", "development")
            os.environ.setdefault("DD_TRACE_OTEL_ENABLED", "true")
            ddtrace.patch_all(httpx=True, psycopg=True, openai=True, logging=True)
            global _dd_inited
            _dd_inited = True
        else:  # dd_exporter == "otlp"
            otlp_endpoint = os.environ.get("DD_OTLP_ENDPOINT")
            if not otlp_endpoint:
                raise ValueError(
                    "DD_EXPORTER=otlp requires DD_OTLP_ENDPOINT to be set to "
                    "Datadog's OTLP HTTP intake URL (see your Datadog docs; "
                    "the path has shifted across Datadog versions)"
                )
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
                endpoint=otlp_endpoint,
                headers={"DD-API-KEY": dd_key},
            )))
            global _dd_otlp_inited
            _dd_otlp_inited = True

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


def _datadog_log(level: str, message: str, attributes: dict) -> None:
    """Fire-and-forget POST to Datadog's HTTP log intake. Tiny timeout — this
    is a demo agent that self-deletes; we don't queue or retry."""
    if not _dd_enabled():
        return
    try:
        import httpx
        payload = {
            "ddsource": "python",
            "service": os.environ.get("DD_SERVICE", "stock-agent"),
            "hostname": get_host(),
            "status": level,
            "message": message,
            "ddtags": ",".join(_dd_common_tags()),
            **attributes,
        }
        httpx.post(
            f"https://http-intake.logs.{_dd_site()}/api/v2/logs",
            headers={
                "DD-API-KEY": os.environ["DD_API_KEY"],
                "Content-Type": "application/json",
            },
            json=[payload],
            timeout=3,
        )
    except Exception:
        pass


def _datadog_metric(name: str, value: float, tags: list[str] | None = None) -> None:
    """Fire-and-forget POST to Datadog's HTTP metrics intake as a gauge point.
    Uses the modern v2/series shape (type 3 = gauge)."""
    if not _dd_enabled():
        return
    try:
        import time as _time
        import httpx
        merged_tags = _dd_common_tags() + (tags or [])
        payload = {
            "series": [{
                "metric": name,
                "type": 3,
                "points": [{"timestamp": int(_time.time()), "value": float(value)}],
                "tags": merged_tags,
                "resources": [{"type": "host", "name": get_host()}],
            }],
        }
        httpx.post(
            f"https://api.{_dd_site()}/api/v2/series",
            headers={
                "DD-API-KEY": os.environ["DD_API_KEY"],
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=3,
        )
    except Exception:
        pass


def emit_log(level: str, message: str, **attributes) -> None:
    """Emit a structured log to stdlib (always), Sentry Logs (when
    SENTRY_DSN_AGENT is set), and Datadog HTTP log intake (when DD_API_KEY
    is set and DD_TRACE_ENABLED != 'false').

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

    _datadog_log(level, message, attributes)


def emit_metric(name: str, value: float, **tags) -> None:
    """Emit a numeric metric to Datadog (via HTTP intake) AND to the current
    OTel span as an attribute (Sentry surfaces span attributes in Trace
    Explorer; Sentry sunset its custom-metrics product in Oct 2024, so span
    attributes are the endorsed replacement).

    tags: keyword args become 'key:value' Datadog tags."""
    span = trace.get_current_span()
    if span and span.is_recording():
        span.set_attribute(name, value)

    _datadog_metric(name, value, tags=[f"{k}:{v}" for k, v in tags.items()])


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
