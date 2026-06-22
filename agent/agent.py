import os
import sys
import traceback
from opentelemetry import trace
from lib.observability import init_observability, flush_observability, record_error
from lib.db import get_job, mark_running, mark_complete, mark_failed
from lib.llm import run_analysis
from lib.self_delete import self_delete

JOB_ID = os.environ.get("JOB_ID", "")

def main() -> None:
    if not JOB_ID:
        print("JOB_ID not set", file=sys.stderr)
        sys.exit(2)

    init_observability(job_id=JOB_ID)
    tracer = trace.get_tracer("stock-agent")

    with tracer.start_as_current_span("agent.run") as span:
        span.set_attribute("job_id", JOB_ID)
        try:
            job = get_job(JOB_ID)
            if job is None or job["status"] != "pending":
                print(f"job {JOB_ID} not pending (status={job and job['status']}); exiting", file=sys.stderr)
                return
            span.set_attribute("ticker", job["ticker"])

            mark_running(JOB_ID)
            result = run_analysis(ticker=job["ticker"])
            mark_complete(JOB_ID, recommendation=result["recommendation"], result=result)
            span.set_attribute("final_status", "complete")
        except Exception as e:
            record_error(span, e)
            mark_failed(JOB_ID, error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
            span.set_attribute("final_status", "failed")
            raise
        finally:
            flush_observability()
            try:
                self_delete()
            except Exception:
                pass

if __name__ == "__main__":
    main()
