from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from mcp.server import MCPServer

from .settings import Settings
from .spotify import SpotifyClient
from .tool_support import AppContext
from .tools_read import register_read_tools
from .tools_write import register_write_tools

INSTRUCTIONS = (
    "Spotify tools acting as the logged-in user, for assembling DJ sets from their account. "
    "Typical workflow: list_my_playlists to find a playlist id, get_playlist_items to read its "
    "tracks, search (or get_artist_albums / get_related_artists) to discover more, create_playlist "
    "for the new set, then add_playlist_items to fill it. Playlist contents can only be read or "
    "written for playlists the user owns or collaborates on. search returns at most 10 results per "
    "call; every list tool pages via `offset` and reports `next_offset` (null once exhausted). "
    "Tools whose description starts with DEPRECATED only work for Spotify apps created before "
    "2024-11-27 — treat a failure there as final, do not retry."
)


def build_server(settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> MCPServer:
    @asynccontextmanager
    async def lifespan(server: MCPServer) -> AsyncIterator[AppContext]:
        async with httpx.AsyncClient(timeout=20, transport=transport) as http:
            yield AppContext(spotify=SpotifyClient(settings, http))

    mcp = MCPServer("spotify", instructions=INSTRUCTIONS, lifespan=lifespan)
    register_read_tools(mcp)
    register_write_tools(mcp)
    return mcp
