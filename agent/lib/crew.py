"""4-agent CrewAI crew for the deep/full analysis tiers: Researcher (You.com
search/news) -> Fundamentals Analyst (yfinance tools + Daytona code-exec) ->
Risk Analyst (You.com + earnings) -> Portfolio Manager (synthesis, no tools).
Sequential process — each task's output becomes the next task's context.
Mirrors run_analysis()'s contract exactly: same input, same output dict shape,
raises on total failure so agent.py's existing except/mark_failed path needs
no changes."""
import os
import time

from crewai import Agent, Crew, LLM, Process, Task
from crewai.tools import tool as crewai_tool
from opentelemetry import trace

from . import metrics
from .finance import Snapshot, fetch_snapshot
from .llm import Thesis, parse_thesis
from .observability import get_host
from .prompts import _format_facts
from .tools import build_toolset, build_code_exec_tool
from .youdotcom import build_youdotcom_tools

_DEFAULT_MAX_EXECUTION_S = {"deep": 780, "full": 1380}


def _max_execution_seconds(depth: str) -> int:
    env_key = f"CREW_MAX_EXECUTION_S_{depth.upper()}"
    raw = os.environ.get(env_key)
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return _DEFAULT_MAX_EXECUTION_S.get(depth, _DEFAULT_MAX_EXECUTION_S["deep"])


def _llm() -> LLM:
    return LLM(
        model=os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.environ.get("OPENAI_API_URL") or None,
    )


def _as_crewai_tools(registry: dict, arg_name: str) -> list:
    """Adapt a name->callable(args: dict) registry (the Responses-API/tools.py
    convention) into CrewAI @tool-decorated callables taking a single named
    string argument, JSON-encoding the underlying dict result for the LLM.

    CrewAI's @tool decorator introspects the wrapped function's real
    signature (via inspect.signature) to build the tool's args schema, and
    requires a docstring — a generic ``**kwargs`` wrapper produces an empty
    schema the LLM can't use. We therefore synthesize a small function per
    tool name with the single named parameter baked in via ``exec``, which
    correctly reflects the parameter name/type/docstring."""
    import json as _json_module

    wrapped = []
    for name, fn in registry.items():
        namespace: dict = {}
        source = (
            f"def _tool_fn({arg_name}: str = \"\"):\n"
            f"    \"\"\"Call the {name} tool with a single {arg_name} string argument.\"\"\"\n"
            f"    return _json.dumps(_fn({{\"{arg_name}\": {arg_name}}}))\n"
        )
        exec(source, {"_fn": fn, "_json": _json_module}, namespace)
        wrapped.append(crewai_tool(name)(namespace["_tool_fn"]))
    return wrapped


def _build_crew(ticker: str, snapshot: Snapshot | None, sandbox_id: str | None, depth: str) -> Crew:
    llm = _llm()
    max_exec = _max_execution_seconds(depth) // 4
    facts = _format_facts(snapshot) if snapshot else f"(No live facts available for {ticker}.)"

    youdotcom_tools = _as_crewai_tools(build_youdotcom_tools(), "query")
    _, financial_registry = build_toolset(ticker)
    financial_tools = _as_crewai_tools(financial_registry, "ticker")
    # Design spec's tool table gives the Risk Analyst youdotcom_search,
    # youdotcom_news, AND get_earnings (an upcoming earnings date/beat-or-miss
    # history is a downside-risk signal in its own right) — adapt just that
    # one entry from the financial registry rather than handing Risk the full
    # financial toolset (that belongs to the Fundamentals Analyst).
    earnings_tools = _as_crewai_tools({"get_earnings": financial_registry["get_earnings"]}, "ticker")
    code_exec_tools = _as_crewai_tools(build_code_exec_tool(sandbox_id), "code")

    researcher = Agent(
        role="Equity Researcher",
        goal=f"Find recent news, catalysts, and management commentary about {ticker}",
        backstory="A sell-side research associate who reads every recent filing and news wire.",
        tools=youdotcom_tools, llm=llm, max_execution_time=max_exec,
    )
    fundamentals = Agent(
        role="Fundamentals Analyst",
        goal=f"Analyze {ticker}'s financials, valuation, and earnings trend, computing any custom ratios needed",
        backstory="A quant-leaning analyst who verifies every claim against hard numbers.",
        tools=[*financial_tools, *code_exec_tools], llm=llm, max_execution_time=max_exec,
    )
    risk = Agent(
        role="Risk Analyst",
        goal=f"Identify the biggest downside risks and catalysts for {ticker}",
        backstory="A skeptical analyst whose job is to find what could go wrong.",
        tools=[*youdotcom_tools, *earnings_tools], llm=llm, max_execution_time=max_exec,
    )
    pm = Agent(
        role="Portfolio Manager",
        goal="Synthesize the research, fundamentals, and risk analysis into one final call",
        backstory="A portfolio manager who weighs the team's research into a single buy/hold/sell decision.",
        tools=[], llm=llm, max_execution_time=max_exec,
    )

    research_task = Task(
        description=(
            f"Ticker: {ticker}\nFacts:\n{facts}\n"
            "Research recent news, catalysts, and management commentary. "
            "Return a JSON list of objects: {\"claim\": str, \"evidence\": str, \"source_url\": str|null}."
        ),
        expected_output="A JSON list of claim/evidence/source_url objects.",
        agent=researcher,
    )
    fundamentals_task = Task(
        description=(
            f"Ticker: {ticker}\nAnalyze financials, valuation, and earnings trend. "
            "Use run_python_snippet for any derived ratio not directly available. "
            "Return a JSON list of objects: {\"claim\": str, \"evidence\": str, \"source_url\": str|null}."
        ),
        expected_output="A JSON list of claim/evidence/source_url objects.",
        agent=fundamentals,
    )
    risk_task = Task(
        description=(
            f"Ticker: {ticker}\nIdentify the biggest downside risks and catalysts. "
            "Return a JSON list of objects: {\"claim\": str, \"evidence\": str, \"source_url\": str|null}."
        ),
        expected_output="A JSON list of claim/evidence/source_url objects.",
        agent=risk,
        context=[research_task],
    )
    pm_task = Task(
        description=(
            f"Ticker: {ticker}\nFacts:\n{facts}\n"
            "Using the researcher's findings, the fundamentals analysis, and the risk analysis, "
            "output ONLY a JSON object matching this schema:\n"
            "{\"recommendation\": \"buy\"|\"hold\"|\"sell\", \"confidence\": \"low\"|\"medium\"|\"high\", "
            "\"summary\": str, \"bull_case\": [...], \"bear_case\": [...], \"key_risks\": [...], "
            "\"researcher_findings\": [...], \"fundamentals_analysis\": [...], \"risk_analysis\": [...]}\n"
            "Each list item is {\"claim\": str, \"evidence\": str, \"source_url\": str|null}. "
            "Copy the upstream agents' findings verbatim into researcher_findings/fundamentals_analysis/"
            "risk_analysis; derive bull_case/bear_case/key_risks yourself from all three. Output JSON only."
        ),
        expected_output="A single JSON object matching the Thesis schema.",
        agent=pm,
        context=[research_task, fundamentals_task, risk_task],
    )

    return Crew(
        agents=[researcher, fundamentals, risk, pm],
        tasks=[research_task, fundamentals_task, risk_task, pm_task],
        process=Process.sequential,
    )


def run_crew_analysis(ticker: str, depth: str, sandbox_id: str | None) -> dict:
    # Fail fast, before building the crew: every You.com call would otherwise
    # 401, get swallowed by _observed_tool into {"error": ...}, and the crew
    # would still produce a "complete" job dressed up as real research —
    # silently contradicting the README's "if unset, only quick tier is
    # available." agent.py's existing except/mark_failed path turns this into
    # an honest job-level failure with this exact message.
    if not os.environ.get("YOUDOTCOM_API_KEY"):
        raise RuntimeError("YOUDOTCOM_API_KEY is not set; deep/full analysis requires it")

    snapshot = fetch_snapshot(ticker)
    crew_instance = _build_crew(ticker, snapshot, sandbox_id, depth)

    tracer = trace.get_tracer("stock-agent")
    with tracer.start_as_current_span("crew.run") as span:
        span.set_attribute("host", get_host())
        span.set_attribute("depth", depth)
        span.set_attribute("ticker", ticker)

        started_at = time.perf_counter()
        final_status = "failed"
        try:
            # NOTE on crewai==1.6.1's max_execution_time behavior (verified by
            # reading crewai/agent/core.py's _execute_with_timeout AND by a
            # live probe against the real installed package — see the final
            # review fix report):
            #   1. A per-agent budget that expires raises TimeoutError out of
            #      kickoff() — it does NOT return a partial/best-effort
            #      result. This alone differs from this feature's original
            #      design assumption.
            #   2. WORSE: _execute_with_timeout runs the agent's LLM call in
            #      a `with concurrent.futures.ThreadPoolExecutor() as executor`
            #      block. future.result(timeout=...) does raise on schedule,
            #      but future.cancel() cannot stop an already-running thread,
            #      and the `with` block's __exit__ calls
            #      executor.shutdown(wait=True) — which blocks until that
            #      thread actually finishes. So max_execution_time does NOT
            #      cap kickoff()'s real wall-clock time: if the underlying
            #      LLM/tool call hangs (e.g. a network hang with no client
            #      timeout), kickoff() hangs right along with it, regardless
            #      of this setting. CREW_MAX_EXECUTION_S_DEEP/FULL are
            #      therefore best-effort, not a hard cap — the Daytona
            #      DAYTONA_AUTO_DELETE_*_S sandbox-level timeout is the only
            #      real backstop against a true hang. No workaround is
            #      implemented here; flagged as a residual concern in the
            #      final review fix report.
            crew_output = crew_instance.kickoff()
            final_status = "complete"
        finally:
            duration_ms = (time.perf_counter() - started_at) * 1000
            metrics.record_crew_run_duration(final_status, ticker, depth, duration_ms)

        # CrewOutput.token_usage is a crew-wide aggregate (total_tokens,
        # prompt_tokens, completion_tokens, successful_requests) with no
        # per-agent breakdown in crewai==1.6.1, so there is nothing usable to
        # feed metrics.record_crew_agent_tokens (which is keyed by
        # agent_role); left uncalled rather than faking a per-agent split.
        raw = getattr(crew_output, "raw", None) or str(crew_output)
        thesis = parse_thesis(raw)
        # Engine-authoritative, same as llm.py's quick-tier path: the crew's
        # entire design is that it always does live research (You.com +
        # yfinance/Daytona) when it succeeds, so "researched" is simpler and
        # more honest here than introspecting which tool calls actually ran
        # (Thesis doesn't carry that data on the crew path).
        thesis = thesis.model_copy(update={"grounding": "researched"})
        return {
            **thesis.model_dump(),
            "snapshot": snapshot.model_dump() if snapshot else None,
        }
