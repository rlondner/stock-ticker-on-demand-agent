"""Vendor-agnostic OTLP endpoint/header resolution for traces, metrics, and logs.

Precedence per signal: explicit per-signal OTEL_* var -> base OTEL_* var ->
Datadog agentless convenience -> None. Explicit OTEL_* vars always win over the
Datadog convenience, so a Collector/other vendor overrides Datadog."""
import os

_SIGNALS = ("traces", "metrics", "logs")


def parse_otlp_headers(raw: str) -> dict[str, str]:
    """Parse the OTel-standard header format: comma-separated key=value pairs."""
    headers: dict[str, str] = {}
    for pair in (raw or "").split(","):
        if "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        k = k.strip()
        if k:
            headers[k] = v.strip()
    return headers


def _dd_enabled() -> bool:
    if not os.environ.get("DD_API_KEY"):
        return False
    return os.environ.get("DD_TRACE_ENABLED", "").strip().lower() != "false"


def _dd_site() -> str:
    return os.environ.get("DD_SITE", "datadoghq.com").strip() or "datadoghq.com"


def resolve_otlp_target(signal: str) -> tuple[str, dict[str, str]] | None:
    """Return (endpoint, headers) for an OTLP signal, or None if not configured."""
    if signal not in _SIGNALS:
        raise ValueError(f"unknown OTLP signal {signal!r}; expected one of {_SIGNALS}")

    per_ep = os.environ.get(f"OTEL_EXPORTER_OTLP_{signal.upper()}_ENDPOINT")
    if per_ep:
        headers = os.environ.get(f"OTEL_EXPORTER_OTLP_{signal.upper()}_HEADERS")
        return per_ep, parse_otlp_headers(headers if headers is not None else "")

    base_ep = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if base_ep:
        headers = os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "")
        return f"{base_ep.rstrip('/')}/v1/{signal}", parse_otlp_headers(headers)

    if _dd_enabled():
        return f"https://otlp.{_dd_site()}/v1/{signal}", {"dd-api-key": os.environ["DD_API_KEY"]}

    return None
