# Agentic Thesis Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat `Analysis` with a tool-using agentic loop that produces a cited bull/bear `Thesis`, using `web_search` as the first live tool.

**Architecture:** A generic Responses-API ReAct loop (`agent_loop.py`) drives `responses.create`, dispatching custom function tools via a registry and stopping at a JSON thesis or an iteration/time budget. `llm.py` uses it (responses path) or a tool-less `chat.completions` fallback (snapshot-only), always returning a valid `Thesis` with an engine-set `grounding` level.

**Tech Stack:** Python, OpenAI SDK (Responses API), pydantic, tenacity, opentelemetry. Tests: pytest with a fake OpenAI client (no network).

## Global Constraints

- The engine ALWAYS returns a valid `Thesis`; research limits (budget, no web_search, non-Responses endpoint) never fail the job. Genuine API errors (after tenacity retries) still fail, as today.
- `grounding` is set by the ENGINE, not the model: `"researched"` if a web_search tool ran AND ≥1 `source_url` is present; `"limited"` if tools ran but no citation; `"snapshot_only"` if no tools ran. The model does not output `grounding` (schema default + engine override).
- Budgets: `MAX_ITERS` default 6 (env `AGENT_MAX_ITERS`), loop timeout default 90.0s (env `AGENT_LOOP_TIMEOUT_S`).
- `Thesis` fields: `recommendation` (buy|hold|sell), `confidence` (low|medium|high), `summary`, `bull_case`/`bear_case` (lists of `ThesisPoint`), `key_risks` (list of `ThesisPoint`), `grounding` (researched|limited|snapshot_only, default `snapshot_only`). `ThesisPoint`: `claim`, `evidence`, `source_url: str | None = None`.
- The `agent_loop` module is generic and has NO import of `llm`/`Thesis` (decoupled so sub-project 2 registers real tools).
- Only `web_search` is wired live; custom-tool dispatch is built + tested with a fake tool, no real tools registered.
- Agent tests use the venv: `agent/.venv/bin/python -m pytest ...` (system `pip` unavailable).

---

### Task 1: Generic agentic loop (`agent/lib/agent_loop.py`)

**Files:**
- Create: `agent/lib/agent_loop.py`
- Create: `agent/tests/test_agent_loop.py`

**Interfaces:**
- Produces:
  - `@dataclass LoopResult(text: str, iterations: int, tools_used: list[str], tokens_in: int, tokens_out: int, budget_exhausted: bool = False)`
  - `run_agent_loop(create_response, initial_input, tools, function_registry, max_iters=6, timeout_s=90.0) -> LoopResult`
    - `create_response`: callable `(input=..., tools=...) -> resp` where `resp` has `.output` (iterable of items; a custom call item has `.type == "function_call"`, `.name`, `.arguments` (JSON str), `.call_id`), `.output_text` (str), and optional `.usage` with `.input_tokens`/`.output_tokens`.
    - `function_registry`: `dict[str, Callable[[dict], object]]` for custom tools.

- [ ] **Step 1: Write the failing tests**

Create `agent/tests/test_agent_loop.py`:

```python
import json
from types import SimpleNamespace
from lib.agent_loop import run_agent_loop, LoopResult


def _resp(output_items, text="", tin=0, tout=0):
    return SimpleNamespace(
        output=output_items,
        output_text=text,
        usage=SimpleNamespace(input_tokens=tin, output_tokens=tout),
    )


def _fn_call(name, arguments, call_id="c1"):
    return SimpleNamespace(type="function_call", name=name, arguments=arguments, call_id=call_id)


def test_returns_text_when_no_tool_calls():
    calls = []
    def create(input, tools):
        calls.append((input, tools))
        return _resp([SimpleNamespace(type="web_search_call")], text="THESIS_JSON", tin=10, tout=5)
    r = run_agent_loop(create, [{"role": "user", "content": "hi"}], tools=[{"type": "web_search"}], function_registry={})
    assert r.text == "THESIS_JSON"
    assert r.iterations == 1
    assert "web_search_call" in r.tools_used
    assert r.tokens_in == 10 and r.tokens_out == 5
    assert r.budget_exhausted is False


def test_dispatches_custom_tool_then_finalizes():
    seen_args = {}
    def get_x(args):
        seen_args.update(args)
        return {"value": 42}
    responses = [
        _resp([_fn_call("get_x", '{"a": 1}')], text="", tin=3, tout=1),
        _resp([], text="FINAL", tin=4, tout=2),
    ]
    def create(input, tools):
        return responses.pop(0)
    r = run_agent_loop(create, [{"role": "user", "content": "hi"}], tools=[], function_registry={"get_x": get_x})
    assert seen_args == {"a": 1}
    assert r.text == "FINAL"
    assert r.iterations == 2
    assert "get_x" in r.tools_used
    assert r.tokens_in == 7 and r.tokens_out == 3


def test_tool_exception_becomes_error_output_and_loop_continues():
    def boom(args):
        raise RuntimeError("nope")
    outputs = []
    responses = [_resp([_fn_call("boom", "{}")], text=""), _resp([], text="DONE")]
    def create(input, tools):
        # capture the function_call_output appended to the conversation
        for item in input:
            if isinstance(item, dict) and item.get("type") == "function_call_output":
                outputs.append(item["output"])
        return responses.pop(0)
    r = run_agent_loop(create, [], tools=[], function_registry={"boom": boom})
    assert r.text == "DONE"
    assert any("nope" in o for o in outputs)


def test_budget_cap_stops_and_finalizes():
    def create(input, tools):
        # Always emit a tool call while tools are offered; return text on the
        # final no-tools request the loop makes after the cap.
        if tools:
            return _resp([_fn_call("loop", "{}")], text="")
        return _resp([], text="CAPPED")
    r = run_agent_loop(create, [], tools=[{"type": "web_search"}],
                       function_registry={"loop": lambda a: {}}, max_iters=3)
    assert r.iterations == 3
    assert r.budget_exhausted is True
    assert r.text == "CAPPED"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd agent && .venv/bin/python -m pytest tests/test_agent_loop.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.agent_loop'`.

- [ ] **Step 3: Implement `agent/lib/agent_loop.py`**

```python
"""Generic Responses-API tool loop. Decoupled from the thesis: it drives
`create_response`, dispatches custom function tools via a registry, and stops
at a final text answer or an iteration/time budget. Never raises for budget;
tool exceptions become error outputs fed back to the model."""
import json
import time
from dataclasses import dataclass, field


@dataclass
class LoopResult:
    text: str
    iterations: int
    tools_used: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    budget_exhausted: bool = False


def _usage(resp):
    u = getattr(resp, "usage", None)
    tin = getattr(u, "input_tokens", 0) if u else 0
    tout = getattr(u, "output_tokens", 0) if u else 0
    return (tin or 0), (tout or 0)


def run_agent_loop(create_response, initial_input, tools, function_registry,
                   max_iters=6, timeout_s=90.0):
    conversation = list(initial_input)
    tools_used: list[str] = []
    tokens_in = tokens_out = 0
    iterations = 0
    start = time.monotonic()

    while iterations < max_iters and (time.monotonic() - start) < timeout_s:
        iterations += 1
        resp = create_response(input=conversation, tools=tools)
        tin, tout = _usage(resp)
        tokens_in += tin
        tokens_out += tout

        output_items = list(getattr(resp, "output", None) or [])
        for item in output_items:
            t = getattr(item, "type", None)
            if isinstance(t, str) and t.endswith("_call"):
                tools_used.append(getattr(item, "name", None) or t)

        function_calls = [it for it in output_items if getattr(it, "type", None) == "function_call"]
        if not function_calls:
            return LoopResult(getattr(resp, "output_text", "") or "", iterations,
                              tools_used, tokens_in, tokens_out, budget_exhausted=False)

        for call in function_calls:
            conversation.append(call)
            fn = function_registry.get(getattr(call, "name", ""))
            try:
                args = json.loads(getattr(call, "arguments", "") or "{}")
                result = fn(args) if fn else {"error": f"unknown tool {getattr(call, 'name', '')!r}"}
                output_str = result if isinstance(result, str) else json.dumps(result)
            except Exception as e:  # tool failure is fed back, never crashes the loop
                output_str = json.dumps({"error": str(e)})
            conversation.append({
                "type": "function_call_output",
                "call_id": getattr(call, "call_id", ""),
                "output": output_str,
            })

    # Budget/time exhausted: one final no-tools request to force an answer.
    resp = create_response(input=conversation, tools=[])
    tin, tout = _usage(resp)
    tokens_in += tin
    tokens_out += tout
    return LoopResult(getattr(resp, "output_text", "") or "", iterations,
                      tools_used, tokens_in, tokens_out, budget_exhausted=True)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd agent && .venv/bin/python -m pytest tests/test_agent_loop.py -v`
Expected: PASS (all 4 tests).

- [ ] **Step 5: Commit**

```bash
git add agent/lib/agent_loop.py agent/tests/test_agent_loop.py
git commit -m "feat(agent): add generic Responses-API agentic tool loop"
```

---

### Task 2: Thesis schema + prompt + wire `analyze`/`run_analysis` to the loop

**Files:**
- Modify: `agent/lib/llm.py`
- Modify: `agent/lib/prompts.py`
- Modify: `agent/tests/test_llm.py`
- Modify: `agent/tests/test_prompts.py`

**Interfaces:**
- Consumes: `lib.agent_loop.run_agent_loop`, `LoopResult` (Task 1).
- Produces: `Thesis`, `ThesisPoint`, `parse_thesis(raw) -> Thesis`; `OpenAIClient.analyze(ticker, snapshot) -> Thesis`; `run_analysis(ticker) -> dict`.

- [ ] **Step 1: Replace the schema + parser in `agent/lib/llm.py`**

Replace the `Signal`/`Analysis`/`LLMClient`/`parse_response` block (lines ~24-52) with:

```python
class ThesisPoint(BaseModel):
    claim: str
    evidence: str
    source_url: str | None = None

class Thesis(BaseModel):
    recommendation: str = Field(pattern="^(buy|hold|sell)$")
    confidence: str = Field(pattern="^(low|medium|high)$")
    summary: str
    bull_case: list[ThesisPoint]
    bear_case: list[ThesisPoint]
    key_risks: list[ThesisPoint]
    # Set by the engine (not the model): overridden after parse. Default keeps
    # parsing valid when the model omits it (which it should).
    grounding: str = Field(default="snapshot_only", pattern="^(researched|limited|snapshot_only)$")

class LLMClient(Protocol):
    def analyze(self, ticker: str) -> Thesis: ...

def parse_thesis(raw: str) -> Thesis:
    """Strip optional markdown fences, parse JSON, validate against Thesis."""
    cleaned = raw.strip()
    fenced = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```$", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        snippet = raw[:200]
        raise ValueError(
            f"LLM did not return valid JSON ({e}); "
            f"raw_length={len(raw)}, snippet={snippet!r}"
        ) from e
    return Thesis(**data)
```

- [ ] **Step 2: Update the trace helper + add budgets**

In `agent/lib/llm.py`, replace `_record_parsed_response` with a thesis version and add budget constants after `DEFAULT_MODEL`:

```python
MAX_ITERS = int(os.environ.get("AGENT_MAX_ITERS", "6"))
LOOP_TIMEOUT_S = float(os.environ.get("AGENT_LOOP_TIMEOUT_S", "90"))
```

```python
def _record_parsed_response(span, thesis: "Thesis") -> None:
    span.set_attribute("llm.response.recommendation", thesis.recommendation)
    span.set_attribute("llm.response.confidence", thesis.confidence)
    span.set_attribute("llm.response.grounding", thesis.grounding)
    span.set_attribute("llm.response.summary", thesis.summary[:_LLM_SUMMARY_TRACE_MAX])
    span.set_attribute("llm.response.bull_count", len(thesis.bull_case))
    span.set_attribute("llm.response.bear_count", len(thesis.bear_case))
    span.set_attribute("llm.response.risk_count", len(thesis.key_risks))
    emit_log(
        "info",
        "llm.responded",
        recommendation=thesis.recommendation,
        confidence=thesis.confidence,
        grounding=thesis.grounding,
        summary=thesis.summary[:_LLM_SUMMARY_TRACE_MAX],
    )
```

Add the import at the top (with the other `from .` imports):

```python
from .agent_loop import run_agent_loop
```

- [ ] **Step 3: Rewrite `analyze` to run the loop / fallback and set grounding**

Replace the `analyze` method body (keep the `@retry(...)` decorator unchanged) with:

```python
    def analyze(self, ticker: str, snapshot: Snapshot | None = None) -> Thesis:
        metrics.set_current_ticker(ticker)
        tracer = trace.get_tracer("stock-agent")
        api = "responses" if self._use_responses_api else "chat.completions"
        with tracer.start_as_current_span("llm.analyze") as span:
            span.set_attribute("host", get_host())
            span.set_attribute("model", self._model)
            span.set_attribute("api", api)
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt(ticker, snapshot=snapshot)},
            ]
            request_started_at = time.perf_counter()
            try:
                if self._use_responses_api:
                    def _create(input, tools):
                        return self._client.responses.create(model=self._model, input=input, tools=tools)
                    loop = run_agent_loop(
                        _create, messages, tools=[{"type": "web_search"}],
                        function_registry={}, max_iters=MAX_ITERS, timeout_s=LOOP_TIMEOUT_S,
                    )
                    text, tin, tout = loop.text, loop.tokens_in, loop.tokens_out
                    finish_reason = "budget_exhausted" if loop.budget_exhausted else "stop"
                    span.set_attribute("llm.iterations", loop.iterations)
                    span.set_attribute("llm.tools_used", ",".join(loop.tools_used))
                    tools_ran = bool(loop.tools_used)
                else:
                    resp = self._client.chat.completions.create(model=self._model, messages=messages)
                    choice = resp.choices[0]
                    text = choice.message.content
                    finish_reason = choice.finish_reason
                    usage = getattr(resp, "usage", None)
                    tin = getattr(usage, "prompt_tokens", 0) if usage else 0
                    tout = getattr(usage, "completion_tokens", 0) if usage else 0
                    tools_ran = False

                span.set_attribute("tokens_in", tin)
                span.set_attribute("tokens_out", tout)
                metrics.record_llm_tokens(self._model, api, tin, tout, ticker)
                _require_nonempty(text, api=api, finish_reason=finish_reason,
                                  span=span, model=self._model, ticker=ticker)

                _record_raw_response(span, text, finish_reason)
                thesis = parse_thesis(text)
                thesis = thesis.model_copy(update={"grounding": _grounding(tools_ran, thesis)})
                _record_parsed_response(span, thesis)
                metrics.record_llm_call(self._model, api, "ok", ticker)
                return thesis
            except Exception:
                metrics.record_llm_call(self._model, api, "error", ticker)
                raise
            finally:
                metrics.record_llm_duration(
                    self._model, api,
                    (time.perf_counter() - request_started_at) * 1000,
                    ticker,
                )
```

Add the grounding helper above `class OpenAIClient`:

```python
def _grounding(tools_ran: bool, thesis: "Thesis") -> str:
    """Engine-authoritative grounding level (never trust the model's self-report)."""
    if not tools_ran:
        return "snapshot_only"
    has_citation = any(
        p.source_url for section in (thesis.bull_case, thesis.bear_case, thesis.key_risks) for p in section
    )
    return "researched" if has_citation else "limited"
```

- [ ] **Step 4: Update `run_analysis`**

Replace `run_analysis` with:

```python
def run_analysis(ticker: str) -> dict:
    snapshot = fetch_snapshot(ticker)
    client: LLMClient = OpenAIClient()
    thesis = client.analyze(ticker, snapshot=snapshot)
    return {
        **thesis.model_dump(),
        "snapshot": snapshot.model_dump() if snapshot else None,
    }
```

- [ ] **Step 5: Rewrite the system prompt**

In `agent/lib/prompts.py`, replace `SYSTEM_PROMPT` with:

```python
SYSTEM_PROMPT = """\
You are an equity research analyst. You will receive a US-listed stock ticker
and a compact set of facts about the company. Treat those facts as ground truth
for numbers (price, market cap, ranges, analyst counts) — do not invent or
contradict them. Use the web_search tool to research recent news, catalysts,
guidance, and risks that the facts do not capture.

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
```

(`user_prompt` and `_format_facts` are unchanged — they still inject the snapshot facts and the analyst-ratings line.)

- [ ] **Step 6: Update the prompt tests**

In `agent/tests/test_prompts.py`, replace `test_system_prompt_does_not_mention_web_search` with:

```python
def test_system_prompt_uses_web_search_and_thesis_schema():
    assert "web_search" in SYSTEM_PROMPT
    assert "bull_case" in SYSTEM_PROMPT
    assert "bear_case" in SYSTEM_PROMPT
    assert "key_risks" in SYSTEM_PROMPT
```

Leave `test_system_prompt_allows_null_sources` and the `_format_facts`/analyst-ratings tests as-is (still valid).

- [ ] **Step 7: Rewrite the affected `test_llm.py` tests for `Thesis`**

Add a shared thesis fixture near the top of `agent/tests/test_llm.py` (after imports), and update the import line `from lib.llm import Analysis, EmptyLLMResponseError, OpenAIClient, Signal, _env_flag, parse_response` to:

```python
from lib.llm import Thesis, EmptyLLMResponseError, OpenAIClient, _env_flag, parse_thesis
```

```python
_THESIS_JSON = (
    '{"recommendation":"buy","confidence":"medium","summary":"s",'
    '"bull_case":[{"claim":"c","evidence":"e","source_url":"https://x.test/a"}],'
    '"bear_case":[{"claim":"c","evidence":"e","source_url":null}],'
    '"key_risks":[{"claim":"c","evidence":"e","source_url":null}]}'
)
```

Then, for EVERY existing test in `test_llm.py` that used the old `valid = '{"recommendation":...,"signals":[]}'` fixture or asserted `parse_response`/`Analysis`/`.signals`:
- replace the fixture string with `_THESIS_JSON`;
- replace `parse_response(` → `parse_thesis(` and `Analysis` → `Thesis`;
- delete assertions referencing `.signals`;
- for the **responses-API** fake client, return a Responses-shaped object (`.output` = `[]`, `.output_text` = `_THESIS_JSON`, `.usage.input_tokens/output_tokens`) since `analyze` now drives the loop via `responses.create`. Concretely, the responses-path fake becomes:

```python
class _FakeResponses:
    def __init__(self, text): self._text = text
    def create(self, **kw):
        from types import SimpleNamespace
        return SimpleNamespace(output=[], output_text=self._text,
                               usage=SimpleNamespace(input_tokens=100, output_tokens=40))

class _FakeResponsesClient:
    def __init__(self, text): self.responses = _FakeResponses(text)
```

Replace the responses-path metrics test with:

```python
def test_analyze_emits_llm_metrics(monkeypatch):
    import importlib, lib.metrics as mtr, lib.llm as llm
    importlib.reload(mtr)
    seen = {"tokens": [], "calls": []}
    monkeypatch.setattr(mtr, "record_llm_tokens",
                        lambda model, api, tin, tout, ticker: seen["tokens"].append((model, api, tin, tout, ticker)))
    monkeypatch.setattr(mtr, "record_llm_call",
                        lambda model, api, outcome, ticker: seen["calls"].append((model, api, outcome, ticker)))
    importlib.reload(llm)

    client = llm.OpenAIClient.__new__(llm.OpenAIClient)
    client._client = _FakeResponsesClient(_THESIS_JSON)
    client._model = "gpt-4.1-mini"
    client._use_responses_api = True

    t = client.analyze("AAPL")
    assert isinstance(t, llm.Thesis)
    assert t.recommendation == "buy"
    assert t.grounding == "snapshot_only"   # fake returns no tool items → tools_ran False
    assert seen["tokens"] == [("gpt-4.1-mini", "responses", 100, 40, "AAPL")]
    assert seen["calls"] == [("gpt-4.1-mini", "responses", "ok", "AAPL")]
```

Add a grounding test and keep the chat.completions branch test (updated to Thesis):

```python
def test_analyze_grounding_researched_when_web_search_and_citation(monkeypatch):
    import importlib, lib.metrics as mtr, lib.llm as llm
    importlib.reload(mtr)
    monkeypatch.setattr(mtr, "record_llm_tokens", lambda *a, **k: None)
    monkeypatch.setattr(mtr, "record_llm_call", lambda *a, **k: None)
    importlib.reload(llm)

    from types import SimpleNamespace
    class _WS:
        def create(self, **kw):
            return SimpleNamespace(
                output=[SimpleNamespace(type="web_search_call")],
                output_text=_THESIS_JSON,
                usage=SimpleNamespace(input_tokens=1, output_tokens=1),
            )
    client = llm.OpenAIClient.__new__(llm.OpenAIClient)
    client._client = SimpleNamespace(responses=_WS())
    client._model = "gpt-4.1-mini"
    client._use_responses_api = True
    t = client.analyze("AAPL")
    assert t.grounding == "researched"   # web_search ran + bull_case has a source_url


def test_analyze_chat_completions_fallback_is_snapshot_only(monkeypatch):
    import importlib, lib.metrics as mtr, lib.llm as llm
    importlib.reload(mtr)
    monkeypatch.setattr(mtr, "record_llm_tokens", lambda *a, **k: None)
    monkeypatch.setattr(mtr, "record_llm_call", lambda *a, **k: None)
    importlib.reload(llm)

    from unittest.mock import MagicMock
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=_THESIS_JSON), finish_reason="stop")]
    resp.usage = MagicMock(prompt_tokens=50, completion_tokens=25)
    fake = MagicMock()
    fake.chat.completions.create.return_value = resp
    client = llm.OpenAIClient.__new__(llm.OpenAIClient)
    client._client = fake
    client._model = "gpt-4.1-mini"
    client._use_responses_api = False
    t = client.analyze("TSLA")
    assert t.recommendation == "buy" and t.grounding == "snapshot_only"
```

For any remaining pre-existing `test_llm.py` tests (retry/empty/parse tests) that referenced `parse_response`/`Analysis`/signals, apply the same mechanical swap (fixture → `_THESIS_JSON`, `parse_response` → `parse_thesis`, `Analysis` → `Thesis`, drop `.signals`). The retry/empty tests keep asserting the retry behavior; their fake responses just return `_THESIS_JSON` (or empty string for the empty-response case).

- [ ] **Step 8: Run the tests to verify they pass**

Run: `cd agent && .venv/bin/python -m pytest tests/test_llm.py tests/test_prompts.py -v`
Expected: PASS (new + updated tests). Then confirm nothing else references the removed names:

Run: `grep -rn "parse_response\|Analysis\|\.signals\|Signal\b" agent/lib agent/tests --include=*.py | grep -v ".venv"`
Expected: no output (all migrated to Thesis).

- [ ] **Step 9: Commit**

```bash
git add agent/lib/llm.py agent/lib/prompts.py agent/tests/test_llm.py agent/tests/test_prompts.py
git commit -m "feat(agent): produce a cited bull/bear Thesis via the agentic loop"
```

---

### Task 3: Config + docs + full verification

**Files:**
- Modify: `.env.example`
- Modify: `OTEL.md`

- [ ] **Step 1: Document the new env knobs in `.env.example`**

Add near the agent/OpenAI settings:

```
# --- Agentic thesis engine ---
# The agent researches a bull/bear thesis with the OpenAI web_search tool.
# AGENT_MAX_ITERS=6            # max tool-call turns per analysis
# AGENT_LOOP_TIMEOUT_S=90      # wall-clock budget for the tool loop (seconds)
```

- [ ] **Step 2: Note the LLM shape change in `OTEL.md`**

In `OTEL.md`, update the `llm.analyze` span row (in the traces table) so its attributes read: `model`, `api`, `tokens_in`, `tokens_out`, `llm.iterations`, `llm.tools_used`, `llm.response.recommendation`, `llm.response.confidence`, `llm.response.grounding`. (Replace the old `signals`/`empty_response` mention for that row; the metrics table is unchanged.)

- [ ] **Step 3: Run the full Python suite**

Run: `cd agent && .venv/bin/python -m pytest -q`
Expected: PASS (all agent tests; DB tests skip without `NEON_DATABASE_URL`).

- [ ] **Step 4: Run the full Node suite (sanity — result-shape change)**

Run: `npm run test`
Expected: PASS. (The frontend `KeyInsights` reads `result.signals`, now absent → renders nothing; no Node test asserts it, so the suite stays green. This empty-panel gap is the known interim transition until the frontend sub-project.)

- [ ] **Step 5: Commit**

```bash
git add .env.example OTEL.md
git commit -m "docs: document the agentic thesis engine (env + trace attributes)"
```

---

## Self-Review

**Spec coverage:**
- Generic loop + tool registry + budgets → Task 1. ✓
- `Thesis`/`ThesisPoint` schema + `parse_thesis` → Task 2 Step 1. ✓
- Engine-set grounding (researched/limited/snapshot_only), never trust model → Task 2 Step 3 `_grounding` + `model_copy` override; `grounding` default in schema. ✓
- Always produce a thesis; budget/no-tools/fallback never fail → loop `budget_exhausted` finalization (Task 1) + `chat.completions` fallback (Task 2 Step 3). ✓
- web_search wired live; custom dispatch built + fake-tool tested → Task 1 tests + Task 2 `function_registry={}`. ✓
- New analyst-research prompt → Task 2 Step 5. ✓
- Wiring `run_analysis`/`recommendation` unchanged for `agent.py` → Task 2 Step 4. ✓
- Minimal observability (iterations/tools_used/grounding span attrs; existing metrics kept) → Task 2 Step 3 + Task 3 Step 2. ✓
- Budgets via env (`AGENT_MAX_ITERS`, `AGENT_LOOP_TIMEOUT_S`) → Task 2 Step 2 + Task 3 Step 1. ✓
- Interim KeyInsights gap acknowledged → Task 3 Step 4 note. ✓
- Out of scope (custom tools, frontend, rich metrics) → not in any task. ✓

**Placeholder scan:** No TBD/TODO. Task 2 Step 7 gives a concrete mechanical transform rule + the `_THESIS_JSON` fixture + complete code for the core new tests; the remaining fixture swaps are a precise find/replace, not vague. All code steps show code. ✓

**Type consistency:** `run_agent_loop(create_response, initial_input, tools, function_registry, max_iters, timeout_s) -> LoopResult(text, iterations, tools_used, tokens_in, tokens_out, budget_exhausted)` defined Task 1, consumed in Task 2 Step 3 with matching kwargs and `.text/.tokens_in/.tokens_out/.iterations/.tools_used/.budget_exhausted`. `Thesis`/`ThesisPoint`/`parse_thesis`/`_grounding` defined Task 2 and used consistently. `grounding` enum values identical across schema, `_grounding`, and tests. ✓
