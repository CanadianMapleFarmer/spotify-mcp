#!/usr/bin/env bash
set -euo pipefail

PORT="${1:-8000}"
LOG_FILE="$(mktemp)"

echo "Starting cloudflared quick tunnel to http://127.0.0.1:${PORT} ..." >&2
cloudflared tunnel --url "http://127.0.0.1:${PORT}" >"$LOG_FILE" 2>&1 &
TUNNEL_PID=$!
trap 'kill "$TUNNEL_PID" 2>/dev/null || true' EXIT

HOSTNAME=""
for _ in $(seq 1 30); do
  HOSTNAME="$(grep -oE '[A-Za-z0-9-]+\.trycloudflare\.com' "$LOG_FILE" | head -n1 || true)"
  [ -n "$HOSTNAME" ] && break
  sleep 1
done

if [ -z "$HOSTNAME" ]; then
  echo "Timed out waiting for a trycloudflare.com hostname; check $LOG_FILE" >&2
  exit 1
fi

echo "" >&2
echo "Tunnel is up: https://${HOSTNAME}" >&2
echo "" >&2
echo "Run this in a second terminal (in the repo, with env exported):" >&2
echo "" >&2
echo "  uv run spotify-mcp serve --transport streamable-http --port ${PORT} --allow-host ${HOSTNAME}" >&2
echo "" >&2
echo "Then set the ChatGPT connector URL to: https://${HOSTNAME}/mcp" >&2
echo "" >&2
echo "Press Ctrl+C to stop the tunnel." >&2

wait "$TUNNEL_PID"
