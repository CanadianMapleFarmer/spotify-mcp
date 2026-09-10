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
    return Token(**json.loads(settings.token_path.read_text()))


def save_token(settings: Settings, token: Token) -> None:
    settings.config_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(settings.config_dir, 0o700)
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


def wait_for_code(settings: Settings, state: str, timeout: float = CALLBACK_TIMEOUT_S) -> str:
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
                result["error"] = "state_mismatch"
                self.send_response(400)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(FAILURE_HTML.format(message="State mismatch; login was not completed.").encode())
                return
            result.update(query)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(SUCCESS_HTML.encode())

        def log_message(self, *args) -> None:
            pass

    with HTTPServer((host, port), Handler) as server:
        server.timeout = timeout
        server.handle_request()
    if result.get("error"):
        raise AuthError(f"Spotify returned error: {result['error']}")
    if "code" not in result:
        raise AuthError("Timed out waiting for the Spotify redirect.")
    return result["code"]
