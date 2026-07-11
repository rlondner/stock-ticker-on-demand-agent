import json
from unittest.mock import MagicMock, patch
import httpx
import pytest
from openai import InternalServerError
from pydantic import ValidationError
from lib.llm import Thesis, EmptyLLMResponseError, OpenAIClient, _env_flag, parse_thesis

_THESIS_JSON = (
    '{"recommendation":"buy","confidence":"medium","summary":"s",'
    '"bull_case":[{"claim":"c","evidence":"e","source_url":"https://x.test/a"}],'
    '"bear_case":[{"claim":"c","evidence":"e","source_url":null}],'
    '"key_risks":[{"claim":"c","evidence":"e","source_url":null}]}'
)


class _FakeResponses:
    def __init__(self, text): self._text = text
    def create(self, **kw):
        from types import SimpleNamespace
        return SimpleNamespace(output=[], output_text=self._text,
                               usage=SimpleNamespace(input_tokens=100, output_tokens=40))

class _FakeResponsesClient:
    def __init__(self, text): self.responses = _FakeResponses(text)


def test_thesis_validates_buy_hold_sell():
    t = parse_thesis(_THESIS_JSON)
    assert t.recommendation == "buy"

def test_thesis_rejects_invalid_recommendation():
    bad = _THESIS_JSON.replace('"buy"', '"strong-buy"')
    with pytest.raises(ValidationError):
        parse_thesis(bad)

def test_thesis_rejects_invalid_confidence():
    bad = _THESIS_JSON.replace('"medium"', '"very-high"')
    with pytest.raises(ValidationError):
        parse_thesis(bad)

def test_thesis_accepts_bull_bear_risks():
    t = parse_thesis(_THESIS_JSON)
    assert len(t.bull_case) == 1
    assert t.bull_case[0].source_url == "https://x.test/a"
    assert t.bear_case[0].source_url is None
    assert len(t.key_risks) == 1

def test_parse_thesis_extracts_json():
    t = parse_thesis(_THESIS_JSON)
    assert t.recommendation == "buy"

def test_parse_thesis_rejects_malformed():
    with pytest.raises(ValueError):
        parse_thesis("not json")


def test_parse_thesis_error_includes_snippet_and_length():
    raw = "Sure, here you go: not actually json at all"
    with pytest.raises(ValueError) as exc_info:
        parse_thesis(raw)
    msg = str(exc_info.value)
    assert f"raw_length={len(raw)}" in msg
    assert "Sure, here you go" in msg


def test_parse_thesis_error_caps_snippet_at_200_chars():
    raw = "x" * 5000
    with pytest.raises(ValueError) as exc_info:
        parse_thesis(raw)
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
    from types import SimpleNamespace
    return SimpleNamespace(output=[], output_text=text,
                           usage=SimpleNamespace(input_tokens=10, output_tokens=20))


def _fake_chat_resp(text: str):
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=text), finish_reason="stop")]
    resp.usage = MagicMock(prompt_tokens=10, completion_tokens=20)
    return resp


def test_client_default_uses_responses_api(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("OPENAI_USE_RESPONSES_API", raising=False)
    with patch("lib.llm.OpenAI") as openai_ctor:
        instance = openai_ctor.return_value
        instance.responses.create.return_value = _fake_responses_resp(_THESIS_JSON)
        client = OpenAIClient()
        result = client.analyze("AAPL")
        assert result.recommendation == "buy"
        instance.responses.create.assert_called_once()
        instance.chat.completions.create.assert_not_called()


def test_client_uses_chat_completions_when_flag_false(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_USE_RESPONSES_API", "false")
    with patch("lib.llm.OpenAI") as openai_ctor:
        instance = openai_ctor.return_value
        instance.chat.completions.create.return_value = _fake_chat_resp(_THESIS_JSON)
        client = OpenAIClient()
        result = client.analyze("AAPL")
        assert result.recommendation == "buy"
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
            _fake_chat_resp(_THESIS_JSON),
        ]
        with patch("lib.llm.wait_exponential", return_value=lambda *a, **kw: 0):
            client = OpenAIClient()
            result = client.analyze("AAPL")
        assert result.recommendation == "buy"
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
            _fake_chat_resp(_THESIS_JSON),
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
            _fake_chat_resp(_THESIS_JSON),
        ]
        with patch("lib.llm.wait_exponential", return_value=lambda *a, **kw: 0):
            client = OpenAIClient()
            result = client.analyze("AAPL")
        assert result.recommendation == "buy"
        assert instance.chat.completions.create.call_count == 3

def test_parse_thesis_handles_json_fence():
    fenced = '```json\n' + _THESIS_JSON + '\n```'
    t = parse_thesis(fenced)
    assert t.recommendation == "buy"

def test_parse_thesis_handles_bare_fence():
    fenced = '```\n' + _THESIS_JSON + '\n```'
    t = parse_thesis(fenced)
    assert t.recommendation == "buy"

def test_parse_thesis_handles_inline_fence():
    fenced = '```' + _THESIS_JSON + '```'
    t = parse_thesis(fenced)
    assert t.recommendation == "buy"


def test_analyze_emits_llm_metrics(monkeypatch):
    import importlib, lib.metrics as mtr, lib.llm as llm
    importlib.reload(mtr)
    seen = {"tokens": [], "calls": []}
    monkeypatch.setattr(mtr, "record_llm_tokens",
                        lambda model, api, tin, tout, ticker: seen["tokens"].append((model, api, tin, tout, ticker)))
    monkeypatch.setattr(mtr, "record_llm_call",
                        lambda model, api, outcome, ticker: seen["calls"].append((model, api, outcome, ticker)))
    importlib.reload(llm)

    client = llm.OpenAIClient.__new__(llm.OpenAIClient)
    client._client = _FakeResponsesClient(_THESIS_JSON)
    client._model = "gpt-4.1-mini"
    client._use_responses_api = True

    t = client.analyze("AAPL")
    assert isinstance(t, llm.Thesis)
    assert t.recommendation == "buy"
    assert t.grounding == "snapshot_only"   # fake returns no tool items → tools_ran False
    assert seen["tokens"] == [("gpt-4.1-mini", "responses", 100, 40, "AAPL")]
    assert seen["calls"] == [("gpt-4.1-mini", "responses", "ok", "AAPL")]


def test_analyze_grounding_researched_when_web_search_and_citation(monkeypatch):
    import importlib, lib.metrics as mtr, lib.llm as llm
    importlib.reload(mtr)
    monkeypatch.setattr(mtr, "record_llm_tokens", lambda *a, **k: None)
    monkeypatch.setattr(mtr, "record_llm_call", lambda *a, **k: None)
    importlib.reload(llm)

    from types import SimpleNamespace
    captured = {}
    class _WS:
        def create(self, **kw):
            captured["tools"] = kw.get("tools")
            return SimpleNamespace(
                output=[SimpleNamespace(type="web_search_call")],
                output_text=_THESIS_JSON,
                usage=SimpleNamespace(input_tokens=1, output_tokens=1),
            )
    client = llm.OpenAIClient.__new__(llm.OpenAIClient)
    client._client = SimpleNamespace(responses=_WS())
    client._model = "gpt-4.1-mini"
    client._use_responses_api = True
    t = client.analyze("AAPL")
    assert t.grounding == "researched"   # web_search ran + bull_case has a source_url
    assert {"type": "web_search"} in (captured["tools"] or [])


def test_analyze_chat_completions_fallback_is_snapshot_only(monkeypatch):
    import importlib, lib.metrics as mtr, lib.llm as llm
    importlib.reload(mtr)
    monkeypatch.setattr(mtr, "record_llm_tokens", lambda *a, **k: None)
    monkeypatch.setattr(mtr, "record_llm_call", lambda *a, **k: None)
    importlib.reload(llm)

    from unittest.mock import MagicMock
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=_THESIS_JSON), finish_reason="stop")]
    resp.usage = MagicMock(prompt_tokens=50, completion_tokens=25)
    fake = MagicMock()
    fake.chat.completions.create.return_value = resp
    client = llm.OpenAIClient.__new__(llm.OpenAIClient)
    client._client = fake
    client._model = "gpt-4.1-mini"
    client._use_responses_api = False
    t = client.analyze("TSLA")
    assert t.recommendation == "buy" and t.grounding == "snapshot_only"


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

    class FakeCompletions:
        def create(self, **kw):
            from unittest.mock import MagicMock
            resp = MagicMock()
            resp.choices = [MagicMock(message=MagicMock(content=_THESIS_JSON), finish_reason="stop")]
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


def test_analyze_records_llm_duration(monkeypatch):
    import importlib, lib.metrics as mtr, lib.llm as llm
    importlib.reload(mtr)
    seen = []
    monkeypatch.setattr(mtr, "record_llm_tokens", lambda *a, **kw: None)
    monkeypatch.setattr(mtr, "record_llm_call", lambda *a, **kw: None)
    monkeypatch.setattr(mtr, "record_llm_duration",
                        lambda model, api, duration_ms, ticker: seen.append((model, api, ticker)))
    importlib.reload(llm)

    client = llm.OpenAIClient.__new__(llm.OpenAIClient)
    client._client = _FakeResponsesClient(_THESIS_JSON)
    client._model = "gpt-4.1-mini"
    client._use_responses_api = True

    client.analyze("AAPL")
    assert seen == [("gpt-4.1-mini", "responses", "AAPL")]
