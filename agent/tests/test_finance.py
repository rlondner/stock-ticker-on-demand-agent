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
