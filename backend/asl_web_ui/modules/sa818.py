"""SA818 RF modules: sa818-menu's settings and programming.

    GET  /api/v1/sa818                  saved settings, serial ports, choices
    PUT  /api/v1/sa818    {"settings"}  save to /etc/sa818.conf and program the module
    POST /api/v1/sa818/program          program the module again with the saved settings
    POST /api/v1/sa818/version          ask the module for its firmware version
    GET  /api/v1/sa818/file             /etc/sa818.conf as text (Manual Config Edit)
    POST /api/v1/sa818/file/check       {"content"}          findings
    POST /api/v1/sa818/file/plan        {"content", "hash"}  diff -> plan id
    POST /api/v1/sa818/file/plans/{id}/apply  {"confirm_errors"}  write (does not program)

The settings file and the serial port need root, so everything goes
through the privileged helper (asl_web_ui_priv.sa818 has the details).
sa818-menu sources the file as root, so the helper refuses text that is
not plain settings (sa818.lint_text errors); "Save anyway" cannot override it.
"""

import difflib
import logging
import secrets
import time

from aiohttp import web

from asl_web_ui_priv import sa818

from ..privileged import PRIV_KEY, PrivError
from ..security import USER_KEY
from .changes import STORE_KEY, error, read_json

log = logging.getLogger("asl-web-ui.sa818")
routes = web.RouteTableDef()
PLANS_KEY = web.AppKey("sa818_plans", dict)
PLAN_LIFETIME = 900

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
    status = {"not_found": 404, "invalid": 400, "conflict": 409, "denied": 403, "unavailable": 503}.get(exc.code, 500)
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


# ---- the settings file as text ---------------------------------------------------------


async def _file(request: web.Request) -> dict:
    f = await _priv(request, "file.read", {"path": sa818.CONF})
    if not f["exists"]:
        raise PrivError(f"{sa818.CONF} does not exist yet. Save the settings on the SA818 page first.", "not_found")
    return f


@routes.get("/api/v1/sa818/file")
async def read_file(request: web.Request) -> web.Response:
    try:
        f = await _file(request)
    except PrivError as exc:
        return _priv_error(exc)
    return web.json_response({**f, "name": "sa818.conf", "path": sa818.CONF, "optional": False, "writable": True,
                              "findings": sa818.lint_text(f["content"])})


@routes.post("/api/v1/sa818/file/check")
async def check_file(request: web.Request) -> web.Response:
    body = await read_json(request)
    if not isinstance(body.get("content"), str):
        return error(400, "invalid", "content is required.")
    return web.json_response({"findings": sa818.lint_text(body["content"])})


@routes.post("/api/v1/sa818/file/plan")
async def plan_file(request: web.Request) -> web.Response:
    body = await read_json(request)
    content, expected = body.get("content"), body.get("hash")
    if not isinstance(content, str) or not isinstance(expected, str):
        return error(400, "invalid", "content and hash are required.")
    try:
        current = await _file(request)
    except PrivError as exc:
        return _priv_error(exc)
    if current["hash"] != expected:
        return error(409, "conflict", f"{sa818.CONF} changed since you opened it. Reload it first.")
    findings = sa818.lint_text(content)
    if content == current["content"]:
        return web.json_response({"unchanged": True, "findings": findings})
    plans = request.app[PLANS_KEY]
    now = time.monotonic()
    for key in [k for k, p in plans.items() if p["expires"] < now]:
        del plans[key]
    plan_id = secrets.token_urlsafe(12)
    plans[plan_id] = {"user": request[USER_KEY], "content": content, "hash": expected, "expires": now + PLAN_LIFETIME}
    diff = "".join(difflib.unified_diff(current["content"].splitlines(True), content.splitlines(True),
                                        f"a{sa818.CONF}", f"b{sa818.CONF}"))
    return web.json_response({"id": plan_id, "name": "sa818.conf", "action": "SA818: edit sa818.conf", "diff": diff,
                              "created": False, "findings": findings})


@routes.post("/api/v1/sa818/file/plans/{id}/apply")
async def apply_file(request: web.Request) -> web.Response:
    await read_json(request)
    plan = request.app[PLANS_KEY].pop(request.match_info["id"], None)
    if plan is None or plan["user"] != request[USER_KEY]:
        return error(404, "not_found", "That change is no longer available. Review it again.")
    try:
        res = await _priv(request, "file.write", {"path": sa818.CONF, "content": plan["content"],
                                                  "expected_hash": plan["hash"]})
    except PrivError as exc:
        request.app[STORE_KEY].record(request[USER_KEY], "SA818: edit sa818.conf", "failed", [exc.message],
                                      files=[sa818.CONF])
        return _priv_error(exc)
    request.app[STORE_KEY].record(request[USER_KEY], "SA818: edit sa818.conf", "applied", [], files=[sa818.CONF])
    log.info("%s: edited %s", request[USER_KEY], sa818.CONF)
    return web.json_response({"hash": res["hash"], "warnings": []})


def setup(app: web.Application) -> None:
    app[PLANS_KEY] = {}
    app.add_routes(routes)
