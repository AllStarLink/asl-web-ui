"""44Net Connect: a public 44Net address through a WireGuard tunnel, on the
ASL3 appliance (asl_web_ui_priv.net44 has the details).

    GET    /api/v1/net44                          tunnel, firewall zone, hand-made tunnel, what the zone should open
    PUT    /api/v1/net44/zone        {"echolink", "rtcm"}             create or update the firewall zone
    POST   /api/v1/net44/connection  {"config", "private_key", "mode"}  set up or replace the tunnel
    POST   /api/v1/net44/migrate                  take over a tunnel set up by hand with wg-quick
    PUT    /api/v1/net44/mode        {"mode"}     full tunnel or split routing
    POST   /api/v1/net44/start       {"rollback"} start; stopped again unless confirmed in time
    POST   /api/v1/net44/confirm                  keep it running, and start it at boot
    POST   /api/v1/net44/stop
    DELETE /api/v1/net44?delete_zone=1            remove the tunnel (password re-entry)
    GET    /api/v1/net44/check                    the address the internet sees, registrations

The zone always opens IAX2 on the port in iax.conf; EchoLink and VOTER/RTCM
(on voter.conf's port) only when chosen. The choice is kept in the state
directory (SELECTION_FILE), so that when the IAX or VOTER port changes, the
zone follows with the same choice (an after-apply step of node changes).
Without that file (a zone made by hand), it is read from the zone.

The tunnel's private key passes through here once, on its way to the
helper. It is never logged, recorded or sent back.
"""

import asyncio
import ipaddress
import json
import logging
import os
import socket

import aiohttp
from aiohttp import web
from aiohttp_session import get_session

from asl_web_ui_priv import net44

from ..asterisk_cli import AsteriskUnavailable, parse_rpt_registrations
from ..configengine.edit import Workspace, module_state
from ..nodes.info import iax_port
from ..privileged import PRIV_KEY, PrivError
from ..security import SETTINGS_KEY, USER_KEY
from .auth import recently_authenticated
from .changes import STORE_KEY, error, read_json, register_after
from .status import CLI_KEY

log = logging.getLogger("asl-web-ui.net44")
routes = web.RouteTableDef()
MYIP_URL = "https://www.allstarlink.org/myip.php"
DEFAULT_VOTER_PORT = 1667
SELECTION_FILE = "net44-zone.json"


def _priv_error(exc: PrivError) -> web.Response:
    status = {"not_found": 404, "invalid": 400, "denied": 403, "unavailable": 503, "order": 409, "busy": 409,
              "conflict": 409, "expired": 410}.get(exc.code, 500)
    return error(status, exc.code, exc.message)


async def _priv(request: web.Request, command: str, args: dict | None = None, timeout: float = 120) -> dict:
    return await request.app[PRIV_KEY].call(command, args or {}, request[USER_KEY], timeout=timeout)


def _audit(request: web.Request, action: str, result: str, detail: list[str] | None = None) -> None:
    request.app[STORE_KEY].record(request[USER_KEY], action, result, detail or [])
    log.info("%s: %s (%s)", request[USER_KEY], action, result)


def asterisk_ports(config_dir: str) -> dict:
    """What the zone can open, from the Asterisk configuration."""
    ws = Workspace(config_dir)
    modules = ws.exists("modules.conf")
    voter_port = None
    if modules and module_state(ws, "chan_voter") is True and ws.exists("voter.conf"):
        value = ws.model("voter.conf").value("general", "port") or ""
        voter_port = int(value) if value.isdigit() and 0 < int(value) < 65536 else DEFAULT_VOTER_PORT
    return {"iax_port": iax_port(ws), "echolink": modules and module_state(ws, "chan_echolink") is True,
            "voter_port": voter_port}


def _selection(request: web.Request, zone: dict | None, ports: dict) -> dict:
    """Which of the optional services the zone opens (as last chosen here)."""
    try:
        with open(os.path.join(request.app[SETTINGS_KEY].state_dir, SELECTION_FILE)) as f:
            saved = json.load(f)
        if isinstance(saved.get("echolink"), bool) and isinstance(saved.get("rtcm"), bool):
            return {"echolink": saved["echolink"], "rtcm": saved["rtcm"] and ports["voter_port"] is not None}
    except (OSError, ValueError, AttributeError):
        pass
    if not zone:
        return {"echolink": False, "rtcm": False}
    voter = ports["voter_port"]
    return {"echolink": "echolink" in zone["services"],
            "rtcm": voter is not None and ("rtcm" in zone["services"] or f"{voter}/udp" in zone["ports"])}


def _save_selection(request: web.Request, echolink: bool, rtcm: bool) -> None:
    state = request.app[SETTINGS_KEY].state_dir
    try:
        os.makedirs(state, exist_ok=True)
        with open(os.path.join(state, SELECTION_FILE), "w") as f:
            json.dump({"echolink": echolink, "rtcm": rtcm}, f)
    except OSError as exc:
        log.warning("cannot save the 44Net Connect zone choice: %s", exc)


def _zone_args(ports: dict, echolink: bool, rtcm: bool) -> dict:
    return {"iax_port": ports["iax_port"], "echolink": echolink,
            "rtcm_port": ports["voter_port"] if rtcm and ports["voter_port"] is not None else None}


def _expected(args: dict) -> dict:
    services, ports = net44.zone_contents(args["iax_port"], args["echolink"], args["rtcm_port"])
    return {"services": sorted(services), "ports": sorted(ports)}


@routes.get("/api/v1/net44")
async def status(request: web.Request) -> web.Response:
    try:
        res = await _priv(request, "net44.status", timeout=60)
    except PrivError as exc:
        return _priv_error(exc)
    if not res.get("available"):
        return web.json_response(res)
    ports = asterisk_ports(request.app[SETTINGS_KEY].config_dir)
    selection = _selection(request, res["zone"], ports)
    expected = _expected(_zone_args(ports, **selection))
    zone = res["zone"]
    res.update(asterisk=ports, selection=selection, expected_zone=expected,
               zone_current=bool(zone) and zone["services"] == expected["services"]
               and zone["ports"] == expected["ports"])
    return web.json_response(res)


def _changes_refused(request: web.Request) -> web.Response | None:
    if request.app[SETTINGS_KEY].dev:
        return error(501, "dev_mode", "Development mode never changes the host's network.")
    return None


async def _change(request: web.Request, action: str, command: str, args: dict | None = None,
                  timeout: float = 120) -> web.Response:
    refused = _changes_refused(request)
    if refused is not None:
        return refused
    try:
        res = await _priv(request, command, args, timeout=timeout)
    except PrivError as exc:
        _audit(request, action, "failed", [exc.message[-200:]])
        return _priv_error(exc)
    _audit(request, action, "done")
    return web.json_response(res)


@routes.put("/api/v1/net44/zone")
async def set_zone(request: web.Request) -> web.Response:
    body = await read_json(request)
    if not isinstance(body.get("echolink"), bool) or not isinstance(body.get("rtcm"), bool):
        return error(400, "invalid", "echolink and rtcm must be true or false.")
    ports = asterisk_ports(request.app[SETTINGS_KEY].config_dir)
    if body["rtcm"] and ports["voter_port"] is None:
        return error(400, "invalid", "chan_voter is not loaded, so there is no VOTER/RTCM port to open.")
    resp = await _change(request, "44Net Connect: firewall zone", "net44.zone",
                         _zone_args(ports, body["echolink"], body["rtcm"]))
    if resp.status == 200:
        _save_selection(request, body["echolink"], body["rtcm"])
    return resp


@routes.post("/api/v1/net44/connection")
async def configure(request: web.Request) -> web.Response:
    body = await read_json(request)
    args = {"config": body.get("config"), "mode": body.get("mode")}
    if body.get("private_key"):
        args["private_key"] = body["private_key"]
    return await _change(request, "44Net Connect: set up the tunnel", "net44.configure", args)


@routes.post("/api/v1/net44/migrate")
async def migrate(request: web.Request) -> web.Response:
    return await _change(request, "44Net Connect: migrate the wg-quick tunnel", "net44.migrate")


@routes.put("/api/v1/net44/mode")
async def set_mode(request: web.Request) -> web.Response:
    body = await read_json(request)
    if body.get("mode") not in ("full", "split"):
        return error(400, "invalid", "mode must be full or split.")
    return await _change(request, f"44Net Connect: {'split routing' if body['mode'] == 'split' else 'full tunnel'}",
                         "net44.mode", {"mode": body["mode"]})


@routes.post("/api/v1/net44/start")
async def start(request: web.Request) -> web.Response:
    body = await read_json(request)
    args = {"rollback": body["rollback"]} if "rollback" in body else {}
    return await _change(request, "44Net Connect: start the tunnel", "net44.start", args)


@routes.post("/api/v1/net44/confirm")
async def confirm(request: web.Request) -> web.Response:
    return await _change(request, "44Net Connect: keep the tunnel running", "net44.confirm")


@routes.post("/api/v1/net44/stop")
async def stop(request: web.Request) -> web.Response:
    return await _change(request, "44Net Connect: stop the tunnel", "net44.stop")


@routes.delete("/api/v1/net44")
async def remove(request: web.Request) -> web.Response:
    session = await get_session(request)
    if not recently_authenticated(session, request.app[SETTINGS_KEY]):
        return error(403, "reauth_required", "Enter your password again to continue.")
    delete_zone = request.query.get("delete_zone") == "1"
    return await _change(request, "44Net Connect: remove the tunnel" + (" and its zone" if delete_zone else ""),
                         "net44.remove", {"delete_zone": delete_zone})


async def _public_ip() -> tuple[str | None, str | None]:
    try:
        connector = aiohttp.TCPConnector(family=socket.AF_INET)
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10, connect=5),
                                         connector=connector) as http:
            async with http.get(MYIP_URL) as resp:
                text = (await resp.text())[:200].strip()
                resp.raise_for_status()
        return str(ipaddress.IPv4Address(text)), None
    except ValueError:
        return None, "www.allstarlink.org answered with something other than an address."
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        return None, f"www.allstarlink.org could not be reached ({exc.__class__.__name__})."


def _on_44net(address: str) -> bool:
    host = address.rsplit(":", 1)[0]
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(ip in net for net in net44.AMPRNET)


@routes.get("/api/v1/net44/check")
async def check(request: web.Request) -> web.Response:
    """What the doc's two checks show: the address the internet sees (should
    be the 44Net one) and the address the AllStarLink servers see."""
    public_ip, ip_error = await _public_ip()
    regs, reg_error = [], None
    try:
        regs = [{"node": r.username, "perceived": r.perceived, "state": r.state, "on_44net": _on_44net(r.perceived)}
                for r in parse_rpt_registrations(await request.app[CLI_KEY].run("rpt show registrations"))]
    except AsteriskUnavailable as exc:
        reg_error = f"Asterisk is not running ({exc})."
    return web.json_response({"public_ip": public_ip, "public_ip_on_44net": bool(public_ip) and _on_44net(public_ip),
                              "public_ip_error": ip_error, "registrations": regs, "registrations_error": reg_error})


async def _after_ports(request: web.Request, plan, args) -> list[str]:
    """After the IAX or VOTER port changed: open the new port in the zone (if there is one)."""
    if request.app[SETTINGS_KEY].dev:
        return []
    try:
        res = await _priv(request, "net44.status", timeout=60)
        if not res.get("available") or not res.get("zone"):
            return []
        ports = asterisk_ports(request.app[SETTINGS_KEY].config_dir)
        args = _zone_args(ports, **_selection(request, res["zone"], ports))
        if _expected(args) == {"services": res["zone"]["services"], "ports": res["zone"]["ports"]}:
            return []
        await _priv(request, "net44.zone", args)
    except PrivError as exc:
        return [f"The 44Net Connect firewall zone could not be updated to the new port: {exc.message} Update it on "
                "the 44Net Connect page."]
    _audit(request, "44Net Connect: firewall zone follows the new port", "done")
    return []


def setup(app: web.Application) -> None:
    register_after(app, "net44_zone", _after_ports)
    app.add_routes(routes)
