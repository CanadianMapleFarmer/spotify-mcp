import time

import httpx
from typer.testing import CliRunner

import spotify_mcp.cli as cli
from spotify_mcp.auth import Token, save_token
from spotify_mcp.server import build_server
from spotify_mcp.settings import Settings

runner = CliRunner()


def test_status_exit_1_with_no_token(monkeypatch, tmp_path):
    monkeypatch.setenv("SPOTIFY_MCP_CONFIG_DIR", str(tmp_path))
    result = runner.invoke(cli.app, ["status"])
    assert result.exit_code == 1
    assert "none" in result.stderr


def test_status_exit_0_with_seeded_token(monkeypatch, tmp_path):
    monkeypatch.setenv("SPOTIFY_MCP_CONFIG_DIR", str(tmp_path))
    settings = Settings(client_id="cid", client_secret="csecret", config_dir=tmp_path)
    save_token(settings, Token("at", "rt", time.time() + 3600, "user-read-private", "cid"))
    result = runner.invoke(cli.app, ["status"])
    assert result.exit_code == 0
    assert "valid for" in result.stderr


def test_tools_lists_all_24_offline(monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
    server = build_server(Settings(client_id="", client_secret=""))

    async def _names():
        from mcp import Client

        async with Client(server, raise_exceptions=True) as c:
            return [t.name for t in (await c.list_tools()).tools]

    import asyncio

    names = asyncio.run(_names())
    assert len(names) == 24

    result = runner.invoke(cli.app, ["tools"])
    assert result.exit_code == 0
    for name in names:
        assert name in result.stderr
    assert result.stdout == ""


def test_serve_help_mentions_both_transports():
    result = runner.invoke(cli.app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "stdio" in result.output
    assert "streamable-http" in result.output


def test_whoami_uses_mocked_client_factory(monkeypatch, tmp_path):
    monkeypatch.setenv("SPOTIFY_MCP_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "cid")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "csecret")
    settings = Settings(client_id="cid", client_secret="csecret", config_dir=tmp_path)
    save_token(settings, Token("at", "rt", time.time() + 3600, "user-read-private", "cid"))

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer at"
        return httpx.Response(200, json={"id": "me1", "display_name": "Gerhard", "product": "premium"})

    monkeypatch.setattr(cli, "_new_http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    result = runner.invoke(cli.app, ["whoami"])
    assert result.exit_code == 0
    assert "Gerhard" in result.stderr
    assert result.stdout == ""


def test_whoami_reports_error_without_login(monkeypatch, tmp_path):
    monkeypatch.setenv("SPOTIFY_MCP_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "cid")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "csecret")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not reach Spotify when not logged in")

    monkeypatch.setattr(cli, "_new_http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    result = runner.invoke(cli.app, ["whoami"])
    assert result.exit_code == 1
    assert "Not logged in" in result.stderr


def test_missing_env_reports_exit_1(monkeypatch, tmp_path):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
    result = runner.invoke(cli.app, ["whoami"])
    assert result.exit_code == 1
    assert "SPOTIFY_CLIENT_ID" in result.stderr
