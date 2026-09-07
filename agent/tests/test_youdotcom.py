import httpx
import pytest
from unittest.mock import MagicMock, patch
import lib.youdotcom as youdotcom


def _spy(monkeypatch):
    logs = []
    monkeypatch.setattr(youdotcom.tools, "emit_log",
                        lambda level, msg, **kw: logs.append((level, msg, kw)))
    span = MagicMock()
    monkeypatch.setattr(youdotcom.tools.trace, "get_current_span", lambda: span)
    return logs, span


def test_search_maps_response_to_results(monkeypatch):
    _spy(monkeypatch)
    fake_response = MagicMock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {
        "hits": [{"title": "Acme Q3 beats estimates", "url": "https://x.test/a", "description": "Acme reported..."}]
    }
    with patch.object(youdotcom.httpx, "get", return_value=fake_response) as get:
        out = youdotcom._search({"query": "Acme Q3 earnings"})
    assert out == {"results": [{"title": "Acme Q3 beats estimates", "url": "https://x.test/a", "snippet": "Acme reported..."}]}
    assert get.call_args.kwargs["params"]["query"] == "Acme Q3 earnings"


def test_search_missing_query_returns_error(monkeypatch):
    _spy(monkeypatch)
    assert youdotcom._search({}) == {"error": "missing query"}


def test_search_http_error_is_caught_by_observed_tool(monkeypatch):
    logs, span = _spy(monkeypatch)
    with patch.object(youdotcom.httpx, "get", side_effect=httpx.HTTPError("boom")):
        registry = youdotcom.build_youdotcom_tools()
        out = registry["youdotcom_search"]({"query": "Acme"})
    assert "error" in out
    assert any(m == "tool.youdotcom_search.failed" for _, m, _ in logs)


def test_news_maps_response_to_results(monkeypatch):
    _spy(monkeypatch)
    fake_response = MagicMock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {
        "news": {"results": [{"title": "Acme guidance raised", "url": "https://x.test/b", "description": "..."}]}
    }
    with patch.object(youdotcom.httpx, "get", return_value=fake_response):
        out = youdotcom._news({"query": "Acme"})
    assert out["results"][0]["title"] == "Acme guidance raised"


def test_build_youdotcom_tools_returns_matching_registry():
    registry = youdotcom.build_youdotcom_tools()
    assert set(registry.keys()) == {"youdotcom_search", "youdotcom_news"}
    assert all(callable(fn) for fn in registry.values())
