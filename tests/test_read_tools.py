import pytest


@pytest.mark.anyio
async def test_get_playlist_items_maps_item_key_and_next_offset(client, fake):
    fake.add(
        "GET",
        "/v1/playlists/p1/items",
        {
            "items": [{"added_at": "2026-01-01", "item": {"id": "t1", "uri": "spotify:track:t1", "name": "Song 1", "artists": [], "duration_ms": 1000}}],
            "total": 3,
            "offset": 0,
            "next": "http://next",
        },
    )
    result = await client.call_tool("get_playlist_items", {"playlist_id": "p1"})
    assert result.is_error is False
    assert result.structured_content["items"] == [
        {"added_at": "2026-01-01", "id": "t1", "uri": "spotify:track:t1", "name": "Song 1", "artists": [], "album": None, "duration_ms": 1000, "explicit": None}
    ]
    assert result.structured_content["next_offset"] == 1
    assert fake.requests[-1].url.params["limit"] == "50"
    assert fake.requests[-1].url.params["offset"] == "0"


@pytest.mark.anyio
async def test_get_playlist_items_maps_legacy_track_key(client, fake):
    fake.add(
        "GET",
        "/v1/playlists/p1/items",
        {"items": [{"added_at": "2026-01-01", "track": {"id": "t2", "uri": "spotify:track:t2", "name": "Song 2"}}], "total": 1, "offset": 0, "next": None},
    )
    result = await client.call_tool("get_playlist_items", {"playlist_id": "p1"})
    assert result.structured_content["items"][0]["id"] == "t2"
    assert result.structured_content["next_offset"] is None


@pytest.mark.anyio
async def test_search_sends_type_list_and_limit(client, fake):
    fake.add("GET", "/v1/search", {"tracks": {"items": [], "total": 0, "offset": 0, "next": None}})
    result = await client.call_tool("search", {"q": "artist:New Order track:Blue Monday", "types": ["track"], "limit": 5})
    assert result.is_error is False
    params = fake.requests[-1].url.params
    assert params["type"] == "track"
    assert params["limit"] == "5"
    assert params["q"] == "artist:New Order track:Blue Monday"


@pytest.mark.anyio
async def test_search_limit_over_10_is_a_validation_error(client, fake):
    result = await client.call_tool("search", {"q": "x", "limit": 11})
    assert result.is_error is True
    assert len(fake.requests) == 0


@pytest.mark.anyio
async def test_search_filters_null_playlist_items(client, fake):
    fake.add(
        "GET",
        "/v1/search",
        {"playlists": {"items": [None, {"id": "pl1", "name": "Mix"}], "total": 2, "offset": 0, "next": None}},
    )
    result = await client.call_tool("search", {"q": "house", "types": ["playlist"]})
    assert len(result.structured_content["playlists"]["items"]) == 1
    assert result.structured_content["playlists"]["items"][0]["id"] == "pl1"


@pytest.mark.anyio
async def test_get_top_items_sends_time_range(client, fake):
    fake.add("GET", "/v1/me/top/artists", {"items": [], "total": 0, "offset": 0, "next": None})
    result = await client.call_tool("get_top_items", {"type": "artists", "time_range": "long_term"})
    assert result.is_error is False
    assert fake.requests[-1].url.params["time_range"] == "long_term"


@pytest.mark.anyio
async def test_get_recently_played_rejects_after_and_before(client, fake):
    result = await client.call_tool("get_recently_played", {"after": 100, "before": 200})
    assert result.is_error is True
    assert "not both" in result.content[0].text
    assert len(fake.requests) == 0


@pytest.mark.anyio
async def test_get_recently_played_returns_cursors(client, fake):
    fake.add(
        "GET",
        "/v1/me/player/recently-played",
        {"items": [{"played_at": "2026-01-01T00:00:00Z", "track": {"id": "t1", "name": "Song"}}], "cursors": {"after": "1", "before": "2"}},
    )
    result = await client.call_tool("get_recently_played", {"after": 100})
    assert result.structured_content["cursors"] == {"after": "1", "before": "2"}
    assert result.structured_content["items"][0]["played_at"] == "2026-01-01T00:00:00Z"
    assert fake.requests[-1].url.params["after"] == "100"
    assert "before" not in fake.requests[-1].url.params


@pytest.mark.anyio
async def test_get_track_slims_result(client, fake):
    fake.add("GET", "/v1/tracks/t1", {"id": "t1", "uri": "spotify:track:t1", "name": "Song", "artists": [{"name": "A"}]})
    result = await client.call_tool("get_track", {"track_id": "t1"})
    assert result.structured_content["artists"] == ["A"]


@pytest.mark.anyio
async def test_get_artist_albums_sends_include_groups(client, fake):
    fake.add("GET", "/v1/artists/a1/albums", {"items": [], "total": 0, "offset": 0, "next": None})
    result = await client.call_tool("get_artist_albums", {"artist_id": "a1", "include_groups": ["album", "single"]})
    assert result.is_error is False
    assert fake.requests[-1].url.params["include_groups"] == "album,single"


@pytest.mark.anyio
async def test_get_album_includes_first_page_of_tracks(client, fake):
    fake.add(
        "GET",
        "/v1/albums/al1",
        {"id": "al1", "name": "Album X", "tracks": {"items": [{"id": "t1", "name": "Song"}], "total": 1, "offset": 0, "next": None}},
    )
    result = await client.call_tool("get_album", {"album_id": "al1"})
    assert result.structured_content["name"] == "Album X"
    assert result.structured_content["tracks"]["items"][0]["id"] == "t1"


@pytest.mark.anyio
async def test_get_liked_songs_maps_added_at(client, fake):
    fake.add(
        "GET",
        "/v1/me/tracks",
        {"items": [{"added_at": "2026-01-01", "track": {"id": "t1", "name": "Song"}}], "total": 1, "offset": 0, "next": None},
    )
    result = await client.call_tool("get_liked_songs", {})
    assert result.structured_content["items"][0]["added_at"] == "2026-01-01"


@pytest.mark.anyio
async def test_deprecated_recommendations_requires_a_seed(client, fake):
    result = await client.call_tool("get_recommendations", {})
    assert result.is_error is True
    assert len(fake.requests) == 0
