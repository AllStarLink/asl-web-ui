"""Request checks applied to every API call.

- HTTPS: the web server reports the browser's scheme in X-Forwarded-Proto.
  Plain HTTP is refused unless allow_insecure_http is set.
- Origin: state-changing requests and WebSocket upgrades must come from a
  page served by this host (blocks CSRF and cross-site WebSocket hijacking).
- Authentication: everything except public routes needs a logged-in user
  who is still a member of the login group.
- CSRF token: state-changing requests also carry X-CSRF-Token matching the
  session.
"""

import grp
import os
import pwd
import time
from urllib.parse import urlsplit

from aiohttp import web
from aiohttp_session import get_session

from .config import Settings

SETTINGS_KEY = web.AppKey("settings", Settings)
PUBLIC = {"/api/v1/health", "/api/v1/auth/login", "/api/v1/auth/session"}
PUBLIC_PREFIXES = ("/api/v1/auth/login/",)
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_HEADER = "X-CSRF-Token"
USER_KEY = "asl_web_ui.user"  # request key (aiohttp 3.11 has no web.RequestKey)

_GROUP_CACHE_SECONDS = 10
_group_cache: dict[tuple[str, str], tuple[bool, float]] = {}


def _last(header: str | None) -> str | None:
    if not header:
        return None
    value = header.split(",")[-1].strip()
    return value or None


def client_ip(request: web.Request) -> str:
    """The browser's address. Apache appends to any X-Forwarded-For the client
    sent and nginx replaces it, so only the last entry is trustworthy."""
    return _last(request.headers.get("X-Forwarded-For")) or request.remote or "local"


def is_https(request: web.Request) -> bool:
    return (_last(request.headers.get("X-Forwarded-Proto")) or "").lower() == "https"


def public_host(request: web.Request) -> str:
    return _last(request.headers.get("X-Forwarded-Host")) or request.host


def is_group_member(user: str, group: str) -> bool:
    now = time.monotonic()
    cached = _group_cache.get((user, group))
    if cached and now - cached[1] < _GROUP_CACHE_SECONDS:
        return cached[0]
    try:
        gid = grp.getgrnam(group).gr_gid
        member = gid in os.getgrouplist(user, pwd.getpwnam(user).pw_gid)
    except KeyError:
        member = False
    _group_cache[(user, group)] = (member, now)
    return member


def _error(status: int, code: str, message: str) -> web.Response:
    return web.json_response({"error": code, "message": message}, status=status)


def _is_public(path: str) -> bool:
    return path in PUBLIC or path.startswith(PUBLIC_PREFIXES)


def _origin_ok(request: web.Request) -> bool:
    origin = request.headers.get("Origin")
    if not origin:
        return False
    return urlsplit(origin).netloc.lower() == public_host(request).lower()


@web.middleware
async def security_middleware(request: web.Request, handler):
    settings = request.app[SETTINGS_KEY]
    path = request.path
    if not path.startswith("/api/") or path == "/api/v1/health":
        return await handler(request)

    if not settings.dev and not settings.allow_insecure_http and not is_https(request):
        return _error(403, "https_required", "Log in over HTTPS. Plain HTTP is not allowed on this server.")

    is_websocket = request.headers.get("Upgrade", "").lower() == "websocket"
    if (request.method in UNSAFE_METHODS or is_websocket) and not _origin_ok(request):
        return _error(403, "bad_origin", "The request did not come from this site.")

    if _is_public(path):
        return await handler(request)

    session = await get_session(request)
    user = session.get("user")
    if not user:
        return _error(401, "not_logged_in", "Log in to continue.")
    # --dev logs in a fake user that is not a real account; skip the group check.
    if not settings.dev and not is_group_member(user, settings.login_group):
        session.invalidate()
        return _error(401, "not_permitted", "Your account is no longer allowed to use the web interface.")
    if request.method in UNSAFE_METHODS and request.headers.get(CSRF_HEADER) != session.get("csrf"):
        return _error(403, "bad_csrf", "Your session token is missing or out of date. Reload the page.")
    request[USER_KEY] = user
    return await handler(request)
