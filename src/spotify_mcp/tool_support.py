from dataclasses import dataclass
from typing import Annotated, Any, Callable

from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations
from pydantic import Field

from .spotify import SpotifyClient, page, slim_album, slim_track

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True)
WRITE_IDEMPOTENT = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=True)
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=True)

DEPRECATED_NOTE = (
    "Spotify disabled this endpoint for apps created after 2024-11-27 (and for Development Mode "
    "apps generally); it only works for legacy/extended-quota developer apps and returns a 403 "
    "with no replacement endpoint otherwise."
)

Limit50 = Annotated[int, Field(ge=1, le=50, description="Page size, 1-50.")]
Offset = Annotated[int, Field(ge=0, description="Zero-based paging offset.")]
Uris = Annotated[list[str], Field(min_length=1, max_length=100, description="1-100 spotify:track:... URIs.")]


@dataclass
class AppContext:
    spotify: SpotifyClient


def api(ctx: Context[AppContext]) -> SpotifyClient:
    return ctx.request_context.lifespan_context.spotify


def slim_page(data: dict[str, Any], mapper: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    result = page(data)
    return {**result, "items": [mapper(i) for i in result["items"] if i]}


def playlist_entry(i: dict[str, Any]) -> dict[str, Any]:
    return {"added_at": i.get("added_at"), **slim_track(i.get("item") or i.get("track"))}


def saved_album_entry(i: dict[str, Any]) -> dict[str, Any]:
    return {"added_at": i.get("added_at"), **slim_album(i.get("album"))}


def deprecated(text: str) -> str:
    return f"DEPRECATED: {DEPRECATED_NOTE} {text}"
