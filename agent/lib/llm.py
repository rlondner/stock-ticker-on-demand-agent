import json
import logging
import os
import re
import time
from typing import Protocol
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from openai import OpenAI, RateLimitError, APIConnectionError, InternalServerError
from opentelemetry import trace
from .prompts import SYSTEM_PROMPT, user_prompt
from .observability import get_host, emit_log
from .finance import Snapshot, fetch_snapshot
from . import metrics
from .agent_loop import run_agent_loop

logger = logging.getLogger(__name__)


class EmptyLLMResponseError(Exception):
    """The model returned empty content (None or blank). Retryable — some
    server-managed bots and small local models produce this ~1-in-10 times
    with finish_reason='stop' and no error status."""

class ThesisPoint(BaseModel):
    claim: str
    evidence: str
    source_url: str | None = None

class Thesis(BaseModel):
    recommendation: str = Field(pattern="^(buy|hold|sell)$")
    confidence: str = Field(pattern="^(low|medium|high)$")
    summary: str
    bull_case: list[ThesisPoint]
    bear_case: list[ThesisPoint]
    key_risks: list[ThesisPoint]
    # Set by the engine (not the model): overridden after parse. Default keeps
    # parsing valid when the model omits it (which it should).
    grounding: str = Field(default="snapshot_only", pattern="^(researched|limited|snapshot_only)$")

class LLMClient(Protocol):
    def analyze(self, ticker: str) -> Thesis: ...

def parse_thesis(raw: str) -> Thesis:
    """Strip optional markdown fences, parse JSON, validate against Thesis."""
    cleaned = raw.strip()
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
    return Thesis(**data)

DEFAULT_MODEL = "gpt-4.1-mini"
MAX_ITERS = int(os.environ.get("AGENT_MAX_ITERS", "6"))
LOOP_TIMEOUT_S = float(os.environ.get("AGENT_LOOP_TIMEOUT_S", "90"))

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


def _record_parsed_response(span, thesis: "Thesis") -> None:
    """Attach the parsed thesis to the span and emit a structured log so
    recommendations are queryable across all backends without parsing raw text."""
    span.set_attribute("llm.response.recommendation", thesis.recommendation)
    span.set_attribute("llm.response.confidence", thesis.confidence)
    span.set_attribute("llm.response.grounding", thesis.grounding)
    span.set_attribute("llm.response.summary", thesis.summary[:_LLM_SUMMARY_TRACE_MAX])
    span.set_attribute("llm.response.bull_count", len(thesis.bull_case))
    span.set_attribute("llm.response.bear_count", len(thesis.bear_case))
    span.set_attribute("llm.response.risk_count", len(thesis.key_risks))
    emit_log(
        "info",
        "llm.responded",
        recommendation=thesis.recommendation,
        confidence=thesis.confidence,
        grounding=thesis.grounding,
        summary=thesis.summary[:_LLM_SUMMARY_TRACE_MAX],
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


def _grounding(tools_ran: bool, thesis: "Thesis") -> str:
    """Engine-authoritative grounding level (never trust the model's self-report)."""
    if not tools_ran:
        return "snapshot_only"
    has_citation = any(
        p.source_url for section in (thesis.bull_case, thesis.bear_case, thesis.key_risks) for p in section
    )
    return "researched" if has_citation else "limited"


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
    def analyze(self, ticker: str, snapshot: Snapshot | None = None) -> Thesis:
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
                    def _create(input, tools):
                        kw = {"model": self._model, "input": input}
                        if tools:
                            kw["tools"] = tools
                        return self._client.responses.create(**kw)
                    loop = run_agent_loop(
                        _create, messages, tools=[{"type": "web_search"}],
                        function_registry={}, max_iters=MAX_ITERS, timeout_s=LOOP_TIMEOUT_S,
                    )
                    text, tin, tout = loop.text, loop.tokens_in, loop.tokens_out
                    finish_reason = "budget_exhausted" if loop.budget_exhausted else "stop"
                    span.set_attribute("llm.iterations", loop.iterations)
                    span.set_attribute("llm.tools_used", ",".join(loop.tools_used))
                    tools_ran = bool(loop.tools_used)
                else:
                    resp = self._client.chat.completions.create(model=self._model, messages=messages)
                    choice = resp.choices[0]
                    text = choice.message.content
                    finish_reason = choice.finish_reason
                    usage = getattr(resp, "usage", None)
                    tin = getattr(usage, "prompt_tokens", 0) if usage else 0
                    tout = getattr(usage, "completion_tokens", 0) if usage else 0
                    tools_ran = False

                span.set_attribute("tokens_in", tin)
                span.set_attribute("tokens_out", tout)
                metrics.record_llm_tokens(self._model, api, tin, tout, ticker)
                _require_nonempty(text, api=api, finish_reason=finish_reason,
                                  span=span, model=self._model, ticker=ticker)

                _record_raw_response(span, text, finish_reason)
                thesis = parse_thesis(text)
                thesis = thesis.model_copy(update={"grounding": _grounding(tools_ran, thesis)})
                _record_parsed_response(span, thesis)
                metrics.record_llm_call(self._model, api, "ok", ticker)
                return thesis
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
    thesis = client.analyze(ticker, snapshot=snapshot)
    return {
        **thesis.model_dump(),
        "snapshot": snapshot.model_dump() if snapshot else None,
    }
