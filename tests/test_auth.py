import dataclasses
import threading
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from spotify_mcp import auth
from spotify_mcp.auth import Token, load_token, save_token
from spotify_mcp.settings import SCOPES


def test_authorize_url_has_scopes_state_and_redirect(settings):
    url = auth.authorize_url(settings, "state123")
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert query["state"] == ["state123"]
    assert query["redirect_uri"] == [settings.redirect_uri]
    assert query["client_id"] == [settings.client_id]
    assert set(query["scope"][0].split()) == set(SCOPES)


@pytest.mark.anyio
async def test_exchange_code_uses_basic_auth(settings, fake, mock_http):
    fake.add("POST", "/api/token", {"access_token": "at", "refresh_token": "rt", "expires_in": 3600, "scope": "a b"})
    async with mock_http as http:
        token = await auth.exchange_code(http, settings, "the-code")
    assert token.access_token == "at"
    assert token.refresh_token == "rt"
    request = fake.requests[0]
    assert request.headers["Authorization"].startswith("Basic ")
    assert b"grant_type=authorization_code" in request.content
    assert b"code=the-code" in request.content


@pytest.mark.anyio
async def test_refresh_persists_new_token_and_keeps_old_refresh_token(settings, fake, mock_http):
    old = Token("old-at", "old-rt", time.time() - 10, "", "cid")
    save_token(settings, old)
    fake.add("POST", "/api/token", {"access_token": "new-at", "expires_in": 3600, "scope": "x"})
    async with mock_http as http:
        new = await auth.refresh(http, settings, old)
    assert new.access_token == "new-at"
    assert new.refresh_token == "old-rt"
    saved = load_token(settings)
    assert saved.access_token == "new-at"
    assert saved.refresh_token == "old-rt"


@pytest.mark.anyio
async def test_refresh_persists_rotated_refresh_token_when_present(settings, fake, mock_http):
    old = Token("old-at", "old-rt", time.time() - 10, "", "cid")
    save_token(settings, old)
    fake.add("POST", "/api/token", {"access_token": "new-at", "refresh_token": "new-rt", "expires_in": 3600, "scope": "x"})
    async with mock_http as http:
        new = await auth.refresh(http, settings, old)
    assert new.refresh_token == "new-rt"
    assert load_token(settings).refresh_token == "new-rt"


@pytest.mark.anyio
async def test_refresh_invalid_grant_clears_token_and_raises(settings, fake, mock_http):
    old = Token("old-at", "old-rt", time.time() - 10, "", "cid")
    save_token(settings, old)
    fake.add("POST", "/api/token", {"error": "invalid_grant"}, status=400)
    async with mock_http as http:
        with pytest.raises(auth.AuthError, match="spotify-mcp login"):
            await auth.refresh(http, settings, old)
    assert not settings.token_path.exists()


@pytest.mark.anyio
async def test_refresh_non_json_400_raises_auth_error_with_status(settings):
    old = Token("old-at", "old-rt", time.time() - 10, "", "cid")
    save_token(settings, old)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, content=b"<html>bad gateway</html>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(auth.AuthError, match="400"):
            await auth.refresh(http, settings, old)


def test_save_token_sets_file_and_dir_permissions(settings):
    save_token(settings, Token("at", "rt", time.time() + 3600, "scope", "cid"))
    assert oct(settings.token_path.stat().st_mode & 0o777) == "0o600"
    assert oct(settings.config_dir.stat().st_mode & 0o777) == "0o700"


def test_save_token_leaves_no_temp_files_behind(settings):
    save_token(settings, Token("at1", "rt1", time.time() + 3600, "s", "cid"))
    save_token(settings, Token("at2", "rt2", time.time() + 3600, "s", "cid"))
    assert list(settings.config_dir.glob("token.*.tmp")) == []
    assert load_token(settings).access_token == "at2"


def test_save_token_failure_does_not_corrupt_existing_token(settings, monkeypatch):
    save_token(settings, Token("at1", "rt1", time.time() + 3600, "s", "cid"))

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(auth.os, "fsync", boom)
    with pytest.raises(OSError):
        save_token(settings, Token("at2", "rt2", time.time() + 3600, "s", "cid"))

    assert load_token(settings).access_token == "at1"
    assert list(settings.config_dir.glob("token.*.tmp")) == []


def test_wait_for_code_returns_code_on_matching_state(settings):
    def do_request():
        time.sleep(0.05)
        httpx.get(f"http://{settings.callback[0]}:{settings.callback[1]}{settings.callback[2]}?code=abc123&state=good")

    thread = threading.Thread(target=do_request)
    thread.start()
    code = auth.wait_for_code(settings, "good", timeout=5)
    thread.join()
    assert code == "abc123"


def test_wait_for_code_survives_stray_request_before_real_callback(settings):
    def do_requests():
        time.sleep(0.05)
        httpx.get(f"http://{settings.callback[0]}:{settings.callback[1]}/favicon.ico")
        time.sleep(0.05)
        httpx.get(f"http://{settings.callback[0]}:{settings.callback[1]}{settings.callback[2]}?code=abc123&state=good")

    thread = threading.Thread(target=do_requests)
    thread.start()
    code = auth.wait_for_code(settings, "good", timeout=5)
    thread.join()
    assert code == "abc123"


def test_wait_for_code_raises_on_state_mismatch(settings):
    def do_request():
        time.sleep(0.05)
        httpx.get(f"http://{settings.callback[0]}:{settings.callback[1]}{settings.callback[2]}?code=abc123&state=bad")

    thread = threading.Thread(target=do_request)
    thread.start()
    with pytest.raises(auth.AuthError, match="CSRF"):
        auth.wait_for_code(settings, "good", timeout=5)
    thread.join()


def test_wait_for_code_spotify_error_redirect_returns_failure_page_and_raises(settings):
    responses: list[httpx.Response] = []

    def do_request():
        time.sleep(0.05)
        responses.append(
            httpx.get(f"http://{settings.callback[0]}:{settings.callback[1]}{settings.callback[2]}?error=access_denied&state=good")
        )

    thread = threading.Thread(target=do_request)
    thread.start()
    with pytest.raises(auth.AuthError, match="access_denied"):
        auth.wait_for_code(settings, "good", timeout=5)
    thread.join()
    assert responses[0].status_code == 400
    assert "Login failed" in responses[0].text


def test_wait_for_code_rejects_non_loopback_redirect_host(settings):
    bad_settings = dataclasses.replace(settings, redirect_uri="http://0.0.0.0:8888/callback")
    with pytest.raises(auth.AuthError, match="loopback"):
        auth.wait_for_code(bad_settings, "state", timeout=1)
