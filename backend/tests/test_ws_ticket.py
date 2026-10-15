"""WebSockets without cookies: one-time tickets (for Safari)."""

import aiohttp
import pytest

from asl_web_ui.auth import sessions
from test_backups_api import cloud, env  # noqa: F401 (fixtures)


async def ws(a, ticket=None, cookie=None):
    """Open /api/v1/ws/events the way a browser that sends no cookie would."""
    client = a.client_
    headers = {"X-Forwarded-Proto": "https", "Origin": f"https://{client.server.host}:{client.server.port}"}
    if cookie:
        headers["Cookie"] = cookie
    url = "/api/v1/ws/events" + (f"?ticket={ticket}" if ticket else "")
    try:
        sock = await client.ws_connect(url, headers=headers)
    except aiohttp.WSServerHandshakeError as exc:
        return exc.status
    msg = await sock.receive_json()
    await sock.close()
    return msg["type"]


async def test_websocket_with_ticket_and_no_cookie(env):
    a = await env.make()
    assert await ws(a) == 401  # no cookie, no ticket
    status_, body = await a.call("POST", "auth/ws-ticket", {})
    assert status_ == 200
    assert await ws(a, body["ticket"]) == "status"
    assert await ws(a, body["ticket"]) == 401  # used up


async def test_ticket_only_for_websockets_and_briefly(env, monkeypatch):
    a = await env.make()
    _, body = await a.call("POST", "auth/ws-ticket", {})
    client = a.client_
    plain = await client.get(f"/api/v1/status?ticket={body['ticket']}", headers={"X-Forwarded-Proto": "https"})
    assert plain.status == 401  # an ordinary request never accepts a ticket
    monkeypatch.setattr(sessions, "TICKET_LIFETIME", -1)
    _, expired = await a.call("POST", "auth/ws-ticket", {})
    assert await ws(a, expired["ticket"]) == 401


async def test_ticket_needs_a_session(env):
    a = await env.make()
    client = a.client_
    r = await client.post("/api/v1/auth/ws-ticket", json={},
                          headers={"X-Forwarded-Proto": "https",
                                   "Origin": f"https://{client.server.host}:{client.server.port}"})
    assert r.status in (401, 403)
