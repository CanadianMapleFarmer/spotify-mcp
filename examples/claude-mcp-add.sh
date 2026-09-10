#!/usr/bin/env bash
set -euo pipefail

claude mcp add --scope user --transport stdio spotify-mcp \
  -e SPOTIFY_CLIENT_ID="$SPOTIFY_CLIENT_ID" \
  -e SPOTIFY_CLIENT_SECRET="$SPOTIFY_CLIENT_SECRET" \
  -e SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback \
  -e UV_NO_SYNC=1 \
  -- uv run --directory /path/to/spotify-mcp spotify-mcp serve

claude mcp get spotify-mcp
