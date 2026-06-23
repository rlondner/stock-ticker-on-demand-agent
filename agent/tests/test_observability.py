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
    monkeypatch.delenv("DD_TRACE_ENABLED", raising=False)
    monkeypatch.setenv("JOB_ID", "job-dd-default")
    import importlib, lib.observability as o
    importlib.reload(o)
    o.init_observability(job_id="job-dd-default")
    # Default behavior preserved: with DD_API_KEY set and DD_TRACE_ENABLED unset, Datadog inits.
    assert o._dd_inited is True
    o.flush_observability(timeout_s=1.0)
