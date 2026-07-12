"""Custom function tools the agentic thesis loop can call for precise, on-demand
structured data (yfinance-backed). Decoupled from agent_loop and llm. Every tool
is wrapped by _observed_tool so it can never crash the loop and every call is
visible in logs + on the current trace span."""
import yfinance
from opentelemetry import trace

from .observability import emit_log


def _observed_tool(name, fn):
    """Wrap a raw tool(args)->dict with uniform guarding + observability.
    Emits tool.<name>.ok / .failed logs and an outcome span event on every call.
    A raised exception OR a returned {'error': ...} counts as a failure; a tool
    can never crash the loop (a failure returns {'error': ...})."""
    def _run(args):
        args = args or {}
        ticker = args.get("ticker")
        span = trace.get_current_span()
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
    cols = list(data.keys())[:_FINANCIAL_YEARS]
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
        growth.append(round((cur - prev) / prev * 100, 1) if (prev and cur is not None) else None)
    return {
        "fiscal_years": fiscal_years,
        "revenue": revenue,
        "net_income": net_income,
        "gross_margin_pct": gross_margin,
        "operating_margin_pct": op_margin,
        "revenue_growth_pct": growth,
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


def _get_earnings(args):
    df = yfinance.Ticker(args.get("ticker")).earnings_dates
    if df is None or getattr(df, "empty", True):
        return {"error": "no earnings data"}
    records = df.reset_index().to_dict("records")
    next_date, recent = None, []
    for rec in records:
        actual = _num(rec.get("Reported EPS"))
        if actual is None:
            if next_date is None:
                next_date = _earnings_date(rec)
        elif len(recent) < _EARNINGS_QUARTERS:
            recent.append({
                "date": _earnings_date(rec),
                "eps_estimate": _num(rec.get("EPS Estimate")),
                "eps_actual": actual,
                "surprise_pct": _num(rec.get("Surprise(%)")),
            })
    if not recent and next_date is None:
        return {"error": "no earnings data"}
    return {"next_earnings_date": next_date, "recent_quarters": recent}


def _schema(name, description):
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": {"ticker": {"type": "string", "description": "US-listed ticker symbol"}},
            "required": ["ticker"],
        },
    }


_TOOLS = (
    ("get_financials", _get_financials,
     "Last 3 fiscal years of revenue, net income, gross/operating margins, and YoY revenue growth for a ticker."),
    ("get_valuation", _get_valuation,
     "Valuation multiples (trailing/forward P/E, P/S, EV/EBITDA, PEG, P/B) for a ticker."),
    ("get_earnings", _get_earnings,
     "Next scheduled earnings date and recent quarterly EPS estimate vs actual (surprise %) for a ticker."),
)


def build_toolset():
    """Return (schemas, registry) to drop into run_agent_loop: the Responses-API
    function-tool schemas and a name->callable registry of observed tools."""
    schemas = [_schema(name, desc) for name, _fn, desc in _TOOLS]
    registry = {name: _observed_tool(name, fn) for name, fn, _desc in _TOOLS}
    return schemas, registry
