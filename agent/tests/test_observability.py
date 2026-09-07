import os
import pytest
from opentelemetry import trace
from lib.observability import init_observability, record_error, flush_observability

def test_init_is_idempotent(monkeypatch):
    monkeypatch.setenv("JOB_ID", "job-1")
    init_observability(job_id="job-1")
    init_observability(job_id="job-1")

def test_record_error_marks_span(monkeypatch):
    monkeypatch.setenv("JOB_ID", "job-2")
    init_observability(job_id="job-2")
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("t") as span:
        record_error(span, ValueError("nope"))
    flush_observability(timeout_s=1.0)

def test_flush_without_exporters_is_no_op(monkeypatch):
    monkeypatch.setenv("JOB_ID", "job-3")
    init_observability(job_id="job-3")
    flush_observability(timeout_s=1.0)

def test_init_with_sentry_dsn_does_not_crash(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN_AGENT", "https://public@o0.ingest.sentry.io/0")
    monkeypatch.setenv("JOB_ID", "job-sentry")
    import importlib, lib.observability as o
    importlib.reload(o)
    o.init_observability(job_id="job-sentry")
    o.flush_observability(timeout_s=1.0)

def test_init_with_dd_api_key_does_not_crash(monkeypatch):
    monkeypatch.setenv("DD_API_KEY", "dd-test-key")
    monkeypatch.setenv("DD_SITE", "datadoghq.com")
    monkeypatch.setenv("JOB_ID", "job-dd")
    import importlib, lib.observability as o
    importlib.reload(o)
    o.init_observability(job_id="job-dd")
    o.flush_observability(timeout_s=1.0)

def test_init_with_both_vendors_does_not_crash(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN_AGENT", "https://public@o0.ingest.sentry.io/0")
    monkeypatch.setenv("DD_API_KEY", "dd-test-key")
    monkeypatch.setenv("JOB_ID", "job-both")
    import importlib, lib.observability as o
    importlib.reload(o)
    o.init_observability(job_id="job-both")
    o.flush_observability(timeout_s=1.0)


def test_dd_trace_enabled_false_short_circuits(monkeypatch):
    monkeypatch.setenv("DD_API_KEY", "dd-test-key")
    monkeypatch.setenv("DD_TRACE_ENABLED", "false")
    monkeypatch.setenv("JOB_ID", "job-dd-disabled")
    import importlib, lib.observability as o
    importlib.reload(o)
    o.init_observability(job_id="job-dd-disabled")
    # _dd_inited should remain False when DD_TRACE_ENABLED=false even though DD_API_KEY is set.
    assert o._dd_inited is False
    o.flush_observability(timeout_s=1.0)


def test_dd_trace_enabled_unset_still_inits(monkeypatch):
    monkeypatch.setenv("DD_API_KEY", "dd-test-key")
    monkeypatch.setenv("DD_EXPORTER", "agent")
    monkeypatch.delenv("DD_TRACE_ENABLED", raising=False)
    monkeypatch.setenv("JOB_ID", "job-dd-default")
    import importlib, lib.observability as o
    importlib.reload(o)
    o.init_observability(job_id="job-dd-default")
    # agent-mode: with DD_EXPORTER=agent, DD_API_KEY set, and DD_TRACE_ENABLED unset, ddtrace inits.
    assert o._dd_inited is True
    o.flush_observability(timeout_s=1.0)


def test_dd_exporter_otlp_uses_otlp_path(monkeypatch):
    monkeypatch.setenv("DD_API_KEY", "dd-test-key")
    monkeypatch.setenv("DD_EXPORTER", "otlp")
    monkeypatch.delenv("DD_TRACE_ENABLED", raising=False)
    monkeypatch.setenv("JOB_ID", "job-otlp")
    import importlib, lib.observability as o
    importlib.reload(o)
    o.init_observability(job_id="job-otlp")
    # OTLP path is active (resolver finds DD_API_KEY); ddtrace.patch_all path is NOT.
    assert o._otlp_traces_inited is True
    assert o._dd_inited is False
    o.flush_observability(timeout_s=1.0)


def test_dd_exporter_otlp_without_api_key_no_exporter(monkeypatch):
    monkeypatch.setenv("DD_EXPORTER", "otlp")
    monkeypatch.delenv("DD_API_KEY", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("DD_TRACE_ENABLED", raising=False)
    monkeypatch.setenv("JOB_ID", "job-otlp-no-key")
    import importlib, lib.observability as o
    importlib.reload(o)
    o.init_observability(job_id="job-otlp-no-key")
    # No DD_API_KEY and no OTEL vars → resolver returns None → no OTLP exporter.
    assert o._otlp_traces_inited is False
    o.flush_observability(timeout_s=1.0)


def test_dd_exporter_unknown_value_raises(monkeypatch):
    monkeypatch.setenv("DD_API_KEY", "dd-test-key")
    monkeypatch.setenv("DD_EXPORTER", "kafka")
    monkeypatch.setenv("JOB_ID", "job-bad-exporter")
    import importlib, lib.observability as o
    importlib.reload(o)
    with pytest.raises(ValueError, match="DD_EXPORTER"):
        o.init_observability(job_id="job-bad-exporter")


def test_dd_exporter_agent_explicit(monkeypatch):
    monkeypatch.setenv("DD_API_KEY", "dd-test-key")
    monkeypatch.setenv("DD_EXPORTER", "agent")
    monkeypatch.delenv("DD_TRACE_ENABLED", raising=False)
    monkeypatch.setenv("JOB_ID", "job-agent-exporter")
    import importlib, lib.observability as o
    importlib.reload(o)
    o.init_observability(job_id="job-agent-exporter")
    # Explicit DD_EXPORTER=agent → ddtrace path; OTLP path stays inactive.
    assert o._dd_inited is True
    assert o._otlp_traces_inited is False
    o.flush_observability(timeout_s=1.0)


def test_init_sets_up_metrics(monkeypatch):
    monkeypatch.setenv("JOB_ID", "job-metrics")
    import importlib, lib.observability as o, lib.metrics as mtr
    importlib.reload(mtr)
    importlib.reload(o)
    o.init_observability(job_id="job-metrics")
    assert mtr._meter is not None
    o.flush_observability(timeout_s=1.0)


def test_trace_otlp_processor_added_when_resolver_returns(monkeypatch):
    monkeypatch.setenv("JOB_ID", "job-traces")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "https://otlp.example/v1/traces")
    import importlib, lib.observability as o
    importlib.reload(o)
    o.init_observability(job_id="job-traces")
    assert o._otlp_traces_inited is True
    o.flush_observability(timeout_s=1.0)


def test_trace_otlp_absent_when_unconfigured(monkeypatch):
    monkeypatch.setenv("JOB_ID", "job-none")
    import importlib, lib.observability as o
    importlib.reload(o)
    o.init_observability(job_id="job-none")
    assert o._otlp_traces_inited is False
    o.flush_observability(timeout_s=1.0)


def test_emit_log_bridges_to_otel_logs(monkeypatch):
    monkeypatch.setenv("JOB_ID", "job-logs")
    import importlib, lib.observability as o
    importlib.reload(o)
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import InMemoryLogExporter, SimpleLogRecordProcessor

    # Prior tests may leave a LoggingHandler on the shared stdlib logger (it is a
    # module-level singleton that survives importlib.reload). Remove any stale OTel
    # handlers so _install_log_bridge's idempotency guard does not short-circuit.
    # Capture the original handler list so we can restore it after the test.
    original_handlers = list(o._stdlib_logger.handlers)
    try:
        for h in list(o._stdlib_logger.handlers):
            if isinstance(h, LoggingHandler):
                o._stdlib_logger.removeHandler(h)

        exporter = InMemoryLogExporter()
        lp = LoggerProvider()
        lp.add_log_record_processor(SimpleLogRecordProcessor(exporter))
        o._install_log_bridge(lp)  # attach a stdlib->OTel handler

        o.emit_log("warn", "snapshot.missing", ticker="AAPL")
        lp.force_flush()
        # Installed SDK uses get_finished_logs() (brief named get_finished_log_records,
        # but this SDK version exposes get_finished_logs instead).
        records = exporter.get_finished_logs()
        assert any("snapshot.missing" in (r.log_record.body or "") for r in records)
    finally:
        # Restore the logger's handler list to what it was before this test.
        o._stdlib_logger.handlers = original_handlers


def test_init_observability_calls_init_llmobs(monkeypatch):
    import importlib, lib.observability as o
    calls = []
    monkeypatch.setattr("lib.llmobs.init_llmobs", lambda: calls.append("init") or True)
    monkeypatch.setenv("JOB_ID", "job-llmobs-init")
    importlib.reload(o)
    o.init_observability(job_id="job-llmobs-init")
    assert calls == ["init"]
    o.flush_observability(timeout_s=1.0)


def test_flush_observability_calls_flush_llmobs(monkeypatch):
    import importlib, lib.observability as o
    calls = []
    monkeypatch.setattr("lib.llmobs.flush_llmobs", lambda timeout_s=5.0: calls.append(timeout_s))
    monkeypatch.setenv("JOB_ID", "job-llmobs-flush")
    importlib.reload(o)
    o.init_observability(job_id="job-llmobs-flush")
    o.flush_observability(timeout_s=2.5)
    assert calls == [2.5]
