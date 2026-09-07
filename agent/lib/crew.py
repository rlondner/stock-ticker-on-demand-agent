"""4-agent CrewAI crew for the deep/full analysis tiers: Researcher (You.com
search/news) -> Fundamentals Analyst (yfinance tools + Daytona code-exec) ->
Risk Analyst (You.com) -> Portfolio Manager (synthesis, no tools). Sequential
process — each task's output becomes the next task's context. Mirrors
run_analysis()'s contract exactly: same input, same output dict shape, raises
on total failure so agent.py's existing except/mark_failed path needs no
changes."""
import json
import os

from crewai import Agent, Crew, LLM, Process, Task
from crewai.tools import tool as crewai_tool

from .finance import Snapshot, fetch_snapshot
from .llm import Thesis
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
    wrapped = []
    for name, fn in registry.items():
        namespace: dict = {}
        source = (
            f"def _tool_fn({arg_name}: str = \"\"):\n"
            f"    \"\"\"Call the {name} tool with a single {arg_name} string argument.\"\"\"\n"
            f"    return _json.dumps(_fn({{\"{arg_name}\": {arg_name}}}))\n"
        )
        exec(source, {"_fn": fn, "_json": json}, namespace)
        wrapped.append(crewai_tool(name)(namespace["_tool_fn"]))
    return wrapped


def _build_crew(ticker: str, snapshot: Snapshot | None, sandbox_id: str | None, depth: str) -> Crew:
    llm = _llm()
    max_exec = _max_execution_seconds(depth) // 4
    facts = _format_facts(snapshot) if snapshot else f"(No live facts available for {ticker}.)"

    youdotcom_tools = _as_crewai_tools(build_youdotcom_tools(), "query")
    _, financial_registry = build_toolset(ticker)
    financial_tools = _as_crewai_tools(financial_registry, "ticker")
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
        tools=youdotcom_tools, llm=llm, max_execution_time=max_exec,
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


def _extract_thesis_dict(crew_output) -> dict:
    raw = getattr(crew_output, "raw", None) or str(crew_output)
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[len("json"):]
        cleaned = cleaned.strip()
    return json.loads(cleaned)


def run_crew_analysis(ticker: str, depth: str, sandbox_id: str | None) -> dict:
    snapshot = fetch_snapshot(ticker)
    crew_instance = _build_crew(ticker, snapshot, sandbox_id, depth)
    crew_output = crew_instance.kickoff()
    thesis_dict = _extract_thesis_dict(crew_output)
    thesis = Thesis(**thesis_dict)
    return {
        **thesis.model_dump(),
        "snapshot": snapshot.model_dump() if snapshot else None,
    }
