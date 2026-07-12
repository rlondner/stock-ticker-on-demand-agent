from unittest.mock import MagicMock, patch
import lib.tools as tools


def _fake_ticker(**attrs):
    t = MagicMock()
    for k, v in attrs.items():
        setattr(t, k, v)
    return t


def _frame(empty=False, to_dict=None, records=None):
    df = MagicMock()
    df.empty = empty
    if to_dict is not None:
        df.to_dict.return_value = to_dict
    if records is not None:
        df.reset_index.return_value.to_dict.return_value = records
    return df


def _spy(monkeypatch):
    logs = []
    monkeypatch.setattr(tools, "emit_log",
                        lambda level, msg, **kw: logs.append((level, msg, kw)))
    span = MagicMock()
    monkeypatch.setattr(tools.trace, "get_current_span", lambda: span)
    return logs, span


def test_observed_tool_ok(monkeypatch):
    logs, span = _spy(monkeypatch)
    run = tools._observed_tool("get_x", lambda args: {"value": args["ticker"]})
    out = run({"ticker": "AAPL"})
    assert out == {"value": "AAPL"}
    assert ("info", "tool.get_x.ok", {"ticker": "AAPL"}) in logs
    span.add_event.assert_any_call("tool.get_x", {"outcome": "ok"})


def test_observed_tool_swallows_exception(monkeypatch):
    logs, span = _spy(monkeypatch)
    def boom(args):
        raise RuntimeError("nope")
    run = tools._observed_tool("get_x", boom)
    out = run({"ticker": "AAPL"})
    assert "error" in out and "nope" in out["error"]
    assert any(lvl == "warn" and m == "tool.get_x.failed" and "nope" in kw.get("reason", "")
               for lvl, m, kw in logs)
    ev = span.add_event.call_args_list[-1]
    assert ev.args[0] == "tool.get_x" and ev.args[1]["outcome"] == "error"
    assert "nope" in ev.args[1]["error"]


def test_observed_tool_treats_error_dict_as_failure(monkeypatch):
    logs, span = _spy(monkeypatch)
    run = tools._observed_tool("get_x", lambda args: {"error": "no data"})
    out = run({"ticker": "AAPL"})
    assert out == {"error": "no data"}
    assert any(m == "tool.get_x.failed" for _, m, _ in logs)
    span.add_event.assert_any_call("tool.get_x", {"outcome": "error", "error": "no data"})


def test_get_financials_curates_three_years():
    income = _frame(to_dict={
        "2025-12-31": {"Total Revenue": 1000, "Net Income": 100, "Gross Profit": 600, "Operating Income": 200},
        "2024-12-31": {"Total Revenue": 900, "Net Income": 80, "Gross Profit": 520, "Operating Income": 150},
        "2023-12-31": {"Total Revenue": 800, "Net Income": 60, "Gross Profit": 460, "Operating Income": 130},
    })
    with patch.object(tools, "yfinance") as yf:
        yf.Ticker.return_value = _fake_ticker(income_stmt=income)
        out = tools._get_financials({"ticker": "MDB"})
    assert out["fiscal_years"] == ["2025", "2024", "2023"]
    assert out["revenue"] == [1000.0, 900.0, 800.0]
    assert out["gross_margin_pct"] == [60.0, round(520 / 900 * 100, 1), round(460 / 800 * 100, 1)]
    # YoY growth for the most-recent year vs the prior: (1000-900)/900*100
    assert out["revenue_growth_pct"][0] == round((1000 - 900) / 900 * 100, 1)
    assert len(out["fiscal_years"]) == 3
    assert out["revenue_growth_pct"][-1] is None


def test_get_financials_empty_returns_error():
    with patch.object(tools, "yfinance") as yf:
        yf.Ticker.return_value = _fake_ticker(income_stmt=_frame(empty=True))
        assert tools._get_financials({"ticker": "X"}) == {"error": "no financials"}


def test_get_valuation_maps_info_fields():
    info = {
        "trailingPE": 30.1, "forwardPE": 25.0, "priceToSalesTrailing12Months": 12.4,
        "enterpriseToEbitda": 40.0, "trailingPegRatio": 1.8, "priceToBook": 15.0,
    }
    with patch.object(tools, "yfinance") as yf:
        yf.Ticker.return_value = _fake_ticker(info=info)
        out = tools._get_valuation({"ticker": "MDB"})
    assert out == {
        "trailing_pe": 30.1, "forward_pe": 25.0, "price_to_sales": 12.4,
        "ev_to_ebitda": 40.0, "peg_ratio": 1.8, "price_to_book": 15.0,
    }


def test_get_valuation_all_missing_returns_error():
    with patch.object(tools, "yfinance") as yf:
        yf.Ticker.return_value = _fake_ticker(info={"foo": "bar"})
        assert tools._get_valuation({"ticker": "X"}) == {"error": "no valuation data"}


def test_get_earnings_next_date_and_recent_quarters():
    records = [
        {"Earnings Date": "2026-04-30", "EPS Estimate": 1.5, "Reported EPS": None, "Surprise(%)": None},
        {"Earnings Date": "2026-01-30", "EPS Estimate": 1.2, "Reported EPS": 1.3, "Surprise(%)": 8.3},
        {"Earnings Date": "2025-10-30", "EPS Estimate": 1.0, "Reported EPS": 0.9, "Surprise(%)": -10.0},
    ]
    with patch.object(tools, "yfinance") as yf:
        yf.Ticker.return_value = _fake_ticker(earnings_dates=_frame(records=records))
        out = tools._get_earnings({"ticker": "MDB"})
    assert out["next_earnings_date"] == "2026-04-30"
    assert out["recent_quarters"][0] == {
        "date": "2026-01-30", "eps_estimate": 1.2, "eps_actual": 1.3, "surprise_pct": 8.3,
    }
    assert len(out["recent_quarters"]) == 2


def test_build_toolset_returns_schemas_and_matching_registry():
    schemas, registry = tools.build_toolset()
    names = [s["name"] for s in schemas]
    assert names == ["get_financials", "get_valuation", "get_earnings"]
    for s in schemas:
        assert s["type"] == "function"
        assert s["parameters"]["properties"]["ticker"]["type"] == "string"
        assert s["parameters"]["required"] == ["ticker"]
    assert set(registry.keys()) == set(names)
    assert all(callable(fn) for fn in registry.values())
