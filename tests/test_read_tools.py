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
    assert dict(fake.requests[-1].url.params) == {"limit": "50", "offset": "0", "additional_types": "track"}


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
async def test_search_empty_types_is_a_validation_error(client, fake):
    result = await client.call_tool("search", {"q": "x", "types": []})
    assert result.is_error is True
    assert len(fake.requests) == 0


@pytest.mark.anyio
async def test_search_filters_null_playlist_items_and_slims_them(client, fake):
    fake.add(
        "GET",
        "/v1/search",
        {
            "playlists": {
                "items": [
                    None,
                    {
                        "id": "pl1",
                        "uri": "spotify:playlist:pl1",
                        "name": "Mix",
                        "description": "Deep cuts",
                        "external_urls": {"spotify": "https://open.spotify.com/playlist/pl1"},
                        "owner": {"id": "someone", "display_name": "Someone"},
                        "public": True,
                        "collaborative": False,
                        "snapshot_id": "snap",
                        "images": [{"url": "http://img"}],
                        "href": "https://api.spotify.com/v1/playlists/pl1",
                        "primary_color": None,
                        "tracks": {"total": 120},
                    },
                ],
                "total": 2,
                "offset": 0,
                "next": None,
            }
        },
    )
    result = await client.call_tool("search", {"q": "house", "types": ["playlist"]})
    items = result.structured_content["playlists"]["items"]
    assert len(items) == 1
    assert items[0] == {
        "id": "pl1",
        "uri": "spotify:playlist:pl1",
        "name": "Mix",
        "description": "Deep cuts",
        "url": "https://open.spotify.com/playlist/pl1",
        "owner": "someone",
        "public": True,
        "collaborative": False,
        "item_count": 120,
        "snapshot_id": "snap",
    }


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


@pytest.mark.anyio
async def test_get_current_user_hits_me(client, fake):
    fake.add("GET", "/v1/me", {"id": "me1", "display_name": "Gerhard"})
    result = await client.call_tool("get_current_user", {})
    assert result.is_error is False
    assert result.structured_content == {"id": "me1", "display_name": "Gerhard"}
    assert fake.requests[-1].url.path == "/v1/me"


@pytest.mark.anyio
async def test_list_my_playlists_hits_me_playlists_and_uses_tracks_fallback(client, fake):
    fake.add(
        "GET",
        "/v1/me/playlists",
        {
            "items": [{"id": "p1", "name": "Warmup", "owner": {"id": "me"}, "tracks": {"total": 3}}],
            "total": 1,
            "offset": 0,
            "next": None,
        },
    )
    result = await client.call_tool("list_my_playlists", {"limit": 10, "offset": 5})
    assert result.is_error is False
    assert result.structured_content["items"][0]["item_count"] == 3
    assert fake.requests[-1].url.path == "/v1/me/playlists"
    assert dict(fake.requests[-1].url.params) == {"limit": "10", "offset": "5"}


@pytest.mark.anyio
async def test_get_playlist_hits_playlists_by_id(client, fake):
    fake.add(
        "GET",
        "/v1/playlists/p1",
        {"id": "p1", "name": "Warmup", "description": "Deep cuts", "owner": {"id": "me"}, "items": {"total": 5}},
    )
    result = await client.call_tool("get_playlist", {"playlist_id": "p1"})
    assert result.is_error is False
    assert result.structured_content["name"] == "Warmup"
    assert result.structured_content["description"] == "Deep cuts"
    assert fake.requests[-1].url.path == "/v1/playlists/p1"


@pytest.mark.anyio
async def test_get_artist_hits_artists_by_id(client, fake):
    fake.add("GET", "/v1/artists/a1", {"id": "a1", "name": "Artist A", "genres": ["house"]})
    result = await client.call_tool("get_artist", {"artist_id": "a1"})
    assert result.is_error is False
    assert result.structured_content["name"] == "Artist A"
    assert fake.requests[-1].url.path == "/v1/artists/a1"


@pytest.mark.anyio
async def test_get_album_tracks_hits_albums_tracks(client, fake):
    fake.add(
        "GET",
        "/v1/albums/al1/tracks",
        {"items": [{"id": "t1", "name": "Song"}], "total": 1, "offset": 0, "next": None},
    )
    result = await client.call_tool("get_album_tracks", {"album_id": "al1"})
    assert result.is_error is False
    assert result.structured_content["items"][0]["id"] == "t1"
    assert fake.requests[-1].url.path == "/v1/albums/al1/tracks"


@pytest.mark.anyio
async def test_get_saved_albums_hits_me_albums(client, fake):
    fake.add(
        "GET",
        "/v1/me/albums",
        {"items": [{"added_at": "2026-01-01", "album": {"id": "al1", "name": "Album X"}}], "total": 1, "offset": 0, "next": None},
    )
    result = await client.call_tool("get_saved_albums", {})
    assert result.is_error is False
    assert result.structured_content["items"][0]["added_at"] == "2026-01-01"
    assert result.structured_content["items"][0]["id"] == "al1"
    assert fake.requests[-1].url.path == "/v1/me/albums"


@pytest.mark.anyio
async def test_get_audio_features_is_restricted_and_reports_development_mode(client, fake):
    fake.add("GET", "/v1/audio-features/t1", {"error": {"status": 403, "message": "Forbidden"}}, status=403)
    result = await client.call_tool("get_audio_features", {"track_id": "t1"})
    assert result.is_error is True
    assert "Development Mode" in result.content[0].text
    assert fake.requests[-1].url.path == "/v1/audio-features/t1"
    assert len(fake.requests) == 1


@pytest.mark.anyio
async def test_get_related_artists_is_restricted_and_reports_development_mode(client, fake):
    fake.add("GET", "/v1/artists/a1/related-artists", {"error": {"status": 403, "message": "Forbidden"}}, status=403)
    result = await client.call_tool("get_related_artists", {"artist_id": "a1"})
    assert result.is_error is True
    assert "Development Mode" in result.content[0].text
    assert fake.requests[-1].url.path == "/v1/artists/a1/related-artists"
    assert len(fake.requests) == 1


@pytest.mark.anyio
async def test_get_artist_top_tracks_is_restricted_and_reports_development_mode(client, fake):
    fake.add("GET", "/v1/artists/a1/top-tracks", {"error": {"status": 403, "message": "Forbidden"}}, status=403)
    result = await client.call_tool("get_artist_top_tracks", {"artist_id": "a1"})
    assert result.is_error is True
    assert "Development Mode" in result.content[0].text
    assert fake.requests[-1].url.path == "/v1/artists/a1/top-tracks"
    assert len(fake.requests) == 1
