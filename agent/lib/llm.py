import json
import os
import re
from typing import Protocol
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from openai import OpenAI, APIError, RateLimitError, APIConnectionError
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
        raise ValueError(f"LLM did not return valid JSON: {e}") from e
    return Analysis(**data)

class OpenAIClient:
    def __init__(self, model: str = "gpt-4.1-mini"):
        self._client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self._model = model

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=16),
        retry=retry_if_exception_type((RateLimitError, APIConnectionError)),
        reraise=True,
    )
    def analyze(self, ticker: str) -> Analysis:
        tracer = trace.get_tracer("stock-agent")
        with tracer.start_as_current_span("llm.analyze") as span:
            span.set_attribute("model", self._model)
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
            return parse_response(text)

def run_analysis(ticker: str) -> dict:
    client: LLMClient = OpenAIClient()
    return client.analyze(ticker).model_dump()
