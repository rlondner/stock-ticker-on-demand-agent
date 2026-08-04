from lib.otlp_target import parse_otlp_headers, resolve_otlp_target

_ALL = ("traces", "metrics", "logs")


def _clear(monkeypatch):
    for v in (
        "OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_HEADERS",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_HEADERS",
        "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "OTEL_EXPORTER_OTLP_METRICS_HEADERS",
        "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", "OTEL_EXPORTER_OTLP_LOGS_HEADERS",
        "DD_API_KEY", "DD_SITE", "DD_TRACE_ENABLED",
    ):
        monkeypatch.delenv(v, raising=False)


def test_parse_headers_splits_pairs():
    assert parse_otlp_headers("dd-api-key=abc,x-extra=1") == {"dd-api-key": "abc", "x-extra": "1"}
    assert parse_otlp_headers("") == {}
    assert parse_otlp_headers("  k = v  ") == {"k": "v"}


def test_unconfigured_returns_none(monkeypatch):
    _clear(monkeypatch)
    for s in _ALL:
        assert resolve_otlp_target(s) is None


def test_per_signal_endpoint_wins(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://base.example/otlp")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "https://metrics.example/v1/metrics")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_METRICS_HEADERS", "authorization=Bearer m")
    ep, headers = resolve_otlp_target("metrics")
    assert ep == "https://metrics.example/v1/metrics"
    assert headers == {"authorization": "Bearer m"}


def test_base_endpoint_used_when_no_per_signal(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://base.example/otlp")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "authorization=Bearer b")
    ep, headers = resolve_otlp_target("traces")
    assert ep == "https://base.example/otlp/v1/traces"
    assert headers == {"authorization": "Bearer b"}


def test_datadog_convenience_fills_endpoint_and_header(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DD_API_KEY", "dd-key")
    monkeypatch.setenv("DD_SITE", "datadoghq.eu")
    for s in _ALL:
        ep, headers = resolve_otlp_target(s)
        assert ep == f"https://otlp.datadoghq.eu/v1/{s}"
        assert headers == {"dd-api-key": "dd-key"}


def test_datadog_convenience_default_site(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DD_API_KEY", "dd-key")
    ep, _ = resolve_otlp_target("logs")
    assert ep == "https://otlp.datadoghq.com/v1/logs"


def test_explicit_var_beats_datadog_convenience(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DD_API_KEY", "dd-key")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "https://collector.local/v1/traces")
    ep, headers = resolve_otlp_target("traces")
    assert ep == "https://collector.local/v1/traces"
    assert headers == {}


def test_datadog_disabled_flag_suppresses_convenience(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DD_API_KEY", "dd-key")
    monkeypatch.setenv("DD_TRACE_ENABLED", "false")
    assert resolve_otlp_target("metrics") is None


def test_base_endpoint_beats_datadog_convenience(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://collector.example/otlp")
    monkeypatch.setenv("DD_API_KEY", "dd-key")
    ep, headers = resolve_otlp_target("traces")
    assert ep == "https://collector.example/otlp/v1/traces"
    assert "dd-api-key" not in headers
