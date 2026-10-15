"""Nodes: node-setup's operations as planned changes, plus access lists.

    GET    /api/v1/nodes                              nodes, first-run state, choices
    GET    /api/v1/nodes/{node}                       one node in detail
    POST   /api/v1/nodes/plan          {"op", ...}    plan a change -> diffs, notes, plan id
    GET    /api/v1/nodes/{node}/access                allow/deny lists (AstDB)
    POST   /api/v1/nodes/{node}/access {"list", "entry", "reason"}
    DELETE /api/v1/nodes/{node}/access/{list}/{entry}
    DELETE /api/v1/nodes/{node}/access/{list}
    GET    /api/v1/asterisk/settings                  IAX port, AMI users

Plans are applied with POST /api/v1/changes/{id}/apply (modules/changes.py).
Access lists take effect immediately and need no restart.
"""

import logging
import os
import re
from dataclasses import asdict

from aiohttp import web
from aiohttp_session import get_session

from ..asterisk_cli import AsteriskUnavailable
from ..configengine.edit import Workspace
from ..configengine.lint import lint
from ..configengine.model import load
from ..configengine.store import Store
from ..nodes import access, customize
from ..nodes.info import (
    DUPLEX_LABELS, INTERFACE_LABELS, PRIVATE_LIMIT, all_nodes, iax_port, is_untouched_template, node_info,
)
from ..nodes.planner import Planner, PlanError
from ..security import SETTINGS_KEY, USER_KEY
from .changes import STORE_KEY, error, read_json, register_after, unwritable
from .status import CLI_KEY

log = logging.getLogger("asl-web-ui.nodes")
routes = web.RouteTableDef()

_NUMBER = re.compile(r"^[0-9]{1,7}$")

# node-setup's "common configurations" for a new node.
COMMON_PRESETS = [
    {"id": "hotspot", "label": "Half-duplex node (hotspot) with telemetry tones", "duplex": 1, "interface": None},
    {"id": "hotspot-quiet", "label": "Half-duplex node (hotspot) with no telemetry tones", "duplex": 0,
     "interface": None},
    {"id": "repeater", "label": "Full-duplex node (repeater or hotspot)", "duplex": 2, "interface": None},
    {"id": "full-norepeat", "label": "Full-duplex node that does not repeat audio", "duplex": 3, "interface": None},
    {"id": "hub", "label": "Hub node with no radio interface", "duplex": 2, "interface": "Pseudo"},
]
# Files whose Asterisk lint is compared before and after a plan.
LINTED = ["rpt.conf", "rpt_http_registrations.conf", "iax.conf", "extensions.conf", "modules.conf",
          "manager.conf", "simpleusb.conf", "usbradio.conf", "voter.conf"]


def _ws(request: web.Request) -> Workspace:
    return Workspace(request.app[SETTINGS_KEY].config_dir)


def _number(value: str) -> str:
    if not _NUMBER.match(value or ""):
        raise web.HTTPNotFound(text="No such node")
    return value


def _plan_error(exc: PlanError) -> web.Response:
    status = 404 if exc.code == "not_found" else 409 if exc.code in ("requirement", "custom_id") else 400
    return error(status, exc.code, exc.message, field=exc.field)


@routes.get("/api/v1/nodes")
async def list_nodes(request: web.Request) -> web.Response:
    ws = _ws(request)
    if not ws.exists("rpt.conf"):
        return error(500, "no_rpt_conf", "rpt.conf was not found in the configuration directory.")
    rpt = ws.model("rpt.conf")
    infos = all_nodes(ws)
    nodes = []
    for info in infos:
        d = info.as_dict()
        d["customizations"] = customize.status(ws, info.number)["state"]
        nodes.append(d)
    return web.json_response({
        "nodes": nodes,
        "first_run": len(infos) == 1 and is_untouched_template(infos[0]),
        "rpt_errors": len(rpt.errors),
        "iax_port": iax_port(ws),
        "interfaces": [{"id": k, "label": v} for k, v in INTERFACE_LABELS.items()],
        "duplex": [{"value": k, "label": v} for k, v in DUPLEX_LABELS.items()],
        "presets": {"common": COMMON_PRESETS, "devices": customize.device_presets(ws.config_dir)},
        # For a new node: what customizations could be chosen, per channel driver.
        "customize": {
            iface: {"reason": customize.structure_reason(ws, chan),
                    "options": [asdict(o) | {"device": o.device} for o in customize.options(ws.config_dir, chan)]}
            for iface, chan in (("SimpleUSB", "simpleusb"), ("USBRadio", "usbradio"), ("other", None))
        },
        "private_limit": PRIVATE_LIMIT,
    })


@routes.get("/api/v1/nodes/{node}")
async def get_node(request: web.Request) -> web.Response:
    number = _number(request.match_info["node"])
    ws = _ws(request)
    try:
        info = node_info(ws, number)
    except KeyError:
        return error(404, "not_found", f"Node {number} is not configured.")
    out = info.as_dict()
    out["customizations"] = customize.status(ws, number)
    return web.json_response(out)


# ---- planning ----------------------------------------------------------------------


def _bool(body: dict, key: str) -> bool | None:
    value = body.get(key)
    return value if isinstance(value, bool) else None


def _str(body: dict, key: str, required: bool = True) -> str | None:
    value = body.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise PlanError(f"{key} is required.", key)
    return value


def _duplex(body: dict) -> int | None:
    value = body.get("duplex")
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise PlanError("duplex must be a number from 0 to 4.", "duplex")
    return value


def _describe(op: str, body: dict) -> str:
    node = body.get("node") or body.get("number") or ""
    return {
        "add": f"add node {body.get('number')}",
        "first_run": f"set up node {body.get('number')}",
        "rename": f"change node number {node} to {body.get('number')}",
        "remove": f"remove node {node}",
        "callsign": f"node {node}: call sign",
        "duplex": f"node {node}: duplex",
        "statpost": f"node {node}: status posting",
        "password": f"node {node}: password",
        "interface": f"node {node}: radio interface",
        "customize": f"node {node}: customizations",
        "enable_customizations": "enable customizations",
        "iax_port": "IAX port",
        "ami_secret": "AMI secret",
    }.get(op, op)


def _run(planner: Planner, op: str, body: dict) -> None:
    node = _str(body, "node") if op not in ("add", "first_run", "iax_port", "ami_secret", "enable_customizations") \
        else None
    if op in ("add", "first_run"):
        kwargs = dict(password=_str(body, "password", False) or None, interface=_str(body, "interface", False),
                      duplex=_duplex(body), linktolink=_str(body, "linktolink", False),
                      callsign=_str(body, "callsign", False) or None, statpost=_bool(body, "statpost"))
        number = _str(body, "number").strip()
        (planner.add if op == "add" else planner.first_run)(number, **kwargs)
        names = body.get("customizations") or []
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            raise PlanError("customizations must be a list of names.", "customizations")
        if names:
            planner.customize(number, names)
    elif op == "rename":
        planner.rename(node, _str(body, "number").strip())
    elif op == "remove":
        planner.remove(node)
    elif op == "callsign":
        planner.set_callsign(node, _str(body, "callsign"), bool(body.get("replace_custom")))
    elif op == "duplex":
        duplex = _duplex(body)
        if duplex is None:
            raise PlanError("duplex is required.", "duplex")
        planner.set_duplex(node, duplex, _str(body, "linktolink", False))
    elif op == "statpost":
        enabled = _bool(body, "enabled")
        if enabled is None:
            raise PlanError("enabled must be true or false.", "enabled")
        planner.set_statpost(node, enabled)
    elif op == "password":
        planner.set_password(node, _str(body, "password"))
    elif op == "interface":
        planner.set_interface(node, _str(body, "interface"))
    elif op == "customize":
        names = body.get("names")
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            raise PlanError("names must be a list.", "names")
        planner.customize(node, names)
    elif op == "enable_customizations":
        changed = customize.enable(planner.ws)
        if not changed:
            raise PlanError("The configuration files did not need changes, but customizations are still not "
                            "available. See Manual Config Edit.", code="requirement")
        planner.effects.note("Your configuration files are rearranged so that customizations can be added. "
                             "Settings stay the same.")
        planner.effects.restart = True
    elif op == "iax_port":
        planner.set_iax_port(body.get("port"))
    elif op == "ami_secret":
        planner.set_ami_secret(_str(body, "secret"))
    else:
        raise PlanError(f"Unknown operation: {op}", "op")


def _lint(ws: Workspace, config_dir: str, after: bool) -> dict[str, list]:
    out = {}
    for name in LINTED:
        if not ws.exists(name):
            continue
        reader = ws.read_bytes if after else (lambda p: _disk(ws, p))
        cfg = load(name, config_dir=config_dir, reader=reader)
        out[name] = [f for f in lint(cfg, config_dir) if f.severity == "error"]
    return out


def _disk(ws: Workspace, path: str) -> bytes:
    data = ws.originals[path] if path in ws.originals else Store.read(path)
    if data is None:
        raise FileNotFoundError(path)
    return data


@routes.post("/api/v1/nodes/plan")
async def plan(request: web.Request) -> web.Response:
    body = await read_json(request)
    op = body.get("op")
    if not isinstance(op, str):
        return error(400, "invalid", "op is required.")
    settings = request.app[SETTINGS_KEY]
    ws = _ws(request)
    planner = Planner(ws)
    try:
        _run(planner, op, body)
    except PlanError as exc:
        return _plan_error(exc)
    fx = planner.effects
    changes = ws.changes()
    if not changes:
        return web.json_response({"unchanged": True, "notes": [n.__dict__ for n in fx.notes]})
    bad = unwritable([c.path for c in changes])
    if bad:
        names = " ".join(bad)
        return error(409, "not_writable", "Some files cannot be changed by the web interface because of their "
                     f"ownership. Fix it with: sudo chown asterisk:asterisk {names}", files=bad)
    before = _lint(ws, settings.config_dir, after=False)
    after = _lint(ws, settings.config_dir, after=True)
    new_errors = []
    for name, findings in after.items():
        old = {(f.code, f.message) for f in before.get(name, [])}
        new_errors += [f.as_dict() for f in findings if (f.code, f.message) not in old]
    session = await get_session(request)
    stored = request.app[STORE_KEY].plan(session.identity or "", request[USER_KEY], _describe(op, body), changes)
    stored.errors = len(new_errors)
    after_steps = [("astdb", list(a)) for a in fx.astdb]
    stored.meta = {"after": after_steps, "reauth": op == "remove", "restart": fx.restart}
    return web.json_response({
        "id": stored.id,
        "action": stored.action,
        "files": [{"name": os.path.relpath(c.path, settings.config_dir), "diff": c.diff(
            os.path.relpath(c.path, settings.config_dir))} for c in changes],
        "notes": [n.__dict__ for n in fx.notes],
        "allmon3": fx.allmon3,
        "restart": fx.restart,
        "tune": fx.tune,
        "errors": new_errors,
        "reauth": op == "remove",
    })


async def _after_astdb(request: web.Request, plan, args: list) -> list[str]:
    if args[0] == "rename":
        try:
            await access.rename(request.app[CLI_KEY], args[1], args[2])
        except AsteriskUnavailable:
            return [f"Asterisk is not running, so node {args[1]}'s access list was not moved to node {args[2]}."]
    return []


# ---- access lists ----------------------------------------------------------------------


def _configured(request: web.Request, number: str) -> None:
    rpt = load("rpt.conf", config_dir=request.app[SETTINGS_KEY].config_dir)
    cat = rpt.get(number)
    if cat is None or cat.template:
        raise web.HTTPNotFound(text=f"Node {number} is not configured")


async def _access_response(request: web.Request, number: str) -> web.Response:
    try:
        entries = await access.lists(request.app[CLI_KEY], number)
    except AsteriskUnavailable as exc:
        return error(503, "asterisk_unavailable", f"Asterisk is not running, so the access list cannot be read. {exc}")
    return web.json_response({**entries, "mode": access.mode(entries)})


def _audit(request: web.Request, action: str, detail: list[str]) -> None:
    request.app[STORE_KEY].record(request[USER_KEY], action, "applied", detail)
    log.info("%s: %s %s", request[USER_KEY], action, " ".join(detail))


@routes.get("/api/v1/nodes/{node}/access")
async def get_access(request: web.Request) -> web.Response:
    number = _number(request.match_info["node"])
    _configured(request, number)
    return await _access_response(request, number)


@routes.post("/api/v1/nodes/{node}/access")
async def add_access(request: web.Request) -> web.Response:
    number = _number(request.match_info["node"])
    _configured(request, number)
    body = await read_json(request)
    try:
        await access.add(request.app[CLI_KEY], number, str(body.get("list", "")), str(body.get("entry", "")),
                         str(body.get("reason", "")))
    except PlanError as exc:
        return _plan_error(exc)
    except AsteriskUnavailable as exc:
        return error(503, "asterisk_unavailable", str(exc))
    _audit(request, f"node {number}: access list", [f"add {body.get('list')} {body.get('entry')}"])
    return await _access_response(request, number)


@routes.delete("/api/v1/nodes/{node}/access/{list}/{entry}")
async def remove_access(request: web.Request) -> web.Response:
    number = _number(request.match_info["node"])
    _configured(request, number)
    kind, entry = request.match_info["list"], request.match_info["entry"]
    try:
        await access.remove(request.app[CLI_KEY], number, kind, entry)
    except PlanError as exc:
        return _plan_error(exc)
    except AsteriskUnavailable as exc:
        return error(503, "asterisk_unavailable", str(exc))
    _audit(request, f"node {number}: access list", [f"remove {kind} {entry}"])
    return await _access_response(request, number)


@routes.delete("/api/v1/nodes/{node}/access/{list}")
async def clear_access(request: web.Request) -> web.Response:
    number = _number(request.match_info["node"])
    _configured(request, number)
    kind = request.match_info["list"]
    try:
        await access.clear(request.app[CLI_KEY], number, kind)
    except PlanError as exc:
        return _plan_error(exc)
    except AsteriskUnavailable as exc:
        return error(503, "asterisk_unavailable", str(exc))
    _audit(request, f"node {number}: access list", [f"clear {kind}"])
    return await _access_response(request, number)


# ---- Asterisk settings -------------------------------------------------------------------


@routes.get("/api/v1/asterisk/settings")
async def asterisk_settings(request: web.Request) -> web.Response:
    ws = _ws(request)
    planner = Planner(ws)
    users = planner.ami_users()
    return web.json_response({"iax_port": iax_port(ws), "ami_users": users, "ami_admin": "admin" in
                              [u.lower() for u in users]})


def setup(app: web.Application) -> None:
    register_after(app, "astdb", _after_astdb)
    app.add_routes(routes)
