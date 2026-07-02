from datetime import datetime, timezone
from pydantic import BaseModel
import yfinance

from opentelemetry import trace
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .observability import emit_log


class Snapshot(BaseModel):
    company_name: str | None = None
    sector: str | None = None
    industry: str | None = None
    close: float | None = None
    previous_close: float | None = None
    change_pct: float | None = None
    market_cap: int | None = None
    fifty_two_week_high: float | None = None
    fifty_two_week_low: float | None = None
    average_volume: int | None = None
    analyst_recommendation: str | None = None
    analyst_opinion_count: int | None = None
    business_summary: str | None = None
    currency: str
    as_of: str


def _now_iso_utc() -> str:
    # 'Z' suffix matches the rest of the codebase's ISO timestamp convention.
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _derive_change_pct(close: float | None, previous: float | None) -> float | None:
    if close is None or previous is None or previous == 0:
        return None
    return round((close - previous) / previous * 100, 2)


def _snapshot_from_info(info: dict) -> Snapshot:
    close = info.get("regularMarketPrice")
    previous = info.get("regularMarketPreviousClose")
    rec = info.get("recommendationKey")
    return Snapshot(
        company_name=info.get("longName"),
        sector=info.get("sector"),
        industry=info.get("industry"),
        close=close,
        previous_close=previous,
        change_pct=_derive_change_pct(close, previous),
        market_cap=info.get("marketCap"),
        fifty_two_week_high=info.get("fiftyTwoWeekHigh"),
        fifty_two_week_low=info.get("fiftyTwoWeekLow"),
        average_volume=info.get("averageVolume"),
        analyst_recommendation=rec.lower() if isinstance(rec, str) else None,
        analyst_opinion_count=info.get("numberOfAnalystOpinions"),
        business_summary=info.get("longBusinessSummary"),
        currency=info.get("currency") or "USD",
        as_of=_now_iso_utc(),
    )


def _backfill_from_history(ticker_obj) -> tuple[float | None, float | None]:
    """Return (close, previous_close) from the last two rows of a 5-day history frame.
    Returns (None, None) on empty history or any indexing failure."""
    try:
        h = ticker_obj.history(period="5d")
        if getattr(h, "empty", False):
            return (None, None)
        closes = h["Close"]
        # iloc[-1] is the latest, iloc[-2] is the previous session.
        close = float(closes.iloc[-1]) if closes.iloc[-1] is not None else None
        previous = float(closes.iloc[-2]) if closes.iloc[-2] is not None else None
        return (close, previous)
    except Exception:
        return (None, None)


def _annotate_span_success(span, ticker: str, snap: "Snapshot") -> None:
    span.set_attribute("snapshot.fetched", True)
    span.set_attribute("snapshot.ticker", ticker)
    if snap.close is not None:
        span.set_attribute("snapshot.close", snap.close)
    if snap.change_pct is not None:
        span.set_attribute("snapshot.change_pct", snap.change_pct)


def _annotate_span_failure(span, ticker: str) -> None:
    span.set_attribute("snapshot.fetched", False)
    span.set_attribute("snapshot.ticker", ticker)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def _fetch_snapshot_once(ticker: str) -> Snapshot | None:
    t = yfinance.Ticker(ticker)
    info = t.info or {}
    if not info:
        return None
    snap = _snapshot_from_info(info)
    if snap.close is None or snap.previous_close is None:
        close, previous = _backfill_from_history(t)
        if snap.close is None:
            snap = snap.model_copy(update={"close": close})
        if snap.previous_close is None:
            snap = snap.model_copy(update={"previous_close": previous})
        snap = snap.model_copy(update={"change_pct": _derive_change_pct(snap.close, snap.previous_close)})
    return snap


def fetch_snapshot(ticker: str) -> Snapshot | None:
    """Best-effort ticker snapshot. Never raises. Returns None on total failure."""
    span = trace.get_current_span()
    try:
        snap = _fetch_snapshot_once(ticker)
    except Exception as exc:
        _annotate_span_failure(span, ticker)
        emit_log(
            "warn",
            "snapshot.missing",
            ticker=ticker,
            reason="exception",
            exception_type=type(exc).__name__,
        )
        return None
    if snap is None:
        _annotate_span_failure(span, ticker)
        emit_log("warn", "snapshot.missing", ticker=ticker, reason="empty_info")
        return None
    _annotate_span_success(span, ticker, snap)
    return snap
