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


def test_metrics_otlp_reader_added_when_resolver_returns(monkeypatch):
    import importlib, lib.metrics as m
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    importlib.reload(m)
    monkeypatch.setattr(m, "resolve_otlp_target",
                        lambda signal: ("https://otlp.example/v1/metrics", {"dd-api-key": "k"}) if signal == "metrics" else None)
    m.init_metrics(Resource.create({"service.name": "test"}))
    # A periodic OTLP reader should have been constructed and attached.
    assert m._meter is not None
    readers = list(m._meter_provider._metric_readers)
    assert any(isinstance(r, PeriodicExportingMetricReader) for r in readers), (
        f"Expected a PeriodicExportingMetricReader to be attached, got: {readers}"
    )


def test_no_otlp_reader_when_resolver_returns_none(monkeypatch):
    import importlib, lib.metrics as m
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    importlib.reload(m)
    monkeypatch.setattr(m, "resolve_otlp_target", lambda signal: None)
    m.init_metrics(Resource.create({"service.name": "test"}))
    readers = list(m._meter_provider._metric_readers)
    assert not any(isinstance(r, PeriodicExportingMetricReader) for r in readers), (
        f"Expected no PeriodicExportingMetricReader when resolver returns None, got: {readers}"
    )


def test_record_llm_duration_histogram(monkeypatch):
    import importlib, lib.metrics as m
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    importlib.reload(m)
    reader = InMemoryMetricReader()
    m.init_metrics(Resource.create({"service.name": "test"}), extra_readers=[reader])
    m.record_llm_duration("gpt-4.1-mini", "responses", 512.0, "AAPL")
    points = []
    for rm in reader.get_metrics_data().resource_metrics:
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                if metric.name == "llm.duration_ms":
                    points.extend(metric.data.data_points)
    assert points[0].sum == 512.0
    assert points[0].attributes == {"model": "gpt-4.1-mini", "api": "responses", "ticker": "AAPL"}
    assert "job_id" not in points[0].attributes


def test_sentry_mirror_calls_count_with_attributes(monkeypatch):
    """Sentry mirror uses count(..., attributes=) — not incr/tags — and never passes job_id."""
    import importlib, lib.metrics as m
    importlib.reload(m)
    monkeypatch.setenv("SENTRY_DSN_AGENT", "https://test@sentry.io/999")
    from opentelemetry.sdk.resources import Resource
    m.init_metrics(Resource.create({"service.name": "test"}))

    import sentry_sdk
    count_calls = []
    dist_calls = []
    monkeypatch.setattr(sentry_sdk.metrics, "count",
                        lambda name, value, unit=None, attributes=None: count_calls.append((name, value, attributes)))
    monkeypatch.setattr(sentry_sdk.metrics, "distribution",
                        lambda name, value, unit=None, attributes=None: dist_calls.append((name, value, attributes)))

    m.record_job_completed("complete", "AAPL")

    assert len(count_calls) == 1
    name, value, attributes = count_calls[0]
    assert name == "jobs.completed"
    assert value == 1
    assert attributes["ticker"] == "AAPL"
    assert "job_id" not in attributes

    # Distribution mirror: agent run duration
    m.record_agent_run_duration("complete", "AAPL", 500.0)
    assert len(dist_calls) == 1
    name, value, attributes = dist_calls[0]
    assert name == "agent.run.duration_ms"
    assert attributes["ticker"] == "AAPL"
    assert "job_id" not in attributes
