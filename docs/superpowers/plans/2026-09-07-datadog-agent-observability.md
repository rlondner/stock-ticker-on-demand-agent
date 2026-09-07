# Datadog Agent Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire Datadog's native `ddtrace.llmobs` SDK onto the Python agent's LLM/tool-use loop so it shows up in Datadog's dedicated Agent (LLM) Observability UI, and fix a pre-existing dead `initOtel()` call on the Next.js side.

**Architecture:** A new `agent/lib/llmobs.py` module wraps `ddtrace.llmobs.LLMObs` behind gated, never-raising helpers (`workflow_span`, `agent_span`, `llm_span`, `tool_span`, `annotate`). These are layered onto the *existing* OTel span tree — not replacing it — at four call sites: `agent.py` (workflow), `llm.py` (agent span around the tool-use loop, llm span around each model call), and `tools.py` (tool span around each function-tool dispatch). A new `DD_LLMOBS_ENABLED` env var gates this signal independently of `DD_TRACE_ENABLED`, since it's the one signal that ships full prompt/completion text.

**Tech Stack:** Python 3.14 (agent), `ddtrace` 4.x (`ddtrace.llmobs`), pytest; TypeScript/Next.js (frontend env plumbing + `instrumentation.ts` fix), vitest.

## Global Constraints

- `DD_API_KEY` remains the master switch for all Datadog signals; `DD_LLMOBS_ENABLED` is a secondary, independent kill switch (mirrors the existing `DD_TRACE_ENABLED` pattern) — `"false"` (case-insensitive) disables LLM Observability even when `DD_API_KEY` is set.
- LLM Observability runs in **agentless mode** (`agentless_enabled=True`) — no local Datadog Agent is assumed (Daytona sandboxes have none).
- `ml_app="stock-agent"`, `session_id=JOB_ID` (set once, on the top-level workflow span only — it propagates automatically to child spans in the same trace; do not repeat it on `agent`/`llm`/`tool` spans).
- Every LLMObs call must be try/except-guarded or gated so it **never** raises out into application code — telemetry failures must not break an agent run (same discipline as every existing exporter in `agent/lib/observability.py`).
- Full prompt/completion capture — no redaction of `input_data`/`output_data`.
- No new instrumentation on the Next.js side — it makes no LLM calls itself.
- Evaluations are explicitly out of scope for this plan.
- Run agent tests with `cd agent && .venv/bin/pytest tests/<file> -v`; run frontend tests with `pnpm vitest run tests/<file>`.

---

### Task 1: `agent/lib/llmobs.py` — core LLMObs helper module

**Files:**
- Create: `agent/lib/llmobs.py`
- Test: `agent/tests/test_llmobs.py`

**Interfaces:**
- Produces: `init_llmobs() -> bool`, `llmobs_enabled() -> bool`, `flush_llmobs(timeout_s: float = 5.0) -> None`, `workflow_span(name: str, session_id: str | None = None)` (context manager yielding a span or `None`), `agent_span(name: str)` (context manager), `llm_span(name: str, model_name: str)` (context manager), `tool_span(name: str)` (context manager), `annotate(span, **kwargs) -> None`.
- Consumes: `os.environ["DD_API_KEY"]`, `os.environ["DD_LLMOBS_ENABLED"]`, `os.environ["DD_SITE"]`, `os.environ["DD_ENV"]`, `os.environ["DD_SERVICE"]`; `ddtrace.llmobs.LLMObs` (imported lazily inside functions, matching this codebase's existing lazy-import style for vendor SDKs in `agent/lib/observability.py`).

- [ ] **Step 1: Write the failing tests**

Create `agent/tests/test_llmobs.py`:

```python
import contextlib
from unittest.mock import MagicMock
import lib.llmobs as llmobs


def test_init_llmobs_noop_without_api_key(monkeypatch):
    monkeypatch.delenv("DD_API_KEY", raising=False)
    monkeypatch.setattr(llmobs, "_llmobs_inited", False)
    assert llmobs.init_llmobs() is False
    assert llmobs.llmobs_enabled() is False


def test_init_llmobs_noop_when_flag_false(monkeypatch):
    monkeypatch.setenv("DD_API_KEY", "dd-test-key")
    monkeypatch.setenv("DD_LLMOBS_ENABLED", "false")
    monkeypatch.setattr(llmobs, "_llmobs_inited", False)
    assert llmobs.init_llmobs() is False
    assert llmobs.llmobs_enabled() is False


def test_init_llmobs_enables_when_configured(monkeypatch):
    monkeypatch.setenv("DD_API_KEY", "dd-test-key")
    monkeypatch.setenv("DD_SITE", "datadoghq.eu")
    monkeypatch.setenv("DD_ENV", "staging")
    monkeypatch.setenv("DD_SERVICE", "stock-agent-test")
    monkeypatch.delenv("DD_LLMOBS_ENABLED", raising=False)
    monkeypatch.setattr(llmobs, "_llmobs_inited", False)

    calls = []
    fake_llmobs = MagicMock()
    fake_llmobs.enable.side_effect = lambda **kw: calls.append(kw)
    import ddtrace.llmobs as ddllmobs
    monkeypatch.setattr(ddllmobs, "LLMObs", fake_llmobs)

    assert llmobs.init_llmobs() is True
    assert llmobs.llmobs_enabled() is True
    assert calls == [{
        "ml_app": "stock-agent",
        "agentless_enabled": True,
        "api_key": "dd-test-key",
        "site": "datadoghq.eu",
        "env": "staging",
        "service": "stock-agent-test",
    }]


def test_init_llmobs_handles_enable_exception(monkeypatch):
    monkeypatch.setenv("DD_API_KEY", "dd-test-key")
    monkeypatch.setattr(llmobs, "_llmobs_inited", False)

    fake_llmobs = MagicMock()
    fake_llmobs.enable.side_effect = RuntimeError("boom")
    import ddtrace.llmobs as ddllmobs
    monkeypatch.setattr(ddllmobs, "LLMObs", fake_llmobs)

    assert llmobs.init_llmobs() is False
    assert llmobs.llmobs_enabled() is False


def test_workflow_span_yields_none_when_disabled(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", False)
    with llmobs.workflow_span("agent.run", session_id="job-1") as span:
        assert span is None


def test_agent_span_yields_none_when_disabled(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", False)
    with llmobs.agent_span("llm.analyze") as span:
        assert span is None


def test_llm_span_yields_none_when_disabled(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", False)
    with llmobs.llm_span("llm.call", "gpt-4.1-mini") as span:
        assert span is None


def test_tool_span_yields_none_when_disabled(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", False)
    with llmobs.tool_span("tool.get_financials") as span:
        assert span is None


def _fake_cm(sentinel):
    @contextlib.contextmanager
    def _cm(**kwargs):
        _cm.calls.append(kwargs)
        yield sentinel
    _cm.calls = []
    return _cm


def test_workflow_span_delegates_to_llmobs_when_enabled(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", True)
    fake_workflow = _fake_cm("SPAN")
    fake_llmobs = MagicMock(workflow=fake_workflow)
    import ddtrace.llmobs as ddllmobs
    monkeypatch.setattr(ddllmobs, "LLMObs", fake_llmobs)

    with llmobs.workflow_span("agent.run", session_id="job-1") as span:
        assert span == "SPAN"
    assert fake_workflow.calls == [{"name": "agent.run", "session_id": "job-1"}]


def test_agent_span_delegates_to_llmobs_when_enabled(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", True)
    fake_agent = _fake_cm("SPAN")
    fake_llmobs = MagicMock(agent=fake_agent)
    import ddtrace.llmobs as ddllmobs
    monkeypatch.setattr(ddllmobs, "LLMObs", fake_llmobs)

    with llmobs.agent_span("llm.analyze") as span:
        assert span == "SPAN"
    assert fake_agent.calls == [{"name": "llm.analyze"}]


def test_llm_span_delegates_to_llmobs_when_enabled(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", True)
    fake_llm = _fake_cm("SPAN")
    fake_llmobs = MagicMock(llm=fake_llm)
    import ddtrace.llmobs as ddllmobs
    monkeypatch.setattr(ddllmobs, "LLMObs", fake_llmobs)

    with llmobs.llm_span("llm.call", "gpt-4.1-mini") as span:
        assert span == "SPAN"
    assert fake_llm.calls == [{"name": "llm.call", "model_name": "gpt-4.1-mini"}]


def test_tool_span_delegates_to_llmobs_when_enabled(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", True)
    fake_tool = _fake_cm("SPAN")
    fake_llmobs = MagicMock(tool=fake_tool)
    import ddtrace.llmobs as ddllmobs
    monkeypatch.setattr(ddllmobs, "LLMObs", fake_llmobs)

    with llmobs.tool_span("tool.get_financials") as span:
        assert span == "SPAN"
    assert fake_tool.calls == [{"name": "tool.get_financials"}]


def test_annotate_noop_when_span_none():
    llmobs.annotate(None, input_data="x", output_data="y")  # must not raise


def test_annotate_calls_llmobs_annotate_with_kwargs(monkeypatch):
    fake_llmobs = MagicMock()
    import ddtrace.llmobs as ddllmobs
    monkeypatch.setattr(ddllmobs, "LLMObs", fake_llmobs)

    llmobs.annotate("SPAN", input_data="x", output_data="y", metrics={"input_tokens": 1})
    fake_llmobs.annotate.assert_called_once_with(
        "SPAN", input_data="x", output_data="y", metrics={"input_tokens": 1}
    )


def test_annotate_swallows_exception(monkeypatch):
    fake_llmobs = MagicMock()
    fake_llmobs.annotate.side_effect = RuntimeError("boom")
    import ddtrace.llmobs as ddllmobs
    monkeypatch.setattr(ddllmobs, "LLMObs", fake_llmobs)

    llmobs.annotate("SPAN", input_data="x")  # must not raise


def test_flush_llmobs_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", False)
    llmobs.flush_llmobs(timeout_s=1.0)  # must not raise, must not import ddtrace


def test_flush_llmobs_calls_llmobs_flush_when_enabled(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", True)
    fake_llmobs = MagicMock()
    import ddtrace.llmobs as ddllmobs
    monkeypatch.setattr(ddllmobs, "LLMObs", fake_llmobs)

    llmobs.flush_llmobs(timeout_s=1.0)
    fake_llmobs.flush.assert_called_once()


def test_flush_llmobs_swallows_exception(monkeypatch):
    monkeypatch.setattr(llmobs, "_llmobs_inited", True)
    fake_llmobs = MagicMock()
    fake_llmobs.flush.side_effect = RuntimeError("boom")
    import ddtrace.llmobs as ddllmobs
    monkeypatch.setattr(ddllmobs, "LLMObs", fake_llmobs)

    llmobs.flush_llmobs(timeout_s=1.0)  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent && .venv/bin/pytest tests/test_llmobs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.llmobs'`

- [ ] **Step 3: Write the implementation**

Create `agent/lib/llmobs.py`:

```python
"""Datadog Agent (LLM) Observability instrumentation. Thin wrappers around
ddtrace.llmobs so every call site can use them unconditionally: they gate on
whether LLMObs is enabled and never raise, so telemetry can never break an
agent run. This runs alongside (not instead of) the OTel spans set up in
observability.py — it's an additional signal feeding Datadog's dedicated LLM
Observability UI, not a replacement for the unified OTel/Sentry/Datadog-APM
pipeline."""
import contextlib
import os

_llmobs_inited = False


def init_llmobs() -> bool:
    """Enable ddtrace's LLM Observability SDK in agentless mode (Daytona
    sandboxes have no local Datadog Agent). Gated on DD_API_KEY and the
    independent DD_LLMOBS_ENABLED kill switch (this is the one signal that
    ships full prompt/completion text). Idempotent-ish: safe to call once per
    process; returns whether LLMObs ended up enabled. Never raises."""
    global _llmobs_inited
    if not os.environ.get("DD_API_KEY"):
        return False
    if os.environ.get("DD_LLMOBS_ENABLED", "").strip().lower() == "false":
        return False
    try:
        from ddtrace.llmobs import LLMObs
        LLMObs.enable(
            ml_app="stock-agent",
            agentless_enabled=True,
            api_key=os.environ["DD_API_KEY"],
            site=os.environ.get("DD_SITE", "datadoghq.com"),
            env=os.environ.get("DD_ENV", "development"),
            service=os.environ.get("DD_SERVICE", "stock-agent"),
        )
    except Exception:
        return False
    _llmobs_inited = True
    return True


def llmobs_enabled() -> bool:
    return _llmobs_inited


@contextlib.contextmanager
def workflow_span(name: str, session_id: str | None = None):
    """Top-level span for one job. Set session_id here only — it propagates
    to child agent/llm/tool spans in the same trace automatically."""
    if not _llmobs_inited:
        yield None
        return
    from ddtrace.llmobs import LLMObs
    with LLMObs.workflow(name=name, session_id=session_id) as span:
        yield span


@contextlib.contextmanager
def agent_span(name: str):
    """Span for one tool-use loop (one run_agent_loop() call)."""
    if not _llmobs_inited:
        yield None
        return
    from ddtrace.llmobs import LLMObs
    with LLMObs.agent(name=name) as span:
        yield span


@contextlib.contextmanager
def llm_span(name: str, model_name: str):
    """Span for one actual model API call."""
    if not _llmobs_inited:
        yield None
        return
    from ddtrace.llmobs import LLMObs
    with LLMObs.llm(name=name, model_name=model_name) as span:
        yield span


@contextlib.contextmanager
def tool_span(name: str):
    """Span for one tool dispatch (a function-tool call or the hosted web_search)."""
    if not _llmobs_inited:
        yield None
        return
    from ddtrace.llmobs import LLMObs
    with LLMObs.tool(name=name) as span:
        yield span


def annotate(span, **kwargs) -> None:
    """Attach input/output/metadata/metrics to an LLMObs span. No-op if span
    is None (LLMObs disabled). Never raises — an annotation failure must not
    break the agent run."""
    if span is None:
        return
    try:
        from ddtrace.llmobs import LLMObs
        LLMObs.annotate(span, **kwargs)
    except Exception:
        pass


def flush_llmobs(timeout_s: float = 5.0) -> None:
    """Drain the LLMObs writer. MUST run before the Daytona sandbox
    self-deletes. No-op if LLMObs was never enabled."""
    if not _llmobs_inited:
        return
    try:
        from ddtrace.llmobs import LLMObs
        LLMObs.flush()
    except Exception:
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agent && .venv/bin/pytest tests/test_llmobs.py -v`
Expected: PASS (19 tests)

- [ ] **Step 5: Commit**

```bash
cd agent && git add lib/llmobs.py tests/test_llmobs.py
git commit -m "$(cat <<'EOF'
feat: add ddtrace LLMObs helper module for agent observability

Thin, always-safe wrappers around ddtrace.llmobs (workflow/agent/llm/tool
spans + annotate), gated on DD_API_KEY + DD_LLMOBS_ENABLED. Not yet wired
into any call site.

🌸 Shipped with Kanna — https://kanna.sh

Co-Authored-By: Kanna <noreply@kanna.sh>
Kanna-Agent: claude/sonnet
EOF
)"
```

---

### Task 2: Wire `DD_LLMOBS_ENABLED` end-to-end

**Files:**
- Modify: `agent/lib/observability.py:1-9` (imports unaffected — uses lazy `from lib.llmobs import ...` inline, matching existing style), `agent/lib/observability.py:108-109`, `agent/lib/observability.py:250-256`
- Modify: `agent/agent.py:18-40` (`EXPECTED_ENV_VARS`)
- Modify: `lib/daytona.ts:19-33` (`spawnAnalysisSandbox` env block)
- Modify: `.env.example:78-85` (Datadog block)
- Test: `agent/tests/test_observability.py` (append), `tests/daytona.test.ts` (append)

**Interfaces:**
- Consumes: `init_llmobs`, `flush_llmobs` from `lib.llmobs` (Task 1).
- Produces: `init_observability()` now calls `init_llmobs()`; `flush_observability()` now calls `flush_llmobs(timeout_s=timeout_s)`; `agent.py`'s env-presence boot log includes `env_has_DD_LLMOBS_ENABLED`; `spawnAnalysisSandbox` forwards `DD_LLMOBS_ENABLED` into the sandbox when set.

- [ ] **Step 1: Write the failing agent-side tests**

Append to `agent/tests/test_observability.py`:

```python
def test_init_observability_calls_init_llmobs(monkeypatch):
    import importlib, lib.observability as o
    calls = []
    monkeypatch.setattr("lib.llmobs.init_llmobs", lambda: calls.append("init") or True)
    monkeypatch.setenv("JOB_ID", "job-llmobs-init")
    importlib.reload(o)
    o.init_observability(job_id="job-llmobs-init")
    assert calls == ["init"]
    o.flush_observability(timeout_s=1.0)


def test_flush_observability_calls_flush_llmobs(monkeypatch):
    import importlib, lib.observability as o
    calls = []
    monkeypatch.setattr("lib.llmobs.flush_llmobs", lambda timeout_s=5.0: calls.append(timeout_s))
    monkeypatch.setenv("JOB_ID", "job-llmobs-flush")
    importlib.reload(o)
    o.init_observability(job_id="job-llmobs-flush")
    o.flush_observability(timeout_s=2.5)
    assert calls == [2.5]
```

- [ ] **Step 2: Run agent tests to verify they fail**

Run: `cd agent && .venv/bin/pytest tests/test_observability.py -v -k llmobs`
Expected: FAIL — `calls == []` (nothing calls `init_llmobs`/`flush_llmobs` yet)

- [ ] **Step 3: Wire `init_llmobs`/`flush_llmobs` into `observability.py`**

In `agent/lib/observability.py`, after the existing Datadog/OTLP trace exporter block (ends at line 108 with `_install_trace_instrumentors()`) and before the `# Logs:` comment (line 110), insert:

```python
    # === Datadog LLM Observability ===
    # Separate signal from APM traces: native ddtrace.llmobs SDK, agentless
    # mode (Daytona sandboxes have no local Agent), gated independently via
    # DD_LLMOBS_ENABLED since this is the one signal that ships full prompt/
    # completion text. See lib/llmobs.py.
    from lib.llmobs import init_llmobs
    init_llmobs()

```

In `flush_observability` (currently ending at line 256 with the `ddtrace.tracer.shutdown` block), append at the end of the function body:

```python

    try:
        from lib.llmobs import flush_llmobs
        flush_llmobs(timeout_s=timeout_s)
    except Exception:
        pass
```

- [ ] **Step 4: Run agent tests to verify they pass**

Run: `cd agent && .venv/bin/pytest tests/test_observability.py -v`
Expected: PASS (all tests, including the two new ones)

- [ ] **Step 5: Add `DD_LLMOBS_ENABLED` to `agent.py`'s `EXPECTED_ENV_VARS`**

In `agent/agent.py`, in the `EXPECTED_ENV_VARS` tuple (lines 18-40), add `"DD_LLMOBS_ENABLED",` immediately after `"DD_TRACE_ENABLED",` (line 32):

```python
    "DD_TRACE_ENABLED",
    "DD_LLMOBS_ENABLED",
    "DD_EXPORTER",
```

- [ ] **Step 6: Run agent test suite to confirm no regression**

Run: `cd agent && .venv/bin/pytest tests/ -v -k "env_presence or test_agent"`
Expected: PASS (no test asserts the exact tuple contents, so this is a safety check, not a new assertion)

- [ ] **Step 7: Write the failing frontend test**

Append to `tests/daytona.test.ts` (inside the existing `describe("spawnAnalysisSandbox", ...)` block, after the `"forwards DD_TRACE_ENABLED only when set"` test):

```ts
  it("forwards DD_LLMOBS_ENABLED only when set", async () => {
    process.env.DD_LLMOBS_ENABLED = "false";
    const { spawnAnalysisSandbox } = await import("@/lib/daytona");
    const span = trace.getTracer("t").startSpan("p");
    await spawnAnalysisSandbox("job-llmobs", span);
    span.end();
    const call = createMock.mock.calls.at(-1)![0] as any;
    expect(call.envVars.DD_LLMOBS_ENABLED).toBe("false");
  });
```

Also add a cleanup line to the `beforeEach` block (line 30-39), immediately after the existing `delete process.env.DD_TRACE_ENABLED;` (line 37):

```ts
    delete process.env.DD_TRACE_ENABLED;
    delete process.env.DD_LLMOBS_ENABLED;
```

- [ ] **Step 8: Run frontend test to verify it fails**

Run: `pnpm vitest run tests/daytona.test.ts`
Expected: FAIL — `call.envVars.DD_LLMOBS_ENABLED` is `undefined`

- [ ] **Step 9: Forward `DD_LLMOBS_ENABLED` in `lib/daytona.ts`**

In `lib/daytona.ts`, add a line to the `env` object (lines 19-33), immediately after `...forwardIfSet("DD_TRACE_ENABLED"),` (line 29):

```ts
    ...forwardIfSet("DD_TRACE_ENABLED"),
    ...forwardIfSet("DD_LLMOBS_ENABLED"),
    ...forwardIfSet("DD_EXPORTER"),
```

- [ ] **Step 10: Run frontend test to verify it passes**

Run: `pnpm vitest run tests/daytona.test.ts`
Expected: PASS (all tests in the file)

- [ ] **Step 11: Document the env var in `.env.example`**

In `.env.example`, in the Datadog block (lines 78-85), add after the `DD_TRACE_ENABLED=` line (line 85):

```
# Independent kill switch for Datadog LLM (Agent) Observability — the one
# signal that ships full prompt/completion text. Defaults to on whenever
# DD_API_KEY is set; 'false' disables just this signal.
DD_LLMOBS_ENABLED=
```

- [ ] **Step 12: Commit**

```bash
git add agent/lib/observability.py agent/agent.py agent/tests/test_observability.py \
        lib/daytona.ts tests/daytona.test.ts .env.example
git commit -m "$(cat <<'EOF'
feat: wire DD_LLMOBS_ENABLED through init/flush/sandbox-forwarding

Connects the llmobs helper module (init_llmobs/flush_llmobs) into the
agent's observability init/flush lifecycle, forwards the new env var
into the Daytona sandbox, and documents it in .env.example.

🌸 Shipped with Kanna — https://kanna.sh

Co-Authored-By: Kanna <noreply@kanna.sh>
Kanna-Agent: claude/sonnet
EOF
)"
```

---

### Task 3: Instrument `agent.py`'s `agent.run` workflow span

**Files:**
- Modify: `agent/agent.py:1-10` (imports), `agent/agent.py:59-86` (`with tracer.start_as_current_span("agent.run") as span:` block)
- Test: `agent/tests/test_agent.py` (append)

**Interfaces:**
- Consumes: `workflow_span(name, session_id=None)`, `annotate(span, **kwargs)` from `lib.llmobs` (Task 1).

- [ ] **Step 1: Write the failing test**

Append to `agent/tests/test_agent.py`:

```python
def test_agent_run_uses_llmobs_workflow_span(monkeypatch):
    import contextlib, importlib, agent as agent_module

    calls = {"workflow": [], "annotate": []}

    @contextlib.contextmanager
    def fake_workflow_span(name, session_id=None):
        calls["workflow"].append((name, session_id))
        yield "WORKFLOW_SPAN"

    def fake_annotate(span, **kw):
        calls["annotate"].append((span, kw))

    importlib.reload(agent_module)
    monkeypatch.setattr(agent_module.llmobs, "workflow_span", fake_workflow_span)
    monkeypatch.setattr(agent_module.llmobs, "annotate", fake_annotate)
    monkeypatch.setattr(agent_module, "get_job",
                        lambda job_id: {"ticker": "AAPL", "status": "pending", "sandbox_id": None})
    monkeypatch.setattr(agent_module, "mark_running", lambda job_id: None)
    monkeypatch.setattr(agent_module, "mark_complete", lambda job_id, recommendation, result: None)
    monkeypatch.setattr(agent_module, "run_analysis", lambda ticker: {"recommendation": "buy"})
    monkeypatch.setattr(agent_module, "self_delete", lambda sandbox_id=None: None)
    monkeypatch.setattr(agent_module, "init_observability", lambda **kw: None)
    monkeypatch.setattr(agent_module, "flush_observability", lambda *a, **kw: None)
    monkeypatch.setattr(agent_module._metrics, "record_job_completed", lambda *a, **kw: None)
    monkeypatch.setattr(agent_module._metrics, "record_agent_run_duration", lambda *a, **kw: None)
    monkeypatch.setattr(agent_module, "JOB_ID", "job-llmobs-wf")

    agent_module.main()

    assert calls["workflow"] == [("agent.run", "job-llmobs-wf")]
    assert any(span == "WORKFLOW_SPAN" for span, _ in calls["annotate"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && .venv/bin/pytest tests/test_agent.py -v -k llmobs_workflow`
Expected: FAIL — `AttributeError: module 'agent' has no attribute 'llmobs'`

- [ ] **Step 3: Wire the workflow span into `agent.py`**

In `agent/agent.py`, add the import after line 6 (`from lib.observability import ...`):

```python
from lib import llmobs
```

Replace the `with tracer.start_as_current_span("agent.run") as span:` block (lines 59-86) with:

```python
    with tracer.start_as_current_span("agent.run") as span, \
         llmobs.workflow_span("agent.run", session_id=JOB_ID) as lspan:
        span.set_attribute("host", get_host())
        span.set_attribute("job_id", JOB_ID)
        job = None
        try:
            job = get_job(JOB_ID)
            if job is None or job["status"] != "pending":
                print(f"job {JOB_ID} not pending (status={job and job['status']}); exiting", file=sys.stderr)
                final_status = "skipped"
                return
            span.set_attribute("ticker", job["ticker"])
            llmobs.annotate(lspan, input_data={"job_id": JOB_ID, "ticker": job["ticker"]})

            mark_running(JOB_ID)
            result = run_analysis(ticker=job["ticker"])
            mark_complete(JOB_ID, recommendation=result["recommendation"], result=result)
            span.set_attribute("final_status", "complete")
            final_status = "complete"
            llmobs.annotate(lspan, output_data=result, metadata={"final_status": "complete"})
            _metrics.record_job_completed("complete", job["ticker"])
            _metrics.record_agent_run_duration("complete", job["ticker"], (time.monotonic() - _start) * 1000)
        except Exception as e:
            record_error(span, e)
            mark_failed(JOB_ID, error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
            span.set_attribute("final_status", "failed")
            llmobs.annotate(lspan, metadata={"final_status": "failed", "error": f"{type(e).__name__}: {e}"})
            _ticker = job["ticker"] if job else "unknown"
            _metrics.record_job_completed("failed", _ticker)
            _metrics.record_agent_run_duration("failed", _ticker, (time.monotonic() - _start) * 1000)
            final_status = "failed"
            raise
        finally:
            duration_ms = (time.perf_counter() - started_at) * 1000
            emit_log(
                "info",
                "agent.finished",
                job_id=JOB_ID,
                final_status=final_status,
                duration_ms=duration_ms,
            )
            flush_observability()
            try:
                sandbox_id = (job["sandbox_id"] if job and "sandbox_id" in job else None)
                self_delete(sandbox_id=sandbox_id)
            except Exception:
                pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent && .venv/bin/pytest tests/test_agent.py -v`
Expected: PASS (all tests in the file, including the new one)

- [ ] **Step 5: Run the full agent test suite**

Run: `cd agent && .venv/bin/pytest tests/ -v`
Expected: PASS (no regressions; DB-backed tests skip if `NEON_DATABASE_URL` is unset, same as before)

- [ ] **Step 6: Commit**

```bash
cd agent && git add agent.py tests/test_agent.py
git commit -m "$(cat <<'EOF'
feat: wrap agent.run in an LLMObs workflow span

session_id=JOB_ID is set once here; it propagates to the agent/llm/tool
spans added in later tasks.

🌸 Shipped with Kanna — https://kanna.sh

Co-Authored-By: Kanna <noreply@kanna.sh>
Kanna-Agent: claude/sonnet
EOF
)"
```

---

### Task 4: Instrument `llm.py`'s tool-use loop and model calls

**Files:**
- Modify: `agent/lib/llm.py:1-17` (imports), `agent/lib/llm.py:169-230` (`OpenAIClient.analyze`)
- Test: `agent/tests/test_llm.py` (append)

**Interfaces:**
- Consumes: `agent_span(name)`, `llm_span(name, model_name)`, `annotate(span, **kwargs)` from `lib.llmobs` (Task 1).

- [ ] **Step 1: Write the failing tests**

Append to `agent/tests/test_llm.py`:

```python
def test_analyze_uses_llmobs_agent_and_llm_spans(monkeypatch):
    import contextlib, importlib, lib.metrics as mtr, lib.llm as llm
    importlib.reload(mtr)
    monkeypatch.setattr(mtr, "record_llm_tokens", lambda *a, **k: None)
    monkeypatch.setattr(mtr, "record_llm_call", lambda *a, **k: None)
    monkeypatch.setattr(mtr, "record_llm_duration", lambda *a, **k: None)
    importlib.reload(llm)

    calls = {"agent": [], "llm": [], "annotate": []}

    @contextlib.contextmanager
    def fake_agent_span(name):
        calls["agent"].append(name)
        yield "AGENT_SPAN"

    @contextlib.contextmanager
    def fake_llm_span(name, model_name):
        calls["llm"].append((name, model_name))
        yield "LLM_SPAN"

    monkeypatch.setattr(llm.llmobs, "agent_span", fake_agent_span)
    monkeypatch.setattr(llm.llmobs, "llm_span", fake_llm_span)
    monkeypatch.setattr(llm.llmobs, "annotate",
                        lambda span, **kw: calls["annotate"].append((span, kw)))

    client = llm.OpenAIClient.__new__(llm.OpenAIClient)
    client._client = _FakeResponsesClient(_THESIS_JSON)
    client._model = "gpt-4.1-mini"
    client._use_responses_api = True

    client.analyze("AAPL")

    assert calls["agent"] == ["llm.analyze"]
    assert calls["llm"] == [("llm.call", "gpt-4.1-mini")]
    assert any(span == "AGENT_SPAN" for span, _ in calls["annotate"])
    assert any(span == "LLM_SPAN" for span, _ in calls["annotate"])


def test_chat_completions_uses_llmobs_llm_span_only(monkeypatch):
    import contextlib, importlib, lib.metrics as mtr, lib.llm as llm
    importlib.reload(mtr)
    monkeypatch.setattr(mtr, "record_llm_tokens", lambda *a, **k: None)
    monkeypatch.setattr(mtr, "record_llm_call", lambda *a, **k: None)
    monkeypatch.setattr(mtr, "record_llm_duration", lambda *a, **k: None)
    importlib.reload(llm)

    calls = {"agent": [], "llm": []}

    @contextlib.contextmanager
    def fake_agent_span(name):
        calls["agent"].append(name)
        yield None

    @contextlib.contextmanager
    def fake_llm_span(name, model_name):
        calls["llm"].append((name, model_name))
        yield None

    monkeypatch.setattr(llm.llmobs, "agent_span", fake_agent_span)
    monkeypatch.setattr(llm.llmobs, "llm_span", fake_llm_span)
    monkeypatch.setattr(llm.llmobs, "annotate", lambda *a, **k: None)

    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=_THESIS_JSON), finish_reason="stop")]
    resp.usage = MagicMock(prompt_tokens=50, completion_tokens=25)
    fake = MagicMock()
    fake.chat.completions.create.return_value = resp
    client = llm.OpenAIClient.__new__(llm.OpenAIClient)
    client._client = fake
    client._model = "gpt-4.1-mini"
    client._use_responses_api = False

    client.analyze("TSLA")

    assert calls["agent"] == []
    assert calls["llm"] == [("llm.call", "gpt-4.1-mini")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent && .venv/bin/pytest tests/test_llm.py -v -k llmobs`
Expected: FAIL — `AttributeError: module 'lib.llm' has no attribute 'llmobs'`

- [ ] **Step 3: Wire the spans into `llm.py`**

Add the import after line 16 (`from .tools import build_toolset`):

```python
from . import llmobs
```

Replace the body of `OpenAIClient.analyze` from `if self._use_responses_api:` through the end of the `else:` branch (lines 183-207 in the original) with:

```python
                if self._use_responses_api:
                    def _create(input, tools):
                        kw = {"model": self._model, "input": input}
                        if tools:
                            kw["tools"] = tools
                        with llmobs.llm_span("llm.call", self._model) as lspan:
                            resp = self._client.responses.create(**kw)
                            usage = getattr(resp, "usage", None)
                            llmobs.annotate(
                                lspan,
                                input_data=input,
                                output_data=getattr(resp, "output_text", "") or "",
                                metrics={
                                    "input_tokens": getattr(usage, "input_tokens", 0) if usage else 0,
                                    "output_tokens": getattr(usage, "output_tokens", 0) if usage else 0,
                                },
                            )
                        return resp
                    _schemas, _registry = build_toolset(ticker)
                    with llmobs.agent_span("llm.analyze") as aspan:
                        loop = run_agent_loop(
                            _create, messages, tools=[{"type": "web_search"}, *_schemas],
                            function_registry=_registry, max_iters=MAX_ITERS, timeout_s=LOOP_TIMEOUT_S,
                        )
                        llmobs.annotate(
                            aspan,
                            input_data=messages,
                            output_data=loop.text,
                            metadata={
                                "iterations": loop.iterations,
                                "tools_used": loop.tools_used,
                                "budget_exhausted": loop.budget_exhausted,
                            },
                            metrics={"input_tokens": loop.tokens_in, "output_tokens": loop.tokens_out},
                        )
                    text, tin, tout = loop.text, loop.tokens_in, loop.tokens_out
                    finish_reason = "budget_exhausted" if loop.budget_exhausted else "stop"
                    span.set_attribute("llm.iterations", loop.iterations)
                    span.set_attribute("llm.tools_used", ",".join(loop.tools_used))
                    tools_ran = bool(loop.tools_used)
                else:
                    with llmobs.llm_span("llm.call", self._model) as lspan:
                        resp = self._client.chat.completions.create(model=self._model, messages=messages)
                        choice = resp.choices[0]
                        text = choice.message.content
                        finish_reason = choice.finish_reason
                        usage = getattr(resp, "usage", None)
                        tin = getattr(usage, "prompt_tokens", 0) if usage else 0
                        tout = getattr(usage, "completion_tokens", 0) if usage else 0
                        tools_ran = False
                        llmobs.annotate(
                            lspan, input_data=messages, output_data=text or "",
                            metrics={"input_tokens": tin, "output_tokens": tout},
                        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agent && .venv/bin/pytest tests/test_llm.py -v`
Expected: PASS (all tests in the file — the two new ones plus every pre-existing test, since token/finish_reason/grounding bookkeeping is unchanged)

- [ ] **Step 5: Run the full agent test suite**

Run: `cd agent && .venv/bin/pytest tests/ -v`
Expected: PASS, no regressions

- [ ] **Step 6: Commit**

```bash
cd agent && git add lib/llm.py tests/test_llm.py
git commit -m "$(cat <<'EOF'
feat: wrap the tool-use loop and model calls in LLMObs agent/llm spans

One agent span per run_agent_loop() call, one llm span per actual model
API call (Responses API iterations and the chat.completions fallback).
Token/finish_reason bookkeeping is unchanged.

🌸 Shipped with Kanna — https://kanna.sh

Co-Authored-By: Kanna <noreply@kanna.sh>
Kanna-Agent: claude/sonnet
EOF
)"
```

---

### Task 5: Instrument `tools.py`'s `_observed_tool`

**Files:**
- Modify: `agent/lib/tools.py:1-11` (imports), `agent/lib/tools.py:23-54` (`_observed_tool`'s `_run`)
- Test: `agent/tests/test_tools.py` (append)

**Interfaces:**
- Consumes: `tool_span(name)`, `annotate(span, **kwargs)` from `lib.llmobs` (Task 1).

- [ ] **Step 1: Write the failing test**

Append to `agent/tests/test_tools.py`:

```python
def test_observed_tool_uses_llmobs_tool_span(monkeypatch):
    import contextlib
    logs, span = _spy(monkeypatch)
    calls = {"span": [], "annotate": []}

    @contextlib.contextmanager
    def fake_tool_span(name):
        calls["span"].append(name)
        yield "TOOL_SPAN"

    monkeypatch.setattr(tools.llmobs, "tool_span", fake_tool_span)
    monkeypatch.setattr(tools.llmobs, "annotate",
                        lambda span, **kw: calls["annotate"].append((span, kw)))

    run = tools._observed_tool("get_x", lambda args: {"value": args["ticker"]})
    out = run({"ticker": "AAPL"})

    assert out == {"value": "AAPL"}
    assert calls["span"] == ["tool.get_x"]
    assert calls["annotate"] == [
        ("TOOL_SPAN", {"input_data": {"ticker": "AAPL"}, "output_data": {"value": "AAPL"}})
    ]


def test_observed_tool_annotates_error_outcome(monkeypatch):
    import contextlib
    logs, span = _spy(monkeypatch)
    calls = {"annotate": []}

    @contextlib.contextmanager
    def fake_tool_span(name):
        yield "TOOL_SPAN"

    monkeypatch.setattr(tools.llmobs, "tool_span", fake_tool_span)
    monkeypatch.setattr(tools.llmobs, "annotate",
                        lambda span, **kw: calls["annotate"].append((span, kw)))

    def boom(args):
        raise RuntimeError("nope")
    run = tools._observed_tool("get_x", boom)
    out = run({"ticker": "AAPL"})

    assert "error" in out
    assert calls["annotate"] == [
        ("TOOL_SPAN", {"input_data": {"ticker": "AAPL"}, "output_data": {"error": "RuntimeError: nope"}})
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent && .venv/bin/pytest tests/test_tools.py -v -k llmobs`
Expected: FAIL — `AttributeError: module 'lib.tools' has no attribute 'llmobs'`

- [ ] **Step 3: Wire the tool span into `tools.py`**

Add the import after line 10 (`from .observability import emit_log`):

```python
from . import llmobs
```

Replace `_observed_tool`'s `_run` function (lines 23-54) with:

```python
    def _run(args):
        # The model controls the JSON in function_call.arguments; json.loads can
        # yield a non-dict. Coerce BEFORE any .get so the observability guarantee
        # below (failed log + span event) always holds.
        args = args if isinstance(args, dict) else {}
        span = trace.get_current_span()
        with llmobs.tool_span(f"tool.{name}") as tspan:
            if bound_ticker is not None:
                supplied = args.get("ticker")
                if supplied and str(supplied).strip().upper() != bound_ticker.upper():
                    reason = (f"ticker {supplied!r} does not match the analyzed "
                              f"ticker {bound_ticker!r}")
                    emit_log("warn", f"tool.{name}.failed", ticker=bound_ticker, reason=reason)
                    span.add_event(f"tool.{name}", {"outcome": "error", "error": reason})
                    llmobs.annotate(tspan, input_data=args, output_data={"error": reason})
                    return {"error": reason}
                args = {**args, "ticker": bound_ticker}
            ticker = args.get("ticker")
            try:
                result = fn(args)
            except Exception as exc:
                reason = f"{type(exc).__name__}: {exc}"
                emit_log("warn", f"tool.{name}.failed", ticker=ticker, reason=reason)
                span.add_event(f"tool.{name}", {"outcome": "error", "error": reason})
                llmobs.annotate(tspan, input_data=args, output_data={"error": reason})
                return {"error": reason}
            if isinstance(result, dict) and "error" in result:
                emit_log("warn", f"tool.{name}.failed", ticker=ticker, reason=str(result["error"]))
                span.add_event(f"tool.{name}", {"outcome": "error", "error": str(result["error"])})
                llmobs.annotate(tspan, input_data=args, output_data=result)
                return result
            emit_log("info", f"tool.{name}.ok", ticker=ticker)
            span.add_event(f"tool.{name}", {"outcome": "ok"})
            llmobs.annotate(tspan, input_data=args, output_data=result)
            return result

    return _run
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agent && .venv/bin/pytest tests/test_tools.py -v`
Expected: PASS (all tests in the file, including the two new ones — existing tests are unaffected since `_llmobs_inited` defaults to `False` and none of them call `init_llmobs()`, so the real `tool_span`/`annotate` no-op exactly as before)

- [ ] **Step 5: Run the full agent test suite**

Run: `cd agent && .venv/bin/pytest tests/ -v`
Expected: PASS, no regressions

- [ ] **Step 6: Commit**

```bash
cd agent && git add lib/tools.py tests/test_tools.py
git commit -m "$(cat <<'EOF'
feat: wrap each observed tool dispatch in an LLMObs tool span

Every get_financials/get_valuation/get_earnings call now annotates an
LLMObs tool span with its args and result/error, alongside the existing
emit_log + span.add_event observability guarantee.

🌸 Shipped with Kanna — https://kanna.sh

Co-Authored-By: Kanna <noreply@kanna.sh>
Kanna-Agent: claude/sonnet
EOF
)"
```

---

### Task 6: Fix the dead `initOtel()` call in `instrumentation.ts`

**Files:**
- Modify: `instrumentation.ts:1-7`
- Test: Create `tests/instrumentation.test.ts`

**Interfaces:**
- Consumes: `initOtel()` from `lib/observability/otel.ts` (already exists, exported, currently unused).

- [ ] **Step 1: Write the failing test**

Create `tests/instrumentation.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";

const initDatadogMock = vi.fn(() => true);
const initOtelMock = vi.fn();

vi.mock("@/lib/observability/exporters/datadog", () => ({
  initDatadogIfEnabled: initDatadogMock,
}));
vi.mock("@/lib/observability/otel", () => ({
  initOtel: initOtelMock,
}));

describe("instrumentation register()", () => {
  beforeEach(() => {
    initDatadogMock.mockClear();
    initOtelMock.mockClear();
  });

  it("initializes both Datadog and OTel on the nodejs runtime", async () => {
    process.env.NEXT_RUNTIME = "nodejs";
    const { register } = await import("@/instrumentation");
    await register();
    expect(initDatadogMock).toHaveBeenCalledTimes(1);
    expect(initOtelMock).toHaveBeenCalledTimes(1);
  });

  it("does nothing on non-nodejs runtimes", async () => {
    process.env.NEXT_RUNTIME = "edge";
    const { register } = await import("@/instrumentation");
    await register();
    expect(initDatadogMock).not.toHaveBeenCalled();
    expect(initOtelMock).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm vitest run tests/instrumentation.test.ts`
Expected: FAIL — `initOtelMock` was not called in the nodejs-runtime test

- [ ] **Step 3: Fix `instrumentation.ts`**

Replace the full contents of `instrumentation.ts`:

```ts
export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    const { initDatadogIfEnabled } = await import("./lib/observability/exporters/datadog");
    initDatadogIfEnabled();
    const { initOtel } = await import("./lib/observability/otel");
    initOtel();
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm vitest run tests/instrumentation.test.ts`
Expected: PASS (both tests)

- [ ] **Step 5: Run the full frontend test suite**

Run: `pnpm vitest run`
Expected: PASS, no regressions

- [ ] **Step 6: Commit**

```bash
git add instrumentation.ts tests/instrumentation.test.ts
git commit -m "$(cat <<'EOF'
fix: call the dead initOtel() from instrumentation.ts register()

lib/observability/otel.ts exported a working Node OTel SDK setup
(auto-instrumentations-node) that nothing ever called, leaving Next.js
without vendor-neutral HTTP/DB auto-instrumentation. Found while adding
Datadog Agent Observability to the Python agent.

🌸 Shipped with Kanna — https://kanna.sh

Co-Authored-By: Kanna <noreply@kanna.sh>
Kanna-Agent: claude/sonnet
EOF
)"
```

---

### Task 7: Document Agent Observability in `OTEL.md`

**Files:**
- Modify: `OTEL.md`

**Interfaces:**
- None (documentation only).

- [ ] **Step 1: Add an "Agent Observability (Datadog LLM Obs)" section**

In `OTEL.md`, insert a new section immediately after the "## Metrics" section (after the `Facade modules:` line, before "## Backends & configuration"):

```markdown
## Agent Observability (Datadog LLM Obs)

Separate from the APM traces/metrics/logs above: the Python agent also emits
to Datadog's dedicated [Agent Observability](https://www.datadoghq.com/products/ai/agent-observability/)
product via the native `ddtrace.llmobs` SDK (`agent/lib/llmobs.py`), running
**alongside** the OTel spans, not instead of them.

| Span kind  | Call site                                          | Notes |
|------------|-----------------------------------------------------|-------|
| `workflow` | `agent.py` — one per job (`agent.run`)              | `session_id=JOB_ID`, set once; propagates to children |
| `agent`    | `lib/llm.py` — one per `run_agent_loop()` call      | the tool-use loop |
| `llm`      | `lib/llm.py` — one per actual model API call        | full input messages, output text, token usage |
| `tool`     | `lib/tools.py` — one per tool dispatch              | `get_financials`/`get_valuation`/`get_earnings`, args + result/error |

Full prompt/completion capture (no redaction) — the content involved is
ticker/financial-snapshot data, not user PII.

Gated on `DD_API_KEY` **and** the independent `DD_LLMOBS_ENABLED` (default on;
`"false"` disables just this signal — it's the one that ships full prompt
text). Runs in agentless mode (`agentless_enabled=True`, `ml_app=
"stock-agent"`) since Daytona sandboxes have no local Datadog Agent. Flushed
in `flush_observability()` before the sandbox self-deletes.

Evaluations (quality/faithfulness scoring) are not yet wired up.
```

- [ ] **Step 2: Add `DD_LLMOBS_ENABLED` to the Datadog config table**

In `OTEL.md`'s "### Datadog (`DD_API_KEY` is the master switch — unset = fully disabled)" section, add a bullet after the existing `DD_EXPORTER=agent` line:

```markdown
- `DD_LLMOBS_ENABLED`: independent kill switch for Agent Observability (see
  above); defaults to on whenever `DD_API_KEY` is set.
```

- [ ] **Step 3: Add `lib/llmobs.py` to "Key files"**

In `OTEL.md`'s "Core observability" file list, add:

```markdown
- `agent/lib/llmobs.py` — Agent Observability (Datadog LLM Obs) span helpers
```

- [ ] **Step 4: Commit**

```bash
git add OTEL.md
git commit -m "$(cat <<'EOF'
docs: document Datadog Agent Observability in OTEL.md

🌸 Shipped with Kanna — https://kanna.sh

Co-Authored-By: Kanna <noreply@kanna.sh>
Kanna-Agent: claude/sonnet
EOF
)"
```
