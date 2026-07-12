"""Custom function tools the agentic thesis loop can call for precise, on-demand
structured data (yfinance-backed). Decoupled from agent_loop and llm. Every tool
is wrapped by _observed_tool so it can never crash the loop and every call is
visible in logs + on the current trace span."""
import yfinance
from opentelemetry import trace

from .observability import emit_log


def _observed_tool(name, fn):
    """Wrap a raw tool(args)->dict with uniform guarding + observability.
    Emits tool.<name>.ok / .failed logs and an outcome span event on every call.
    A raised exception OR a returned {'error': ...} counts as a failure; a tool
    can never crash the loop (a failure returns {'error': ...})."""
    def _run(args):
        args = args or {}
        ticker = args.get("ticker")
        span = trace.get_current_span()
        try:
            result = fn(args)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            emit_log("warn", f"tool.{name}.failed", ticker=ticker, reason=reason)
            span.add_event(f"tool.{name}", {"outcome": "error", "error": reason})
            return {"error": reason}
        if isinstance(result, dict) and "error" in result:
            emit_log("warn", f"tool.{name}.failed", ticker=ticker, reason=str(result["error"]))
            span.add_event(f"tool.{name}", {"outcome": "error", "error": str(result["error"])})
            return result
        emit_log("info", f"tool.{name}.ok", ticker=ticker)
        span.add_event(f"tool.{name}", {"outcome": "ok"})
        return result

    return _run
