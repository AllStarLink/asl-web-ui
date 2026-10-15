"""SA818 RF modules: sa818-menu's settings and programming.

    GET  /api/v1/sa818                  saved settings, serial ports, choices
    PUT  /api/v1/sa818    {"settings"}  save to /etc/sa818.conf and program the module
    POST /api/v1/sa818/program          program the module again with the saved settings
    POST /api/v1/sa818/version          ask the module for its firmware version

The settings file and the serial port need root, so everything goes
through the privileged helper (asl_web_ui_priv.sa818 has the details).
"""

import logging

from aiohttp import web

from asl_web_ui_priv import sa818

from ..privileged import PRIV_KEY, PrivError
from ..security import USER_KEY
from .changes import STORE_KEY, error, read_json

log = logging.getLogger("asl-web-ui.sa818")
routes = web.RouteTableDef()

CHOICES = {
    "ctcss": sa818.CTCSS,
    "dcs": sa818.DCS_CODES,
    "speeds": sa818.SPEEDS,
    "bands": {band: list(limits) for band, limits in sa818.BAND_LIMITS.items()},
}


def _priv_error(exc: PrivError) -> web.Response:
    if exc.code == "invalid" and exc.message.startswith("CURRENT_"):
        field, _, text = exc.message.partition(": ")
        return error(400, "invalid", text, field=field)
    status = {"not_found": 404, "invalid": 400, "denied": 403, "unavailable": 503}.get(exc.code, 500)
    return error(status, exc.code, exc.message)


async def _priv(request: web.Request, command: str, args: dict | None = None) -> dict:
    return await request.app[PRIV_KEY].call(command, args or {}, request[USER_KEY], timeout=180)


def _audit(request: web.Request, action: str, res: dict) -> None:
    result = "applied" if res["programmed"] else "failed"
    request.app[STORE_KEY].record(request[USER_KEY], action, result, res["log"][-3:], files=[sa818.CONF])
    log.info("%s: %s (%s)", request[USER_KEY], action, result)


@routes.get("/api/v1/sa818")
async def read(request: web.Request) -> web.Response:
    try:
        res = await _priv(request, "sa818.read")
    except PrivError as exc:
        return _priv_error(exc)
    return web.json_response({**res, "choices": CHOICES})


@routes.put("/api/v1/sa818")
async def apply(request: web.Request) -> web.Response:
    body = await read_json(request)
    if not isinstance(body.get("settings"), dict):
        return error(400, "invalid", "settings are required.")
    try:
        res = await _priv(request, "sa818.apply", {"settings": body["settings"]})
    except PrivError as exc:
        return _priv_error(exc)
    _audit(request, "SA818: save and program", res)
    return web.json_response(res)


@routes.post("/api/v1/sa818/program")
async def program(request: web.Request) -> web.Response:
    try:
        saved = await _priv(request, "sa818.read")
        if not saved["saved"]:
            return error(409, "not_saved", "There are no saved SA818 settings yet. Save them first.")
        res = await _priv(request, "sa818.apply", {"settings": saved["settings"]})
    except PrivError as exc:
        return _priv_error(exc)
    _audit(request, "SA818: program again", res)
    return web.json_response(res)


@routes.post("/api/v1/sa818/version")
async def version(request: web.Request) -> web.Response:
    try:
        return web.json_response(await _priv(request, "sa818.version"))
    except PrivError as exc:
        return _priv_error(exc)


def setup(app: web.Application) -> None:
    app.add_routes(routes)
