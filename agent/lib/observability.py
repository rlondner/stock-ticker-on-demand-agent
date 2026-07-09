import os
from opentelemetry import trace, propagate, context as ot_context
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace.status import Status, StatusCode

_initialized = False
_sentry_inited = False
_dd_inited = False
_dd_otlp_inited = False

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
        )
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
