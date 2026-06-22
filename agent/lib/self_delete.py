import os
import httpx

def self_delete() -> None:
    """DELETE this sandbox via the Daytona REST API. Never raises.
    Safety net: Daytona's autoDeleteInterval reclaims the sandbox if this fails."""
    sandbox_id = os.environ.get("DAYTONA_SANDBOX_ID")
    api_key = os.environ.get("DAYTONA_API_KEY")
    if not sandbox_id or not api_key:
        return
    base = os.environ.get("DAYTONA_API_URL", "https://app.daytona.io/api")
    try:
        httpx.delete(
            f"{base}/sandbox/{sandbox_id}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
    except Exception:
        pass
