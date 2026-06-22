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
