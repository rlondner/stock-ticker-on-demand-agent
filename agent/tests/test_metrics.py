import importlib
import httpx
import pytest
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.metrics.export import InMemoryMetricReader


def _fresh(reader=None):
    """Reload the module for a clean global state, init with an in-memory reader."""
    import lib.metrics as m
    importlib.reload(m)
    m.init_metrics(Resource.create({"service.name": "test"}),
                   extra_readers=[reader] if reader else None)
    return m


def _find_points(reader, name):
    data = reader.get_metrics_data()
    points = []
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                if metric.name == name:
                    points.extend(metric.data.data_points)
    return points


def test_no_op_when_unconfigured():
    import lib.metrics as m
    importlib.reload(m)
    m.init_metrics(Resource.create({"service.name": "test"}))  # no readers
    # Emitting without a reader must not raise.
    m.record_job_completed("complete", "AAPL")
    m.flush_metrics(timeout_s=1.0)


def test_job_completed_counter_records_attrs():
    reader = InMemoryMetricReader()
    m = _fresh(reader)
    m.record_job_completed("complete", "AAPL")
    points = _find_points(reader, "jobs.completed")
    assert len(points) == 1
    assert points[0].value == 1
    assert points[0].attributes["final_status"] == "complete"
    assert points[0].attributes["ticker"] == "AAPL"


def test_llm_tokens_histograms():
    reader = InMemoryMetricReader()
    m = _fresh(reader)
    m.record_llm_tokens("gpt-4.1-mini", "responses", 100, 40, "MSFT")
    tin = _find_points(reader, "llm.tokens_in")
    tout = _find_points(reader, "llm.tokens_out")
    assert tin[0].sum == 100 and tin[0].attributes["model"] == "gpt-4.1-mini"
    assert tout[0].sum == 40 and tout[0].attributes["api"] == "responses"


def test_no_metric_carries_job_id():
    """Global constraint: job_id must never be a metric attribute."""
    reader = InMemoryMetricReader()
    m = _fresh(reader)
    m.set_current_ticker("AAPL")
    m.record_job_completed("complete", "AAPL")
    m.record_agent_run_duration("complete", "AAPL", 1234.0)
    m.record_llm_tokens("gpt-4.1-mini", "responses", 10, 5, "AAPL")
    m.record_llm_call("gpt-4.1-mini", "responses", "ok", "AAPL")
    m.record_llm_empty_response("gpt-4.1-mini", "responses", "AAPL")
    m.record_llm_web_search("responses", "AAPL")
    m.record_http_request("api.openai.com", 200, 12.5, "AAPL")
    data = reader.get_metrics_data()
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                for pt in metric.data.data_points:
                    assert "job_id" not in pt.attributes, metric.name


def test_http_hook_records_request(monkeypatch):
    reader = InMemoryMetricReader()
    m = _fresh(reader)
    m.set_current_ticker("AAPL")
    # Drive the response hook directly with a real httpx.Response + request.
    request = httpx.Request("GET", "https://api.openai.com/v1/responses")
    m._on_request(request)  # stamps start time
    response = httpx.Response(200, request=request)
    m._on_response(response)
    points = _find_points(reader, "agent.http.requests")
    assert points[0].value == 1
    assert points[0].attributes["host"] == "api.openai.com"
    assert points[0].attributes["status_code"] == 200
