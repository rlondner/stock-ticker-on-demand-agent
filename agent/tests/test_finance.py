from lib.finance import Snapshot
from unittest.mock import MagicMock, patch, PropertyMock


def _fake_recs(records):
    m = MagicMock()
    m.to_dict.return_value = records
    return m


def test_fetch_recommendation_distribution_reads_0m_row():
    from lib import finance
    recs = _fake_recs([
        {"period": "0m", "strongBuy": 12, "buy": 8, "hold": 5, "sell": 1, "strongSell": 0},
        {"period": "-1m", "strongBuy": 10, "buy": 9, "hold": 6, "sell": 2, "strongSell": 1},
    ])
    t = MagicMock()
    t.recommendations = recs
    d = finance._fetch_recommendation_distribution(t)
    assert (d.strong_buy, d.buy, d.hold, d.sell, d.strong_sell) == (12, 8, 5, 1, 0)


def test_fetch_recommendation_distribution_none_when_no_0m_row():
    from lib import finance
    t = MagicMock()
    t.recommendations = _fake_recs([{"period": "-1m", "strongBuy": 1, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0}])
    assert finance._fetch_recommendation_distribution(t) is None


def test_fetch_recommendation_distribution_none_on_all_zero():
    from lib import finance
    t = MagicMock()
    t.recommendations = _fake_recs([{"period": "0m", "strongBuy": 0, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0}])
    assert finance._fetch_recommendation_distribution(t) is None


def test_fetch_recommendation_distribution_none_on_exception():
    from lib import finance
    t = MagicMock()
    type(t).recommendations = PropertyMock(side_effect=RuntimeError("boom"))
    assert finance._fetch_recommendation_distribution(t) is None


def test_fetch_snapshot_attaches_analyst_distribution():
    from lib import finance
    fake_ticker = MagicMock()
    fake_ticker.info = dict(_HAPPY_INFO)
    fake_ticker.recommendations = _fake_recs([
        {"period": "0m", "strongBuy": 12, "buy": 8, "hold": 5, "sell": 1, "strongSell": 0},
    ])
    with patch.object(finance, "yfinance") as yf:
        yf.Ticker.return_value = fake_ticker
        s = finance.fetch_snapshot("MDB")
    assert s.analyst_distribution is not None
    assert s.analyst_distribution.strong_buy == 12
    assert s.analyst_distribution.strong_sell == 0


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
        "analyst_distribution": None,
        "currency": "USD",
        "as_of": "2026-07-02T12:00:00Z",
    }
    s = Snapshot(**payload)
    assert s.model_dump() == payload


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


def test_fetch_snapshot_uses_history_when_regular_market_price_missing():
    """No regularMarketPrice in info → derive close/previous from history."""
    from lib import finance

    info_without_prices = {k: v for k, v in _HAPPY_INFO.items() if not k.startswith("regularMarket")}
    fake_ticker = MagicMock()
    fake_ticker.info = info_without_prices

    # Fake pandas-like history: two rows with a 'Close' column.
    # yfinance returns a DataFrame; we don't need real pandas in the test — we mock
    # the two lookups fetch_snapshot performs.
    history_df = MagicMock()
    history_df.empty = False
    close_col = MagicMock()
    close_col.iloc = [None, None, None, 346.44, 342.15]  # last two = prev, close
    history_df.__getitem__.return_value = close_col
    fake_ticker.history.return_value = history_df

    with patch.object(finance, "yfinance") as yf:
        yf.Ticker.return_value = fake_ticker
        s = finance.fetch_snapshot("MDB")

    assert s is not None
    assert s.close == 342.15
    assert s.previous_close == 346.44
    assert s.change_pct == -1.24
    # Sector/industry/etc. still present from info.
    assert s.sector == "Technology"


def test_fetch_snapshot_partial_info_leaves_nulls_and_change_pct_none():
    """info has no prices AND history is empty → close/previous/change_pct all None; other fields still populate."""
    from lib import finance

    minimal_info = {
        "longName": "Some Co.",
        "sector": "Utilities",
        "currency": "USD",
    }
    fake_ticker = MagicMock()
    fake_ticker.info = minimal_info
    empty_history = MagicMock()
    empty_history.empty = True
    fake_ticker.history.return_value = empty_history

    with patch.object(finance, "yfinance") as yf:
        yf.Ticker.return_value = fake_ticker
        s = finance.fetch_snapshot("SOMECO")

    assert s is not None
    assert s.company_name == "Some Co."
    assert s.sector == "Utilities"
    assert s.close is None
    assert s.previous_close is None
    assert s.change_pct is None
    assert s.currency == "USD"


def test_fetch_snapshot_returns_none_when_info_is_empty():
    """Delisted / unknown ticker: yfinance returns an empty info dict → None."""
    from lib import finance

    fake_ticker = MagicMock()
    fake_ticker.info = {}
    with patch.object(finance, "yfinance") as yf:
        yf.Ticker.return_value = fake_ticker
        assert finance.fetch_snapshot("XXXX") is None


def test_fetch_snapshot_retries_then_returns_none_on_persistent_failure(caplog):
    """yfinance raises on every attempt → fetch_snapshot returns None after retries."""
    from lib import finance

    with patch.object(finance, "yfinance") as yf:
        yf.Ticker.side_effect = RuntimeError("yahoo says no")
        with caplog.at_level("WARNING"):
            result = finance.fetch_snapshot("MDB")

    assert result is None
    # yfinance.Ticker should have been called 3 times (initial + 2 retries).
    assert yf.Ticker.call_count == 3
    # Warning about the missing snapshot should have been logged.
    assert any("snapshot.missing" in r.getMessage() for r in caplog.records)


def test_fetch_snapshot_sets_span_attributes_on_current_span():
    """fetch_snapshot annotates trace.get_current_span() with snapshot.* attrs on success."""
    from lib import finance

    fake_ticker = MagicMock()
    fake_ticker.info = dict(_HAPPY_INFO)
    fake_span = MagicMock()

    with patch.object(finance, "yfinance") as yf, \
         patch.object(finance.trace, "get_current_span", return_value=fake_span):
        yf.Ticker.return_value = fake_ticker
        finance.fetch_snapshot("MDB")

    fake_span.set_attribute.assert_any_call("snapshot.fetched", True)
    fake_span.set_attribute.assert_any_call("snapshot.ticker", "MDB")
    fake_span.set_attribute.assert_any_call("snapshot.close", 342.15)
    fake_span.set_attribute.assert_any_call("snapshot.change_pct", -1.24)


def test_fetch_snapshot_sets_failure_span_attributes():
    """On failure (empty info), fetch_snapshot marks the span with snapshot.fetched=False."""
    from lib import finance

    fake_ticker = MagicMock()
    fake_ticker.info = {}
    fake_span = MagicMock()

    with patch.object(finance, "yfinance") as yf, \
         patch.object(finance.trace, "get_current_span", return_value=fake_span):
        yf.Ticker.return_value = fake_ticker
        assert finance.fetch_snapshot("XXXX") is None

    fake_span.set_attribute.assert_any_call("snapshot.fetched", False)
    fake_span.set_attribute.assert_any_call("snapshot.ticker", "XXXX")


# --- Metrics emission tests ---

def _spy_snapshot_metrics(monkeypatch):
    """Patch the four snapshot emitters on the metrics module and capture calls."""
    from lib import metrics
    calls = {"fetch": [], "backfilled": [], "field_missing": [], "completeness": []}
    monkeypatch.setattr(metrics, "record_snapshot_fetch",
                        lambda outcome, ticker, duration_ms: calls["fetch"].append((outcome, ticker)))
    monkeypatch.setattr(metrics, "record_snapshot_backfilled",
                        lambda ticker: calls["backfilled"].append(ticker))
    monkeypatch.setattr(metrics, "record_snapshot_field_missing",
                        lambda field, ticker: calls["field_missing"].append(field))
    monkeypatch.setattr(metrics, "record_snapshot_completeness",
                        lambda populated, ticker: calls["completeness"].append(populated))
    return calls


def test_fetch_snapshot_emits_success_metrics(monkeypatch):
    from lib import finance
    calls = _spy_snapshot_metrics(monkeypatch)
    fake_ticker = MagicMock()
    fake_ticker.info = dict(_HAPPY_INFO)
    fake_ticker.recommendations = _fake_recs([
        {"period": "0m", "strongBuy": 12, "buy": 8, "hold": 5, "sell": 1, "strongSell": 0},
    ])
    with patch.object(finance, "yfinance") as yf:
        yf.Ticker.return_value = fake_ticker
        finance.fetch_snapshot("MDB")
    assert calls["fetch"] == [("success", "MDB")]
    assert calls["backfilled"] == []
    assert calls["field_missing"] == []
    assert calls["completeness"] == [13]


def test_fetch_snapshot_emits_backfilled_on_history_fallback(monkeypatch):
    from lib import finance
    calls = _spy_snapshot_metrics(monkeypatch)
    info_without_prices = {k: v for k, v in _HAPPY_INFO.items() if not k.startswith("regularMarket")}
    fake_ticker = MagicMock()
    fake_ticker.info = info_without_prices
    history_df = MagicMock()
    history_df.empty = False
    close_col = MagicMock()
    close_col.iloc = [None, None, None, 346.44, 342.15]
    history_df.__getitem__.return_value = close_col
    fake_ticker.history.return_value = history_df
    with patch.object(finance, "yfinance") as yf:
        yf.Ticker.return_value = fake_ticker
        finance.fetch_snapshot("MDB")
    assert calls["fetch"] == [("success", "MDB")]
    assert calls["backfilled"] == ["MDB"]


def test_fetch_snapshot_emits_field_missing_and_completeness_for_partial(monkeypatch):
    from lib import finance
    calls = _spy_snapshot_metrics(monkeypatch)
    minimal_info = {"longName": "Some Co.", "sector": "Utilities", "currency": "USD"}
    fake_ticker = MagicMock()
    fake_ticker.info = minimal_info
    empty_history = MagicMock()
    empty_history.empty = True
    fake_ticker.history.return_value = empty_history
    with patch.object(finance, "yfinance") as yf:
        yf.Ticker.return_value = fake_ticker
        finance.fetch_snapshot("SOMECO")
    assert calls["fetch"] == [("success", "SOMECO")]
    # Only company_name + sector populated (of 13 key fields) → 11 missing, completeness 2.
    assert set(calls["field_missing"]) == {
        "industry", "close", "previous_close", "market_cap",
        "fifty_two_week_high", "fifty_two_week_low", "average_volume",
        "analyst_recommendation", "analyst_opinion_count", "business_summary",
        "analyst_distribution",
    }
    assert calls["completeness"] == [2]


def test_fetch_snapshot_emits_error_outcome_on_exception(monkeypatch):
    from lib import finance
    calls = _spy_snapshot_metrics(monkeypatch)
    with patch.object(finance, "yfinance") as yf:
        yf.Ticker.side_effect = RuntimeError("yahoo says no")
        assert finance.fetch_snapshot("MDB") is None
    assert calls["fetch"] == [("error", "MDB")]
    assert calls["backfilled"] == [] and calls["completeness"] == []


def test_fetch_snapshot_emits_missing_outcome_on_empty_info(monkeypatch):
    from lib import finance
    calls = _spy_snapshot_metrics(monkeypatch)
    fake_ticker = MagicMock()
    fake_ticker.info = {}
    with patch.object(finance, "yfinance") as yf:
        yf.Ticker.return_value = fake_ticker
        assert finance.fetch_snapshot("XXXX") is None
    assert calls["fetch"] == [("missing", "XXXX")]
    assert calls["completeness"] == []
