# Agent stock-data enrichment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The agent pre-fetches real stock facts (company name, close, previous close, %-change, market cap, 52w range, sector/industry, analyst consensus, business summary) via `yfinance` before calling the LLM. Facts are injected into the LLM's user message as ground truth, persisted with the job in `jobs.result.snapshot`, and consumed by the Done page's `StockHeader` — no more hardcoded `$342.15 / -1.24%`.

**Architecture:**
`agent/lib/finance.py` (new) does a best-effort yfinance fetch and returns a `Snapshot` pydantic model or `None`. `agent/lib/prompts.py` is rewritten to drop the web-search premise and to accept a snapshot argument. `agent/lib/llm.py::run_analysis` calls `fetch_snapshot`, threads it through the prompt, and merges it into the persisted result. The Next.js side adds a matching `Snapshot` TS type, small `format-price` helpers, and re-wires `StockHeader` to read `job.result.snapshot`. No DB migration (`jobs.result` is already `jsonb`).

**Tech Stack:** Python 3.12 + pydantic + tenacity + yfinance (new). Next.js 16 + React 19 + vitest (node env). Postgres/Neon (no migration).

**Related spec:** [docs/superpowers/specs/2026-07-02-agent-stock-data-design.md](../specs/2026-07-02-agent-stock-data-design.md)

---

## Prerequisites

Before starting Task 1:

- Working tree is clean or only holds the current UX-refactor changes.
- Python venv at `agent/.venv` is activated (see `agent/README` or existing agent conventions).
- Node deps are installed (`npm install`).
- `agent/tests/` currently green: `cd agent && pytest -q` passes.
- `npm test` currently green.
- Dev server runs cleanly at `http://localhost:3000`.

If any of the above fails, fix that before touching this plan.

---

## Task 1: Add yfinance dependency + define the Snapshot model

**Files:**
- Modify: `agent/requirements.txt`
- Create: `agent/lib/finance.py`
- Create: `agent/tests/test_finance.py`

- [ ] **Step 1: Add yfinance to requirements**

Edit `agent/requirements.txt` — append after `httpx>=0.27.0` line:

```
yfinance>=0.2.40
```

- [ ] **Step 2: Install the new dep**

Run (inside the agent venv):

```
cd agent && pip install -r requirements.txt
```

Expected: `yfinance-0.2.4x` installed along with transitive `pandas`, `numpy`, `beautifulsoup4`, `requests`, `lxml`.

- [ ] **Step 3: Write the failing test for the Snapshot model**

Create `agent/tests/test_finance.py`:

```python
from datetime import datetime
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
```

- [ ] **Step 4: Run the test to verify it fails**

Run:

```
cd agent && pytest tests/test_finance.py -v
```

Expected: `ModuleNotFoundError: No module named 'lib.finance'`.

- [ ] **Step 5: Create the Snapshot model (module exists but no fetcher yet)**

Create `agent/lib/finance.py`:

```python
from pydantic import BaseModel


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
```

- [ ] **Step 6: Run the test to verify it passes**

Run:

```
cd agent && pytest tests/test_finance.py -v
```

Expected: 2 passed.

- [ ] **Step 7: Commit**

```
git add agent/requirements.txt agent/lib/finance.py agent/tests/test_finance.py
git commit -m "feat(agent): add yfinance dep + Snapshot pydantic model"
```

---

## Task 2: fetch_snapshot happy path (yfinance.info populated)

**Files:**
- Modify: `agent/lib/finance.py`
- Modify: `agent/tests/test_finance.py`

- [ ] **Step 1: Write the failing test**

Append to `agent/tests/test_finance.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```
cd agent && pytest tests/test_finance.py::test_fetch_snapshot_happy_path_from_info -v
```

Expected: `AttributeError: module 'lib.finance' has no attribute 'fetch_snapshot'`.

- [ ] **Step 3: Implement the happy path**

Replace the contents of `agent/lib/finance.py` with:

```python
from datetime import datetime, timezone
from pydantic import BaseModel
import yfinance


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


def fetch_snapshot(ticker: str) -> Snapshot | None:
    t = yfinance.Ticker(ticker)
    info = t.info or {}
    if not info:
        return None
    return _snapshot_from_info(info)
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```
cd agent && pytest tests/test_finance.py -v
```

Expected: 3 passed (the 2 model tests + the new happy-path test).

- [ ] **Step 5: Commit**

```
git add agent/lib/finance.py agent/tests/test_finance.py
git commit -m "feat(agent): fetch_snapshot happy path (yfinance info)"
```

---

## Task 3: fetch_snapshot — history fallback + partial data

**Files:**
- Modify: `agent/lib/finance.py`
- Modify: `agent/tests/test_finance.py`

The `regularMarketPrice` field is sometimes absent (delayed feed, illiquid names, weekends). Fall back to the last two rows of `.history(period="5d")` for close + previous_close.

- [ ] **Step 1: Write the failing test**

Append to `agent/tests/test_finance.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```
cd agent && pytest tests/test_finance.py -v
```

Expected: the two new tests fail (history is not consulted; close/previous stay `None`).

- [ ] **Step 3: Add the history fallback**

In `agent/lib/finance.py`, replace `fetch_snapshot` and add a helper:

```python
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


def fetch_snapshot(ticker: str) -> Snapshot | None:
    t = yfinance.Ticker(ticker)
    info = t.info or {}
    if not info:
        return None
    snap = _snapshot_from_info(info)
    if snap.close is None or snap.previous_close is None:
        close, previous = _backfill_from_history(t)
        # Only overwrite fields that are still missing; don't clobber values from info.
        if snap.close is None:
            snap = snap.model_copy(update={"close": close})
        if snap.previous_close is None:
            snap = snap.model_copy(update={"previous_close": previous})
        snap = snap.model_copy(update={"change_pct": _derive_change_pct(snap.close, snap.previous_close)})
    return snap
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```
cd agent && pytest tests/test_finance.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```
git add agent/lib/finance.py agent/tests/test_finance.py
git commit -m "feat(agent): fetch_snapshot history fallback + partial-data handling"
```

---

## Task 4: fetch_snapshot — retry + None on failure + observability

**Files:**
- Modify: `agent/lib/finance.py`
- Modify: `agent/tests/test_finance.py`

- [ ] **Step 1: Write the failing tests**

Append to `agent/tests/test_finance.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```
cd agent && pytest tests/test_finance.py -v
```

Expected: three failing tests (no retry, no logging, no span attrs yet).

- [ ] **Step 3: Add retry + logging + span attribution**

Replace `fetch_snapshot` in `agent/lib/finance.py` with the wrapped version, and add the required imports at the top:

```python
import logging
from opentelemetry import trace
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)


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
        logger.warning(
            "snapshot.missing ticker=%s reason=exception type=%s",
            ticker, type(exc).__name__,
        )
        return None
    if snap is None:
        _annotate_span_failure(span, ticker)
        logger.warning("snapshot.missing ticker=%s reason=empty_info", ticker)
        return None
    _annotate_span_success(span, ticker, snap)
    return snap
```

Remove the old inline `fetch_snapshot` — the new one wraps `_fetch_snapshot_once`.

- [ ] **Step 4: Run the full finance test suite**

Run:

```
cd agent && pytest tests/test_finance.py -v
```

Expected: 9 passed (2 model + 1 happy + 2 partial/history + 4 retry/failure/span).

- [ ] **Step 5: Commit**

```
git add agent/lib/finance.py agent/tests/test_finance.py
git commit -m "feat(agent): fetch_snapshot retry + null-on-failure + span attrs"
```

---

## Task 5: Rewrite prompts.py

**Files:**
- Modify: `agent/lib/prompts.py`
- Create: `agent/tests/test_prompts.py`

- [ ] **Step 1: Write the failing tests**

Create `agent/tests/test_prompts.py`:

```python
from lib.finance import Snapshot
from lib.prompts import SYSTEM_PROMPT, user_prompt


def _snap(**overrides) -> Snapshot:
    base = dict(
        company_name="MongoDB, Inc.",
        sector="Technology",
        industry="Software—Infrastructure",
        close=342.15,
        previous_close=346.44,
        change_pct=-1.24,
        market_cap=28_100_000_000,
        fifty_two_week_high=410.05,
        fifty_two_week_low=210.00,
        average_volume=1_800_000,
        analyst_recommendation="buy",
        analyst_opinion_count=34,
        business_summary="MongoDB, Inc. develops a document-based, distributed database.",
        currency="USD",
        as_of="2026-07-02T12:00:00Z",
    )
    base.update(overrides)
    return Snapshot(**base)


def test_system_prompt_does_not_mention_web_search():
    assert "web_search" not in SYSTEM_PROMPT
    assert "web search" not in SYSTEM_PROMPT.lower()


def test_system_prompt_allows_null_sources():
    # LLM should know it can leave source as null when it can't cite one.
    assert "null" in SYSTEM_PROMPT


def test_user_prompt_with_full_snapshot_includes_key_facts():
    p = user_prompt("MDB", snapshot=_snap())
    assert "MDB" in p
    assert "MongoDB, Inc." in p
    assert "Technology" in p
    assert "342.15" in p
    assert "-1.24%" in p
    # Business summary is present but truncated if long.
    assert "distributed database" in p


def test_user_prompt_truncates_long_business_summary():
    long_summary = "MongoDB " + ("x" * 2000)
    p = user_prompt("MDB", snapshot=_snap(business_summary=long_summary))
    # Truncation ceiling: ~800 chars of business summary in the prompt.
    assert len(p) < 4000
    assert long_summary not in p  # full text was cut


def test_user_prompt_without_snapshot_uses_fallback():
    p = user_prompt("MDB", snapshot=None)
    assert "MDB" in p
    # No prices/company names invented into the fallback.
    assert "342.15" not in p
    assert "MongoDB" not in p
    # Signal the model that data is missing.
    assert "unavailable" in p.lower() or "no live facts" in p.lower()


def test_user_prompt_ends_with_json_only_instruction():
    p_with = user_prompt("MDB", snapshot=_snap())
    p_without = user_prompt("MDB", snapshot=None)
    assert p_with.strip().endswith("Output JSON only.")
    assert p_without.strip().endswith("Output JSON only.")


def test_user_prompt_skips_none_fields():
    # sector missing → no "Sector:" line at all (not "Sector: None").
    snap = _snap(sector=None, market_cap=None)
    p = user_prompt("MDB", snapshot=snap)
    assert "Sector:" not in p
    assert "None" not in p
    assert "Market cap" not in p
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```
cd agent && pytest tests/test_prompts.py -v
```

Expected: multiple failures — old prompt mentions web_search, `user_prompt` takes no snapshot arg.

- [ ] **Step 3: Rewrite prompts.py**

Replace `agent/lib/prompts.py` with:

```python
from lib.finance import Snapshot


SYSTEM_PROMPT = """\
You are a financial analysis assistant. You will receive a single
US-listed stock ticker and a compact set of facts about the company.
Use those facts as ground truth: do not invent prices, company names,
market caps, or other numbers.

Output ONLY a JSON object matching this schema:

{
  "recommendation": "buy" | "hold" | "sell",
  "summary": "<2-3 sentence plain-English take that references the company name and, if available, the price move>",
  "signals": [
    {"label": "<short label>", "evidence": "<one sentence>", "source": "<URL or null>"}
  ]
}

Provide 3 to 5 signals. Set "source" to null when you cannot cite a
specific URL (you do not have web access). Do not include markdown,
commentary, or preamble around the JSON. This is not financial advice
and the output will be shown to the user with a demo disclaimer.
"""


_BUSINESS_SUMMARY_MAX = 800


def _format_facts(snapshot: Snapshot) -> str:
    """Format only the fields that are present. Skip Nones entirely."""
    lines: list[str] = []
    if snapshot.company_name:
        lines.append(f"- Company: {snapshot.company_name}")
    if snapshot.sector or snapshot.industry:
        parts = [x for x in (snapshot.sector, snapshot.industry) if x]
        lines.append(f"- Sector: {' / '.join(parts)}")
    if snapshot.close is not None:
        pct_bit = f" ({snapshot.change_pct:+.2f}% vs previous close ${snapshot.previous_close:.2f})" \
            if snapshot.change_pct is not None and snapshot.previous_close is not None else ""
        lines.append(f"- Close: ${snapshot.close:.2f}{pct_bit}")
    if snapshot.market_cap is not None:
        lines.append(f"- Market cap: ${snapshot.market_cap:,}")
    if snapshot.fifty_two_week_high is not None and snapshot.fifty_two_week_low is not None:
        lines.append(
            f"- 52-week range: ${snapshot.fifty_two_week_low:.2f} – ${snapshot.fifty_two_week_high:.2f}"
        )
    if snapshot.average_volume is not None:
        lines.append(f"- Average volume: {snapshot.average_volume:,}")
    if snapshot.analyst_recommendation:
        n = snapshot.analyst_opinion_count
        n_bit = f" ({n} analysts)" if n else ""
        lines.append(f"- Analyst consensus: {snapshot.analyst_recommendation}{n_bit}")
    if snapshot.business_summary:
        summary = snapshot.business_summary[:_BUSINESS_SUMMARY_MAX]
        if len(snapshot.business_summary) > _BUSINESS_SUMMARY_MAX:
            summary = summary.rstrip() + "…"
        lines.append(f"- Business summary: {summary}")
    return "\n".join(lines)


def user_prompt(ticker: str, snapshot: Snapshot | None = None) -> str:
    if snapshot is None:
        return (
            f"Ticker: {ticker}\n"
            "(No live facts available for this ticker. Base your take on general\n"
            " knowledge and be explicit that some data is unavailable.)\n"
            "Task: Output JSON only."
        )
    return (
        f"Ticker: {ticker}\n"
        f"Facts:\n{_format_facts(snapshot)}\n"
        "Task: Output JSON only."
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```
cd agent && pytest tests/test_prompts.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```
git add agent/lib/prompts.py agent/tests/test_prompts.py
git commit -m "feat(agent): rewrite prompts to inject snapshot facts, drop web_search"
```

---

## Task 6: Thread snapshot through llm.py and agent flow

**Files:**
- Modify: `agent/lib/llm.py`
- Modify: `agent/tests/test_agent.py`

Now that `user_prompt` takes a snapshot, `OpenAIClient.analyze` must accept and pass it, and `run_analysis` must call `fetch_snapshot` first and merge the result.

- [ ] **Step 1: Write the failing tests**

Append to `agent/tests/test_agent.py`:

```python
from lib.finance import Snapshot


def _fake_snapshot() -> Snapshot:
    return Snapshot(
        company_name="MongoDB, Inc.",
        close=342.15,
        previous_close=346.44,
        change_pct=-1.24,
        currency="USD",
        as_of="2026-07-02T12:00:00Z",
    )


def test_main_persists_snapshot_when_fetch_succeeds(neon_url, fresh_job, monkeypatch):
    monkeypatch.setenv("JOB_ID", fresh_job)
    monkeypatch.setenv("NEON_DATABASE_URL", neon_url)

    with patch("lib.llm.OpenAIClient.analyze", return_value=FAKE_ANALYSIS), \
         patch("lib.llm.fetch_snapshot", return_value=_fake_snapshot()), \
         patch("lib.self_delete.self_delete"):
        import importlib
        import agent
        importlib.reload(agent)
        agent.main()

    with psycopg.connect(neon_url) as conn:
        row = conn.execute(
            "SELECT status, result FROM jobs WHERE id=%s", (fresh_job,)
        ).fetchone()
    assert row[0] == "complete"
    assert row[1]["summary"] == "strong"
    assert row[1]["snapshot"]["company_name"] == "MongoDB, Inc."
    assert row[1]["snapshot"]["close"] == 342.15
    assert row[1]["snapshot"]["change_pct"] == -1.24


def test_main_persists_none_snapshot_when_fetch_fails(neon_url, fresh_job, monkeypatch):
    """Best-effort: LLM still runs, result.snapshot is None, job completes."""
    monkeypatch.setenv("JOB_ID", fresh_job)
    monkeypatch.setenv("NEON_DATABASE_URL", neon_url)

    with patch("lib.llm.OpenAIClient.analyze", return_value=FAKE_ANALYSIS), \
         patch("lib.llm.fetch_snapshot", return_value=None), \
         patch("lib.self_delete.self_delete"):
        import importlib
        import agent
        importlib.reload(agent)
        agent.main()

    with psycopg.connect(neon_url) as conn:
        row = conn.execute(
            "SELECT status, result FROM jobs WHERE id=%s", (fresh_job,)
        ).fetchone()
    assert row[0] == "complete"
    assert row[1]["snapshot"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```
cd agent && pytest tests/test_agent.py::test_main_persists_snapshot_when_fetch_succeeds tests/test_agent.py::test_main_persists_none_snapshot_when_fetch_fails -v
```

Expected: `AttributeError: module 'lib.llm' has no attribute 'fetch_snapshot'` (the patch target doesn't exist yet).

- [ ] **Step 3: Update llm.py to fetch + inject + merge**

Edit `agent/lib/llm.py`:

1. Add the import near the other `.prompts` / `.observability` imports:

```python
from .finance import Snapshot, fetch_snapshot
```

2. Change the `OpenAIClient.analyze` signature and its `messages` construction. Find the method and replace the signature + the two lines that build `messages`. The method should look like:

```python
    def analyze(self, ticker: str, snapshot: Snapshot | None = None) -> Analysis:
        tracer = trace.get_tracer("stock-agent")
        with tracer.start_as_current_span("llm.analyze") as span:
            span.set_attribute("host", get_host())
            span.set_attribute("model", self._model)
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt(ticker, snapshot=snapshot)},
            ]
            request_started_at = time.perf_counter()
```

(The rest of the method body is unchanged.)

3. Replace `run_analysis` at the bottom of the file with:

```python
def run_analysis(ticker: str) -> dict:
    snapshot = fetch_snapshot(ticker)
    client: LLMClient = OpenAIClient()
    analysis = client.analyze(ticker, snapshot=snapshot)
    return {
        **analysis.model_dump(),
        "snapshot": snapshot.model_dump() if snapshot else None,
    }
```

- [ ] **Step 4: Run the two new tests to verify they pass**

Run:

```
cd agent && pytest tests/test_agent.py -v
```

Expected: 5 passed (the 3 existing tests + the 2 new snapshot tests).

- [ ] **Step 5: Run the full agent test suite as a regression check**

Run:

```
cd agent && pytest -q
```

Expected: all tests pass. If `test_main_writes_failed_on_llm_error` regresses, it's because `fetch_snapshot` is now called before the LLM — patch it in that test too:

```python
    with patch("lib.llm.OpenAIClient.analyze", side_effect=RuntimeError("LLM blew up")), \
         patch("lib.llm.fetch_snapshot", return_value=None), \
         patch("lib.self_delete.self_delete"):
```

Re-run and confirm green.

- [ ] **Step 6: Commit**

```
git add agent/lib/llm.py agent/tests/test_agent.py
git commit -m "feat(agent): thread snapshot through OpenAIClient.analyze + run_analysis"
```

---

## Task 7: Add Snapshot TS type

**Files:**
- Modify: `lib/job/types.ts`

- [ ] **Step 1: Update the type file**

Replace `lib/job/types.ts` with:

```typescript
import type { JobStatus } from "@/lib/ui/status-pill";
import type { Recommendation } from "@/lib/ui/signal-pill";
import type { RawSignal } from "@/lib/job/map-insights";

export type Snapshot = {
  company_name: string | null;
  sector: string | null;
  industry: string | null;
  close: number | null;
  previous_close: number | null;
  change_pct: number | null;
  market_cap: number | null;
  fifty_two_week_high: number | null;
  fifty_two_week_low: number | null;
  average_volume: number | null;
  // yfinance returns lowercased strings like "buy", "hold", "sell",
  // "strong_buy", "strong_sell", "underperform", "outperform". Kept as
  // `string | null` so we don't churn this union when Yahoo adds a bucket.
  analyst_recommendation: string | null;
  analyst_opinion_count: number | null;
  business_summary: string | null;
  currency: string;
  as_of: string;
};

export type SerializedJob = {
  id: string;
  ticker: string;
  status: JobStatus;
  recommendation: Recommendation | null;
  result: {
    summary?: string;
    signals?: RawSignal[];
    snapshot?: Snapshot | null;
  } | null;
  error: string | null;
  sandboxId: string | null;
  createdAt: string; // ISO
  startedAt: string | null; // ISO
  completedAt: string | null; // ISO
};
```

- [ ] **Step 2: Verify the TypeScript compiler**

Run:

```
npx tsc --noEmit
```

Expected: no errors. If `noUnusedLocals` warns about `Snapshot` being unused elsewhere yet, that's fine — Tasks 8–10 consume it.

- [ ] **Step 3: Commit**

```
git add lib/job/types.ts
git commit -m "feat(ui): add Snapshot type to SerializedJob result"
```

---

## Task 8: Add format-price helpers + tests

**Files:**
- Create: `lib/ui/format-price.ts`
- Create: `tests/components/format-price.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `tests/components/format-price.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { formatPrice, formatChangePct } from "@/lib/ui/format-price";

describe("formatPrice", () => {
  it("formats a positive USD number with symbol + 2 decimals", () => {
    expect(formatPrice(342.15, "USD")).toBe("$342.15");
  });

  it("formats zero", () => {
    expect(formatPrice(0, "USD")).toBe("$0.00");
  });

  it("respects the currency argument", () => {
    // Intl.NumberFormat in Node outputs "€1,234.50" for EUR/en-US.
    expect(formatPrice(1234.5, "EUR")).toMatch(/€\s?1,234\.50/);
  });

  it("returns em-dash for null", () => {
    expect(formatPrice(null, "USD")).toBe("—");
  });
});

describe("formatChangePct", () => {
  it("formats a positive change with plus sign and up tone", () => {
    expect(formatChangePct(2.4)).toEqual({ text: "+2.40%", tone: "up" });
  });

  it("formats a negative change with sign preserved and down tone", () => {
    expect(formatChangePct(-1.24)).toEqual({ text: "-1.24%", tone: "down" });
  });

  it("treats zero as up (neutral or up, not down)", () => {
    expect(formatChangePct(0)).toEqual({ text: "+0.00%", tone: "up" });
  });

  it("returns em-dash + neutral for null", () => {
    expect(formatChangePct(null)).toEqual({ text: "—", tone: "neutral" });
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```
npm test -- tests/components/format-price.test.ts
```

Expected: `Cannot find module '@/lib/ui/format-price'`.

- [ ] **Step 3: Implement the helpers**

Create `lib/ui/format-price.ts`:

```typescript
export function formatPrice(n: number | null, currency: string): string {
  if (n === null) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
  }).format(n);
}

export type ChangeTone = "up" | "down" | "neutral";

export function formatChangePct(
  n: number | null,
): { text: string; tone: ChangeTone } {
  if (n === null) return { text: "—", tone: "neutral" };
  const sign = n >= 0 ? "+" : "";
  const text = `${sign}${n.toFixed(2)}%`;
  const tone: ChangeTone = n < 0 ? "down" : "up";
  return { text, tone };
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```
npm test -- tests/components/format-price.test.ts
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```
git add lib/ui/format-price.ts tests/components/format-price.test.ts
git commit -m "feat(ui): add formatPrice + formatChangePct helpers"
```

---

## Task 9: Thread snapshot through the job page + JobLivePoller

**Files:**
- Modify: `app/(app)/jobs/[id]/page.tsx`
- Modify: `components/job/job-live-poller.tsx`

- [ ] **Step 1: Read the current job page**

Open `app/(app)/jobs/[id]/page.tsx`. The `SerializedJob` construction already spreads `row.result`, so `result.snapshot` will flow through automatically once the DB has the field. No changes needed to the page itself — verify by re-reading.

Confirm: `result: (row.result as SerializedJob["result"]) ?? null` already covers the new `snapshot` sub-field via the widened type from Task 7.

- [ ] **Step 2: Update JobLivePoller to forward snapshot to StockHeader**

Edit `components/job/job-live-poller.tsx`. Find the `<StockHeader ... />` call and add a `snapshot` prop:

```tsx
      <StockHeader
        ticker={job.ticker}
        status={job.status}
        recommendation={job.recommendation}
        summary={job.result?.summary ?? null}
        snapshot={job.result?.snapshot ?? null}
      />
```

The rest of `JobLivePoller` is unchanged. `SerializedJob` from Task 7 already includes `result.snapshot`, so `job.result?.snapshot ?? null` type-checks.

- [ ] **Step 3: Verify TypeScript still compiles**

Run:

```
npx tsc --noEmit
```

Expected: **one** error at the `<StockHeader />` call site — `snapshot` is not a known prop yet. That's expected; Task 10 fixes it.

- [ ] **Step 4: DO NOT commit yet**

Task 10's StockHeader change makes this compile. Chain the commit at the end of Task 10.

---

## Task 10: Rewrite StockHeader to consume the snapshot

**Files:**
- Modify: `components/job/stock-header.tsx`

This removes the Spec-D10 hardcoded `$342.15 / -1.24%` and the ticker-echoed H3, replacing them with snapshot-driven fields.

- [ ] **Step 1: Rewrite the component**

Replace `components/job/stock-header.tsx` with:

```tsx
import { StatusPill } from "@/components/ui/status-pill";
import { SignalPill } from "@/components/ui/signal-pill";
import type { JobStatus } from "@/lib/ui/status-pill";
import type { Recommendation } from "@/lib/ui/signal-pill";
import type { Snapshot } from "@/lib/job/types";
import { formatPrice, formatChangePct } from "@/lib/ui/format-price";

type Props = {
  ticker: string;
  status: JobStatus;
  recommendation: Recommendation | null;
  summary: string | null;
  snapshot: Snapshot | null;
};

const TONE_CLASS = {
  up: "text-af-secondary",
  down: "text-af-error",
  neutral: "text-af-on-surface-variant",
} as const;

export function StockHeader({ ticker, status, recommendation, summary, snapshot }: Props) {
  const displayName = snapshot?.company_name ?? ticker;
  const currency = snapshot?.currency ?? "USD";
  const priceText = formatPrice(snapshot?.close ?? null, currency);
  const change = formatChangePct(snapshot?.change_pct ?? null);

  return (
    <section className="flex flex-col md:flex-row md:items-end justify-between gap-6 bg-af-surface-container-lowest p-8 rounded-xl border border-af-outline-variant">
      <div className="space-y-2">
        <div className="flex items-center gap-4">
          <h2 className="text-5xl font-bold text-af-on-surface tracking-tight">{ticker}</h2>
          <StatusPill status={status} />
          <SignalPill recommendation={recommendation} />
        </div>
        <div>
          <h3 className="text-2xl font-semibold text-af-on-surface">{displayName}</h3>
          {summary && (
            <p className="text-af-on-surface-variant text-base max-w-2xl mt-4">{summary}</p>
          )}
        </div>
      </div>
      <div className="flex flex-col items-end gap-2">
        <div className="text-right">
          <p className="text-[12px] text-af-on-surface-variant uppercase tracking-wider">Current Price</p>
          <p className="text-3xl font-semibold text-af-on-surface">
            {priceText}{" "}
            <span className={`text-sm font-medium ${TONE_CLASS[change.tone]}`}>{change.text}</span>
          </p>
        </div>
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run:

```
npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Run the full JS test suite as a regression check**

Run:

```
npm test
```

Expected: all tests pass (the only new tests are `format-price.test.ts` from Task 8; the pre-existing component tests are unaffected).

- [ ] **Step 4: Commit (bundle Tasks 9 + 10 together)**

```
git add components/job/job-live-poller.tsx components/job/stock-header.tsx
git commit -m "feat(ui): wire StockHeader to job.result.snapshot (company name + price)"
```

---

## Task 11: End-to-end sanity check against a live ticker

**Files:** none (manual verification).

- [ ] **Step 1: Confirm dev server + env**

Ensure the Next.js dev server is running at `http://localhost:3000` and the local agent runtime (see `agent/analyze.py` conventions) is wired up so that submitting a ticker from `/analyze` actually runs the agent end-to-end.

- [ ] **Step 2: Submit a real ticker**

Visit `http://localhost:3000/analyze`. Pick `AAPL` from Suggested Tickers, leave Quick Scan selected, click Launch AI Agent. Note the redirect to `/jobs/<id>`.

- [ ] **Step 3: Wait for completion, verify the Done page**

While the job runs:
- The header shows `AAPL` and empty price fields (or `—`) — that's expected until `complete`.

After the job reaches `complete`:
- `<h2>` still shows `AAPL`.
- `<h3>` shows **Apple Inc.** (or the actual current `longName` — no longer the ticker echoed).
- Current Price shows a real USD number (e.g. `$237.42`).
- The `%` change shows a real `+X.XX%` or `-X.XX%`, colored green when positive / red when negative.
- Summary paragraph mentions Apple by name (LLM saw the facts).

- [ ] **Step 4: Submit an unknown ticker (failure path)**

Submit an obviously bad ticker (e.g. `ZZZZZ`). Wait for completion.

Expected:
- Job still completes (best-effort mode).
- `<h3>` falls back to `ZZZZZ`.
- Current Price shows `— —` (both em-dashes).
- Summary text is present but explicitly notes data unavailability.

- [ ] **Step 5: If everything checks out**

No commit needed — this task is verification only. If any step fails, open a follow-up task with a concrete repro (which ticker, which field wrong, what the response JSON looked like). Do NOT paper over bugs by inlining fallbacks; go back to the tasks above and fix the root cause.

---

## Post-implementation checklist

- [ ] `cd agent && pytest -q` — green.
- [ ] `npm test` — green.
- [ ] `npx tsc --noEmit` — no errors.
- [ ] Dev server manually verified with one known ticker + one unknown ticker (Task 11).
- [ ] `git log --oneline` shows one commit per task (~7 commits).
- [ ] No new files under `docs/superpowers/plans/` beyond this one.

## Out of scope (deliberately deferred)

Tracked in the spec's "Non-goals" and "Open questions" sections:

- Making the `AnalystSentiment` bento card dynamic (needs a different data-source strategy).
- Refreshing the header price on view instead of freezing it at analysis time.
- Backfilling snapshots for jobs completed before this change.
- Home dashboard cards (Welcome / AiSentiment / TopGainers / MarketRisk) stay static — they're market-level, not per-ticker.
