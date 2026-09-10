from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from .spotify import slim_album, slim_artist, slim_playlist, slim_track
from .tool_support import (
    AppContext,
    Limit50,
    Offset,
    READ,
    api,
    deprecated,
    playlist_entry,
    saved_album_entry,
    slim_page,
)

SearchLimit = Annotated[int, Field(ge=1, le=10, description="Max results per requested type, 1-10 (Spotify cap).")]
SearchOffset = Annotated[int, Field(ge=0, le=1000, description="Zero-based paging offset, max 1000.")]
SearchTypes = Annotated[
    list[Literal["track", "artist", "album", "playlist"]],
    Field(min_length=1, max_length=4, description="Which entity types to search; at least one."),
]
IncludeGroup = Literal["album", "single", "appears_on", "compilation"]

_SEARCH_MAPPERS = {"tracks": slim_track, "artists": slim_artist, "albums": slim_album, "playlists": slim_playlist}


def register_read_tools(mcp: MCPServer) -> None:
    @mcp.tool(annotations=READ)
    async def get_current_user(ctx: Context[AppContext]) -> dict[str, Any]:
        """Profile of the logged-in Spotify user (id, display_name). Call this first to confirm which account is connected."""
        return await api(ctx).request("GET", "/me")

    @mcp.tool(annotations=READ)
    async def list_my_playlists(ctx: Context[AppContext], limit: Limit50 = 50, offset: Offset = 0) -> dict[str, Any]:
        """List playlists the user owns or follows. Start here when building a DJ set — the returned id feeds get_playlist_items. Paginate with offset when next_offset is not null."""
        data = await api(ctx).request("GET", "/me/playlists", params={"limit": limit, "offset": offset})
        return slim_page(data, slim_playlist)

    @mcp.tool(annotations=READ)
    async def get_playlist(ctx: Context[AppContext], playlist_id: str) -> dict[str, Any]:
        """Metadata for one playlist (name, description, owner, item count). Contents are only readable for playlists the user owns or collaborates on — use get_playlist_items for tracks."""
        return slim_playlist(await api(ctx).request("GET", f"/playlists/{playlist_id}"))

    @mcp.tool(annotations=READ)
    async def get_playlist_items(
        ctx: Context[AppContext], playlist_id: str, limit: Limit50 = 50, offset: Offset = 0
    ) -> dict[str, Any]:
        """Read the tracks of one of my playlists (only playlists I own or collaborate on). Use list_my_playlists first to find the id. Paginate with offset until next_offset is null."""
        params = {"limit": limit, "offset": offset, "additional_types": "track"}
        data = await api(ctx).request("GET", f"/playlists/{playlist_id}/items", params=params)
        return slim_page(data, playlist_entry)

    @mcp.tool(annotations=READ)
    async def search(
        ctx: Context[AppContext],
        q: Annotated[str, Field(description="Query text; supports artist:, track:, album:, year:, isrc: filters.")],
        types: SearchTypes = ["track"],
        limit: SearchLimit = 10,
        offset: SearchOffset = 0,
    ) -> dict[str, Any]:
        """Search Spotify's catalog for tracks/artists/albums/playlists to add to a set. At most 10 results per requested type per call — paginate with offset (max 1000)."""
        params = {"q": q, "type": ",".join(types), "limit": limit, "offset": offset}
        data = await api(ctx).request("GET", "/search", params=params)
        return {k: slim_page(v, _SEARCH_MAPPERS.get(k, lambda x: x)) for k, v in data.items() if isinstance(v, dict)}

    @mcp.tool(annotations=READ)
    async def get_track(ctx: Context[AppContext], track_id: str) -> dict[str, Any]:
        """A single track by id. One call per id — Spotify removed the batch /tracks?ids= endpoint for dev-mode apps."""
        return slim_track(await api(ctx).request("GET", f"/tracks/{track_id}"))

    @mcp.tool(annotations=READ)
    async def get_artist(ctx: Context[AppContext], artist_id: str) -> dict[str, Any]:
        """A single artist by id (name, genres, images). Use search to find the id first."""
        return slim_artist(await api(ctx).request("GET", f"/artists/{artist_id}"))

    @mcp.tool(annotations=READ)
    async def get_artist_albums(
        ctx: Context[AppContext],
        artist_id: str,
        include_groups: Annotated[list[IncludeGroup] | None, Field(description="Subset of album,single,appears_on,compilation; omit for all.")] = None,
        limit: Limit50 = 20,
        offset: Offset = 0,
    ) -> dict[str, Any]:
        """An artist's albums, singles and compilations — useful for finding more tracks by an artist already in a set. Paginate with offset."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if include_groups:
            params["include_groups"] = ",".join(include_groups)
        data = await api(ctx).request("GET", f"/artists/{artist_id}/albums", params=params)
        return slim_page(data, slim_album)

    @mcp.tool(annotations=READ)
    async def get_album(ctx: Context[AppContext], album_id: str) -> dict[str, Any]:
        """An album by id with its metadata and the first page of tracks. Use get_album_tracks to page through the rest."""
        data = await api(ctx).request("GET", f"/albums/{album_id}")
        return {**slim_album(data), "tracks": slim_page(data.get("tracks") or {}, slim_track)}

    @mcp.tool(annotations=READ)
    async def get_album_tracks(
        ctx: Context[AppContext], album_id: str, limit: Limit50 = 50, offset: Offset = 0
    ) -> dict[str, Any]:
        """Paged tracks of an album by id. Paginate with offset until next_offset is null."""
        data = await api(ctx).request("GET", f"/albums/{album_id}/tracks", params={"limit": limit, "offset": offset})
        return slim_page(data, slim_track)

    @mcp.tool(annotations=READ)
    async def get_liked_songs(ctx: Context[AppContext], limit: Limit50 = 50, offset: Offset = 0) -> dict[str, Any]:
        """The user's Liked Songs, newest first — a good source of DJ set material. Paginate with offset."""
        data = await api(ctx).request("GET", "/me/tracks", params={"limit": limit, "offset": offset})
        return slim_page(data, playlist_entry)

    @mcp.tool(annotations=READ)
    async def get_saved_albums(ctx: Context[AppContext], limit: Limit50 = 50, offset: Offset = 0) -> dict[str, Any]:
        """The user's saved albums, newest first. Paginate with offset."""
        data = await api(ctx).request("GET", "/me/albums", params={"limit": limit, "offset": offset})
        return slim_page(data, saved_album_entry)

    @mcp.tool(annotations=READ)
    async def get_top_items(
        ctx: Context[AppContext],
        type: Literal["artists", "tracks"],
        time_range: Literal["short_term", "medium_term", "long_term"] = "medium_term",
        limit: Limit50 = 20,
        offset: Offset = 0,
    ) -> dict[str, Any]:
        """The user's most-played artists or tracks over the last ~4 weeks (short_term), ~6 months (medium_term) or ~1 year (long_term). Good seed material for a set that matches the user's taste. Paginate with offset."""
        params = {"time_range": time_range, "limit": limit, "offset": offset}
        data = await api(ctx).request("GET", f"/me/top/{type}", params=params)
        return slim_page(data, slim_track if type == "tracks" else slim_artist)

    @mcp.tool(annotations=READ)
    async def get_recently_played(
        ctx: Context[AppContext],
        limit: Limit50 = 50,
        after: Annotated[int | None, Field(description="Unix ms; return items played after this cursor. Mutually exclusive with before.")] = None,
        before: Annotated[int | None, Field(description="Unix ms; return items played before this cursor. Mutually exclusive with after.")] = None,
    ) -> dict[str, Any]:
        """Recently played tracks with when they were played — useful for avoiding repeats in a new set. Pass after OR before (not both) to page through history using the returned cursors."""
        if after is not None and before is not None:
            raise ToolError("Pass either `after` or `before`, not both.")
        params: dict[str, Any] = {"limit": limit}
        if after is not None:
            params["after"] = after
        if before is not None:
            params["before"] = before
        data = await api(ctx).request("GET", "/me/player/recently-played", params=params)
        items = [{"played_at": i.get("played_at"), **slim_track(i.get("track"))} for i in data.get("items", []) if i]
        return {"items": items, "cursors": data.get("cursors")}

    @mcp.tool(annotations=READ, description=deprecated("Tempo, key, energy and other audio features for one track by id — the only source of BPM for DJ matching, when it works."))
    async def get_audio_features(ctx: Context[AppContext], track_id: str) -> dict[str, Any]:
        return await api(ctx).request("GET", f"/audio-features/{track_id}", restricted=True)

    @mcp.tool(annotations=READ, description=deprecated("Seed-based track recommendations from up to 5 combined seed_tracks/seed_artists/seed_genres."))
    async def get_recommendations(
        ctx: Context[AppContext],
        seed_tracks: list[str] | None = None,
        seed_artists: list[str] | None = None,
        seed_genres: list[str] | None = None,
        limit: Limit50 = 20,
    ) -> dict[str, Any]:
        if not (seed_tracks or seed_artists or seed_genres):
            raise ToolError("Provide at least one of seed_tracks, seed_artists or seed_genres.")
        params: dict[str, Any] = {"limit": limit}
        if seed_tracks:
            params["seed_tracks"] = ",".join(seed_tracks)
        if seed_artists:
            params["seed_artists"] = ",".join(seed_artists)
        if seed_genres:
            params["seed_genres"] = ",".join(seed_genres)
        data = await api(ctx).request("GET", "/recommendations", params=params, restricted=True)
        return {"items": [slim_track(t) for t in data.get("tracks", [])]}

    @mcp.tool(annotations=READ, description=deprecated("Artists similar to a given artist, for widening a set around a sound."))
    async def get_related_artists(ctx: Context[AppContext], artist_id: str) -> dict[str, Any]:
        data = await api(ctx).request("GET", f"/artists/{artist_id}/related-artists", restricted=True)
        return {"items": [slim_artist(a) for a in data.get("artists", [])]}

    @mcp.tool(annotations=READ, description=deprecated("An artist's top tracks. Use `search` with an `artist:` filter instead when this fails."))
    async def get_artist_top_tracks(ctx: Context[AppContext], artist_id: str) -> dict[str, Any]:
        data = await api(ctx).request("GET", f"/artists/{artist_id}/top-tracks", restricted=True)
        return {"items": [slim_track(t) for t in data.get("tracks", [])]}
