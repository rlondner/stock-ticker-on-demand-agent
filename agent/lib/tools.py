"""Custom function tools the agentic thesis loop can call for precise, on-demand
structured data (yfinance-backed). Decoupled from agent_loop and llm. Every tool
is wrapped by _observed_tool so it can never crash the loop and every call is
visible in logs + on the current trace span."""
import datetime

import yfinance
from opentelemetry import trace

from .observability import emit_log


def _observed_tool(name, fn, bound_ticker=None):
    """Wrap a raw tool(args)->dict with uniform guarding + observability.
    Emits tool.<name>.ok / .failed logs and an outcome span event on every call.
    A raised exception OR a returned {'error': ...} counts as a failure; a tool
    can never crash the loop (a failure returns {'error': ...}).

    When ``bound_ticker`` is set the tool is pinned to the company under
    analysis: a mismatching model-supplied ticker is rejected (so a hallucinated
    symbol can't pull another company's numbers into the thesis), and the bound
    ticker is otherwise injected."""
    def _run(args):
        # The model controls the JSON in function_call.arguments; json.loads can
        # yield a non-dict. Coerce BEFORE any .get so the observability guarantee
        # below (failed log + span event) always holds.
        args = args if isinstance(args, dict) else {}
        span = trace.get_current_span()
        if bound_ticker is not None:
            supplied = args.get("ticker")
            if supplied and str(supplied).strip().upper() != bound_ticker.upper():
                reason = (f"ticker {supplied!r} does not match the analyzed "
                          f"ticker {bound_ticker!r}")
                emit_log("warn", f"tool.{name}.failed", ticker=bound_ticker, reason=reason)
                span.add_event(f"tool.{name}", {"outcome": "error", "error": reason})
                return {"error": reason}
            args = {**args, "ticker": bound_ticker}
        ticker = args.get("ticker")
        try:
            result = fn(args)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            emit_log("warn", f"tool.{name}.failed", ticker=ticker, reason=reason)
            span.add_event(f"tool.{name}", {"outcome": "error", "error": reason})
            return {"error": reason}
        if isinstance(result, dict) and "error" in result:
            emit_log("warn", f"tool.{name}.failed", ticker=ticker, reason=str(result["error"]))
            span.add_event(f"tool.{name}", {"outcome": "error", "error": str(result["error"])})
            return result
        emit_log("info", f"tool.{name}.ok", ticker=ticker)
        span.add_event(f"tool.{name}", {"outcome": "ok"})
        return result

    return _run


_FINANCIAL_YEARS = 3
_EARNINGS_QUARTERS = 4


def _num(v):
    """Coerce to float, or None if missing/NaN."""
    try:
        f = float(v)
        return None if f != f else f  # NaN
    except (TypeError, ValueError):
        return None


def _get_financials(args):
    df = yfinance.Ticker(args.get("ticker")).income_stmt
    if df is None or getattr(df, "empty", True):
        return {"error": "no financials"}
    data = df.to_dict()  # {period: {line_item: value}}
    # Keep one extra (oldest) year so the oldest *emitted* year still gets a YoY
    # growth figure; the extra year is trimmed off the emitted lists below.
    cols = list(data.keys())[:_FINANCIAL_YEARS + 1]
    if not cols:
        return {"error": "no financials"}
    fiscal_years, revenue, net_income, gross_margin, op_margin = [], [], [], [], []
    for col in cols:
        row = data[col]
        rev = _num(row.get("Total Revenue"))
        gp = _num(row.get("Gross Profit"))
        oi = _num(row.get("Operating Income"))
        fiscal_years.append(str(col)[:4])
        revenue.append(rev)
        net_income.append(_num(row.get("Net Income")))
        gross_margin.append(round(gp / rev * 100, 1) if rev and gp is not None else None)
        op_margin.append(round(oi / rev * 100, 1) if rev and oi is not None else None)
    growth = []
    for i in range(len(revenue)):
        prev = revenue[i + 1] if i + 1 < len(revenue) else None
        cur = revenue[i]
        growth.append(round((cur - prev) / prev * 100, 1) if (prev is not None and prev > 0 and cur is not None) else None)
    # Trim the extra prior year used only to seed the oldest growth figure.
    n = _FINANCIAL_YEARS
    return {
        "fiscal_years": fiscal_years[:n],
        "revenue": revenue[:n],
        "net_income": net_income[:n],
        "gross_margin_pct": gross_margin[:n],
        "operating_margin_pct": op_margin[:n],
        "revenue_growth_pct": growth[:n],
    }


def _get_valuation(args):
    info = yfinance.Ticker(args.get("ticker")).info or {}
    if not info:
        return {"error": "no valuation data"}
    out = {
        "trailing_pe": _num(info.get("trailingPE")),
        "forward_pe": _num(info.get("forwardPE")),
        "price_to_sales": _num(info.get("priceToSalesTrailing12Months")),
        "ev_to_ebitda": _num(info.get("enterpriseToEbitda")),
        "peg_ratio": _num(info.get("trailingPegRatio")) if info.get("trailingPegRatio") is not None else _num(info.get("pegRatio")),
        "price_to_book": _num(info.get("priceToBook")),
    }
    if all(v is None for v in out.values()):
        return {"error": "no valuation data"}
    return out


def _earnings_date(rec):
    for k in ("Earnings Date", "index", "Date"):
        if k in rec:
            return str(rec[k])[:10]
    return None


def _parse_date(date_str):
    """Parse an ISO 'YYYY-MM-DD' prefix to a date, or None if unparseable."""
    try:
        return datetime.date.fromisoformat(date_str[:10])
    except (TypeError, ValueError):
        return None


def _get_earnings(args):
    df = yfinance.Ticker(args.get("ticker")).earnings_dates
    if df is None or getattr(df, "empty", True):
        return {"error": "no earnings data"}
    records = df.reset_index().to_dict("records")
    today = datetime.date.today()
    next_date, recent = None, []
    for rec in records:
        date_str = _earnings_date(rec)
        actual = _num(rec.get("Reported EPS"))
        if actual is None:
            # An unreported row is only the *next* earnings date if it is
            # strictly in the future. yfinance lists several future quarters
            # (newest-first) and leaves past quarters' EPS NaN when a report is
            # missing, so pick the earliest genuinely-future date, not the first
            # unreported row (which is the furthest-out or even a past gap).
            d = _parse_date(date_str)
            if d is not None and d > today and (next_date is None or date_str < next_date):
                next_date = date_str
        elif len(recent) < _EARNINGS_QUARTERS:
            recent.append({
                "date": date_str,
                "eps_estimate": _num(rec.get("EPS Estimate")),
                "eps_actual": actual,
                "surprise_pct": _num(rec.get("Surprise(%)")),
            })
    if not recent and next_date is None:
        return {"error": "no earnings data"}
    return {"next_earnings_date": next_date, "recent_quarters": recent}


def _schema(name, description, api="responses"):
    """Build a function-tool schema for the target API. The Responses API takes
    a flat shape ({type, name, description, parameters}); chat.completions
    nests the function under a `function` key."""
    parameters = {
        "type": "object",
        "properties": {"ticker": {"type": "string", "description": "US-listed ticker symbol"}},
        "required": ["ticker"],
    }
    if api == "chat":
        return {"type": "function", "function": {
            "name": name, "description": description, "parameters": parameters,
        }}
    return {"type": "function", "name": name, "description": description, "parameters": parameters}


_TOOLS = (
    ("get_financials", _get_financials,
     "Last 3 fiscal years of revenue, net income, gross/operating margins, and YoY revenue growth for a ticker."),
    ("get_valuation", _get_valuation,
     "Valuation multiples (trailing/forward P/E, P/S, EV/EBITDA, PEG, P/B) for a ticker."),
    ("get_earnings", _get_earnings,
     "Next scheduled earnings date and recent quarterly EPS estimate vs actual (surprise %) for a ticker."),
)


def build_toolset(ticker=None, api="responses"):
    """Return (schemas, registry) to drop into the agent loop: function-tool
    schemas shaped for the target API (``"responses"`` or ``"chat"``) and a
    name->callable registry of observed tools (API-agnostic).

    Pass ``ticker`` (the company under analysis) to pin every tool to it so a
    model-supplied mismatching/hallucinated symbol is rejected instead of
    returning another company's data."""
    schemas = [_schema(name, desc, api=api) for name, _fn, desc in _TOOLS]
    registry = {name: _observed_tool(name, fn, ticker) for name, fn, _desc in _TOOLS}
    return schemas, registry
