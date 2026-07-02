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
