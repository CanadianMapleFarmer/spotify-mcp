import asyncio
from typing import Any

import httpx
from mcp.server.mcpserver.exceptions import ToolError

from . import auth
from .settings import Settings

API = "https://api.spotify.com/v1"
MAX_RETRY_AFTER_S = 30

RESTRICTED_MESSAGE = (
    "Spotify no longer allows this endpoint for apps created after 2024-11-27 or running in "
    "Development Mode (HTTP 403). There is no replacement endpoint."
)
OWNERSHIP_MESSAGE = (
    "Spotify returned 403: this resource is only available for content the logged-in user owns, "
    "collaborates on, or has permission to access."
)
QUOTA_MESSAGE = "Spotify Development Mode quota for this developer account is exhausted; try again later."
NOT_LOGGED_IN_MESSAGE = "Not logged in. Run `spotify-mcp login` in a terminal first."
REAUTH_MESSAGE = "Spotify rejected the token (401). Run `spotify-mcp login` again."


class SpotifyClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self.settings = settings
        self.http = http
        self._lock = asyncio.Lock()

    async def _access_token(self) -> str:
        async with self._lock:
            token = auth.load_token(self.settings)
            if token is None:
                raise ToolError(NOT_LOGGED_IN_MESSAGE)
            if token.expired:
                if not self.settings.client_id or not self.settings.client_secret:
                    raise ToolError("SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET are not set; cannot refresh the token.")
                try:
                    token = await auth.refresh(self.http, self.settings, token)
                except auth.AuthError as e:
                    raise ToolError(str(e)) from e
            return token.access_token

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        restricted: bool = False,
    ) -> dict[str, Any] | None:
        headers = {"Authorization": f"Bearer {await self._access_token()}"}
        r = await self.http.request(method, f"{API}{path}", params=params, json=json, headers=headers)
        if r.status_code == 429:
            if _reason(r) == "QUOTA_EXCEEDED":
                raise ToolError(QUOTA_MESSAGE)
            wait_s = min(int(r.headers.get("Retry-After", "1")), MAX_RETRY_AFTER_S)
            await asyncio.sleep(wait_s)
            r = await self.http.request(method, f"{API}{path}", params=params, json=json, headers=headers)
        if r.status_code == 403 and restricted:
            raise ToolError(RESTRICTED_MESSAGE)
        if r.status_code == 403:
            raise ToolError(OWNERSHIP_MESSAGE)
        if r.status_code == 401:
            raise ToolError(REAUTH_MESSAGE)
        if r.status_code >= 400:
            raise ToolError(f"Spotify {r.status_code} on {method} {path}: {_message(r)}")
        return r.json() if r.content else None


def _message(r: httpx.Response) -> str:
    try:
        return r.json()["error"]["message"]
    except Exception:
        return r.text[:200]


def _reason(r: httpx.Response) -> str | None:
    try:
        return r.json()["error"].get("reason")
    except Exception:
        return None


def slim_track(t: dict[str, Any] | None) -> dict[str, Any]:
    if not t:
        return {}
    return {
        "id": t.get("id"),
        "uri": t.get("uri"),
        "name": t.get("name"),
        "artists": [a.get("name") for a in t.get("artists", [])],
        "album": (t.get("album") or {}).get("name"),
        "duration_ms": t.get("duration_ms"),
        "explicit": t.get("explicit"),
    }


def slim_artist(a: dict[str, Any] | None) -> dict[str, Any]:
    if not a:
        return {}
    return {
        "id": a.get("id"),
        "uri": a.get("uri"),
        "name": a.get("name"),
        "genres": a.get("genres", []),
        "images": a.get("images", []),
    }


def slim_album(a: dict[str, Any] | None) -> dict[str, Any]:
    if not a:
        return {}
    return {
        "id": a.get("id"),
        "uri": a.get("uri"),
        "name": a.get("name"),
        "artists": [x.get("name") for x in a.get("artists", [])],
        "images": a.get("images", []),
        "release_date": a.get("release_date"),
        "total_tracks": a.get("total_tracks"),
    }


def slim_playlist(p: dict[str, Any] | None) -> dict[str, Any]:
    if not p:
        return {}
    counts = p.get("items") or p.get("tracks") or {}
    return {
        "id": p.get("id"),
        "uri": p.get("uri"),
        "name": p.get("name"),
        "owner": (p.get("owner") or {}).get("id"),
        "public": p.get("public"),
        "collaborative": p.get("collaborative"),
        "item_count": counts.get("total"),
        "snapshot_id": p.get("snapshot_id"),
    }


def page(result: dict[str, Any], key: str = "items") -> dict[str, Any]:
    items = result.get(key) or []
    offset = result.get("offset", 0)
    next_offset = offset + len(items) if result.get("next") else None
    return {"items": items, "total": result.get("total"), "next_offset": next_offset}
