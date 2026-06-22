import os
import pytest

@pytest.fixture(autouse=True)
def reset_env(monkeypatch):
    """Ensure each test starts from a known env baseline."""
    for var in ("SENTRY_DSN_AGENT", "DD_API_KEY", "TRACEPARENT", "JOB_ID"):
        monkeypatch.delenv(var, raising=False)
    yield
