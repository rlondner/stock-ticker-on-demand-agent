import json
from unittest.mock import MagicMock, patch
import httpx
import pytest
from openai import InternalServerError
from pydantic import ValidationError
from lib.llm import Analysis, OpenAIClient, Signal, _env_flag, parse_response

def test_analysis_validates_buy_hold_sell():
    a = Analysis(recommendation="buy", summary="strong fundamentals", signals=[])
    assert a.recommendation == "buy"

def test_analysis_rejects_invalid_recommendation():
    with pytest.raises(ValidationError):
        Analysis(recommendation="strong-buy", summary="x", signals=[])

def test_analysis_accepts_signals():
    a = Analysis(
        recommendation="hold",
        summary="mixed",
        signals=[Signal(label="P/E", evidence="32, above average", source="https://example.com/aapl")],
    )
    assert len(a.signals) == 1
    assert a.signals[0].source == "https://example.com/aapl"

def test_parse_response_extracts_json():
    payload = json.dumps({
        "recommendation": "sell",
        "summary": "declining margins",
        "signals": [{"label": "margin", "evidence": "down 4pp YoY", "source": None}],
    })
    a = parse_response(payload)
    assert a.recommendation == "sell"

def test_parse_response_rejects_malformed():
    with pytest.raises(ValueError):
        parse_response("not json")


def test_parse_response_error_includes_snippet_and_length():
    raw = "Sure, here you go: not actually json at all"
    with pytest.raises(ValueError) as exc_info:
        parse_response(raw)
    msg = str(exc_info.value)
    assert f"raw_length={len(raw)}" in msg
    assert "Sure, here you go" in msg


def test_parse_response_error_caps_snippet_at_200_chars():
    raw = "x" * 5000
    with pytest.raises(ValueError) as exc_info:
        parse_response(raw)
    msg = str(exc_info.value)
    assert "raw_length=5000" in msg
    # The repr of 200 x's is "'xxx…xxx'" — 200 chars + 2 quotes.
    assert "'" + "x" * 200 + "'" in msg


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, True),       # unset → default
        ("", True),         # empty string → treated as unset-ish → default
        ("true", True),
        ("True", True),
        ("1", True),
        ("yes", True),
        ("false", False),
        ("False", False),
        ("0", False),
        ("no", False),
        ("off", False),
    ],
)
def test_env_flag_defaults_true(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("X_FLAG", raising=False)
    else:
        monkeypatch.setenv("X_FLAG", value)
    assert _env_flag("X_FLAG", default=True) is expected


def _fake_responses_resp(text: str):
    resp = MagicMock()
    resp.output_text = text
    resp.usage = MagicMock(input_tokens=10, output_tokens=20)
    return resp


def _fake_chat_resp(text: str):
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=text))]
    resp.usage = MagicMock(prompt_tokens=10, completion_tokens=20)
    return resp


VALID_JSON = json.dumps({"recommendation": "hold", "summary": "ok", "signals": []})


def test_client_default_uses_responses_api(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("OPENAI_USE_RESPONSES_API", raising=False)
    with patch("lib.llm.OpenAI") as openai_ctor:
        instance = openai_ctor.return_value
        instance.responses.create.return_value = _fake_responses_resp(VALID_JSON)
        client = OpenAIClient()
        result = client.analyze("AAPL")
        assert result.recommendation == "hold"
        instance.responses.create.assert_called_once()
        instance.chat.completions.create.assert_not_called()


def test_client_uses_chat_completions_when_flag_false(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_USE_RESPONSES_API", "false")
    with patch("lib.llm.OpenAI") as openai_ctor:
        instance = openai_ctor.return_value
        instance.chat.completions.create.return_value = _fake_chat_resp(VALID_JSON)
        client = OpenAIClient()
        result = client.analyze("AAPL")
        assert result.recommendation == "hold"
        instance.chat.completions.create.assert_called_once()
        instance.responses.create.assert_not_called()
        # chat.completions path must NOT pass the OpenAI hosted web_search tool.
        call_kwargs = instance.chat.completions.create.call_args.kwargs
        assert "tools" not in call_kwargs


def test_client_chat_completions_path_handles_none_content(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_USE_RESPONSES_API", "false")
    with patch("lib.llm.OpenAI") as openai_ctor:
        instance = openai_ctor.return_value
        # Some endpoints return null content; client must not crash with AttributeError.
        resp = MagicMock()
        resp.choices = [MagicMock(message=MagicMock(content=None))]
        resp.usage = None
        instance.chat.completions.create.return_value = resp
        client = OpenAIClient()
        with pytest.raises(ValueError, match="LLM did not return valid JSON"):
            client.analyze("AAPL")


def _make_internal_server_error(status_code: int) -> InternalServerError:
    """Build a real openai.InternalServerError matching a 5xx response (e.g. Anthropic 529)."""
    req = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    resp = httpx.Response(status_code, request=req, json={"error": {"message": "overloaded"}})
    return InternalServerError("overloaded", response=resp, body=None)


def test_client_retries_on_5xx_then_succeeds(monkeypatch):
    """Anthropic returns 529 when overloaded; OpenAI returns 503. tenacity must retry."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_USE_RESPONSES_API", "false")
    with patch("lib.llm.OpenAI") as openai_ctor:
        instance = openai_ctor.return_value
        # First two calls raise 529; third returns a valid response.
        # Patch tenacity's wait so the test doesn't actually sleep through the backoff.
        instance.chat.completions.create.side_effect = [
            _make_internal_server_error(529),
            _make_internal_server_error(529),
            _fake_chat_resp(VALID_JSON),
        ]
        with patch("lib.llm.wait_exponential", return_value=lambda *a, **kw: 0):
            client = OpenAIClient()
            result = client.analyze("AAPL")
        assert result.recommendation == "hold"
        assert instance.chat.completions.create.call_count == 3

def test_parse_response_handles_json_fence():
    payload = '```json\n{"recommendation":"buy","summary":"x","signals":[]}\n```'
    a = parse_response(payload)
    assert a.recommendation == "buy"

def test_parse_response_handles_bare_fence():
    payload = '```\n{"recommendation":"hold","summary":"x","signals":[]}\n```'
    a = parse_response(payload)
    assert a.recommendation == "hold"

def test_parse_response_handles_inline_fence():
    payload = '```{"recommendation":"sell","summary":"x","signals":[]}```'
    a = parse_response(payload)
    assert a.recommendation == "sell"
