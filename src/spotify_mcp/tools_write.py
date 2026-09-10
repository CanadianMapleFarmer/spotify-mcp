from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from .spotify import slim_playlist
from .tool_support import AppContext, DESTRUCTIVE, Offset, Uris, WRITE, WRITE_IDEMPOTENT, api


def register_write_tools(mcp: MCPServer) -> None:
    @mcp.tool(annotations=WRITE)
    async def create_playlist(
        ctx: Context[AppContext],
        name: str,
        description: str = "",
        public: bool = False,
        collaborative: bool = False,
    ) -> dict[str, Any]:
        """Create a new playlist for the logged-in user to hold a DJ set. Follow up with add_playlist_items to fill it."""
        body = {"name": name, "description": description, "public": public, "collaborative": collaborative}
        return slim_playlist(await api(ctx).request("POST", "/me/playlists", json=body))

    @mcp.tool(annotations=WRITE_IDEMPOTENT)
    async def update_playlist_details(
        ctx: Context[AppContext],
        playlist_id: str,
        name: str | None = None,
        description: str | None = None,
        public: bool | None = None,
        collaborative: bool | None = None,
    ) -> dict[str, Any]:
        """Rename, redescribe or toggle public/collaborative on a playlist the user owns. Only the fields you pass are changed."""
        body = {
            k: v
            for k, v in {"name": name, "description": description, "public": public, "collaborative": collaborative}.items()
            if v is not None
        }
        if not body:
            raise ToolError("Provide at least one of name, description, public or collaborative to update.")
        data = await api(ctx).request("PUT", f"/playlists/{playlist_id}", json=body)
        return data or {"playlist_id": playlist_id, "updated": True}

    @mcp.tool(annotations=WRITE)
    async def add_playlist_items(
        ctx: Context[AppContext], playlist_id: str, uris: Uris, position: Offset | None = None
    ) -> dict[str, Any]:
        """Append 1-100 spotify:track: URIs to a playlist the user owns or collaborates on; pass position to insert instead of appending. Use search or get_playlist_items to find URIs first."""
        body: dict[str, Any] = {"uris": uris}
        if position is not None:
            body["position"] = position
        return await api(ctx).request("POST", f"/playlists/{playlist_id}/items", json=body)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def remove_playlist_items(
        ctx: Context[AppContext], playlist_id: str, uris: Uris, snapshot_id: str | None = None
    ) -> dict[str, Any]:
        """Remove every occurrence of 1-100 spotify:track: URIs from a playlist the user owns. Pass the playlist's snapshot_id to guard against concurrent edits."""
        body: dict[str, Any] = {"items": [{"uri": u} for u in uris]}
        if snapshot_id:
            body["snapshot_id"] = snapshot_id
        return await api(ctx).request("DELETE", f"/playlists/{playlist_id}/items", json=body)

    @mcp.tool(annotations=WRITE)
    async def reorder_playlist_items(
        ctx: Context[AppContext],
        playlist_id: str,
        range_start: Offset,
        insert_before: Offset,
        range_length: Annotated[int, Field(ge=1, description="How many consecutive items to move, starting at range_start.")] = 1,
        snapshot_id: str | None = None,
    ) -> dict[str, Any]:
        """Move a block of items within a playlist the user owns: range_length items starting at range_start end up positioned just before insert_before."""
        body: dict[str, Any] = {"range_start": range_start, "insert_before": insert_before, "range_length": range_length}
        if snapshot_id:
            body["snapshot_id"] = snapshot_id
        return await api(ctx).request("PUT", f"/playlists/{playlist_id}/items", json=body)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def replace_playlist_items(
        ctx: Context[AppContext],
        playlist_id: str,
        uris: Annotated[list[str], Field(max_length=100, description="0-100 spotify:track:... URIs; empty list clears the playlist.")],
    ) -> dict[str, Any]:
        """Replace the entire contents of a playlist the user owns with 0-100 spotify:track: URIs. An empty list clears it. Use add_playlist_items instead if you only want to append."""
        return await api(ctx).request("PUT", f"/playlists/{playlist_id}/items", json={"uris": uris})
