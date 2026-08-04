import datetime
from unittest.mock import MagicMock, patch
import lib.tools as tools


def _iso(days):
    """ISO date `days` from today (negative = past)."""
    return (datetime.date.today() + datetime.timedelta(days=days)).isoformat()


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


def test_get_financials_oldest_year_growth_uses_extra_prior_year():
    # A 4-year statement: after trimming to 3 emitted years, the oldest emitted
    # year (2023) still gets a YoY growth from the 4th (2022) prior year.
    income = _frame(to_dict={
        "2025-12-31": {"Total Revenue": 1000, "Net Income": 100, "Gross Profit": 600, "Operating Income": 200},
        "2024-12-31": {"Total Revenue": 900, "Net Income": 80, "Gross Profit": 520, "Operating Income": 150},
        "2023-12-31": {"Total Revenue": 800, "Net Income": 60, "Gross Profit": 460, "Operating Income": 130},
        "2022-12-31": {"Total Revenue": 700, "Net Income": 40, "Gross Profit": 400, "Operating Income": 110},
    })
    with patch.object(tools, "yfinance") as yf:
        yf.Ticker.return_value = _fake_ticker(income_stmt=income)
        out = tools._get_financials({"ticker": "MDB"})
    assert out["fiscal_years"] == ["2025", "2024", "2023"]
    assert len(out["revenue_growth_pct"]) == 3
    # oldest emitted year now has a real figure instead of a wasted None slot
    assert out["revenue_growth_pct"][-1] == round((800 - 700) / 700 * 100, 1)


def test_get_financials_zero_prior_revenue_skips_growth():
    income = _frame(to_dict={
        "2025-12-31": {"Total Revenue": 1000, "Net Income": 100, "Gross Profit": 600, "Operating Income": 200},
        "2024-12-31": {"Total Revenue": 0, "Net Income": -50, "Gross Profit": 0, "Operating Income": -10},
    })
    with patch.object(tools, "yfinance") as yf:
        yf.Ticker.return_value = _fake_ticker(income_stmt=income)
        out = tools._get_financials({"ticker": "X"})
    # prev revenue is 0 → growth guard (prev > 0) yields None, not a ZeroDivisionError
    assert out["revenue_growth_pct"][0] is None


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
    future = _iso(30)
    q1, q2 = _iso(-60), _iso(-150)
    records = [
        {"Earnings Date": future, "EPS Estimate": 1.5, "Reported EPS": None, "Surprise(%)": None},
        {"Earnings Date": q1, "EPS Estimate": 1.2, "Reported EPS": 1.3, "Surprise(%)": 8.3},
        {"Earnings Date": q2, "EPS Estimate": 1.0, "Reported EPS": 0.9, "Surprise(%)": -10.0},
    ]
    with patch.object(tools, "yfinance") as yf:
        yf.Ticker.return_value = _fake_ticker(earnings_dates=_frame(records=records))
        out = tools._get_earnings({"ticker": "MDB"})
    assert out["next_earnings_date"] == future
    assert out["recent_quarters"][0] == {
        "date": q1, "eps_estimate": 1.2, "eps_actual": 1.3, "surprise_pct": 8.3,
    }
    assert len(out["recent_quarters"]) == 2


def test_get_earnings_picks_earliest_future_date():
    # yfinance lists several future quarters newest-first; the next date is the
    # *earliest* future one, not the first (furthest-out) unreported row.
    far, near = _iso(120), _iso(20)
    records = [
        {"Earnings Date": far, "EPS Estimate": 1.6, "Reported EPS": None, "Surprise(%)": None},
        {"Earnings Date": near, "EPS Estimate": 1.5, "Reported EPS": None, "Surprise(%)": None},
        {"Earnings Date": _iso(-60), "EPS Estimate": 1.2, "Reported EPS": 1.3, "Surprise(%)": 8.3},
    ]
    with patch.object(tools, "yfinance") as yf:
        yf.Ticker.return_value = _fake_ticker(earnings_dates=_frame(records=records))
        out = tools._get_earnings({"ticker": "MDB"})
    assert out["next_earnings_date"] == near


def test_get_earnings_ignores_past_unreported_row():
    # A past quarter with a missing/NaN Reported EPS (common yfinance gap) must
    # NOT be reported as the next earnings date.
    records = [
        {"Earnings Date": _iso(-30), "EPS Estimate": 1.4, "Reported EPS": float("nan"), "Surprise(%)": None},
        {"Earnings Date": _iso(-120), "EPS Estimate": 1.2, "Reported EPS": 1.3, "Surprise(%)": 8.3},
    ]
    with patch.object(tools, "yfinance") as yf:
        yf.Ticker.return_value = _fake_ticker(earnings_dates=_frame(records=records))
        out = tools._get_earnings({"ticker": "MDB"})
    assert out["next_earnings_date"] is None
    assert len(out["recent_quarters"]) == 1


def test_num_handles_nan_and_bad_values():
    assert tools._num(float("nan")) is None
    assert tools._num(None) is None
    assert tools._num("not a number") is None
    assert tools._num("3.5") == 3.5
    assert tools._num(7) == 7.0


def test_observed_tool_coerces_non_dict_args(monkeypatch):
    # json.loads can yield a non-dict (e.g. "AAPL"); the observability guarantee
    # must still hold rather than raising outside the guard.
    logs, span = _spy(monkeypatch)
    run = tools._observed_tool("get_x", lambda args: {"ok": True})
    out = run("AAPL")  # non-dict
    assert out == {"ok": True}
    assert ("info", "tool.get_x.ok", {"ticker": None}) in logs
    span.add_event.assert_any_call("tool.get_x", {"outcome": "ok"})


def test_observed_tool_rejects_ticker_mismatch(monkeypatch):
    logs, span = _spy(monkeypatch)
    called = []
    run = tools._observed_tool("get_x", lambda args: called.append(args) or {"ok": True},
                               bound_ticker="AAPL")
    out = run({"ticker": "MSFT"})
    assert "error" in out and "MSFT" in out["error"]
    assert not called  # raw tool never invoked with the wrong company
    assert any(m == "tool.get_x.failed" for _, m, _ in logs)
    ev = span.add_event.call_args_list[-1]
    assert ev.args[0] == "tool.get_x" and ev.args[1]["outcome"] == "error"


def test_observed_tool_injects_bound_ticker(monkeypatch):
    _spy(monkeypatch)
    seen = {}
    run = tools._observed_tool("get_x", lambda args: seen.update(args) or {"ok": True},
                               bound_ticker="AAPL")
    # matching ticker (case-insensitive) is accepted and normalised to the bound one
    run({"ticker": "aapl"})
    assert seen["ticker"] == "AAPL"


def test_build_toolset_binds_ticker(monkeypatch):
    _spy(monkeypatch)
    with patch.object(tools, "yfinance") as yf:
        yf.Ticker.return_value = _fake_ticker(info={"foo": "bar"})
        _schemas, registry = tools.build_toolset("AAPL")
        # a mismatching model-supplied ticker is rejected before hitting yfinance
        out = registry["get_valuation"]({"ticker": "TSLA"})
    assert "error" in out and "TSLA" in out["error"]
    yf.Ticker.assert_not_called()


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


def test_build_toolset_chat_shape_nests_function():
    schemas, registry = tools.build_toolset(api="chat")
    for s in schemas:
        # chat.completions requires {"type":"function","function":{...}}
        assert s["type"] == "function"
        assert isinstance(s.get("function"), dict)
        assert set(s["function"].keys()) == {"name", "description", "parameters"}
        assert s["function"]["parameters"]["required"] == ["ticker"]
    names = {s["function"]["name"] for s in schemas}
    assert names == {"get_financials", "get_valuation", "get_earnings"}
    assert set(registry.keys()) == names


def test_build_toolset_anthropic_shape_uses_input_schema():
    schemas, registry = tools.build_toolset(api="anthropic")
    for s in schemas:
        # Anthropic custom tools: no `type`, JSON Schema under `input_schema`.
        assert "type" not in s
        assert set(s.keys()) == {"name", "description", "input_schema"}
        assert s["input_schema"]["required"] == ["ticker"]
        assert s["input_schema"]["properties"]["ticker"]["type"] == "string"
    names = {s["name"] for s in schemas}
    assert names == {"get_financials", "get_valuation", "get_earnings"}
    assert set(registry.keys()) == names
