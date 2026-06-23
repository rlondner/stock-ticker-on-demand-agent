import json
import os
import re
from typing import Protocol
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from openai import OpenAI, APIError, RateLimitError, APIConnectionError, InternalServerError
from opentelemetry import trace
from .prompts import SYSTEM_PROMPT, user_prompt

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


def _env_flag(name: str, default: bool) -> bool:
    """Parse an env var as a boolean. Unset OR empty → default; 'false'/'0'/'no'/'off' → False; anything else → True."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    stripped = raw.strip().lower()
    if stripped == "":
        return default
    return stripped not in ("false", "0", "no", "off")


class OpenAIClient:
    def __init__(self, model: str | None = None):
        self._client = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.environ.get("OPENAI_API_URL") or None,
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
        retry=retry_if_exception_type((RateLimitError, APIConnectionError, InternalServerError)),
        reraise=True,
    )
    def analyze(self, ticker: str) -> Analysis:
        tracer = trace.get_tracer("stock-agent")
        with tracer.start_as_current_span("llm.analyze") as span:
            span.set_attribute("model", self._model)
            if self._use_responses_api:
                span.set_attribute("api", "responses")
                resp = self._client.responses.create(
                    model=self._model,
                    input=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt(ticker)},
                    ],
                    tools=[{"type": "web_search"}],
                )
                text = resp.output_text
                usage = getattr(resp, "usage", None)
                if usage:
                    span.set_attribute("tokens_in", getattr(usage, "input_tokens", 0))
                    span.set_attribute("tokens_out", getattr(usage, "output_tokens", 0))
            else:
                span.set_attribute("api", "chat.completions")
                resp = self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt(ticker)},
                    ],
                )
                text = resp.choices[0].message.content or ""
                usage = getattr(resp, "usage", None)
                if usage:
                    span.set_attribute("tokens_in", getattr(usage, "prompt_tokens", 0))
                    span.set_attribute("tokens_out", getattr(usage, "completion_tokens", 0))
            return parse_response(text)

def run_analysis(ticker: str) -> dict:
    client: LLMClient = OpenAIClient()
    return client.analyze(ticker).model_dump()
