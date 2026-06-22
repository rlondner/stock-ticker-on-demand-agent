import json
import pytest
from pydantic import ValidationError
from lib.llm import Analysis, Signal, parse_response

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
