"""Starting, stopping and restarting Asterisk; rebooting and powering off.

    POST /api/v1/asterisk/{restart|start|stop}   {"confirm_errors"}
    POST /api/v1/system/{reboot|poweroff}

The service (user asterisk) runs systemctl; the polkit rule shipped in
/usr/share/polkit-1/rules.d/50-asl-web-ui.rules allows exactly these
actions for the asterisk user. Starting or restarting Asterisk while
rpt.conf has errors needs confirmation: app_rpt would bring no node up.
Stopping Asterisk, rebooting and powering off need a recent password entry.

In development mode (--dev with a private Asterisk) restart and stop go
through that instance's CLI, and nothing touches the host's services.
"""

import asyncio
import logging

from aiohttp import web
from aiohttp_session import get_session

from ..asterisk_cli import AsteriskUnavailable
from ..security import SETTINGS_KEY, USER_KEY
from .auth import recently_authenticated
from .changes import STORE_KEY, error, read_json
from .status import CLI_KEY, HUB_KEY

log = logging.getLogger("asl-web-ui.control")
routes = web.RouteTableDef()

SYSTEMCTL = "/usr/bin/systemctl"
UNIT = "asterisk.service"
SYSTEMCTL_KEY = web.AppKey("systemctl", str)


async def systemctl(binary: str, *args: str, timeout: float = 120) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(binary, "--no-ask-password", *args, stdin=asyncio.subprocess.DEVNULL,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 1, "systemctl did not finish in time"
    return proc.returncode or 0, out.decode(errors="replace").strip()


def _denied(output: str) -> bool:
    return "access denied" in output.lower() or "interactive authentication required" in output.lower()


def _failure(action: str, output: str) -> web.Response:
    if _denied(output):
        return error(403, "not_permitted", f"The system did not allow the web interface to {action}. "
                     "Check that the asl-web-ui polkit rule is installed "
                     "(/usr/share/polkit-1/rules.d/50-asl-web-ui.rules).", detail=output[-500:])
    return error(500, "failed", f"Could not {action}: {output[-500:] or 'no output'}")


def _audit(request: web.Request, action: str, result: str, detail: list[str] | None = None) -> None:
    request.app[STORE_KEY].record(request[USER_KEY], action, result, detail or [])
    log.info("%s: %s (%s)", request[USER_KEY], action, result)


@routes.post("/api/v1/asterisk/{action}")
async def asterisk(request: web.Request) -> web.Response:
    action = request.match_info["action"]
    if action not in ("restart", "start", "stop"):
        raise web.HTTPNotFound()
    body = await read_json(request)
    session = await get_session(request)
    settings = request.app[SETTINGS_KEY]
    hub = request.app[HUB_KEY]
    if action == "stop" and not recently_authenticated(session, settings):
        return error(403, "reauth_required", "Enter your password again to stop Asterisk.")
    if action in ("restart", "start"):
        rpt = await asyncio.to_thread(hub.rpt_lint.get)
        if rpt["errors"] and body.get("confirm_errors") is not True:
            return error(409, "rpt_errors", "rpt.conf has errors: app_rpt would start no node. "
                         "Fix rpt.conf first, or confirm to continue anyway.", first_error=rpt["first_error"])
    if settings.dev:
        if action == "start":
            return error(501, "dev_mode", "Development mode cannot start the private Asterisk; start it with "
                         "tests/asterisk/instance.sh.")
        try:
            await request.app[CLI_KEY].run("core restart now" if action == "restart" else "core stop now")
        except AsteriskUnavailable as exc:
            return error(503, "asterisk_unavailable", str(exc))
        code, output = 0, ""
    else:
        code, output = await systemctl(request.app[SYSTEMCTL_KEY], action, UNIT)
    hub.invalidate()
    if code != 0:
        _audit(request, f"{action} Asterisk", "failed", [output[-300:]])
        return _failure(f"{action} Asterisk", output)
    _audit(request, f"{action} Asterisk", "done")
    return web.json_response({"done": True})


@routes.post("/api/v1/system/{action}")
async def power(request: web.Request) -> web.Response:
    action = request.match_info["action"]
    if action not in ("reboot", "poweroff"):
        raise web.HTTPNotFound()
    session = await get_session(request)
    settings = request.app[SETTINGS_KEY]
    word = "restart" if action == "reboot" else "shut down"
    if not recently_authenticated(session, settings):
        return error(403, "reauth_required", f"Enter your password again to {word} the system.")
    if settings.dev:
        return error(501, "dev_mode", "Development mode never reboots or powers off the computer.")
    code, output = await systemctl(request.app[SYSTEMCTL_KEY], action, timeout=30)
    if code != 0:
        _audit(request, action, "failed", [output[-300:]])
        return _failure(f"{word} the system", output)
    _audit(request, action, "done")
    return web.json_response({"done": True})


def setup(app: web.Application) -> None:
    if SYSTEMCTL_KEY not in app:
        app[SYSTEMCTL_KEY] = SYSTEMCTL
    app.add_routes(routes)
