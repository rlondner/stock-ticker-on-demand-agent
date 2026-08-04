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


def _chat_usage(resp):
    u = getattr(resp, "usage", None)
    tin = getattr(u, "prompt_tokens", 0) if u else 0
    tout = getattr(u, "completion_tokens", 0) if u else 0
    return (tin or 0), (tout or 0)


def run_chat_completions_loop(create_chat, initial_messages, tools, function_registry,
                              max_iters=6, timeout_s=90.0):
    """chat.completions-shape sibling of run_agent_loop. Drives ``create_chat``
    (called with ``messages=`` and ``tools=``), dispatches OpenAI-style
    ``tool_calls`` through ``function_registry``, and stops at a final text
    answer or an iteration/time budget. On budget exhaust it makes one final
    no-tools call to force an answer, mirroring the Responses loop."""
    conversation = list(initial_messages)
    tools_used: list[str] = []
    tokens_in = tokens_out = 0
    iterations = 0
    start = time.monotonic()

    while iterations < max_iters and (time.monotonic() - start) < timeout_s:
        iterations += 1
        resp = create_chat(messages=conversation, tools=tools)
        tin, tout = _chat_usage(resp)
        tokens_in += tin
        tokens_out += tout

        choice = resp.choices[0]
        msg = choice.message
        tool_calls = list(getattr(msg, "tool_calls", None) or [])

        if not tool_calls:
            return LoopResult(getattr(msg, "content", "") or "", iterations,
                              tools_used, tokens_in, tokens_out, budget_exhausted=False)

        # Echo the assistant turn (with its tool_calls) back before the tool
        # results so the follow-up call sees a valid transcript. The provider
        # requires tool messages to reference an assistant message whose
        # tool_calls include the same call_id.
        conversation.append({
            "role": "assistant",
            "content": getattr(msg, "content", None),
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"},
                }
                for tc in tool_calls
            ],
        })

        for tc in tool_calls:
            name = tc.function.name
            tools_used.append(name)
            fn = function_registry.get(name)
            try:
                args = json.loads(tc.function.arguments or "{}")
                result = fn(args) if fn else {"error": f"unknown tool {name!r}"}
                output_str = result if isinstance(result, str) else json.dumps(result)
            except Exception as e:  # tool failure is fed back, never crashes the loop
                output_str = json.dumps({"error": str(e)})
            conversation.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": output_str,
            })

    # Budget/time exhausted: one final no-tools request to force an answer.
    resp = create_chat(messages=conversation, tools=None)
    tin, tout = _chat_usage(resp)
    tokens_in += tin
    tokens_out += tout
    final = resp.choices[0].message
    return LoopResult(getattr(final, "content", "") or "", iterations,
                      tools_used, tokens_in, tokens_out, budget_exhausted=True)
