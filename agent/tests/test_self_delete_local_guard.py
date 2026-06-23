from unittest.mock import patch
from lib.self_delete import self_delete


def test_skips_http_call_for_local_prefix(monkeypatch):
    monkeypatch.setenv("DAYTONA_API_KEY", "dt-key")
    with patch("httpx.delete") as mock_del:
        self_delete(sandbox_id="local-abc123")
        mock_del.assert_not_called()


def test_skips_http_call_for_env_local_prefix(monkeypatch):
    monkeypatch.setenv("DAYTONA_API_KEY", "dt-key")
    monkeypatch.setenv("DAYTONA_SANDBOX_ID", "local-from-env")
    with patch("httpx.delete") as mock_del:
        self_delete()
        mock_del.assert_not_called()
