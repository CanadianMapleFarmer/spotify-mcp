import os
import sys

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

pytestmark = pytest.mark.slow


@pytest.mark.anyio
async def test_stdio_serve_lists_tools_with_clean_stdout(tmp_path):
    env = {
        **os.environ,
        "SPOTIFY_CLIENT_ID": "cid",
        "SPOTIFY_CLIENT_SECRET": "csecret",
        "SPOTIFY_MCP_CONFIG_DIR": str(tmp_path),
    }
    params = StdioServerParameters(command=sys.executable, args=["-m", "spotify_mcp", "serve"], env=env)
    async with Client(params, raise_exceptions=True) as c:
        tools = (await c.list_tools()).tools
        assert len(tools) == 24
