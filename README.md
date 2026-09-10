# spotify-mcp

An MCP server that gives an AI agent your Spotify account so it can build DJ sets for you: browse your playlists and Liked Songs, search the catalog, pull your top tracks and recent history, then create and edit playlists on your behalf. Runs over stdio for Codex CLI and Claude Code, or over streamable HTTP behind a tunnel for ChatGPT's developer mode connectors.

## Spotify Developer Dashboard setup

1. Go to https://developer.spotify.com/dashboard and **Create app**.
2. **Redirect URI**: add exactly `http://127.0.0.1:8888/callback` — `localhost` is rejected, and the string must match byte-for-byte (no trailing slash).
3. **Settings → User Management**: add your own Spotify account. Development Mode apps only work for allow-listed users.
4. Note the **Client ID** and **Client Secret** from the app's Settings page.

Development Mode limits to know going in:
- The app owner's Spotify account must have **Premium**.
- Max **5** users, all added manually under User Management.
- No `/recommendations`, `/audio-features`, `/related-artists` or `/artists/{id}/top-tracks` — these return 403 for any app created after 2024-11-27. The four tools that hit them are kept for legacy apps and fail with a clear `DEPRECATED` error otherwise.

## Install

```bash
uv sync
```

Add to `~/.zshrc` (new shells only; already-open terminals need `source ~/.zshrc`):

```bash
export SPOTIFY_CLIENT_ID="..."
export SPOTIFY_CLIENT_SECRET="..."
export SPOTIFY_REDIRECT_URI="http://127.0.0.1:8888/callback"
```

`SPOTIFY_REDIRECT_URI` defaults to `http://127.0.0.1:8888/callback` if unset. `SPOTIFY_MCP_CONFIG_DIR` (default `~/.config/spotify-mcp`) is where `token.json` is cached (dir `0700`, file `0600`).

## First run

```bash
uv run spotify-mcp login
```

Opens a browser to the Spotify consent screen, catches the redirect on a one-shot local server bound to `127.0.0.1:8888`, exchanges the code for a token, and caches it. Rerun this whenever `status` reports no token, or a tool error tells you to.

```bash
uv run spotify-mcp status
```

Shows config dir, whether `SPOTIFY_CLIENT_ID`/`SPOTIFY_CLIENT_SECRET` are set, the redirect URI, and the cached token's remaining lifetime — all without calling Spotify. Exit code is `0` with a token, `1` without.

```bash
uv run spotify-mcp whoami
```

Calls `GET /me` with the cached token (refreshing it if needed) and prints the display name, id and product tier. Confirms which Spotify account is actually connected.

```bash
uv run spotify-mcp tools
```

Lists every MCP tool the server exposes, entirely offline (no network calls, no login required).

## Tools

24 tools total. Reads return slimmed JSON (id/uri/name/artists/album/etc.) to keep responses small; write tools return the fields needed to confirm the change (id, uri, snapshot_id).

| tool | kind | description |
|---|---|---|
| `get_current_user` | read | Profile of the logged-in Spotify user (id, display_name). Call this first to confirm which account is connected. |
| `list_my_playlists` | read | List playlists the user owns or follows. Start here when building a DJ set — the returned id feeds get_playlist_items. Paginate with offset when next_offset is not null. |
| `get_playlist` | read | Metadata for one playlist (name, description, owner, item count). Contents are only readable for playlists the user owns or collaborates on — use get_playlist_items for tracks. |
| `get_playlist_items` | read | Read the tracks of one of my playlists (only playlists I own or collaborate on). Use list_my_playlists first to find the id. Paginate with offset until next_offset is null. |
| `search` | read | Search Spotify's catalog for tracks/artists/albums/playlists to add to a set. At most 10 results per requested type per call — paginate with offset (max 1000). |
| `get_track` | read | A single track by id. One call per id — Spotify removed the batch /tracks?ids= endpoint for dev-mode apps. |
| `get_artist` | read | A single artist by id (name, genres, images). Use search to find the id first. |
| `get_artist_albums` | read | An artist's albums, singles and compilations — useful for finding more tracks by an artist already in a set. Paginate with offset. |
| `get_album` | read | An album by id with its metadata and the first page of tracks. Use get_album_tracks to page through the rest. |
| `get_album_tracks` | read | Paged tracks of an album by id. Paginate with offset until next_offset is null. |
| `get_liked_songs` | read | The user's Liked Songs, newest first — a good source of DJ set material. Paginate with offset. |
| `get_saved_albums` | read | The user's saved albums, newest first. Paginate with offset. |
| `get_top_items` | read | The user's most-played artists or tracks over the last ~4 weeks (short_term), ~6 months (medium_term) or ~1 year (long_term). Good seed material for a set that matches the user's taste. Paginate with offset. |
| `get_recently_played` | read | Recently played tracks with when they were played — useful for avoiding repeats in a new set. Pass after OR before (not both) to page through history using the returned cursors. |
| `get_audio_features` | read | **DEPRECATED** — 403 for apps created after 2024-11-27 / Development Mode. Tempo, key, energy and other audio features for one track by id — the only source of BPM for DJ matching, when it works. |
| `get_recommendations` | read | **DEPRECATED** — same restriction. Seed-based track recommendations from up to 5 combined seed_tracks/seed_artists/seed_genres. |
| `get_related_artists` | read | **DEPRECATED** — same restriction. Artists similar to a given artist, for widening a set around a sound. |
| `get_artist_top_tracks` | read | **DEPRECATED** — same restriction. An artist's top tracks. Use `search` with an `artist:` filter instead when this fails. |
| `create_playlist` | write | Create a new playlist for the logged-in user to hold a DJ set. Follow up with add_playlist_items to fill it. |
| `update_playlist_details` | write | Rename, redescribe or toggle public/collaborative on a playlist the user owns. Only the fields you pass are changed. |
| `add_playlist_items` | write | Append 1-100 spotify:track: URIs to a playlist the user owns or collaborates on; pass position to insert instead of appending. Use search or get_playlist_items to find URIs first. |
| `remove_playlist_items` | write | Remove every occurrence of 1-100 spotify:track: URIs from a playlist the user owns. Pass the playlist's snapshot_id to guard against concurrent edits. |
| `reorder_playlist_items` | write | Move a block of items within a playlist the user owns: range_length items starting at range_start end up positioned just before insert_before. |
| `replace_playlist_items` | write | Replace the entire contents of a playlist the user owns with 0-100 spotify:track: URIs. An empty list clears it. Use add_playlist_items instead if you only want to append. |

Regenerate this table with `uv run spotify-mcp tools`.

## Codex CLI

Add the block from [`examples/codex-config.toml`](examples/codex-config.toml) to `~/.codex/config.toml`. Prereqs: `SPOTIFY_CLIENT_ID`/`SPOTIFY_CLIENT_SECRET` exported in `~/.zshrc` (Codex clears the environment for stdio servers and only forwards names listed in `env_vars`), `uv sync` run once, and `uv run spotify-mcp login` run once.

```bash
codex mcp get spotify-mcp
codex mcp list
```

`codex mcp add` cannot set `env_vars`/timeouts/approval modes — use the TOML block above and edit it directly for those.

## Claude Code

Run [`examples/claude-mcp-add.sh`](examples/claude-mcp-add.sh) (with `SPOTIFY_CLIENT_ID`/`SPOTIFY_CLIENT_SECRET` exported in your shell), or the command directly:

```bash
claude mcp add --scope user --transport stdio spotify-mcp \
  -e SPOTIFY_CLIENT_ID="$SPOTIFY_CLIENT_ID" \
  -e SPOTIFY_CLIENT_SECRET="$SPOTIFY_CLIENT_SECRET" \
  -e SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback \
  -e UV_NO_SYNC=1 \
  -- uv run --directory /path/to/spotify-mcp spotify-mcp serve

claude mcp get spotify-mcp
claude mcp list
```

`--scope user` makes it available in every project (the default `local` scope is this project only). Flags go before `--`; everything after is the server command verbatim.

Project-scope alternative — add to a project's `.mcp.json` (project-scope servers strip env vars whose names contain `TOKEN`/`SECRET`/`PASSWORD`/`KEY`/`AUTH`, so use the `env` map with `${VAR}` expansion instead of relying on inherited env):

```json
{
  "mcpServers": {
    "spotify-mcp": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/path/to/spotify-mcp", "spotify-mcp", "serve"],
      "env": {
        "SPOTIFY_CLIENT_ID": "${SPOTIFY_CLIENT_ID}",
        "SPOTIFY_CLIENT_SECRET": "${SPOTIFY_CLIENT_SECRET}",
        "SPOTIFY_REDIRECT_URI": "${SPOTIFY_REDIRECT_URI:-http://127.0.0.1:8888/callback}",
        "UV_NO_SYNC": "1"
      }
    }
  }
}
```

Slow first start (cold `uv sync`): set `MCP_TIMEOUT=60000` or run `uv sync` in the repo before connecting.

## ChatGPT (developer mode connector)

Requires ChatGPT Pro/Plus/Business/Enterprise/Edu on the **web** (developer mode is web-only). `uv run spotify-mcp login` must already be done.

1. `brew install cloudflared` (once).
2. Run [`examples/chatgpt-tunnel.sh`](examples/chatgpt-tunnel.sh) — it starts `cloudflared tunnel --url http://127.0.0.1:8000` and prints the exact `serve` command to run once the hostname is known.
3. In a second terminal (in this repo, with env exported), run the printed command, e.g.:
   ```bash
   uv run spotify-mcp serve --transport streamable-http --port 8000 --allow-host <random>.trycloudflare.com
   ```
4. Sanity check the tunnel:
   ```bash
   curl -s https://<random>.trycloudflare.com/mcp -X POST \
     -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
     -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
   ```
   A JSON body with `serverInfo` means it's working; a `421` means the hostname isn't allow-listed yet (restart `serve` with the current `--allow-host`).
5. chatgpt.com → Settings → Security and login → enable **Developer mode**.
6. Settings → Apps/Plugins → **+ Create** → Connection = Public endpoint, URL `https://<random>.trycloudflare.com/mcp`, Authentication = **No authentication**, tick the trust acknowledgement → Create.
7. New chat → **+** in the composer → Developer mode → enable the app.

**Security warning**: the connector is set to "No authentication" — anyone with the tunnel URL can act as your logged-in Spotify account (read your library, create/edit/delete playlists) for as long as the tunnel is up. Quick-tunnel hostnames are random and change on every restart of `cloudflared`; stop the tunnel when you're done, and don't share the URL.

After changing tool names or descriptions, click **Refresh** on the app's details page and start a new chat — ChatGPT caches `tools/list`.

## Troubleshooting

| symptom | cause | fix |
|---|---|---|
| `421 Misdirected Request` | Tunnel hostname isn't in the streamable-http allow-list | Restart `serve` with `--allow-host <exact tunnel hostname>` |
| `403` on most catalog tools | Spotify Development Mode restriction (recommendations/audio-features/related-artists/artist-top-tracks are gone for apps created after 2024-11-27) | Expected for the 4 tools marked `DEPRECATED`; no fix — use `search` instead where suggested |
| Tool error mentions `invalid_grant` | Refresh token expired or was revoked (refresh tokens now expire 6 months after original consent) | `uv run spotify-mcp login` again |
| MCP client times out waiting for the server to start | Cold `uv run` (dependency resolution) exceeds the client's startup timeout | Run `uv sync` once ahead of time, set `UV_NO_SYNC=1` in the server's env, and raise `startup_timeout_sec` (Codex) / `MCP_TIMEOUT` (Claude Code) |

## Development

```bash
uv run pytest -q
```

Runs the full suite offline in-process (in-memory MCP client, `httpx.MockTransport` — no network calls, no subprocess). One test is marked `slow` (spawns a real `python -m spotify_mcp serve` subprocess to check stdout stays clean) and is skipped by default; run it explicitly with:

```bash
uv run pytest -q -m slow
```

CI-equivalent: `uv sync --all-groups && uv run pytest`.
