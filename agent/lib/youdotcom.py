"""You.com Search/News API tools for the deep-analysis crew's Researcher and
Risk Analyst agents. Reuses tools.py's _observed_tool for the same
never-raises / uniform-logging contract as the yfinance tools."""
import os
import httpx
from opentelemetry import trace

from . import tools

_SEARCH_URL = "https://api.ydc-index.io/search"
_NEWS_URL = "https://api.ydc-index.io/news"
_MAX_RESULTS = 5


def _headers() -> dict:
    return {"X-API-Key": os.environ.get("YOUDOTCOM_API_KEY", "")}


def _search(args: dict) -> dict:
    query = args.get("query")
    if not query:
        return {"error": "missing query"}
    resp = httpx.get(_SEARCH_URL, headers=_headers(), params={"query": query}, timeout=15)
    resp.raise_for_status()
    hits = resp.json().get("hits", [])[:_MAX_RESULTS]
    return {"results": [
        {"title": h.get("title"), "url": h.get("url"), "snippet": h.get("description")}
        for h in hits
    ]}


def _news(args: dict) -> dict:
    query = args.get("query")
    if not query:
        return {"error": "missing query"}
    resp = httpx.get(_NEWS_URL, headers=_headers(), params={"query": query}, timeout=15)
    resp.raise_for_status()
    hits = resp.json().get("news", {}).get("results", [])[:_MAX_RESULTS]
    return {"results": [
        {"title": h.get("title"), "url": h.get("url"), "snippet": h.get("description")}
        for h in hits
    ]}


def build_youdotcom_tools() -> dict:
    """Return a name->callable registry, each wrapped by _observed_tool so a
    You.com outage or bad response can never crash the crew."""
    return {
        "youdotcom_search": tools._observed_tool("youdotcom_search", _search),
        "youdotcom_news": tools._observed_tool("youdotcom_news", _news),
    }
