import os
import sys
import time
import traceback
from opentelemetry import trace
from lib.observability import init_observability, flush_observability, record_error, emit_log, get_host
from lib.db import get_job, mark_running, mark_complete, mark_failed
from lib.llm import run_analysis
import lib.metrics as _metrics
from lib.self_delete import self_delete

JOB_ID = os.environ.get("JOB_ID", "")

# Env vars we expect NextJS to inject into the sandbox. Logged as booleans
# (never values) at boot so it's possible to verify what actually landed —
# useful when the Daytona sandbox has already self-deleted before you can
# inspect it in the dashboard.
EXPECTED_ENV_VARS = (
    "JOB_ID",
    "NEON_DATABASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_API_URL",
    "OPENAI_MODEL",
    "OPENAI_USE_RESPONSES_API",
    "DAYTONA_API_KEY",
    "TRACEPARENT",
    "SENTRY_DSN_AGENT",
    "DD_API_KEY",
    "DD_SITE",
    "DD_SERVICE",
    "DD_ENV",
    "DD_TRACE_ENABLED",
    "DD_EXPORTER",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_HEADERS",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
    "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
    "AGENT_SOURCE",
)


def _env_presence() -> dict[str, bool]:
    return {f"env_has_{k}": bool(os.environ.get(k)) for k in EXPECTED_ENV_VARS}

def main() -> None:
    if not JOB_ID:
        print("JOB_ID not set", file=sys.stderr)
        sys.exit(2)

    init_observability(job_id=JOB_ID)
    tracer = trace.get_tracer("stock-agent")

    emit_log("info", "agent.started", job_id=JOB_ID, **_env_presence())

    final_status = "unknown"
    started_at = time.monotonic()
    with tracer.start_as_current_span("agent.run") as span:
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

            mark_running(JOB_ID)
            result = run_analysis(ticker=job["ticker"])
            mark_complete(JOB_ID, recommendation=result["recommendation"], result=result)
            final_status = "complete"
        except Exception as e:
            record_error(span, e)
            mark_failed(JOB_ID, error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
            final_status = "failed"
            raise
        finally:
            duration_ms = (time.monotonic() - started_at) * 1000
            ticker = (job["ticker"] if job else "unknown")
            span.set_attribute("final_status", final_status)
            _metrics.record_job_completed(final_status, ticker)
            _metrics.record_agent_run_duration(final_status, ticker, duration_ms)
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
                # Prefer the sandbox_id from the job row (written by NextJS after dt.create).
                # Fall back to the env var inside self_delete() for any custom setup.
                sandbox_id = (job["sandbox_id"] if job and "sandbox_id" in job else None)
                self_delete(sandbox_id=sandbox_id)
            except Exception:
                pass

if __name__ == "__main__":
    main()
