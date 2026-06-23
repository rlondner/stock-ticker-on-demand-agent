import os
import httpx

def self_delete(sandbox_id: str | None = None) -> None:
    """DELETE this sandbox via the Daytona REST API. Never raises.
    Safety net: Daytona's autoDeleteInterval reclaims the sandbox if this fails.

    sandbox_id is preferred; falls back to the DAYTONA_SANDBOX_ID env var."""
    sid = sandbox_id or os.environ.get("DAYTONA_SANDBOX_ID")
    api_key = os.environ.get("DAYTONA_API_KEY")
    if not sid or not api_key:
        return
    if sid.startswith("local-"):
        return
    base = os.environ.get("DAYTONA_API_URL", "https://app.daytona.io/api")
    try:
        httpx.delete(
            f"{base}/sandbox/{sid}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
    except Exception:
        pass
