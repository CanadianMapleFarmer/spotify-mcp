import json
import os
import subprocess
import sys

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

pytestmark = pytest.mark.slow


def _serve_env(tmp_path) -> dict:
    return {
        **os.environ,
        "SPOTIFY_CLIENT_ID": "cid",
        "SPOTIFY_CLIENT_SECRET": "csecret",
        "SPOTIFY_MCP_CONFIG_DIR": str(tmp_path),
    }


@pytest.mark.anyio
async def test_stdio_serve_lists_tools_with_clean_stdout(tmp_path):
    params = StdioServerParameters(command=sys.executable, args=["-m", "spotify_mcp", "serve"], env=_serve_env(tmp_path))
    async with Client(params, raise_exceptions=True) as c:
        tools = (await c.list_tools()).tools
        assert len(tools) == 24


def _rpc(id_or_none, method: str, params: dict) -> bytes:
    body: dict = {"jsonrpc": "2.0", "method": method, "params": params}
    if id_or_none is not None:
        body["id"] = id_or_none
    return (json.dumps(body) + "\n").encode()


def test_stdio_serve_emits_only_json_rpc_on_stdout(tmp_path):
    proc = subprocess.Popen(
        [sys.executable, "-m", "spotify_mcp", "serve"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_serve_env(tmp_path),
        text=True,
        bufsize=1,
    )
    try:
        proc.stdin.write(
            _rpc(
                1,
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "stdout-smoke-test", "version": "0.0.1"},
                },
            ).decode()
        )
        proc.stdin.flush()
        init_line = proc.stdout.readline()

        proc.stdin.write(_rpc(None, "notifications/initialized", {}).decode())
        proc.stdin.flush()

        proc.stdin.write(_rpc(2, "tools/list", {}).decode())
        proc.stdin.flush()
        tools_line = proc.stdout.readline()
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

    for line in (init_line, tools_line):
        parsed = json.loads(line)
        assert parsed["jsonrpc"] == "2.0"

    tools_result = json.loads(tools_line)
    assert len(tools_result["result"]["tools"]) == 24

    stderr = proc.stderr.read()
    assert "spotify-mcp" in stderr
    assert "stdio" in stderr
