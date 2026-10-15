"""Login, logout and password re-entry.

    POST /api/v1/auth/login            {"user", "keep"}  -> step
    POST /api/v1/auth/login/{id}       {"answer"}        -> step
    GET  /api/v1/auth/session                            -> current session
    POST /api/v1/auth/logout
    POST /api/v1/auth/reauth                             -> step (session user)
    POST /api/v1/auth/reauth/{id}      {"answer"}        -> step

A step is {"state": "prompt", "id", "prompt": {"echo", "text"}, "messages"},
{"state": "success", ...} or {"state": "failure", "message", "messages"}.
"""

import logging
import secrets
import time

from aiohttp import web
from aiohttp_session import get_session, new_session

from ..auth.conversation import Conversations, Step
from ..auth.ratelimit import LoginThrottle
from ..auth.sessions import MemoryStorage
from ..security import SETTINGS_KEY, USER_KEY, client_ip

log = logging.getLogger("asl-web-ui.auth")

CONVERSATIONS_KEY = web.AppKey("conversations", Conversations)
REAUTH_KEY = web.AppKey("reauth_conversations", Conversations)
THROTTLE_KEY = web.AppKey("throttle", LoginThrottle)
STORAGE_KEY = web.AppKey("session_storage", MemoryStorage)

FAILURE_MESSAGES = {
    "denied": "Login failed. Check your user name and password.",
    "not_permitted": "Your account is not allowed to use the web interface. "
    "Ask an administrator to add it to the asl-web-ui group.",
    "expired": "Your password has expired. Log in over SSH to change it, then try again.",
}
DEFAULT_FAILURE = "Login failed."

routes = web.RouteTableDef()


def _step_json(step: Step, conv_id: str | None) -> dict:
    body: dict = {"state": step.state, "messages": step.messages}
    if step.state == "prompt":
        body.update(id=conv_id, prompt=step.prompt)
    elif step.state == "failure":
        body["message"] = FAILURE_MESSAGES.get(step.reason or "", DEFAULT_FAILURE)
    return body


async def _json(request: web.Request) -> dict:
    if request.content_type != "application/json":
        raise web.HTTPUnsupportedMediaType(text="Expected JSON")
    try:
        body = await request.json()
    except ValueError:
        raise web.HTTPBadRequest(text="Invalid JSON")
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="Expected a JSON object")
    return body


def _unavailable() -> web.Response:
    return web.json_response(
        {"error": "auth_unavailable", "message": "The login service is not available. "
         "Check it with: systemctl status asl-web-ui-auth.socket"},
        status=503,
    )


def _session_json(request: web.Request, session) -> dict:
    return {
        "user": session.get("user"),
        "csrf": session.get("csrf"),
        "keep": bool(session.get("keep")),
        "recent_auth_until": session.get("last_auth", 0) + request.app[SETTINGS_KEY].recent_auth,
    }


async def _start_session(request: web.Request, user: str, keep: bool) -> dict:
    storage = request.app[STORAGE_KEY]
    old = await get_session(request)
    storage.forget(old.identity)  # never reuse a pre-login session ID
    session = await new_session(request)
    now = int(time.time())
    session["user"] = user
    session["keep"] = keep
    session["csrf"] = secrets.token_urlsafe(32)
    session["last_auth"] = now
    return _session_json(request, session)


@routes.post("/api/v1/auth/login")
async def login(request: web.Request) -> web.Response:
    body = await _json(request)
    user = body.get("user")
    keep = bool(body.get("keep"))
    if not isinstance(user, str) or not user.strip():
        return web.json_response({"state": "failure", "message": "Enter your user name.", "messages": []})
    user = user.strip()
    ip = client_ip(request)
    throttle = request.app[THROTTLE_KEY]
    wait = throttle.retry_after(ip, user)
    if wait > 0:
        return web.json_response(
            {"state": "failure", "message": f"Too many failed logins. Try again in {int(wait) + 1} seconds.",
             "messages": [], "retry_after": int(wait) + 1},
            status=429,
        )
    try:
        conv, step = await request.app[CONVERSATIONS_KEY].begin(user, ip)
    except (OSError, ConnectionError, TimeoutError, ValueError):
        log.exception("cannot reach the auth helper")
        return _unavailable()
    conv.keep = keep
    return await _finish(request, step, conv.id, user, keep)


@routes.post("/api/v1/auth/login/{conv_id}")
async def login_answer(request: web.Request) -> web.Response:
    body = await _json(request)
    answer = body.get("answer")
    if not isinstance(answer, str):
        raise web.HTTPBadRequest(text="answer must be a string")
    convs = request.app[CONVERSATIONS_KEY]
    conv_id = request.match_info["conv_id"]
    conv = convs.get(conv_id)  # remember user and keep before it closes
    try:
        step = await convs.answer(conv_id, client_ip(request), answer)
    except (OSError, ConnectionError, TimeoutError, ValueError):
        log.exception("auth helper failed during login")
        return _unavailable()
    if step is None or conv is None:
        return web.json_response({"state": "failure", "message": "The login timed out. Start again.", "messages": []})
    return await _finish(request, step, conv_id, conv.user, conv.keep)


async def _finish(request: web.Request, step: Step, conv_id: str, user: str, keep: bool) -> web.Response:
    ip = client_ip(request)
    throttle = request.app[THROTTLE_KEY]
    body = _step_json(step, conv_id)
    if step.state == "success":
        throttle.succeeded(ip, user)
        body["session"] = await _start_session(request, user, keep)
        log.info("login: user=%s from %s", user, ip)
    elif step.state == "failure":
        throttle.failed(ip, user)
        log.warning("login failed: user=%s from %s reason=%s", user, ip, step.reason)
    return web.json_response(body)


@routes.get("/api/v1/auth/session")
async def session_info(request: web.Request) -> web.Response:
    session = await get_session(request)
    if not session.get("user"):
        return web.json_response({"user": None})
    return web.json_response(_session_json(request, session))


@routes.post("/api/v1/auth/logout")
async def logout(request: web.Request) -> web.Response:
    session = await get_session(request)
    log.info("logout: user=%s", session.get("user"))
    session.invalidate()
    return web.json_response({"user": None})


@routes.post("/api/v1/auth/reauth")
async def reauth(request: web.Request) -> web.Response:
    user = request[USER_KEY]
    try:
        conv, step = await request.app[REAUTH_KEY].begin(user, client_ip(request))
    except (OSError, ConnectionError, TimeoutError, ValueError):
        log.exception("cannot reach the auth helper")
        return _unavailable()
    return await _finish_reauth(request, step, conv.id)


@routes.post("/api/v1/auth/reauth/{conv_id}")
async def reauth_answer(request: web.Request) -> web.Response:
    body = await _json(request)
    answer = body.get("answer")
    if not isinstance(answer, str):
        raise web.HTTPBadRequest(text="answer must be a string")
    conv_id = request.match_info["conv_id"]
    convs = request.app[REAUTH_KEY]
    conv = convs.get(conv_id)
    if conv is None or conv.user != request[USER_KEY]:
        return web.json_response({"state": "failure", "message": "The request timed out. Start again.", "messages": []})
    try:
        step = await convs.answer(conv_id, client_ip(request), answer)
    except (OSError, ConnectionError, TimeoutError, ValueError):
        log.exception("auth helper failed during reauth")
        return _unavailable()
    if step is None:
        return web.json_response({"state": "failure", "message": "The request timed out. Start again.", "messages": []})
    return await _finish_reauth(request, step, conv_id)


async def _finish_reauth(request: web.Request, step: Step, conv_id: str) -> web.Response:
    body = _step_json(step, conv_id)
    if step.state == "success":
        session = await get_session(request)
        session["last_auth"] = int(time.time())
        body["recent_auth_until"] = session["last_auth"] + request.app[SETTINGS_KEY].recent_auth
    elif step.state == "failure":
        request.app[THROTTLE_KEY].failed(client_ip(request), request[USER_KEY])
    return web.json_response(body)


@routes.post("/api/v1/auth/ws-ticket")
async def ws_ticket(request: web.Request) -> web.Response:
    """A one-time ticket for opening a WebSocket (see auth/sessions.py)."""
    session = await get_session(request)
    if not session.identity:
        return web.json_response({"error": "not_logged_in", "message": "Log in to continue."}, status=401)
    return web.json_response({"ticket": request.app[STORAGE_KEY].issue_ticket(session.identity)})


def recently_authenticated(session, settings) -> bool:
    """For destructive actions: was the password entered recently?"""
    return time.time() - session.get("last_auth", 0) < settings.recent_auth


def setup(app: web.Application) -> None:
    app.add_routes(routes)
