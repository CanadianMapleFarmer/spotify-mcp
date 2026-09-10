import time

import pytest

from spotify_mcp import spotify as spotify_module
from spotify_mcp.auth import Token, save_token
from spotify_mcp.spotify import SpotifyClient, page, slim_album, slim_artist, slim_playlist, slim_track


@pytest.mark.anyio
async def test_missing_token_raises_not_logged_in(settings, mock_http):
    client = SpotifyClient(settings, mock_http)
    with pytest.raises(Exception, match="Not logged in"):
        await client.request("GET", "/me")


@pytest.mark.anyio
async def test_successful_request_returns_json(spotify_client, fake):
    fake.add("GET", "/v1/me", {"id": "me"})
    result = await spotify_client.request("GET", "/me")
    assert result == {"id": "me"}
    assert fake.requests[-1].headers["Authorization"] == "Bearer at"


@pytest.mark.anyio
async def test_expired_token_refreshes_before_request(settings, fake, mock_http):
    save_token(settings, Token("stale", "rt", time.time() - 10, "scope", "cid"))
    fake.add("POST", "/api/token", {"access_token": "fresh", "expires_in": 3600, "scope": "scope"})
    fake.add("GET", "/v1/me", {"id": "me"})
    client = SpotifyClient(settings, mock_http)
    result = await client.request("GET", "/me")
    assert result == {"id": "me"}
    assert fake.requests[-1].headers["Authorization"] == "Bearer fresh"


@pytest.mark.anyio
async def test_401_raises_relogin_message(spotify_client, fake):
    fake.add("GET", "/v1/me", {"error": {"status": 401, "message": "bad token"}}, status=401)
    with pytest.raises(Exception, match="login"):
        await spotify_client.request("GET", "/me")


@pytest.mark.anyio
async def test_restricted_403_raises_development_mode_message(spotify_client, fake):
    fake.add("GET", "/v1/audio-features/t1", {"error": {"status": 403, "message": "Forbidden"}}, status=403)
    with pytest.raises(Exception, match="Development Mode"):
        await spotify_client.request("GET", "/audio-features/t1", restricted=True)
    assert len(fake.requests) == 1


@pytest.mark.anyio
async def test_non_restricted_403_raises_ownership_message(spotify_client, fake):
    fake.add("GET", "/v1/playlists/p1/items", {"error": {"status": 403, "message": "Forbidden"}}, status=403)
    with pytest.raises(Exception, match="owns, collaborates on, or has permission"):
        await spotify_client.request("GET", "/playlists/p1/items")


@pytest.mark.anyio
async def test_5xx_raises_with_status(spotify_client, fake):
    fake.add("GET", "/v1/me", {"error": {"status": 500, "message": "boom"}}, status=500)
    with pytest.raises(Exception, match="500"):
        await spotify_client.request("GET", "/me")


@pytest.mark.anyio
async def test_429_retries_once_after_sleep(spotify_client, fake, monkeypatch):
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(spotify_module.asyncio, "sleep", fake_sleep)
    fake.add("GET", "/v1/me", {"error": {"status": 429, "message": "slow down"}}, status=429, headers={"Retry-After": "5"})
    fake.add("GET", "/v1/me", {"id": "me"})
    result = await spotify_client.request("GET", "/me")
    assert result == {"id": "me"}
    assert slept == [5]
    assert len(fake.requests) == 2


@pytest.mark.anyio
async def test_429_retry_after_is_capped_at_30s(spotify_client, fake, monkeypatch):
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(spotify_module.asyncio, "sleep", fake_sleep)
    fake.add("GET", "/v1/me", {"error": {"status": 429, "message": "slow down"}}, status=429, headers={"Retry-After": "120"})
    fake.add("GET", "/v1/me", {"id": "me"})
    await spotify_client.request("GET", "/me")
    assert slept == [30]


@pytest.mark.anyio
async def test_429_quota_exceeded_does_not_retry(spotify_client, fake, monkeypatch):
    async def fake_sleep(seconds):
        raise AssertionError("should not sleep/retry on QUOTA_EXCEEDED")

    monkeypatch.setattr(spotify_module.asyncio, "sleep", fake_sleep)
    fake.add(
        "GET",
        "/v1/me",
        {"error": {"status": 429, "message": "quota exhausted", "reason": "QUOTA_EXCEEDED"}},
        status=429,
    )
    with pytest.raises(Exception, match="quota"):
        await spotify_client.request("GET", "/me")
    assert len(fake.requests) == 1


def test_slim_track_extracts_fields():
    raw = {
        "id": "t1",
        "uri": "spotify:track:t1",
        "name": "Song",
        "artists": [{"name": "Artist A"}, {"name": "Artist B"}],
        "album": {"name": "Album X"},
        "duration_ms": 210000,
        "explicit": False,
    }
    assert slim_track(raw) == {
        "id": "t1",
        "uri": "spotify:track:t1",
        "name": "Song",
        "artists": ["Artist A", "Artist B"],
        "album": "Album X",
        "duration_ms": 210000,
        "explicit": False,
    }


def test_slim_track_handles_missing_input():
    assert slim_track(None) == {}


def test_slim_artist_extracts_fields():
    raw = {"id": "a1", "uri": "spotify:artist:a1", "name": "Artist A", "genres": ["house"], "images": [{"url": "x"}]}
    assert slim_artist(raw) == raw


def test_slim_album_extracts_fields():
    raw = {
        "id": "al1",
        "uri": "spotify:album:al1",
        "name": "Album X",
        "artists": [{"name": "Artist A"}],
        "images": [],
        "release_date": "2020-01-01",
        "total_tracks": 10,
    }
    result = slim_album(raw)
    assert result["artists"] == ["Artist A"]
    assert result["name"] == "Album X"
    assert result["total_tracks"] == 10


def test_slim_playlist_extracts_fields():
    raw = {
        "id": "p1",
        "uri": "spotify:playlist:p1",
        "name": "Warmup",
        "owner": {"id": "me"},
        "public": False,
        "collaborative": False,
        "items": {"total": 3},
        "snapshot_id": "s1",
    }
    assert slim_playlist(raw) == {
        "id": "p1",
        "uri": "spotify:playlist:p1",
        "name": "Warmup",
        "owner": "me",
        "public": False,
        "collaborative": False,
        "item_count": 3,
        "snapshot_id": "s1",
    }


def test_page_computes_next_offset_when_more_results():
    result = {"items": [1, 2, 3], "total": 10, "offset": 0, "next": "http://next"}
    assert page(result) == {"items": [1, 2, 3], "total": 10, "next_offset": 3}


def test_page_next_offset_none_when_no_more_results():
    result = {"items": [1, 2, 3], "total": 3, "offset": 0, "next": None}
    assert page(result) == {"items": [1, 2, 3], "total": 3, "next_offset": None}


def test_page_reads_from_named_key():
    result = {"tracks": {"items": [1], "total": 1, "offset": 0, "next": None}}
    assert page(result["tracks"], key="items") == {"items": [1], "total": 1, "next_offset": None}
