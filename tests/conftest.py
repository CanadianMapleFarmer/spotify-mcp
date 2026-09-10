import json
import time

import httpx
import pytest

from spotify_mcp.auth import Token, save_token
from spotify_mcp.settings import Settings
from spotify_mcp.spotify import SpotifyClient


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(client_id="cid", client_secret="csecret", config_dir=tmp_path / "config")


@pytest.fixture
def logged_in(settings) -> Settings:
    save_token(settings, Token("at", "rt", time.time() + 3600, "user-read-private", "cid"))
    return settings


class FakeSpotify:
    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], list[tuple[int, dict, dict]]] = {}
        self.requests: list[httpx.Request] = []

    def add(self, method: str, path: str, body: dict, status: int = 200, headers: dict | None = None) -> None:
        self.routes.setdefault((method, path), []).append((status, body, headers or {}))

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = (request.method, request.url.path)
        queue = self.routes.get(key)
        if not queue:
            return httpx.Response(404, json={"error": {"status": 404, "message": f"unmocked {key}"}})
        status, body, headers = queue.pop(0) if len(queue) > 1 else queue[0]
        return httpx.Response(status, json=body, headers=headers)

    def body(self, index: int = -1) -> dict:
        return json.loads(self.requests[index].content)


@pytest.fixture
def fake() -> FakeSpotify:
    return FakeSpotify()


@pytest.fixture
def mock_http(fake):
    return httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))


@pytest.fixture
def spotify_client(logged_in, mock_http) -> SpotifyClient:
    return SpotifyClient(logged_in, mock_http)
