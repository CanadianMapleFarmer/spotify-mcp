# spotify-mcp design

Python MCP server exposing a Spotify account to Codex CLI, Claude Code (stdio) and ChatGPT (streamable HTTP over a tunnel). Built for assembling DJ sets from the owner's playlists.

## Stack

- Python 3.13 (`.python-version` = 3.13; `requires-python = ">=3.13"`) — Homebrew 3.13.15 is installed; mcp 2.2.0 declares 3.10-3.14 but 3.13 is the safest wheel target. Do NOT use 3.9 (/usr/bin/python3).
- uv 0.9.26 (already at uv); build backend `uv_build>=0.9.26,<0.10`; src layout `src/spotify_mcp/`
- mcp==2.2.0 (official SDK, v2 API: `from mcp.server import MCPServer`; pulls mcp-types==2.2.0 and httpx2 — NOT httpx)
- httpx>=0.28 (explicit dependency; mcp does not install it; provides AsyncClient + MockTransport for tests)
- typer>=0.15 and rich>=13 (CLI). Typer depends on rich already; pin whatever `uv lock` resolves on 2026-09-10 and commit uv.lock.
- pydantic>=2 (transitively from mcp; import Field for Annotated constraints)
- dev: pytest>=8, anyio>=4 (anyio pytest plugin ships with anyio; no pytest-asyncio). No respx — httpx.MockTransport is used instead, zero extra deps.
- Not used: spotipy 2.26.0 / tekore 6.2.0 (both wrap the removed /tracks batch + /playlists/{id}/tracks paths; a 150-line httpx wrapper is smaller and dev-mode-correct). Not used: standalone fastmcp 4.0.3.

## Auth

Authorization Code flow with client secret (confidential client), no PKCE in v1.

Why: the user supplies SPOTIFY_CLIENT_ID + SPOTIFY_CLIENT_SECRET, so the Basic-auth code flow is the natural fit and has one practical advantage over PKCE: refresh responses usually omit a new refresh_token, so there is no single-use-rotation race between `serve` and the CLI. Do not mix PKCE params into the Basic-auth exchange (unverified with Spotify).

Env vars (read once via `Settings.from_env()`):
- SPOTIFY_CLIENT_ID (required)
- SPOTIFY_CLIENT_SECRET (required; needed at serve time for refresh)
- SPOTIFY_REDIRECT_URI (default http://127.0.0.1:8888/callback; host/port/path are parsed from it and the login callback server binds to exactly that)
- SPOTIFY_MCP_CONFIG_DIR (default ~/.config/spotify-mcp; tests point it at tmp_path)

`spotify-mcp login` (CLI, blocking):
1. state = secrets.token_urlsafe(16); build https://accounts.spotify.com/authorize?client_id&response_type=code&redirect_uri&scope&state; print URL to stderr and webbrowser.open().
2. Stdlib http.server.HTTPServer bound to 127.0.0.1:8888 serves ONE request (`handle_request()` with 300s timeout); rejects path mismatch (404) and state mismatch (400); captures `code` or `error`.
3. POST https://accounts.spotify.com/api/token with `Authorization: Basic base64(client_id:client_secret)`, body grant_type=authorization_code&code&redirect_uri.
4. Persist Token{access_token, refresh_token, expires_at (epoch, now+expires_in), scope, client_id} to ~/.config/spotify-mcp/token.json — dir 0700, file 0600, written via tmp+rename. Warn if granted `scope` is narrower than requested.

Runtime (server and `whoami`): `SpotifyClient._access_token()` under an asyncio.Lock loads token.json on every call (so a fresh `login` in another terminal is picked up without restarting the server), refreshes when `now >= expires_at - 60s` via grant_type=refresh_token + Basic auth, keeps the old refresh_token if the response omits one, persists any rotated one, and on HTTP 400 {"error":"invalid_grant"} deletes token.json and raises ToolError("Refresh token expired or revoked. Run `spotify-mcp login` again.") — never retries. Refresh tokens now expire 6 months after the original consent regardless of refresh activity, so this path WILL be hit.

Missing token or missing env → ToolError with the exact CLI command to run; the server never triggers a browser flow itself (stdio has no user, ChatGPT has no local browser).

MCP-level auth: none. stdio is local; streamable-http mode is intended for a short-lived tunnel to ChatGPT developer mode with the connector set to "No authentication". Anyone with the tunnel URL acts as the logged-in Spotify user — see gotchas.

Redirect URI: `http://127.0.0.1:8888/callback  (register this exact string in the Spotify Developer Dashboard; `localhost` is rejected, HTTP is allowed only for loopback literals, and casing/trailing-slash must match byte-for-byte)`

Scopes:

- `playlist-read-private`
- `playlist-read-collaborative`
- `playlist-modify-public`
- `playlist-modify-private`
- `user-library-read`
- `user-top-read`
- `user-read-recently-played`
- `user-read-private`

## Tools

| tool | endpoint | write | dev-mode |
|---|---|---|---|
| `get_current_user` | `GET /me` | read | ok |
| `list_my_playlists` | `GET /me/playlists` | read | ok |
| `get_playlist` | `GET /playlists/{id}` | read | ok |
| `get_playlist_items` | `GET /playlists/{id}/items` | read | ok |
| `search` | `GET /search` | read | ok |
| `get_track` | `GET /tracks/{id}` | read | ok |
| `get_artist` | `GET /artists/{id}` | read | ok |
| `get_artist_albums` | `GET /artists/{id}/albums` | read | ok |
| `get_album` | `GET /albums/{id}` | read | ok |
| `get_album_tracks` | `GET /albums/{id}/tracks` | read | ok |
| `get_liked_songs` | `GET /me/tracks` | read | ok |
| `get_saved_albums` | `GET /me/albums` | read | ok |
| `get_top_items` | `GET /me/top/{type}` | read | ok |
| `get_recently_played` | `GET /me/player/recently-played` | read | ok |
| `create_playlist` | `POST /me/playlists` | write | ok |
| `update_playlist_details` | `PUT /playlists/{id}` | write | ok |
| `add_playlist_items` | `POST /playlists/{id}/items` | write | ok |
| `remove_playlist_items` | `DELETE /playlists/{id}/items` | write | ok |
| `reorder_playlist_items` | `PUT /playlists/{id}/items (reorder body)` | write | ok |
| `replace_playlist_items` | `PUT /playlists/{id}/items (body {uris})` | write | ok |
| `get_audio_features` | `GET /audio-features/{id}` | read | DEPRECATED (403 for new apps) |
| `get_recommendations` | `GET /recommendations` | read | DEPRECATED (403 for new apps) |
| `get_related_artists` | `GET /artists/{id}/related-artists` | read | DEPRECATED (403 for new apps) |
| `get_artist_top_tracks` | `GET /artists/{id}/top-tracks` | read | DEPRECATED (403 for new apps) |

- `get_current_user`: Profile of the logged-in user (id, display_name, account_id, product when scope allows). Used by `whoami`.
- `list_my_playlists`: Paged list of the user's own + followed playlists, slimmed (id, uri, name, owner, public, collaborative, item_count). limit 1-50, offset.
- `get_playlist`: Playlist metadata (name, description, owner, snapshot_id, item total). Contents only present for owned/collaborative playlists.
- `get_playlist_items`: Paged tracks of a playlist the user owns or collaborates on; each item = added_at + slim track (id, uri, name, artists, album, duration_ms). limit 1-50, offset. 403 → ToolError explaining ownership rule.
- `search`: Search tracks/artists/albums/playlists. q supports artist:/track:/album:/year:/isrc: filters. limit 1-10 (Spotify cap since Feb 2026), offset 0-1000. Returns one slimmed page per requested type.
- `get_track`: Single track by id (one call per id; batch /tracks?ids= is removed for dev mode).
- `get_artist`: Single artist by id (name, genres, images, uri).
- `get_artist_albums`: Paged albums for an artist; include_groups subset of album,single,appears_on,compilation; limit 1-50, offset.
- `get_album`: Album by id with its first page of tracks.
- `get_album_tracks`: Paged tracks of an album; limit 1-50, offset.
- `get_liked_songs`: Paged Liked Songs (user's saved tracks) newest first; each item = added_at + slim track. limit 1-50, offset.
- `get_saved_albums`: Paged saved albums; limit 1-50, offset.
- `get_top_items`: User's top artists or tracks. type in {artists, tracks}; time_range in {short_term, medium_term, long_term} (default medium_term); limit 1-50, offset.
- `get_recently_played`: Recent listening history with played_at and context. limit 1-50; after XOR before (Unix ms) — ToolError if both given. Returns cursors for paging.
- `create_playlist`: Create a playlist for the current user: name (required), description, public (default false), collaborative (default false). Returns id, uri, snapshot_id, external url.
- `update_playlist_details`: Rename / re-describe / toggle public or collaborative on an owned playlist. Body only includes fields provided.
- `add_playlist_items`: Append (or insert at position) 1-100 spotify:track: URIs to an owned playlist. Body {uris, position?}. Returns snapshot_id.
- `remove_playlist_items`: Remove all occurrences of 1-100 URIs. Body {items:[{uri}], snapshot_id?} — key is `items`, not `tracks`. Returns snapshot_id. destructive_hint=true.
- `reorder_playlist_items`: Move a range: range_start, insert_before, range_length (default 1), snapshot_id?. Returns snapshot_id.
- `replace_playlist_items`: Replace the whole playlist contents with 0-100 URIs (empty list clears it). destructive_hint=true. Mutually exclusive with reorder on the same endpoint.
- `get_audio_features`: Tempo/key/energy for a track. DEPRECATED for apps created after 2024-11-27: dev-mode apps get 403 → ToolError with explanation and no retry. Kept because it works for legacy/extended-quota apps.
- `get_recommendations`: Seed-based recommendations (seed_tracks/seed_artists/seed_genres, limit). DEPRECATED for new apps: 403 → graceful ToolError.
- `get_related_artists`: Artists related to an artist. DEPRECATED for new apps: 403 → graceful ToolError.
- `get_artist_top_tracks`: An artist's top tracks. REMOVED from Development Mode in Feb 2026: 403 → graceful ToolError suggesting `search` with artist: filter instead.

## Transports

Default: `spotify-mcp serve` → `mcp.run(transport="stdio")`. Stdout is the wire: all Rich/console output in the CLI goes to `Console(stderr=True)`, logging uses stdlib `logging` (stderr by default), never print(). This is what Codex and Claude Code launch.

ChatGPT mode: `spotify-mcp serve --transport streamable-http [--host 127.0.0.1] [--port 8000] [--path /mcp] [--allow-host <tunnel-hostname>]... [--insecure-any-host]` → `mcp.run(transport="streamable-http", host, port, streamable_http_path=path, json_response=True, stateless_http=True, transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=not insecure_any_host, allowed_hosts=["127.0.0.1:*","localhost:*", <each --allow-host as "h" and "h:*">], allowed_origins=["https://chatgpt.com","https://chat.openai.com"]))`.
- json_response=True: one JSON body per POST instead of an SSE stream — required because Cloudflare quick tunnels do not support SSE; costs nothing here (no elicitation/progress used).
- stateless_http=True: no Mcp-Session-Id bookkeeping, no 30-minute idle expiry, safe if ChatGPT speaks the legacy 2025-11-25 era; server-to-client features are not needed.
- DNS-rebinding protection stays ON; the tunnel hostname must be allow-listed or every request returns 421 Misdirected Request. `--insecure-any-host` is the escape hatch for local experiments only.
- Legacy SSE transport (/sse) is deliberately not offered.

Both transports share one `build_server(settings, transport=None) -> MCPServer` factory; the lifespan owns a single `httpx.AsyncClient` (absolute URLs for both accounts.spotify.com and api.spotify.com) so tests can inject `httpx.MockTransport`.

## ChatGPT recipe

Prereqs: ChatGPT Pro/Plus/Business/Enterprise/Edu on the WEB (developer mode is web-only; Team/Business workspaces need an admin to enable Workspace Settings → Permissions & Roles → Connected Data → "Developer mode / Create custom MCP connectors"). `spotify-mcp login` already done.

1. brew install cloudflared
2. Terminal A: `cloudflared tunnel --url http://127.0.0.1:8000` — copy the printed https://<random>.trycloudflare.com hostname (it prints before the origin is up).
3. Terminal B (in the repo, env exported): `uv run spotify-mcp serve --transport streamable-http --port 8000 --allow-host <random>.trycloudflare.com`
4. Sanity check: `curl -s https://<random>.trycloudflare.com/mcp -X POST -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'` → JSON with serverInfo (a 421 means the hostname is not allow-listed).
5. chatgpt.com → Settings → Security and login → toggle "Developer mode" on.
6. Settings → Apps/Plugins → "+" (Create) → developer-mode app. Name "Spotify (local)", Connection = Public endpoint, URL `https://<random>.trycloudflare.com/mcp`, Authentication = "No authentication", tick the trust acknowledgement → Create. ChatGPT runs tools/list; all 24 tools should appear (toggle off the 4 DEPRECATED ones on the app's details page if you like).
7. New chat → "+" in the composer → Developer mode → enable the app → e.g. "Create a private playlist 'Warmup' and add the top 5 tracks from my last 4 weeks." Write tools prompt for confirmation by default (driven by destructive_hint/read_only_hint annotations — all tools set them).
8. After changing tool names/descriptions: click "Refresh" on the app's details page and start a new chat (ChatGPT caches the tool list).
9. Every cloudflared restart yields a new hostname: restart `serve` with the new --allow-host and edit the connector URL. For a stable hostname use `ngrok http 8000` (free account; `--allow-host <sub>.ngrok-free.app`) or OpenAI's Secure MCP Tunnel (`tunnel-client` v0.0.14 pointed at http://127.0.0.1:8000/mcp, then Connection = Tunnel).
10. Stop the tunnel when done — the endpoint is unauthenticated and acts as your Spotify account.

## Codex CLI
```toml
# ~/.codex/config.toml  (Codex env_clear()s stdio servers: only HOME/PATH/etc. plus these names/values get through)
[mcp_servers.spotify-mcp]
command = "uv"
args = ["run", "--directory", "/path/to/spotify-mcp", "spotify-mcp", "serve"]
env_vars = ["SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "SPOTIFY_REDIRECT_URI"]
startup_timeout_sec = 60
tool_timeout_sec = 120
default_tools_approval_mode = "prompt"

[mcp_servers.spotify-mcp.env]
UV_NO_SYNC = "1"

# auto-approve the read tools
[mcp_servers.spotify-mcp.tools.search]
approval_mode = "approve"
[mcp_servers.spotify-mcp.tools.get_playlist_items]
approval_mode = "approve"
[mcp_servers.spotify-mcp.tools.list_my_playlists]
approval_mode = "approve"

# CLI equivalent (cannot set env_vars/timeouts/approval — edit TOML afterwards):
# codex mcp add spotify-mcp --env SPOTIFY_CLIENT_ID=... --env SPOTIFY_CLIENT_SECRET=... -- \
#   uv run --directory /path/to/spotify-mcp spotify-mcp serve
# codex mcp get spotify-mcp && codex mcp list

# Prereqs: `export SPOTIFY_CLIENT_ID=... SPOTIFY_CLIENT_SECRET=...` in ~/.zshrc (env_vars forwards them without
# writing secrets to disk), `uv sync` once in the repo, and `uv run spotify-mcp login` once.
```

## Claude Code
```
# User scope (all projects; user/local scope servers inherit the shell env, project .mcp.json strips *SECRET*/*KEY* names)
claude mcp add --scope user --transport stdio spotify-mcp \
  -e SPOTIFY_CLIENT_ID="$SPOTIFY_CLIENT_ID" \
  -e SPOTIFY_CLIENT_SECRET="$SPOTIFY_CLIENT_SECRET" \
  -e SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback \
  -e UV_NO_SYNC=1 \
  -- uv run --directory /path/to/spotify-mcp spotify-mcp serve

claude mcp get spotify-mcp
claude mcp list

# Project-scope alternative: /path/to/your-project/.mcp.json
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
# Flags (-e, --scope, --transport) go BEFORE `--`; everything after is the server command verbatim.
# Slow first start: set MCP_TIMEOUT=60000 or run `uv sync` in the repo first.
```

## Testing

All tests run in-process with `pytest` + the anyio plugin (`@pytest.mark.anyio`, `anyio_backend` fixture returns "asyncio"); no subprocess, no network, no respx.

Seams:
- `Settings(client_id, client_secret, config_dir=tmp_path)` — token cache isolated per test.
- `build_server(settings, transport=httpx.MockTransport(fake.handler))` — the lifespan's httpx.AsyncClient gets the mock transport; the same client serves accounts.spotify.com (token refresh) and api.spotify.com, so the handler routes on `(request.method, request.url.path)` ("/api/token" vs "/v1/...").
- `FakeSpotify` fixture: dict of routes → (status, json), records every `httpx.Request` so tests assert exact bodies/query params.
- `mcp.Client(server, raise_exceptions=True)` from the official SDK connects in-memory; assertions use `result.is_error`, `result.structured_content`, `result.content[0].text`.

Test files (~25 tests, < 2s):
- tests/test_tools_list.py: 24 tool names exactly; every tool has annotations with read_only_hint set; write tools have read_only_hint False; remove/replace have destructive_hint True; deprecated tools' descriptions start with "DEPRECATED".
- tests/test_read_tools.py: get_playlist_items maps `item` (new) and `track` (legacy) to slim tracks, computes next_offset from `next`; search sends type list and limit ≤10 (limit 11 → validation error is_error); get_top_items sends time_range; get_recently_played rejects after+before.
- tests/test_write_tools.py: add sends {"uris":[...],"position":N}; remove sends {"items":[{"uri":..}]} (regression for the `tracks`→`items` rename); reorder sends range_start/insert_before/range_length; replace sends {"uris":[]}; create posts to /v1/me/playlists with public False default; all return snapshot_id in structured_content.
- tests/test_auth.py: expired token → POST /api/token with Basic header + grant_type=refresh_token, new access_token persisted, old refresh_token kept when response omits one, rotated one persisted when present; 400 invalid_grant → is_error, message contains "spotify-mcp login", token.json deleted; no token.json → is_error "Not logged in"; token file written 0600; `authorize_url` contains all 8 scopes, state and redirect_uri; `exchange_code` posts Basic header (sync test via `httpx.AsyncClient(transport=MockTransport)` + anyio).
- tests/test_errors.py: 403 on /v1/audio-features → is_error with "Development Mode" text (no retry, exactly one request); 403 on /v1/playlists/x/items → ownership message; 429 with Retry-After → one retry after `asyncio.sleep` (monkeypatched) then success; 429 with reason QUOTA_EXCEEDED → no retry; 5xx → ToolError with status; unexpected exception is not leaked (mcp masks it, assert is_error).
- tests/test_cli.py: `typer.testing.CliRunner` — `status` exit 1 with no token and 0 with a seeded token; `tools` lists 24 rows offline (uses in-process Client, no network); `serve --help` shows both transports; `login` is not exercised end-to-end (browser), but `wait_for_code` is tested by hitting the loopback HTTPServer from a thread with a good and a bad state.
- tests/test_stdio_smoke.py (marked `slow`, skipped by default): `Client(StdioServerParameters(command=sys.executable, args=["-m","spotify_mcp","serve"], env={...SPOTIFY_MCP_CONFIG_DIR: tmp}))` → list_tools returns 24 names; proves stdout is clean.

Run: `uv run pytest -q`; CI-equivalent: `uv sync --all-groups && uv run pytest`.

## Gotchas

- mcp 2.x API: `from mcp.server import MCPServer` — `from mcp.server.fastmcp import FastMCP` raises ModuleNotFoundError by design. All result/type attributes are snake_case (`result.is_error`, `result.structured_content`, `tool.input_schema`, `ToolAnnotations(read_only_hint=...)`). `mcp.get_context()` is gone; inject `ctx: Context[AppContext]` by type annotation. host/port/json_response/stateless_http/transport_security are kwargs of `mcp.run()`, not the constructor.
- mcp 2.2.0 depends on `httpx2`, not `httpx`; add `httpx>=0.28` explicitly or `import httpx` fails in a fresh venv. Plain `def` tools run on a worker thread — every tool here is `async def` because it touches the shared AsyncClient.
- Never print() in `serve`; stdout is the stdio wire. Rich must use `Console(stderr=True)`; logging defaults to stderr and is fine. Typer's `no_args_is_help` output goes to stdout but only when no command is given, so `serve` itself stays clean.
- Raise `ToolError` (mcp.server.mcpserver.exceptions) for every anticipated failure; any other exception is masked as 'Error executing tool <name>' and the model never sees the reason. Raising `MCPError` inside a tool becomes a JSON-RPC protocol error, not a tool result.
- Python param ordering: `ctx: Context[AppContext]` has no default, so it must come BEFORE parameters with defaults (`limit=50`) or the def is a SyntaxError. Type aliases like `Limit50 = Annotated[int, Field(ge=1, le=50)]` keep signatures readable.
- Spotify redirect URI: `localhost` is rejected; register `http://127.0.0.1:8888/callback` exactly (HTTP only allowed for loopback literals). The login server must bind to the same literal 127.0.0.1, not 0.0.0.0/localhost, and the string sent to /authorize must match byte-for-byte including no trailing slash. The sibling spotify-htmx-app's `http://localhost:5500/authenticate` and spotify-pwa's HTTPS URLs are not reusable.
- Development Mode reality (apps created today): owner must keep Spotify Premium; max 5 allow-listed users (Dashboard > Settings > User Management — add your own account or /me returns 403); quota is per developer account across all its apps; all `/playlists/{id}/tracks` paths return 403 — use `/items`; DELETE body key is `items` not `tracks`; read responses use `item` (with `track` as deprecated alias); batch `GET /tracks?ids=` and `/artists?ids=` are removed — fetch per id; `/artists/{id}/top-tracks`, `/users/{id}/playlists`, `POST /users/{id}/playlists` are removed — create via `POST /me/playlists`.
- Playlist contents are readable only for playlists the user owns or collaborates on; other users' and Spotify editorial playlists return metadata only or 403. Do not promise 'read any public playlist'.
- Search: `limit` max is 10 (default 5) since Feb 2026, offset max 1000; playlist search results can contain null items (filter them). Popularity, available_markets, followers, user country/email/product are stripped from dev-mode responses — do not build on them.
- Recommendations, audio-features (BPM/key!), audio-analysis, related-artists are 403 for apps created after 2024-11-27 with no replacement. The four DEPRECATED tools exist for legacy apps only; they pass `restricted=True` so the 403 becomes a one-line ToolError with no retry. Spotify never documents the status code for these; 403 is from consistent community reports.
- Refresh tokens expire 6 months after the ORIGINAL consent (since 2026-06-18/07-20) and refreshing does not extend them; on `400 invalid_grant` delete token.json and tell the user to run `login` — never retry. Classic-flow refreshes usually omit `refresh_token` (keep the old one) but persist it whenever present. Granted `scope` can be narrower than requested — `login` prints the diff.
- Two kinds of 429: rolling-30s rate limit (honour `Retry-After`, capped at 30s, retry once) and per-account quota (`reason: QUOTA_EXCEEDED`, do not retry). No numeric limits are published.
- Streamable HTTP defaults are wrong for tunnels: DNS-rebinding protection auto-enables when host is 127.0.0.1 and rejects any other Host header with 421 'Invalid Host header' — pass the exact tunnel hostname via `--allow-host` (entries are literal strings; wildcard support such as `*.trycloudflare.com` is unverified, so pass the concrete host). Cloudflare quick tunnels do not support SSE, hence `json_response=True`. Idle sessions expire after 30 minutes since 2.2.0; `stateless_http=True` sidesteps that.
- The ChatGPT connector is 'No authentication': anyone with the tunnel URL is you on Spotify. Quick-tunnel hostnames are random and change on every restart (edit the connector URL each time); stop the tunnel when done. Developer mode is web-only and needs Pro/Plus/Business/Enterprise/Edu; ChatGPT caches tools/list — click Refresh + new chat after schema changes. Write tools prompt for confirmation; all tools must carry read_only_hint/destructive_hint/open_world_hint or ChatGPT may prompt for everything.
- Codex `env_clear()`s stdio servers: only HOME/PATH/SHELL/USER/LANG/TERM/TMPDIR/TZ etc. survive, so SPOTIFY_* must be listed in `env_vars` (forwarded from the launching shell, not persisted) or in `[mcp_servers.spotify-mcp.env]` (plaintext in config.toml). `codex mcp add` cannot set env_vars/cwd/timeouts/approval — edit the TOML. Default startup timeout is 10s; a cold `uv run` can exceed it → `startup_timeout_sec = 60` and `UV_NO_SYNC=1` after a one-time `uv sync`. Use the absolute `uv` path.
- Claude Code: default scope is `local` (this project only); use `--scope user`. Project `.mcp.json` servers get inherited env vars whose names contain TOKEN/SECRET/PASSWORD/KEY/AUTH stripped — use the `env` map with `${VAR}` expansion. Flags go before `--`.
- `uv run --directory <repo> spotify-mcp serve` works from any cwd only because `spotify-mcp` is a `[project.scripts]` entry; add `src/spotify_mcp/__main__.py` too so `python -m spotify_mcp serve` works for the stdio smoke test. The repo /path/to/spotify-mcp does not exist yet — both clients fail to start until it does.
- Token cache concurrency: `serve` (one per client: Codex, Claude Code, ChatGPT tunnel) and the CLI all read token.json on every call and refresh under a per-process lock; two processes may refresh simultaneously, which is harmless with the classic flow (old refresh_token stays valid). Do not switch to PKCE without adding cross-process locking, because PKCE refresh tokens rotate.
- Dev-mode responses are large; every list tool returns slimmed dicts (id, uri, name, artists, album, duration_ms) plus `next_offset` — return raw Spotify JSON only for single-entity tools. Codex default MAX output is 25k tokens per tool call.
- Zero-comment policy for this repo (per user CLAUDE.md): the snippets above contain no comments on purpose; keep it that way and put rationale in commit messages.
- The dotnet-claude-kit pre-bash hook blocks `rm -rf`; use fresh scratch dirs instead of deleting.

## Open questions

- Which Spotify dashboard app to use: create a NEW app for spotify-mcp (guaranteed Development Mode rules: Premium owner, 5 users, /items only) or reuse the client id behind spotify-htmx-app/spotify-pwa — reusing an older app may still allow some pre-Nov-2024 endpoints. Either way the redirect URI http://127.0.0.1:8888/callback must be added in the dashboard and the user added under User Management.
- Whether Spotify accepts PKCE parameters combined with the Basic-auth exchange (would let the same code path work with or without a secret). Not verified; v1 uses classic flow only.
- Whether `TransportSecuritySettings.allowed_hosts` accepts wildcard entries like `*.trycloudflare.com`; brief assumes literal hostnames via `--allow-host`.
- Whether ChatGPT's MCP client speaks the 2026-07-28 stateless revision or only legacy initialize-based revisions; mcp 2.2.0 is dual-era so `stateless_http=True` + `json_response=True` should serve both, but this is untested against ChatGPT.
- Exact `result.content[0].text` format for `dict[str, Any]` structured results (JSON string is expected per spec; tests assert on structured_content and only substring-match ToolError text).
- Latest typer/rich versions on 2026-09-10 were not verified — pyproject uses lower bounds; commit uv.lock after `uv lock`.
- Whether to hide the four DEPRECATED tools by default (e.g. `serve --include-deprecated`) to reduce confirmation noise in ChatGPT; brief exposes them always with a DEPRECATED description.
- Whether liked-song writes (`user-library-modify`, PUT/DELETE /me/library) or playback control should be added later; excluded from v1 scope and scope list.
- Whether `GET /me` still returns `product`/`country` for dev-mode apps (changelog says removed, reference page still documents them); `whoami` prints `n/a` when absent.

## Reference snippets (from research, verified against mcp 2.2.0 where marked)

### pyproject.toml
```
[project]
name = "spotify-mcp"
version = "0.1.0"
description = "Spotify MCP server (stdio + streamable HTTP) with a Typer CLI"
requires-python = ">=3.13"
dependencies = [
    "mcp==2.2.0",
    "httpx>=0.28",
    "typer>=0.15",
    "rich>=13",
    "pydantic>=2",
]

[project.scripts]
spotify-mcp = "spotify_mcp.cli:app"

[dependency-groups]
dev = ["pytest>=8", "anyio>=4"]

[build-system]
requires = ["uv_build>=0.9.26,<0.10"]
build-backend = "uv_build"

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["slow: spawns a subprocess"]
addopts = "-m 'not slow'"

# .python-version
# 3.13
#
# layout:
# src/spotify_mcp/{__init__.py,__main__.py,settings.py,auth.py,spotify.py,server.py,cli.py}
# tests/{conftest.py,test_tools_list.py,test_read_tools.py,test_write_tools.py,test_auth.py,test_errors.py,test_cli.py}
# __main__.py:  from .cli import app; app()
```

### src/spotify_mcp/settings.py
```
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_REDIRECT_URI = "http://127.0.0.1:8888/callback"
DEFAULT_CONFIG_DIR = Path.home() / ".config" / "spotify-mcp"
SCOPES = (
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-public",
    "playlist-modify-private",
    "user-library-read",
    "user-top-read",
    "user-read-recently-played",
    "user-read-private",
)


@dataclass(frozen=True)
class Settings:
    client_id: str
    client_secret: str
    redirect_uri: str = DEFAULT_REDIRECT_URI
    config_dir: Path = DEFAULT_CONFIG_DIR

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            client_id=os.environ.get("SPOTIFY_CLIENT_ID", ""),
            client_secret=os.environ.get("SPOTIFY_CLIENT_SECRET", ""),
            redirect_uri=os.environ.get("SPOTIFY_REDIRECT_URI", DEFAULT_REDIRECT_URI),
            config_dir=Path(os.environ.get("SPOTIFY_MCP_CONFIG_DIR", str(DEFAULT_CONFIG_DIR))).expanduser(),
        )

    @property
    def token_path(self) -> Path:
        return self.config_dir / "token.json"

    @property
    def callback(self) -> tuple[str, int, str]:
        u = urlparse(self.redirect_uri)
        return u.hostname or "127.0.0.1", u.port or 80, u.path or "/"

```

### src/spotify_mcp/auth.py — Authorization Code flow with client secret, token cache, loopback callback
```
import base64
import json
import os
import time
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .settings import SCOPES, Settings

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
EXPIRY_MARGIN_S = 60
CALLBACK_TIMEOUT_S = 300


class AuthError(Exception):
    pass


@dataclass
class Token:
    access_token: str
    refresh_token: str
    expires_at: float
    scope: str
    client_id: str

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at - EXPIRY_MARGIN_S


def load_token(settings: Settings) -> Token | None:
    if not settings.token_path.exists():
        return None
    return Token(**json.loads(settings.token_path.read_text()))


def save_token(settings: Settings, token: Token) -> None:
    settings.config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = settings.token_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(token), indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(settings.token_path)


def clear_token(settings: Settings) -> None:
    settings.token_path.unlink(missing_ok=True)


def authorize_url(settings: Settings, state: str) -> str:
    query = {
        "client_id": settings.client_id,
        "response_type": "code",
        "redirect_uri": settings.redirect_uri,
        "scope": " ".join(SCOPES),
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(query)}"


def _basic_auth(settings: Settings) -> dict[str, str]:
    raw = f"{settings.client_id}:{settings.client_secret}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


def _token_from(settings: Settings, data: dict, previous_refresh: str | None = None) -> Token:
    return Token(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token") or previous_refresh or "",
        expires_at=time.time() + int(data["expires_in"]),
        scope=data.get("scope", ""),
        client_id=settings.client_id,
    )


async def exchange_code(http: httpx.AsyncClient, settings: Settings, code: str) -> Token:
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": settings.redirect_uri}
    r = await http.post(TOKEN_URL, headers=_basic_auth(settings), data=data)
    if r.status_code != 200:
        raise AuthError(f"Token exchange failed: {r.status_code} {r.text}")
    return _token_from(settings, r.json())


async def refresh(http: httpx.AsyncClient, settings: Settings, token: Token) -> Token:
    data = {"grant_type": "refresh_token", "refresh_token": token.refresh_token}
    r = await http.post(TOKEN_URL, headers=_basic_auth(settings), data=data)
    if r.status_code == 400 and r.json().get("error") == "invalid_grant":
        clear_token(settings)
        raise AuthError("Refresh token expired or revoked. Run `spotify-mcp login` again.")
    if r.status_code != 200:
        raise AuthError(f"Token refresh failed: {r.status_code} {r.text}")
    new = _token_from(settings, r.json(), previous_refresh=token.refresh_token)
    save_token(settings, new)
    return new


def wait_for_code(settings: Settings, state: str) -> str:
    host, port, path = settings.callback
    result: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            url = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path != path:
                self.send_error(404)
                return
            if query.get("state") != state:
                self.send_error(400, "state mismatch")
                return
            result.update(query)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"spotify-mcp: login complete, you can close this tab.")

        def log_message(self, *args) -> None:
            pass

    with HTTPServer((host, port), Handler) as server:
        server.timeout = CALLBACK_TIMEOUT_S
        server.handle_request()
    if "error" in result:
        raise AuthError(f"Spotify returned error: {result['error']}")
    if "code" not in result:
        raise AuthError("Timed out waiting for the Spotify redirect.")
    return result["code"]

```

### src/spotify_mcp/spotify.py — one request() wrapper: token refresh, 401/403/429 mapping to ToolError
```
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
PLAYLIST_FORBIDDEN_MESSAGE = (
    "Spotify returned 403: playlist contents are only available for playlists the logged-in user owns or collaborates on."
)


class SpotifyClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self.settings = settings
        self.http = http
        self._lock = asyncio.Lock()

    async def _access_token(self) -> str:
        async with self._lock:
            token = auth.load_token(self.settings)
            if token is None:
                raise ToolError("Not logged in. Run `spotify-mcp login` in a terminal first.")
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
    ) -> Any:
        headers = {"Authorization": f"Bearer {await self._access_token()}"}
        r = await self.http.request(method, f"{API}{path}", params=params, json=json, headers=headers)
        if r.status_code == 429:
            if _reason(r) == "QUOTA_EXCEEDED":
                raise ToolError("Spotify Development Mode quota for this developer account is exhausted; try again later.")
            await asyncio.sleep(min(int(r.headers.get("Retry-After", "1")), MAX_RETRY_AFTER_S))
            r = await self.http.request(method, f"{API}{path}", params=params, json=json, headers=headers)
        if r.status_code == 403 and restricted:
            raise ToolError(RESTRICTED_MESSAGE)
        if r.status_code == 403 and "/playlists/" in path:
            raise ToolError(PLAYLIST_FORBIDDEN_MESSAGE)
        if r.status_code == 401:
            raise ToolError("Spotify rejected the token (401). Run `spotify-mcp login` again.")
        if r.status_code >= 400:
            raise ToolError(f"Spotify {r.status_code} on {method} {path}: {_message(r)}")
        return r.json() if r.content else {}


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

```

### src/spotify_mcp/server.py — build_server() with lifespan, annotations, representative read / write / deprecated tools
```
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Any, Literal

import httpx
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from .settings import Settings
from .spotify import SpotifyClient

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True)
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=True)
DEPRECATED = "DEPRECATED by Spotify for apps created after 2024-11-27 (403 in Development Mode). "

INSTRUCTIONS = (
    "Spotify tools acting as the logged-in user. Use `search` (max 10 results per call, paginate with offset) "
    "to find spotify:track: URIs before add/remove. Playlist contents are only readable for playlists the user "
    "owns or collaborates on. Tools marked DEPRECATED fail on new Spotify apps; do not retry them."
)

Limit50 = Annotated[int, Field(ge=1, le=50)]
Offset = Annotated[int, Field(ge=0)]
Uris = Annotated[list[str], Field(min_length=1, max_length=100, description="spotify:track:... URIs")]


@dataclass
class AppContext:
    spotify: SpotifyClient


def slim_track(t: dict | None) -> dict[str, Any]:
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


def slim_playlist(p: dict) -> dict[str, Any]:
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


def page(data: dict, mapper: Callable[[dict], dict]) -> dict[str, Any]:
    items = data.get("items") or []
    offset = data.get("offset", 0)
    return {
        "total": data.get("total"),
        "offset": offset,
        "next_offset": offset + len(items) if data.get("next") else None,
        "items": [mapper(i) for i in items if i],
    }


def playlist_entry(i: dict) -> dict[str, Any]:
    return {"added_at": i.get("added_at"), **slim_track(i.get("item") or i.get("track"))}


def build_server(settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> MCPServer:
    @asynccontextmanager
    async def lifespan(server: MCPServer) -> AsyncIterator[AppContext]:
        async with httpx.AsyncClient(timeout=20, transport=transport) as http:
            yield AppContext(spotify=SpotifyClient(settings, http))

    mcp = MCPServer("spotify", instructions=INSTRUCTIONS, lifespan=lifespan)

    def api(ctx: Context[AppContext]) -> SpotifyClient:
        return ctx.request_context.lifespan_context.spotify

    @mcp.tool(annotations=READ)
    async def get_current_user(ctx: Context[AppContext]) -> dict[str, Any]:
        """Profile of the logged-in Spotify user."""
        return await api(ctx).request("GET", "/me")

    @mcp.tool(annotations=READ)
    async def list_my_playlists(ctx: Context[AppContext], limit: Limit50 = 50, offset: Offset = 0) -> dict[str, Any]:
        """Playlists owned or followed by the user (paged)."""
        data = await api(ctx).request("GET", "/me/playlists", params={"limit": limit, "offset": offset})
        return page(data, slim_playlist)

    @mcp.tool(annotations=READ)
    async def get_playlist_items(
        ctx: Context[AppContext], playlist_id: str, limit: Limit50 = 50, offset: Offset = 0
    ) -> dict[str, Any]:
        """Tracks in a playlist the user owns or collaborates on (paged)."""
        params = {"limit": limit, "offset": offset, "additional_types": "track"}
        data = await api(ctx).request("GET", f"/playlists/{playlist_id}/items", params=params)
        return page(data, playlist_entry)

    @mcp.tool(annotations=READ)
    async def search(
        ctx: Context[AppContext],
        q: Annotated[str, Field(description="Query; supports artist:, track:, album:, year:, isrc: filters")],
        types: list[Literal["track", "artist", "album", "playlist"]] = ["track"],
        limit: Annotated[int, Field(ge=1, le=10)] = 10,
        offset: Annotated[int, Field(ge=0, le=1000)] = 0,
    ) -> dict[str, Any]:
        """Search Spotify. Max 10 results per call; paginate with offset."""
        params = {"q": q, "type": ",".join(types), "limit": limit, "offset": offset}
        data = await api(ctx).request("GET", "/search", params=params)
        mappers = {"tracks": slim_track, "playlists": slim_playlist}
        return {k: page(v, mappers.get(k, lambda x: x)) for k, v in data.items()}

    @mcp.tool(annotations=READ)
    async def get_top_items(
        ctx: Context[AppContext],
        type: Literal["artists", "tracks"],
        time_range: Literal["short_term", "medium_term", "long_term"] = "medium_term",
        limit: Limit50 = 20,
        offset: Offset = 0,
    ) -> dict[str, Any]:
        """The user's top artists or tracks over ~4 weeks, ~6 months or ~1 year."""
        params = {"time_range": time_range, "limit": limit, "offset": offset}
        data = await api(ctx).request("GET", f"/me/top/{type}", params=params)
        return page(data, slim_track if type == "tracks" else (lambda a: a))

    @mcp.tool(annotations=READ)
    async def get_recently_played(
        ctx: Context[AppContext], limit: Limit50 = 50, after: int | None = None, before: int | None = None
    ) -> dict[str, Any]:
        """Recently played tracks. after/before are Unix ms and mutually exclusive."""
        if after is not None and before is not None:
            raise ToolError("Pass either `after` or `before`, not both.")
        params = {"limit": limit} | ({"after": after} if after is not None else {}) | ({"before": before} if before is not None else {})
        data = await api(ctx).request("GET", "/me/player/recently-played", params=params)
        items = [{"played_at": i.get("played_at"), **slim_track(i.get("track"))} for i in data.get("items", [])]
        return {"items": items, "cursors": data.get("cursors")}

    @mcp.tool(annotations=WRITE)
    async def create_playlist(
        ctx: Context[AppContext], name: str, description: str = "", public: bool = False, collaborative: bool = False
    ) -> dict[str, Any]:
        """Create a playlist for the current user."""
        body = {"name": name, "description": description, "public": public, "collaborative": collaborative}
        return slim_playlist(await api(ctx).request("POST", "/me/playlists", json=body))

    @mcp.tool(annotations=WRITE)
    async def add_playlist_items(
        ctx: Context[AppContext], playlist_id: str, uris: Uris, position: Offset | None = None
    ) -> dict[str, Any]:
        """Add up to 100 tracks to a playlist you own; optional insert position."""
        body = {"uris": uris} | ({"position": position} if position is not None else {})
        return await api(ctx).request("POST", f"/playlists/{playlist_id}/items", json=body)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def remove_playlist_items(
        ctx: Context[AppContext], playlist_id: str, uris: Uris, snapshot_id: str | None = None
    ) -> dict[str, Any]:
        """Remove all occurrences of up to 100 tracks from a playlist you own."""
        body = {"items": [{"uri": u} for u in uris]} | ({"snapshot_id": snapshot_id} if snapshot_id else {})
        return await api(ctx).request("DELETE", f"/playlists/{playlist_id}/items", json=body)

    @mcp.tool(annotations=WRITE)
    async def reorder_playlist_items(
        ctx: Context[AppContext],
        playlist_id: str,
        range_start: Offset,
        insert_before: Offset,
        range_length: Annotated[int, Field(ge=1)] = 1,
        snapshot_id: str | None = None,
    ) -> dict[str, Any]:
        """Move range_length items starting at range_start so they sit before insert_before."""
        body = {"range_start": range_start, "insert_before": insert_before, "range_length": range_length}
        body |= {"snapshot_id": snapshot_id} if snapshot_id else {}
        return await api(ctx).request("PUT", f"/playlists/{playlist_id}/items", json=body)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def replace_playlist_items(
        ctx: Context[AppContext], playlist_id: str, uris: Annotated[list[str], Field(max_length=100)]
    ) -> dict[str, Any]:
        """Replace the entire playlist contents (empty list clears it)."""
        return await api(ctx).request("PUT", f"/playlists/{playlist_id}/items", json={"uris": uris})

    @mcp.tool(annotations=READ, description=DEPRECATED + "Tempo, key, energy and other audio features for a track.")
    async def get_audio_features(ctx: Context[AppContext], track_id: str) -> dict[str, Any]:
        return await api(ctx).request("GET", f"/audio-features/{track_id}", restricted=True)

    @mcp.tool(annotations=READ, description=DEPRECATED + "Top tracks for an artist. Use `search` with an artist: filter instead.")
    async def get_artist_top_tracks(ctx: Context[AppContext], artist_id: str) -> dict[str, Any]:
        data = await api(ctx).request("GET", f"/artists/{artist_id}/top-tracks", restricted=True)
        return {"items": [slim_track(t) for t in data.get("tracks", [])]}

    # remaining tools follow the same shapes:
    # get_playlist, get_track, get_artist, get_artist_albums, get_album, get_album_tracks,
    # get_liked_songs (/me/tracks -> page(data, playlist_entry)), get_saved_albums,
    # update_playlist_details (PUT /playlists/{id}, body = only provided fields),
    # get_recommendations, get_related_artists (restricted=True)
    return mcp

```

### src/spotify_mcp/cli.py — Typer + Rich: login, status, whoami, tools, serve (stdio | streamable-http)
```
import asyncio
import secrets
import time
import webbrowser
from enum import Enum
from typing import Annotated

import httpx
import typer
from mcp import Client
from mcp.server.transport_security import TransportSecuritySettings
from rich.console import Console
from rich.table import Table

from . import auth
from .server import build_server
from .settings import SCOPES, Settings
from .spotify import SpotifyClient

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console(stderr=True)


class Transport(str, Enum):
    stdio = "stdio"
    streamable_http = "streamable-http"


def _settings() -> Settings:
    s = Settings.from_env()
    if not s.client_id or not s.client_secret:
        console.print("[red]SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET must be set.[/red]")
        raise typer.Exit(1)
    return s


@app.command()
def login() -> None:
    """Authorize with Spotify in the browser and cache the token."""
    s = _settings()
    state = secrets.token_urlsafe(16)
    url = auth.authorize_url(s, state)
    console.print(f"Opening browser. If nothing happens, visit:\n{url}")
    webbrowser.open(url)
    code = auth.wait_for_code(s, state)

    async def exchange() -> auth.Token:
        async with httpx.AsyncClient(timeout=20) as http:
            return await auth.exchange_code(http, s, code)

    token = asyncio.run(exchange())
    auth.save_token(s, token)
    console.print(f"[green]Logged in.[/green] Token cached at {s.token_path}")
    missing = set(SCOPES) - set(token.scope.split())
    if missing:
        console.print(f"[yellow]Granted scopes are narrower than requested; missing: {' '.join(sorted(missing))}[/yellow]")


@app.command()
def status() -> None:
    """Show config and token cache state without calling Spotify."""
    s = Settings.from_env()
    token = auth.load_token(s)
    table = Table(show_header=False)
    table.add_row("config dir", str(s.config_dir))
    table.add_row("client id", f"{s.client_id[:6]}..." if s.client_id else "[red]missing[/red]")
    table.add_row("client secret", "set" if s.client_secret else "[red]missing[/red]")
    table.add_row("redirect uri", s.redirect_uri)
    if token is None:
        table.add_row("token", "[red]none - run `spotify-mcp login`[/red]")
    else:
        remaining = int(token.expires_at - time.time())
        table.add_row("token", "expired (refreshes on next call)" if token.expired else f"valid for {remaining}s")
        table.add_row("scopes", token.scope or "-")
    console.print(table)
    raise typer.Exit(0 if token else 1)


@app.command()
def whoami() -> None:
    """Call GET /me with the cached token."""
    s = _settings()

    async def me() -> dict:
        async with httpx.AsyncClient(timeout=20) as http:
            return await SpotifyClient(s, http).request("GET", "/me")

    try:
        user = asyncio.run(me())
    except Exception as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(f"[bold]{user.get('display_name')}[/bold] id={user.get('id')} product={user.get('product', 'n/a')}")


@app.command()
def tools() -> None:
    """List the MCP tools this server exposes."""
    server = build_server(Settings.from_env())

    async def list_tools() -> list:
        async with Client(server, raise_exceptions=True) as c:
            return (await c.list_tools()).tools

    table = Table("tool", "kind", "description")
    for t in asyncio.run(list_tools()):
        kind = "read" if t.annotations and t.annotations.read_only_hint else "write"
        table.add_row(t.name, kind, (t.description or "").splitlines()[0])
    console.print(table)


@app.command()
def serve(
    transport: Transport = Transport.stdio,
    host: str = "127.0.0.1",
    port: int = 8000,
    path: str = "/mcp",
    allow_host: Annotated[list[str] | None, typer.Option(help="Public hostname (tunnel) to accept; repeatable")] = None,
    insecure_any_host: bool = False,
) -> None:
    """Run the MCP server: stdio (default) or streamable-http for ChatGPT."""
    server = build_server(Settings.from_env())
    if transport is Transport.stdio:
        server.run(transport="stdio")
        return
    hosts = ["127.0.0.1:*", "localhost:*"] + [h for a in allow_host or [] for h in (a, f"{a}:*")]
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=not insecure_any_host,
        allowed_hosts=hosts,
        allowed_origins=["https://chatgpt.com", "https://chat.openai.com"],
    )
    console.print(f"Serving streamable HTTP on http://{host}:{port}{path}")
    server.run(
        transport="streamable-http",
        host=host,
        port=port,
        streamable_http_path=path,
        json_response=True,
        stateless_http=True,
        transport_security=security,
    )

```

### tests/conftest.py + tests/test_write_tools.py + tests/test_auth.py (in-process Client, httpx.MockTransport)
```
# tests/conftest.py
import json
import time

import httpx
import pytest
from mcp import Client

from spotify_mcp.auth import Token, save_token
from spotify_mcp.server import build_server
from spotify_mcp.settings import Settings


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(client_id="cid", client_secret="secret", config_dir=tmp_path)


@pytest.fixture
def logged_in(settings) -> Settings:
    save_token(settings, Token("at", "rt", time.time() + 3600, "user-read-private", "cid"))
    return settings


class FakeSpotify:
    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], tuple[int, dict, dict]] = {}
        self.requests: list[httpx.Request] = []

    def add(self, method: str, path: str, body: dict, status: int = 200, headers: dict | None = None) -> None:
        self.routes[(method, path)] = (status, body, headers or {})

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = (request.method, request.url.path)
        if key not in self.routes:
            return httpx.Response(404, json={"error": {"status": 404, "message": f"unmocked {key}"}})
        status, body, headers = self.routes[key]
        return httpx.Response(status, json=body, headers=headers)

    def body(self, index: int = -1) -> dict:
        return json.loads(self.requests[index].content)


@pytest.fixture
def fake() -> FakeSpotify:
    return FakeSpotify()


@pytest.fixture
async def client(logged_in, fake):
    server = build_server(logged_in, transport=httpx.MockTransport(fake.handler))
    async with Client(server, raise_exceptions=True) as c:
        yield c


# tests/test_write_tools.py
import pytest


@pytest.mark.anyio
async def test_remove_uses_items_key(client, fake):
    fake.add("DELETE", "/v1/playlists/p1/items", {"snapshot_id": "s2"})
    result = await client.call_tool("remove_playlist_items", {"playlist_id": "p1", "uris": ["spotify:track:a"]})
    assert result.is_error is False
    assert result.structured_content == {"snapshot_id": "s2"}
    assert fake.body() == {"items": [{"uri": "spotify:track:a"}]}
    assert fake.requests[-1].headers["Authorization"] == "Bearer at"


@pytest.mark.anyio
async def test_reorder_body(client, fake):
    fake.add("PUT", "/v1/playlists/p1/items", {"snapshot_id": "s3"})
    result = await client.call_tool(
        "reorder_playlist_items", {"playlist_id": "p1", "range_start": 1, "insert_before": 3, "range_length": 2}
    )
    assert result.structured_content == {"snapshot_id": "s3"}
    assert fake.body() == {"range_start": 1, "insert_before": 3, "range_length": 2}


@pytest.mark.anyio
async def test_create_playlist_posts_to_me(client, fake):
    fake.add("POST", "/v1/me/playlists", {"id": "p9", "uri": "spotify:playlist:p9", "name": "Warmup", "owner": {"id": "me"}, "public": False, "items": {"total": 0}}, status=201)
    result = await client.call_tool("create_playlist", {"name": "Warmup"})
    assert result.structured_content["id"] == "p9"
    assert fake.body()["public"] is False


# tests/test_auth.py
import json
import time

import httpx
import pytest
from mcp import Client

from spotify_mcp.auth import Token, load_token, save_token
from spotify_mcp.server import build_server


@pytest.mark.anyio
async def test_refreshes_expired_token_and_keeps_old_refresh_token(settings, fake):
    save_token(settings, Token("old", "rt", time.time() - 10, "", "cid"))
    fake.add("POST", "/api/token", {"access_token": "new", "token_type": "Bearer", "expires_in": 3600, "scope": ""})
    fake.add("GET", "/v1/me", {"id": "me"})
    server = build_server(settings, transport=httpx.MockTransport(fake.handler))
    async with Client(server, raise_exceptions=True) as c:
        result = await c.call_tool("get_current_user", {})
    assert result.structured_content == {"id": "me"}
    refresh = fake.requests[0]
    assert refresh.url.host == "accounts.spotify.com"
    assert refresh.headers["Authorization"].startswith("Basic ")
    assert b"grant_type=refresh_token" in refresh.content
    assert fake.requests[1].headers["Authorization"] == "Bearer new"
    saved = load_token(settings)
    assert saved.access_token == "new" and saved.refresh_token == "rt"
    assert oct(settings.token_path.stat().st_mode & 0o777) == "0o600"


@pytest.mark.anyio
async def test_invalid_grant_clears_token(settings, fake):
    save_token(settings, Token("old", "rt", time.time() - 10, "", "cid"))
    fake.add("POST", "/api/token", {"error": "invalid_grant"}, status=400)
    server = build_server(settings, transport=httpx.MockTransport(fake.handler))
    async with Client(server, raise_exceptions=True) as c:
        result = await c.call_tool("get_current_user", {})
    assert result.is_error is True
    assert "spotify-mcp login" in result.content[0].text
    assert not settings.token_path.exists()


@pytest.mark.anyio
async def test_deprecated_endpoint_403_is_graceful(client, fake):
    fake.add("GET", "/v1/audio-features/t1", {"error": {"status": 403, "message": "Forbidden"}}, status=403)
    result = await client.call_tool("get_audio_features", {"track_id": "t1"})
    assert result.is_error is True
    assert "Development Mode" in result.content[0].text
    assert len(fake.requests) == 1

```

### VERIFIED REFERENCE (research, ran on mcp 2.2.0): MCPServer with annotations, structured output, lifespan httpx client, ToolError, both transports
```
import argparse
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated

import httpx
from pydantic import BaseModel, Field

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

logger = logging.getLogger(__name__)


@dataclass
class AppContext:
    http: httpx.AsyncClient


@asynccontextmanager
async def lifespan(server: MCPServer) -> AsyncIterator[AppContext]:
    async with httpx.AsyncClient(timeout=10) as http:
        yield AppContext(http=http)


mcp = MCPServer("Demo", lifespan=lifespan, log_level="INFO")


class Sum(BaseModel):
    total: int = Field(description="Sum of a and b.")


@mcp.tool(
    title="Add two integers",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False),
)
def add(
    a: Annotated[int, Field(description="First addend.")],
    b: Annotated[int, Field(description="Second addend.")],
) -> Sum:
    """Add two integers and return the total."""
    logger.info("add(%s, %s)", a, b)
    return Sum(total=a + b)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True))
async def fetch_status(url: str, ctx: Context[AppContext]) -> int:
    """Return the HTTP status code for a URL."""
    if not url.startswith("https://"):
        raise ToolError("Only https:// URLs are allowed.")
    resp = await ctx.request_context.lifespan_context.http.get(url)
    return resp.status_code


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--path", default="/mcp")
    parser.add_argument("--stateless", action="store_true")
    args = parser.parse_args()
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
            streamable_http_path=args.path,
            stateless_http=args.stateless,
        )

```

### VERIFIED REFERENCE (research, 3 passed on mcp 2.2.0): in-process pytest client
```
import pytest

from mcp import Client
from server import mcp


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    async with Client(mcp, raise_exceptions=True) as c:
        yield c


@pytest.mark.anyio
async def test_lists_tools(client: Client):
    tools = await client.list_tools()
    assert {t.name for t in tools.tools} == {"add", "fetch_status"}
    add = next(t for t in tools.tools if t.name == "add")
    assert add.annotations.read_only_hint is True
    assert add.output_schema["properties"]["total"]["type"] == "integer"


@pytest.mark.anyio
async def test_calls_add(client: Client):
    result = await client.call_tool("add", {"a": 2, "b": 3})
    assert result.is_error is False
    assert result.structured_content == {"total": 5}


@pytest.mark.anyio
async def test_tool_error_is_not_exception(client: Client):
    result = await client.call_tool("fetch_status", {"url": "http://x"})
    assert result.is_error is True
    assert "Only https://" in result.content[0].text

```

### VERIFIED REFERENCE: Connecting a real Client over HTTP and stdio (for the slow smoke test)
```
import asyncio, sys
from mcp import Client
from mcp.client.stdio import StdioServerParameters

async def main():
    async with Client("http://127.0.0.1:8765/mcp", raise_exceptions=True) as c:
        print([t.name for t in (await c.list_tools()).tools])
        print((await c.call_tool("add", {"a": 40, "b": 2})).structured_content)  # {'total': 42}

    params = StdioServerParameters(command=sys.executable, args=["server.py", "--transport", "stdio"])
    async with Client(params, raise_exceptions=True) as c:
        print((await c.call_tool("add", {"a": 1, "b": 1})).structured_content)  # {'total': 2}

asyncio.run(main())

```

### Spotify HTTP shapes used by this server (classic code flow + Feb-2026 playlist endpoints)
```
# Authorize (classic code flow; no PKCE params)
GET https://accounts.spotify.com/authorize?client_id=<ID>&response_type=code&redirect_uri=http%3A%2F%2F127.0.0.1%3A8888%2Fcallback&scope=playlist-read-private%20playlist-read-collaborative%20playlist-modify-public%20playlist-modify-private%20user-library-read%20user-top-read%20user-read-recently-played%20user-read-private&state=<random>

# Exchange
POST https://accounts.spotify.com/api/token
Authorization: Basic base64(<CLIENT_ID>:<CLIENT_SECRET>)
Content-Type: application/x-www-form-urlencoded
grant_type=authorization_code&code=<CODE>&redirect_uri=http%3A%2F%2F127.0.0.1%3A8888%2Fcallback
200 -> {"access_token":"...","token_type":"Bearer","scope":"...","expires_in":3600,"refresh_token":"..."}

# Refresh (classic): refresh_token is usually NOT returned -> keep the old one
POST https://accounts.spotify.com/api/token
Authorization: Basic base64(<CLIENT_ID>:<CLIENT_SECRET>)
grant_type=refresh_token&refresh_token=<REFRESH>
400 {"error":"invalid_grant"} -> expired (6 months after consent) or revoked: delete token.json, re-run login, never retry

# Playlist items (NEW paths; /playlists/{id}/tracks returns 403 for dev-mode apps)
GET    /v1/playlists/{id}/items?limit=50&offset=0&additional_types=track      -> items[].item (track deprecated alias)
POST   /v1/playlists/{id}/items   {"uris":[...<=100],"position":0}            -> 201 {"snapshot_id"}
DELETE /v1/playlists/{id}/items   {"items":[{"uri":"spotify:track:..."}],"snapshot_id":"?"} -> 200 {"snapshot_id"}
PUT    /v1/playlists/{id}/items   {"range_start":1,"insert_before":3,"range_length":2}      -> 200 {"snapshot_id"}
PUT    /v1/playlists/{id}/items   {"uris":[...<=100]}   (replace; exclusive with reorder)     -> 200 {"snapshot_id"}
POST   /v1/me/playlists           {"name":"...","public":false,"collaborative":false,"description":""} -> 201 playlist

# Search (max 10 since Feb 2026)
GET /v1/search?q=track%3ABlue%20Monday%20artist%3ANew%20Order&type=track,artist&limit=10&offset=0

# 429
Retry-After: 7                                                     -> sleep, retry once
{"error":{"status":429,"message":"Too many requests","reason":"QUOTA_EXCEEDED"}} -> do not retry
```

### REFERENCE ONLY (not used in v1): PKCE exchange, in case the client-secret requirement is dropped later
```
POST https://accounts.spotify.com/api/token
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code&code=<CODE>&redirect_uri=http%3A%2F%2F127.0.0.1%3A8888%2Fcallback&client_id=<CLIENT_ID>&code_verifier=<VERIFIER>

200 -> {"access_token":"...","token_type":"Bearer","scope":"...","expires_in":3600,"refresh_token":"..."}

# refresh (PKCE): no Authorization header, client_id in body; the returned refresh_token rotates -> ALWAYS persist it
POST https://accounts.spotify.com/api/token
grant_type=refresh_token&refresh_token=<REFRESH>&client_id=<CLIENT_ID>

# authorize adds: &code_challenge_method=S256&code_challenge=<base64url(sha256(verifier))>  (verifier 43-128 chars)
```
