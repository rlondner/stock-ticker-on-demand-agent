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
