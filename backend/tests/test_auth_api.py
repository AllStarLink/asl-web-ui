"""Login, sessions and the security middleware, with the fake auth helper."""

import socket

import pytest
from aiohttp import DummyCookieJar

from asl_web_ui import config, security
from asl_web_ui.app import create_app
from asl_web_ui.auth.fake import DEV_CODE, DEV_PASSWORD, DEV_USER, FakeTransport


@pytest.fixture(autouse=True)
def everyone_is_a_member(monkeypatch):
    monkeypatch.setattr(security, "is_group_member", lambda user, group: True)


def make_app(with_code=False, **settings):
    async def connect():
        return FakeTransport(with_code=with_code)

    return create_app(config.Settings(**settings), auth_connect=connect)


class Browser:
    """A test client that sends the headers a real page behind HTTPS would.

    The session cookie is Secure, which aiohttp's cookie jar will not send
    over the test server's plain HTTP, so it is carried by hand here.
    """

    def __init__(self, client):
        self.client = client
        self.csrf = None
        self.cookie = None

    def _remember(self, resp):
        morsel = resp.cookies.get("asl_web_ui_session")
        if morsel is not None:
            self.cookie = morsel.value or None

    def headers(self, extra=None):
        host = f"{self.client.server.host}:{self.client.server.port}"
        h = {"X-Forwarded-Proto": "https", "Origin": f"https://{host}"}
        if self.csrf:
            h["X-CSRF-Token"] = self.csrf
        if self.cookie:
            h["Cookie"] = f"asl_web_ui_session={self.cookie}"
        h.update(extra or {})
        return h

    async def post(self, path, json=None, **kw):
        resp = await self.client.post(path, json=json if json is not None else {}, headers=self.headers(kw.pop("headers", None)))
        self._remember(resp)
        return resp, await resp.json()

    async def get(self, path, **kw):
        resp = await self.client.get(path, headers=self.headers(kw.pop("headers", None)))
        self._remember(resp)
        return resp, await resp.json()

    async def login(self, user=DEV_USER, password=DEV_PASSWORD, keep=False):
        _, step = await self.post("/api/v1/auth/login", {"user": user, "keep": keep})
        assert step["state"] == "prompt"
        resp, step = await self.post(f"/api/v1/auth/login/{step['id']}", {"answer": password})
        if step["state"] == "success":
            self.csrf = step["session"]["csrf"]
        return resp, step


@pytest.fixture
async def browser(aiohttp_client):
    return Browser(await aiohttp_client(make_app(), cookie_jar=DummyCookieJar()))


async def test_login_success_creates_session(browser):
    resp, step = await browser.login()
    assert step["state"] == "success"
    assert step["session"]["user"] == DEV_USER
    cookie = resp.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie and "Secure" in cookie
    assert "Max-Age" not in cookie  # not "keep me signed in": a browser-session cookie
    _, session = await browser.get("/api/v1/auth/session")
    assert session["user"] == DEV_USER


async def test_keep_me_signed_in_sets_persistent_cookie(browser):
    resp, _ = await browser.login(keep=True)
    assert f"Max-Age={30 * 86400}" in resp.headers["Set-Cookie"]


async def test_wrong_password_fails_generically(browser):
    _, step = await browser.login(password="nope")
    assert step == {"state": "failure", "messages": [], "message": "Login failed. Check your user name and password."}


async def test_multi_prompt_login(aiohttp_client):
    b = Browser(await aiohttp_client(make_app(with_code=True), cookie_jar=DummyCookieJar()))
    _, step = await b.post("/api/v1/auth/login", {"user": DEV_USER})
    _, step = await b.post(f"/api/v1/auth/login/{step['id']}", {"answer": DEV_PASSWORD})
    assert step["state"] == "prompt" and step["prompt"] == {"echo": True, "text": "Verification code: "}
    _, step = await b.post(f"/api/v1/auth/login/{step['id']}", {"answer": DEV_CODE})
    assert step["state"] == "success"


async def test_protected_route_requires_login(browser):
    resp, body = await browser.post("/api/v1/auth/logout")
    assert resp.status == 401 and body["error"] == "not_logged_in"


async def test_logout_ends_session(browser):
    await browser.login()
    resp, _ = await browser.post("/api/v1/auth/logout")
    assert resp.status == 200
    _, session = await browser.get("/api/v1/auth/session")
    assert session == {"user": None, "hostname": socket.gethostname()}


async def test_csrf_token_required(browser):
    await browser.login()
    browser.csrf = "wrong"
    resp, body = await browser.post("/api/v1/auth/logout")
    assert resp.status == 403 and body["error"] == "bad_csrf"


async def test_cross_origin_post_refused(browser):
    resp, body = await browser.post("/api/v1/auth/login", {"user": "x"}, headers={"Origin": "https://evil.example"})
    assert resp.status == 403 and body["error"] == "bad_origin"


async def test_plain_http_refused(browser):
    resp, body = await browser.get("/api/v1/auth/session", headers={"X-Forwarded-Proto": "http"})
    assert resp.status == 403 and body["error"] == "https_required"


async def test_plain_http_allowed_when_configured(aiohttp_client):
    b = Browser(await aiohttp_client(make_app(allow_insecure_http=True), cookie_jar=DummyCookieJar()))
    resp, _ = await b.get("/api/v1/auth/session", headers={"X-Forwarded-Proto": "http"})
    assert resp.status == 200


async def test_health_needs_nothing(aiohttp_client):
    client = await aiohttp_client(make_app())
    resp = await client.get("/api/v1/health")
    assert resp.status == 200


async def test_failed_logins_are_throttled(browser):
    for _ in range(3):  # FREE_FAILURES
        await browser.login(password="nope")
    resp, body = await browser.post("/api/v1/auth/login", {"user": DEV_USER})
    assert resp.status == 429 and body["retry_after"] >= 1


async def test_removed_from_group_ends_access(browser, monkeypatch):
    await browser.login()
    monkeypatch.setattr(security, "is_group_member", lambda user, group: False)
    resp, body = await browser.post("/api/v1/auth/logout")
    assert resp.status == 401 and body["error"] == "not_permitted"


async def test_reauth_refreshes_recent_auth(browser):
    await browser.login()
    _, step = await browser.post("/api/v1/auth/reauth")
    assert step["state"] == "prompt"
    _, step = await browser.post(f"/api/v1/auth/reauth/{step['id']}", {"answer": DEV_PASSWORD})
    assert step["state"] == "success" and step["recent_auth_until"] > 0


async def test_session_id_changes_at_login(browser):
    first, _ = await browser.login()
    await browser.post("/api/v1/auth/logout")
    second, _ = await browser.login()
    assert first.cookies["asl_web_ui_session"].value != second.cookies["asl_web_ui_session"].value


def test_client_ip_uses_last_forwarded_entry():
    from aiohttp.test_utils import make_mocked_request

    req = make_mocked_request("GET", "/", headers={"X-Forwarded-For": "6.6.6.6, 203.0.113.9"})
    assert security.client_ip(req) == "203.0.113.9"
