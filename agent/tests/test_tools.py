from unittest.mock import MagicMock, patch
import lib.tools as tools


def _spy(monkeypatch):
    logs = []
    monkeypatch.setattr(tools, "emit_log",
                        lambda level, msg, **kw: logs.append((level, msg, kw)))
    span = MagicMock()
    monkeypatch.setattr(tools.trace, "get_current_span", lambda: span)
    return logs, span


def test_observed_tool_ok(monkeypatch):
    logs, span = _spy(monkeypatch)
    run = tools._observed_tool("get_x", lambda args: {"value": args["ticker"]})
    out = run({"ticker": "AAPL"})
    assert out == {"value": "AAPL"}
    assert ("info", "tool.get_x.ok", {"ticker": "AAPL"}) in logs
    span.add_event.assert_any_call("tool.get_x", {"outcome": "ok"})


def test_observed_tool_swallows_exception(monkeypatch):
    logs, span = _spy(monkeypatch)
    def boom(args):
        raise RuntimeError("nope")
    run = tools._observed_tool("get_x", boom)
    out = run({"ticker": "AAPL"})
    assert "error" in out and "nope" in out["error"]
    assert any(lvl == "warn" and m == "tool.get_x.failed" and "nope" in kw.get("reason", "")
               for lvl, m, kw in logs)
    ev = span.add_event.call_args_list[-1]
    assert ev.args[0] == "tool.get_x" and ev.args[1]["outcome"] == "error"
    assert "nope" in ev.args[1]["error"]


def test_observed_tool_treats_error_dict_as_failure(monkeypatch):
    logs, span = _spy(monkeypatch)
    run = tools._observed_tool("get_x", lambda args: {"error": "no data"})
    out = run({"ticker": "AAPL"})
    assert out == {"error": "no data"}
    assert any(m == "tool.get_x.failed" for _, m, _ in logs)
    span.add_event.assert_any_call("tool.get_x", {"outcome": "error", "error": "no data"})
