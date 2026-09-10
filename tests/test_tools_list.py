import pytest

EXPECTED_TOOL_NAMES = {
    "get_current_user",
    "list_my_playlists",
    "get_playlist",
    "get_playlist_items",
    "search",
    "get_track",
    "get_artist",
    "get_artist_albums",
    "get_album",
    "get_album_tracks",
    "get_liked_songs",
    "get_saved_albums",
    "get_top_items",
    "get_recently_played",
    "create_playlist",
    "update_playlist_details",
    "add_playlist_items",
    "remove_playlist_items",
    "reorder_playlist_items",
    "replace_playlist_items",
    "get_audio_features",
    "get_recommendations",
    "get_related_artists",
    "get_artist_top_tracks",
}

WRITE_TOOL_NAMES = {
    "create_playlist",
    "update_playlist_details",
    "add_playlist_items",
    "remove_playlist_items",
    "reorder_playlist_items",
    "replace_playlist_items",
}

DESTRUCTIVE_TOOL_NAMES = {"remove_playlist_items", "replace_playlist_items"}

DEPRECATED_TOOL_NAMES = {
    "get_audio_features",
    "get_recommendations",
    "get_related_artists",
    "get_artist_top_tracks",
}


@pytest.mark.anyio
async def test_exposes_exactly_24_named_tools(client):
    tools = (await client.list_tools()).tools
    assert len(tools) == 24
    assert {t.name for t in tools} == EXPECTED_TOOL_NAMES


@pytest.mark.anyio
async def test_every_tool_has_annotations(client):
    tools = (await client.list_tools()).tools
    for t in tools:
        assert t.annotations is not None, t.name
        assert t.annotations.read_only_hint is not None, t.name


@pytest.mark.anyio
async def test_write_tools_are_not_read_only(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    for name in WRITE_TOOL_NAMES:
        assert tools[name].annotations.read_only_hint is False, name


@pytest.mark.anyio
async def test_read_tools_are_read_only(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    for name in EXPECTED_TOOL_NAMES - WRITE_TOOL_NAMES:
        assert tools[name].annotations.read_only_hint is True, name


@pytest.mark.anyio
async def test_remove_and_replace_are_destructive(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    for name in DESTRUCTIVE_TOOL_NAMES:
        assert tools[name].annotations.destructive_hint is True, name


@pytest.mark.anyio
async def test_non_destructive_write_tools_are_not_destructive(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    for name in WRITE_TOOL_NAMES - DESTRUCTIVE_TOOL_NAMES:
        assert tools[name].annotations.destructive_hint is False, name


@pytest.mark.anyio
async def test_deprecated_tools_are_labelled_in_their_description(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    for name in DEPRECATED_TOOL_NAMES:
        assert tools[name].description.startswith("DEPRECATED:"), name


@pytest.mark.anyio
async def test_non_deprecated_tools_are_not_labelled(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    for name in EXPECTED_TOOL_NAMES - DEPRECATED_TOOL_NAMES:
        assert not tools[name].description.startswith("DEPRECATED:"), name


@pytest.mark.anyio
async def test_server_instructions_summarise_the_dj_workflow(client):
    instructions = client.instructions
    assert "list_my_playlists" in instructions
    assert "add_playlist_items" in instructions
