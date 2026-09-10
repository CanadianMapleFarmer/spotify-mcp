import base64
import ipaddress
import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .settings import DEFAULT_REDIRECT_URI, SCOPES, Settings

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
EXPIRY_MARGIN_S = 60
CALLBACK_TIMEOUT_S = 300

SUCCESS_HTML = "<html><body><h1>Logged in</h1><p>spotify-mcp: login complete, you can close this tab.</p></body></html>"
FAILURE_HTML = "<html><body><h1>Login failed</h1><p>{message}</p></body></html>"


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
    try:
        return Token(**json.loads(settings.token_path.read_text()))
    except (ValueError, TypeError, OSError) as e:
        raise AuthError(f"Corrupt token cache at {settings.token_path} ({e}). Run `spotify-mcp login` again.") from e


def save_token(settings: Settings, token: Token) -> None:
    settings.config_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(settings.config_dir, 0o700)
    fd, tmp_name = tempfile.mkstemp(dir=settings.config_dir, prefix="token.", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps(asdict(token), indent=2))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, settings.token_path)
    except BaseException:
        os.unlink(tmp_name)
        raise


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


def _error_field(r: httpx.Response) -> str | None:
    try:
        parsed = r.json()
    except ValueError:
        return None
    return parsed.get("error") if isinstance(parsed, dict) else None


async def refresh(http: httpx.AsyncClient, settings: Settings, token: Token) -> Token:
    data = {"grant_type": "refresh_token", "refresh_token": token.refresh_token}
    r = await http.post(TOKEN_URL, headers=_basic_auth(settings), data=data)
    if r.status_code == 400 and _error_field(r) == "invalid_grant":
        clear_token(settings)
        raise AuthError("Refresh token expired or revoked. Run `spotify-mcp login` again.")
    if r.status_code != 200:
        raise AuthError(f"Token refresh failed: {r.status_code} {r.text}")
    new = _token_from(settings, r.json(), previous_refresh=token.refresh_token)
    save_token(settings, new)
    return new


def _is_loopback_host(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def wait_for_code(settings: Settings, state: str, timeout: float = CALLBACK_TIMEOUT_S) -> str:
    host, port, path = settings.callback
    if not _is_loopback_host(host):
        raise AuthError(
            f"SPOTIFY_REDIRECT_URI must use a loopback host; register {DEFAULT_REDIRECT_URI} in the Spotify dashboard."
        )
    result: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            url = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path != path:
                self.send_error(404)
                return
            if query.get("state") != state:
                result["state_mismatch"] = "1"
                self._respond(400, "State mismatch; login was not completed.")
                return
            if "error" in query:
                result["error"] = query["error"]
                self._respond(400, query["error"])
                return
            result.update(query)
            self._respond(200, None)

        def _respond(self, status: int, failure_message: str | None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            body = SUCCESS_HTML if failure_message is None else FAILURE_HTML.format(message=failure_message)
            self.wfile.write(body.encode())

        def log_message(self, *args) -> None:
            pass

    with HTTPServer((host, port), Handler) as server:
        deadline = time.monotonic() + timeout
        while not result and time.monotonic() < deadline:
            server.timeout = max(deadline - time.monotonic(), 0)
            server.handle_request()
    if result.get("state_mismatch"):
        raise AuthError("Callback state did not match; login aborted (possible CSRF or a stale browser tab).")
    if result.get("error"):
        raise AuthError(f"Spotify returned error: {result['error']}")
    if "code" not in result:
        raise AuthError("Timed out waiting for the Spotify redirect.")
    return result["code"]
