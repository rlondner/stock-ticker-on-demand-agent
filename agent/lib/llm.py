import json
import logging
import os
import re
import time
from typing import Protocol
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from openai import OpenAI, APIError, RateLimitError, APIConnectionError, InternalServerError
from opentelemetry import trace
from .prompts import SYSTEM_PROMPT, user_prompt
from .observability import get_host, emit_log
from .finance import Snapshot, fetch_snapshot
from . import metrics

logger = logging.getLogger(__name__)


class EmptyLLMResponseError(Exception):
    """The model returned empty content (None or blank). Retryable — some
    server-managed bots and small local models produce this ~1-in-10 times
    with finish_reason='stop' and no error status."""

class Signal(BaseModel):
    label: str
    evidence: str
    source: str | None = None

class Analysis(BaseModel):
    recommendation: str = Field(pattern="^(buy|hold|sell)$")
    summary: str
    signals: list[Signal]

class LLMClient(Protocol):
    def analyze(self, ticker: str) -> Analysis: ...

def parse_response(raw: str) -> Analysis:
    """Strip optional markdown fences, parse JSON, validate."""
    cleaned = raw.strip()
    # Strip ```json\n...\n``` or ```\n...\n``` fences.
    fenced = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```$", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        snippet = raw[:200]
        raise ValueError(
            f"LLM did not return valid JSON ({e}); "
            f"raw_length={len(raw)}, snippet={snippet!r}"
        ) from e
    return Analysis(**data)

DEFAULT_MODEL = "gpt-4.1-mini"

# Chars kept on the span attribute / log payload. Well under Sentry's ~8KB
# per-attribute cap and Datadog's log-line cap. If the model returns more,
# we set llm.response.truncated=true so it's obvious in the UI.
_LLM_RAW_TRACE_MAX = 4000
_LLM_SUMMARY_TRACE_MAX = 1000


def _record_raw_response(span, text: str, finish_reason: str | None) -> None:
    """Attach the raw LLM output to the span BEFORE parse, so a JSON-decode
    failure still leaves the response visible in Trace Explorer."""
    span.set_attribute("llm.response.length", len(text))
    span.set_attribute("llm.response.truncated", len(text) > _LLM_RAW_TRACE_MAX)
    span.set_attribute("llm.response.raw", text[:_LLM_RAW_TRACE_MAX])
    if finish_reason is not None:
        span.set_attribute("llm.finish_reason", str(finish_reason))


def _record_parsed_response(span, analysis: "Analysis") -> None:
    """Attach the parsed structure to the span + emit a log so recommendations
    are queryable across all three backends without parsing raw text."""
    span.set_attribute("llm.response.recommendation", analysis.recommendation)
    span.set_attribute("llm.response.summary", analysis.summary[:_LLM_SUMMARY_TRACE_MAX])
    span.set_attribute("llm.response.signals_count", len(analysis.signals))
    emit_log(
        "info",
        "llm.responded",
        recommendation=analysis.recommendation,
        summary=analysis.summary[:_LLM_SUMMARY_TRACE_MAX],
        signals_count=len(analysis.signals),
    )


def _env_flag(name: str, default: bool) -> bool:
    """Parse an env var as a boolean. Unset OR empty → default; 'false'/'0'/'no'/'off' → False; anything else → True."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    stripped = raw.strip().lower()
    if stripped == "":
        return default
    return stripped not in ("false", "0", "no", "off")


def _require_nonempty(text: str | None, *, api: str, finish_reason: str | None, span,
                      model: str, ticker: str) -> None:
    """Log a warning + record a span event + metric + raise EmptyLLMResponseError
    if the model returned no content. tenacity catches EmptyLLMResponseError and retries."""
    if text and text.strip():
        return
    span.add_event("llm.empty_response", {
        "api": api,
        "finish_reason": finish_reason or "unknown",
        "text_is_none": text is None,
    })
    metrics.record_llm_empty_response(model, api, ticker)
    logger.warning(
        "LLM returned empty response (api=%s, finish_reason=%s, text_is_none=%s); retrying",
        api, finish_reason, text is None,
    )
    raise EmptyLLMResponseError(
        f"empty content (api={api}, finish_reason={finish_reason!r}, text_is_none={text is None})"
    )


class OpenAIClient:
    def __init__(self, model: str | None = None):
        self._client = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.environ.get("OPENAI_API_URL") or None,
            http_client=metrics.build_httpx_client(),
        )
        self._model = model or os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL
        # Default: use OpenAI's Responses API + hosted web_search tool. Set
        # OPENAI_USE_RESPONSES_API=false for endpoints that only implement
        # /v1/chat/completions (Ollama, vLLM, LiteLLM, OpenRouter, Azure, etc.).
        self._use_responses_api = _env_flag("OPENAI_USE_RESPONSES_API", default=True)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=16),
        # InternalServerError covers all 5xx (500, 502, 503, 504, 529-overloaded).
        # Anthropic's compat layer returns 529 when overloaded; OpenAI uses 503.
        # EmptyLLMResponseError covers server-managed bots and small local models
        # that intermittently return content="" with finish_reason='stop'.
        retry=retry_if_exception_type((
            RateLimitError, APIConnectionError, InternalServerError, EmptyLLMResponseError,
        )),
        reraise=True,
    )
    def analyze(self, ticker: str, snapshot: Snapshot | None = None) -> Analysis:
        metrics.set_current_ticker(ticker)
        tracer = trace.get_tracer("stock-agent")
        api = "responses" if self._use_responses_api else "chat.completions"
        with tracer.start_as_current_span("llm.analyze") as span:
            span.set_attribute("host", get_host())
            span.set_attribute("model", self._model)
            span.set_attribute("api", api)
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt(ticker, snapshot=snapshot)},
            ]
            request_started_at = time.perf_counter()
            try:
                if self._use_responses_api:
                    # We now inject the ticker facts into the user prompt as
                    # ground truth, so we no longer need the hosted web_search
                    # tool — and prompts.py explicitly tells the model it has
                    # no web access.
                    resp = self._client.responses.create(
                        model=self._model,
                        input=messages,
                    )
                    text = resp.output_text
                    finish_reason = getattr(resp, "status", None)
                    usage = getattr(resp, "usage", None)
                    tin = getattr(usage, "input_tokens", 0) if usage else 0
                    tout = getattr(usage, "output_tokens", 0) if usage else 0
                else:
                    resp = self._client.chat.completions.create(
                        model=self._model,
                        messages=messages,
                    )
                    choice = resp.choices[0]
                    text = choice.message.content
                    finish_reason = choice.finish_reason
                    usage = getattr(resp, "usage", None)
                    tin = getattr(usage, "prompt_tokens", 0) if usage else 0
                    tout = getattr(usage, "completion_tokens", 0) if usage else 0

                span.set_attribute("tokens_in", tin)
                span.set_attribute("tokens_out", tout)
                metrics.record_llm_tokens(self._model, api, tin, tout, ticker)
                _require_nonempty(text, api=api, finish_reason=finish_reason,
                                  span=span, model=self._model, ticker=ticker)

                _record_raw_response(span, text, finish_reason)
                analysis = parse_response(text)
                _record_parsed_response(span, analysis)
                metrics.record_llm_call(self._model, api, "ok", ticker)
                return analysis
            except Exception:
                metrics.record_llm_call(self._model, api, "error", ticker)
                raise
            finally:
                metrics.record_llm_duration(
                    self._model, api,
                    (time.perf_counter() - request_started_at) * 1000,
                    ticker,
                )

def run_analysis(ticker: str) -> dict:
    snapshot = fetch_snapshot(ticker)
    client: LLMClient = OpenAIClient()
    analysis = client.analyze(ticker, snapshot=snapshot)
    return {
        **analysis.model_dump(),
        "snapshot": snapshot.model_dump() if snapshot else None,
    }
