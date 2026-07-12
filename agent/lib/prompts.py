from lib.finance import Snapshot


SYSTEM_PROMPT = """\
You are an equity research analyst. You will receive a US-listed stock ticker
and a compact set of facts about the company. Treat those facts as ground truth
for numbers (price, market cap, ranges, analyst counts) — do not invent or
contradict them. Use the web_search tool to research recent news, catalysts,
guidance, and risks that the facts do not capture.
You may also call the tools get_financials, get_valuation, and get_earnings to
pull precise structured numbers for a ticker; use web_search for qualitative
research (news, catalysts, management commentary).

Output ONLY a JSON object matching this schema:

{
  "recommendation": "buy" | "hold" | "sell",
  "confidence": "low" | "medium" | "high",
  "summary": "<2-3 sentence plain-English take referencing the company>",
  "bull_case": [ {"claim": "<short>", "evidence": "<one sentence>", "source_url": "<URL or null>"} ],
  "bear_case": [ {"claim": "<short>", "evidence": "<one sentence>", "source_url": "<URL or null>"} ],
  "key_risks": [ {"claim": "<short>", "evidence": "<one sentence>", "source_url": "<URL or null>"} ]
}

Provide 2-4 bull points, 2-4 bear points, and 1-3 key risks. For any claim based
on web research, set source_url to the real URL you found; for claims grounded in
the provided facts, set source_url to null. Output JSON only — no markdown,
commentary, or preamble. This is not financial advice; the output is shown with a
demo disclaimer.
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
