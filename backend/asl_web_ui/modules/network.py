"""Network interfaces and the ASL3 appliance's fallback access point.

    GET /api/v1/network                          active interfaces, fallback AP state
    PUT /api/v1/network/fallback-ap  {"enable"}  enable or disable fallback-ap.timer

Both run in the privileged helper (asl_web_ui_priv.network has the details):
listing addresses needs AF_NETLINK, which this service's sandbox does not
allow. Network settings themselves are left to Cockpit; the page links there.
"""

import logging

from aiohttp import web

from ..privileged import PRIV_KEY, PrivError
from ..security import SETTINGS_KEY, USER_KEY
from .changes import STORE_KEY, error, read_json

log = logging.getLogger("asl-web-ui.network")
routes = web.RouteTableDef()


def _priv_error(exc: PrivError) -> web.Response:
    status = {"not_found": 404, "invalid": 400, "denied": 403, "unavailable": 503}.get(exc.code, 500)
    return error(status, exc.code, exc.message)


@routes.get("/api/v1/network")
async def status(request: web.Request) -> web.Response:
    try:
        return web.json_response(await request.app[PRIV_KEY].call("network.status", {}, request[USER_KEY], timeout=60))
    except PrivError as exc:
        return _priv_error(exc)


@routes.put("/api/v1/network/fallback-ap")
async def fallback_ap(request: web.Request) -> web.Response:
    body = await read_json(request)
    enable = body.get("enable")
    if not isinstance(enable, bool):
        return error(400, "invalid", "enable must be true or false.")
    if request.app[SETTINGS_KEY].dev:
        return error(501, "dev_mode", "Development mode never changes the host's services.")
    action = f"{'Enable' if enable else 'Disable'} the fallback AP"
    try:
        res = await request.app[PRIV_KEY].call("network.fallback_ap", {"enable": enable}, request[USER_KEY],
                                               timeout=120)
    except PrivError as exc:
        request.app[STORE_KEY].record(request[USER_KEY], action, "failed", [exc.message[-200:]])
        return _priv_error(exc)
    request.app[STORE_KEY].record(request[USER_KEY], action, "done", [])
    log.info("%s: %s", request[USER_KEY], action)
    return web.json_response(res)


def setup(app: web.Application) -> None:
    app.add_routes(routes)
