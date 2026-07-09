import json
from unittest.mock import MagicMock, patch
import httpx
import pytest
from openai import InternalServerError
from pydantic import ValidationError
from lib.llm import Analysis, EmptyLLMResponseError, OpenAIClient, Signal, _env_flag, parse_response

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


def _empty_chat_resp():
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=""), finish_reason="stop")]
    resp.usage = MagicMock(prompt_tokens=0, completion_tokens=0)
    return resp


def _none_chat_resp():
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=None), finish_reason="stop")]
    resp.usage = None
    return resp


def test_client_retries_on_empty_response_then_succeeds(monkeypatch):
    """Some server-managed bots and small local models intermittently return
    content='' with finish_reason='stop' and no error. tenacity must retry."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_USE_RESPONSES_API", "false")
    with patch("lib.llm.OpenAI") as openai_ctor:
        instance = openai_ctor.return_value
        instance.chat.completions.create.side_effect = [
            _empty_chat_resp(),
            _none_chat_resp(),
            _fake_chat_resp(VALID_JSON),
        ]
        with patch("lib.llm.wait_exponential", return_value=lambda *a, **kw: 0):
            client = OpenAIClient()
            result = client.analyze("AAPL")
        assert result.recommendation == "hold"
        assert instance.chat.completions.create.call_count == 3


def test_client_raises_empty_error_after_all_retries_exhausted(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_USE_RESPONSES_API", "false")
    with patch("lib.llm.OpenAI") as openai_ctor:
        instance = openai_ctor.return_value
        instance.chat.completions.create.side_effect = [
            _empty_chat_resp(),
            _empty_chat_resp(),
            _empty_chat_resp(),
        ]
        with patch("lib.llm.wait_exponential", return_value=lambda *a, **kw: 0):
            client = OpenAIClient()
            with pytest.raises(EmptyLLMResponseError):
                client.analyze("AAPL")
        assert instance.chat.completions.create.call_count == 3


def test_client_logs_warning_and_records_span_event_on_empty(monkeypatch, caplog):
    """Empty response must produce a WARNING log + a span event, so observability
    picks up the signal even when a retry rescues the outer call."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_USE_RESPONSES_API", "false")
    with patch("lib.llm.OpenAI") as openai_ctor, patch("lib.llm.trace") as trace_mock:
        instance = openai_ctor.return_value
        instance.chat.completions.create.side_effect = [
            _empty_chat_resp(),
            _fake_chat_resp(VALID_JSON),
        ]
        span = MagicMock()
        trace_mock.get_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = span
        with patch("lib.llm.wait_exponential", return_value=lambda *a, **kw: 0):
            client = OpenAIClient()
            with caplog.at_level("WARNING", logger="lib.llm"):
                client.analyze("AAPL")
        # Warning log from the first (empty) attempt.
        assert any(
            "LLM returned empty response" in r.message and r.levelname == "WARNING"
            for r in caplog.records
        )
        # Span event on the first (empty) attempt.
        event_calls = [c for c in span.add_event.call_args_list if c.args[0] == "llm.empty_response"]
        assert len(event_calls) >= 1
        attrs = event_calls[0].args[1]
        assert attrs["api"] == "chat.completions"
        assert attrs["finish_reason"] == "stop"


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


def test_analyze_emits_llm_metrics(monkeypatch):
    import importlib, lib.metrics as mtr, lib.llm as llm
    importlib.reload(mtr)
    seen = {"tokens": [], "calls": []}
    monkeypatch.setattr(mtr, "record_llm_tokens",
                        lambda model, api, tokens_in, tokens_out, ticker: seen["tokens"].append((model, api, tokens_in, tokens_out, ticker)))
    monkeypatch.setattr(mtr, "record_llm_call",
                        lambda model, api, outcome, ticker: seen["calls"].append((model, api, outcome, ticker)))
    importlib.reload(llm)

    valid = '{"recommendation":"buy","summary":"s","signals":[]}'

    class FakeResponses:
        def create(self, **kw):
            class R:
                output_text = valid
                status = "completed"
                class usage:  # noqa: N801
                    input_tokens = 100
                    output_tokens = 40
            return R()

    class FakeClient:
        responses = FakeResponses()

    client = llm.OpenAIClient.__new__(llm.OpenAIClient)
    client._client = FakeClient()
    client._model = "gpt-4.1-mini"
    client._use_responses_api = True

    client.analyze("AAPL")
    assert seen["tokens"] == [("gpt-4.1-mini", "responses", 100, 40, "AAPL")]
    assert seen["calls"] == [("gpt-4.1-mini", "responses", "ok", "AAPL")]


def test_chat_completions_branch_emits_tokens_and_call(monkeypatch):
    """chat.completions branch emits record_llm_tokens and record_llm_call with api='chat.completions'."""
    import importlib, lib.metrics as mtr, lib.llm as llm
    importlib.reload(mtr)
    seen = {"tokens": [], "calls": []}
    monkeypatch.setattr(mtr, "record_llm_tokens",
                        lambda model, api, tin, tout, ticker: seen["tokens"].append((model, api, tin, tout, ticker)))
    monkeypatch.setattr(mtr, "record_llm_call",
                        lambda model, api, outcome, ticker: seen["calls"].append((model, api, outcome, ticker)))
    importlib.reload(llm)

    valid = '{"recommendation":"sell","summary":"s","signals":[]}'

    class FakeCompletions:
        def create(self, **kw):
            from unittest.mock import MagicMock
            resp = MagicMock()
            resp.choices = [MagicMock(message=MagicMock(content=valid), finish_reason="stop")]
            resp.usage = MagicMock(prompt_tokens=50, completion_tokens=25)
            return resp

    class FakeChatClient:
        class chat:
            completions = FakeCompletions()

    client = llm.OpenAIClient.__new__(llm.OpenAIClient)
    client._client = FakeChatClient()
    client._model = "gpt-4.1-mini"
    client._use_responses_api = False

    client.analyze("TSLA")
    assert seen["tokens"] == [("gpt-4.1-mini", "chat.completions", 50, 25, "TSLA")]
    assert seen["calls"] == [("gpt-4.1-mini", "chat.completions", "ok", "TSLA")]


def test_empty_response_emits_record_llm_empty_response(monkeypatch):
    """_require_nonempty with empty text invokes record_llm_empty_response(model, api, ticker)."""
    import importlib, lib.metrics as mtr, lib.llm as llm
    importlib.reload(mtr)
    seen = {"empty": []}
    monkeypatch.setattr(mtr, "record_llm_empty_response",
                        lambda model, api, ticker: seen["empty"].append((model, api, ticker)))
    monkeypatch.setattr(mtr, "record_llm_tokens", lambda *a, **kw: None)
    monkeypatch.setattr(mtr, "record_llm_call", lambda *a, **kw: None)
    importlib.reload(llm)

    from unittest.mock import MagicMock
    span = MagicMock()
    import pytest
    with pytest.raises(llm.EmptyLLMResponseError):
        llm._require_nonempty("", api="chat.completions", finish_reason="stop",
                              span=span, model="gpt-4.1-mini", ticker="NVDA")
    assert seen["empty"] == [("gpt-4.1-mini", "chat.completions", "NVDA")]
