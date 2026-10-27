"""HTTPS in Apache and Let's Encrypt certificates (issue #2).

    GET    /api/v1/https                          listener, certificates, asl-web-ui's site
    POST   /api/v1/https/install                  install certbot (job)
    POST   /api/v1/https/listener                 enable HTTPS on port 443, self-signed (job)
    POST   /api/v1/https/certificate  {"domains", "email", "agree_tos", "redirect"}  (job)
    PUT    /api/v1/https/redirect     {"redirect"}
    POST   /api/v1/https/cockpit                  Cockpit uses the certificate too
    POST   /api/v1/https/renew-test               certbot renew --dry-run (job)
    DELETE /api/v1/https?delete_certificate=1     stop using it (password re-entry)

Everything runs as root in the privileged helper (asl_web_ui_priv.https has
the details). Apache reloads gracefully, so the page's own connection
survives the changes.
"""

import logging

from aiohttp import web
from aiohttp_session import get_session

from asl_web_ui_priv import https

from ..privileged import PRIV_KEY, PrivError
from ..security import SETTINGS_KEY, USER_KEY
from .auth import recently_authenticated
from .changes import STORE_KEY, error, read_json
from .jobs import start as start_job

log = logging.getLogger("asl-web-ui.https")
routes = web.RouteTableDef()


def _priv_error(exc: PrivError) -> web.Response:
    field = None
    message = exc.message
    if exc.code == "invalid" and ": " in message and message.split(": ", 1)[0] in (
            "domains", "email", "agree_tos"):
        field, message = message.split(": ", 1)
    status = {"not_found": 404, "invalid": 400, "denied": 403, "unavailable": 503}.get(exc.code, 500)
    return error(status, exc.code, message, field=field)


async def _priv(request: web.Request, command: str, args: dict | None = None, on_output=None) -> dict:
    return await request.app[PRIV_KEY].call(command, args or {}, request[USER_KEY], on_output, timeout=900)


def _audit(request: web.Request, action: str, result: str, detail: list[str] | None = None) -> None:
    request.app[STORE_KEY].record(request[USER_KEY], action, result, detail or [])
    log.info("%s: %s (%s)", request[USER_KEY], action, result)


async def _job(request: web.Request, title: str, command: str, args: dict | None = None) -> web.Response:
    async def work(job):
        try:
            res = await _priv(request, command, args, on_output=job.output)
        except PrivError as exc:
            _audit(request, title, "failed", [exc.message[-200:]])
            raise  # the job reports its message
        _audit(request, title, "done")
        return res

    return await start_job(request, title, work)


@routes.get("/api/v1/https")
async def status(request: web.Request) -> web.Response:
    try:
        return web.json_response(await _priv(request, "https.status"))
    except PrivError as exc:
        return _priv_error(exc)


@routes.post("/api/v1/https/install")
async def install(request: web.Request) -> web.Response:
    return await _job(request, "Install certbot", "https.install")


@routes.post("/api/v1/https/listener")
async def listener(request: web.Request) -> web.Response:
    return await _job(request, "Enable HTTPS on port 443", "https.enable_listener")


@routes.post("/api/v1/https/certificate")
async def certificate(request: web.Request) -> web.Response:
    body = await read_json(request)
    args = {k: body.get(k) for k in ("domains", "email", "agree_tos", "redirect")}
    try:  # the helper checks again
        args["domains"] = https.check_names(args["domains"])
        args["email"] = https.check_email(args["email"])
    except https.HttpsError as exc:
        return error(400, "invalid", exc.message, field=exc.field)
    if args["agree_tos"] is not True:
        return error(400, "invalid", "Agree to the Let's Encrypt subscriber agreement first.", field="agree_tos")
    return await _job(request, f"Let's Encrypt certificate for {', '.join(map(str, args['domains']))}",
                      "https.obtain", args)


@routes.put("/api/v1/https/redirect")
async def redirect(request: web.Request) -> web.Response:
    body = await read_json(request)
    if not isinstance(body.get("redirect"), bool):
        return error(400, "invalid", "redirect must be true or false.")
    try:
        res = await _priv(request, "https.redirect", {"redirect": body["redirect"]})
    except PrivError as exc:
        return _priv_error(exc)
    _audit(request, f"HTTP to HTTPS redirect {'on' if body['redirect'] else 'off'}", "done")
    return web.json_response(res)


@routes.post("/api/v1/https/cockpit")
async def cockpit(request: web.Request) -> web.Response:
    try:
        res = await _priv(request, "https.cockpit")
    except PrivError as exc:
        return _priv_error(exc)
    _audit(request, "Cockpit uses the Let's Encrypt certificate", "done")
    return web.json_response(res)


@routes.post("/api/v1/https/renew-test")
async def renew_test(request: web.Request) -> web.Response:
    return await _job(request, "Test the certificate renewal", "https.renew_test")


@routes.delete("/api/v1/https")
async def remove(request: web.Request) -> web.Response:
    session = await get_session(request)
    if not recently_authenticated(session, request.app[SETTINGS_KEY]):
        return error(403, "reauth_required", "Enter your password again to continue.")
    delete = request.query.get("delete_certificate") == "1"
    try:
        res = await _priv(request, "https.remove", {"delete_certificate": delete})
    except PrivError as exc:
        return _priv_error(exc)
    _audit(request, "Stop using the Let's Encrypt certificate" + (" and delete it" if delete else ""), "done")
    return web.json_response(res)


def setup(app: web.Application) -> None:
    app.add_routes(routes)
