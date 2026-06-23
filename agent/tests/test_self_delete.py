from unittest.mock import patch, MagicMock
import httpx
from lib.self_delete import self_delete

def test_self_delete_calls_daytona_api(monkeypatch):
    monkeypatch.setenv("DAYTONA_API_KEY", "dt-test")
    monkeypatch.setenv("DAYTONA_SANDBOX_ID", "sb-abc")
    monkeypatch.setenv("DAYTONA_API_URL", "https://api.daytona.test")
    fake = MagicMock(status_code=200)
    with patch("httpx.delete", return_value=fake) as mock_del:
        self_delete()
        mock_del.assert_called_once()
        url, kwargs = mock_del.call_args.args[0], mock_del.call_args.kwargs
        assert "sb-abc" in url
        assert kwargs["headers"]["Authorization"] == "Bearer dt-test"

def test_self_delete_swallows_network_error(monkeypatch):
    monkeypatch.setenv("DAYTONA_API_KEY", "dt-test")
    monkeypatch.setenv("DAYTONA_SANDBOX_ID", "sb-abc")
    with patch("httpx.delete", side_effect=httpx.ConnectError("boom")):
        self_delete()

def test_self_delete_no_op_when_sandbox_id_unset(monkeypatch):
    monkeypatch.delenv("DAYTONA_SANDBOX_ID", raising=False)
    with patch("httpx.delete") as mock_del:
        self_delete()
        mock_del.assert_not_called()

def test_self_delete_uses_parameter_when_provided(monkeypatch):
    monkeypatch.setenv("DAYTONA_API_KEY", "dt-test")
    monkeypatch.delenv("DAYTONA_SANDBOX_ID", raising=False)
    fake = MagicMock(status_code=200)
    with patch("httpx.delete", return_value=fake) as mock_del:
        self_delete(sandbox_id="sb-from-param")
        mock_del.assert_called_once()
        url = mock_del.call_args.args[0]
        assert "sb-from-param" in url
