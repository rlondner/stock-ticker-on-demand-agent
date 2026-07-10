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
    if snapshot.sector:
        parts = [x for x in (snapshot.sector, snapshot.industry) if x]
        lines.append(f"- Sector: {' / '.join(parts)}")
    elif snapshot.industry:
        lines.append(f"- Industry: {snapshot.industry}")
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
    if snapshot.analyst_distribution:
        d = snapshot.analyst_distribution
        lines.append(
            f"- Analyst ratings: {d.strong_buy} strong buy, {d.buy} buy, "
            f"{d.hold} hold, {d.sell} sell, {d.strong_sell} strong sell"
        )
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
