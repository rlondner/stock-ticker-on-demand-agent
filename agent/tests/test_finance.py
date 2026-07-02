from lib.finance import Snapshot


def test_snapshot_defaults_and_required_fields():
    s = Snapshot(currency="USD", as_of="2026-07-02T12:00:00Z")
    # All scalars default to None; only currency + as_of are required.
    assert s.company_name is None
    assert s.close is None
    assert s.previous_close is None
    assert s.change_pct is None
    assert s.market_cap is None
    assert s.fifty_two_week_high is None
    assert s.fifty_two_week_low is None
    assert s.average_volume is None
    assert s.analyst_recommendation is None
    assert s.analyst_opinion_count is None
    assert s.business_summary is None
    assert s.sector is None
    assert s.industry is None
    assert s.currency == "USD"
    assert s.as_of == "2026-07-02T12:00:00Z"


def test_snapshot_full_shape_round_trips_through_model_dump():
    payload = {
        "company_name": "MongoDB, Inc.",
        "sector": "Technology",
        "industry": "Software—Infrastructure",
        "close": 342.15,
        "previous_close": 346.44,
        "change_pct": -1.24,
        "market_cap": 28_100_000_000,
        "fifty_two_week_high": 410.05,
        "fifty_two_week_low": 210.00,
        "average_volume": 1_800_000,
        "analyst_recommendation": "buy",
        "analyst_opinion_count": 34,
        "business_summary": "MongoDB, Inc. develops a document-based database.",
        "currency": "USD",
        "as_of": "2026-07-02T12:00:00Z",
    }
    s = Snapshot(**payload)
    assert s.model_dump() == payload


from unittest.mock import MagicMock, patch


_HAPPY_INFO = {
    "longName": "MongoDB, Inc.",
    "sector": "Technology",
    "industry": "Software—Infrastructure",
    "regularMarketPrice": 342.15,
    "regularMarketPreviousClose": 346.44,
    "marketCap": 28_100_000_000,
    "fiftyTwoWeekHigh": 410.05,
    "fiftyTwoWeekLow": 210.00,
    "averageVolume": 1_800_000,
    "recommendationKey": "buy",
    "numberOfAnalystOpinions": 34,
    "longBusinessSummary": "MongoDB, Inc. develops a document-based database.",
    "currency": "USD",
}


def test_fetch_snapshot_happy_path_from_info():
    """When info has regularMarketPrice + previousClose, use them directly and derive change_pct."""
    from lib import finance

    fake_ticker = MagicMock()
    fake_ticker.info = dict(_HAPPY_INFO)

    with patch.object(finance, "yfinance") as yf:
        yf.Ticker.return_value = fake_ticker
        s = finance.fetch_snapshot("MDB")

    assert s is not None
    assert s.company_name == "MongoDB, Inc."
    assert s.sector == "Technology"
    assert s.industry == "Software—Infrastructure"
    assert s.close == 342.15
    assert s.previous_close == 346.44
    # (342.15 - 346.44) / 346.44 * 100 = -1.238... rounded 2dp = -1.24
    assert s.change_pct == -1.24
    assert s.market_cap == 28_100_000_000
    assert s.fifty_two_week_high == 410.05
    assert s.fifty_two_week_low == 210.00
    assert s.average_volume == 1_800_000
    assert s.analyst_recommendation == "buy"
    assert s.analyst_opinion_count == 34
    assert s.business_summary == "MongoDB, Inc. develops a document-based database."
    assert s.currency == "USD"
    # as_of should be an ISO-8601 UTC timestamp; the exact value is not asserted.
    assert "T" in s.as_of and s.as_of.endswith("Z")
