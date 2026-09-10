import pytest


@pytest.mark.anyio
async def test_add_playlist_items_sends_uris_and_position(client, fake):
    fake.add("POST", "/v1/playlists/p1/items", {"snapshot_id": "s1"})
    result = await client.call_tool("add_playlist_items", {"playlist_id": "p1", "uris": ["spotify:track:a"], "position": 2})
    assert result.structured_content == {"snapshot_id": "s1"}
    assert fake.body() == {"uris": ["spotify:track:a"], "position": 2}


@pytest.mark.anyio
async def test_add_playlist_items_omits_position_when_not_given(client, fake):
    fake.add("POST", "/v1/playlists/p1/items", {"snapshot_id": "s1"})
    await client.call_tool("add_playlist_items", {"playlist_id": "p1", "uris": ["spotify:track:a"]})
    assert fake.body() == {"uris": ["spotify:track:a"]}


@pytest.mark.anyio
async def test_remove_uses_items_key_not_tracks(client, fake):
    fake.add("DELETE", "/v1/playlists/p1/items", {"snapshot_id": "s2"})
    result = await client.call_tool("remove_playlist_items", {"playlist_id": "p1", "uris": ["spotify:track:a"]})
    assert result.is_error is False
    assert result.structured_content == {"snapshot_id": "s2"}
    assert fake.body() == {"items": [{"uri": "spotify:track:a"}]}
    assert fake.requests[-1].headers["Authorization"] == "Bearer at"


@pytest.mark.anyio
async def test_remove_includes_snapshot_id_when_given(client, fake):
    fake.add("DELETE", "/v1/playlists/p1/items", {"snapshot_id": "s3"})
    await client.call_tool("remove_playlist_items", {"playlist_id": "p1", "uris": ["spotify:track:a"], "snapshot_id": "s2"})
    assert fake.body() == {"items": [{"uri": "spotify:track:a"}], "snapshot_id": "s2"}


@pytest.mark.anyio
async def test_reorder_body(client, fake):
    fake.add("PUT", "/v1/playlists/p1/items", {"snapshot_id": "s3"})
    result = await client.call_tool(
        "reorder_playlist_items", {"playlist_id": "p1", "range_start": 1, "insert_before": 3, "range_length": 2}
    )
    assert result.structured_content == {"snapshot_id": "s3"}
    assert fake.body() == {"range_start": 1, "insert_before": 3, "range_length": 2}


@pytest.mark.anyio
async def test_replace_sends_uris_body(client, fake):
    fake.add("PUT", "/v1/playlists/p1/items", {"snapshot_id": "s4"})
    result = await client.call_tool("replace_playlist_items", {"playlist_id": "p1", "uris": []})
    assert result.structured_content == {"snapshot_id": "s4"}
    assert fake.body() == {"uris": []}


@pytest.mark.anyio
async def test_create_playlist_posts_to_me_with_public_false_default(client, fake):
    fake.add(
        "POST",
        "/v1/me/playlists",
        {"id": "p9", "uri": "spotify:playlist:p9", "name": "Warmup", "owner": {"id": "me"}, "public": False, "items": {"total": 0}},
        status=201,
    )
    result = await client.call_tool("create_playlist", {"name": "Warmup"})
    assert result.structured_content["id"] == "p9"
    assert fake.body()["public"] is False
    assert fake.body()["collaborative"] is False


@pytest.mark.anyio
async def test_update_playlist_details_sends_only_provided_fields(client, fake):
    fake.add("PUT", "/v1/playlists/p1", {})
    result = await client.call_tool("update_playlist_details", {"playlist_id": "p1", "name": "New name"})
    assert result.is_error is False
    assert fake.body() == {"name": "New name"}


@pytest.mark.anyio
async def test_update_playlist_details_requires_a_field(client, fake):
    result = await client.call_tool("update_playlist_details", {"playlist_id": "p1"})
    assert result.is_error is True
    assert len(fake.requests) == 0
