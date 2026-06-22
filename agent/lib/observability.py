import os
from opentelemetry import trace, propagate, context as ot_context
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace.status import Status, StatusCode

_initialized = False
_sentry_inited = False
_dd_inited = False

def init_observability(job_id: str) -> None:
    """Initialize OTel and any configured exporters (Sentry/Datadog).
    Idempotent - safe to call multiple times."""
    global _initialized, _sentry_inited, _dd_inited
    if _initialized:
        return

    resource = Resource.create({
        "service.name": "stock-agent",
        "deployment.environment": os.environ.get("DD_ENV", "development"),
        "job.id": job_id,
    })
    provider = TracerProvider(resource=resource)

    # Always log spans to stdout in addition to any exporters (Daytona captures stdout).
    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    # Datadog exporter - wired in Task 19

    trace.set_tracer_provider(provider)

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
        )
        provider.add_span_processor(SentrySpanProcessor())
        propagate.set_global_textmap(SentryPropagator())
        global _sentry_inited
        _sentry_inited = True

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

def flush_observability(timeout_s: float = 5.0) -> None:
    """Drain all active exporters. MUST run before the VM is deleted."""
    tp = trace.get_tracer_provider()
    if hasattr(tp, "shutdown"):
        try:
            tp.shutdown()
        except Exception:
            pass

    if _sentry_inited:
        try:
            import sentry_sdk
            sentry_sdk.flush(timeout=timeout_s)
        except Exception:
            pass
