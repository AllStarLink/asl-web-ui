"""Allmon3 on this server: its nodes, users, web settings and files.

    GET    /api/v1/allmon3                                service, files, local nodes
    POST   /api/v1/allmon3/service/{start|stop|restart}
    GET    /api/v1/allmon3/files/{name}                   content, hash, findings
    POST   /api/v1/allmon3/files/{name}/check  {"content"}          findings
    POST   /api/v1/allmon3/files/{name}/plan   {"content", "hash"}  diff -> plan id
    DELETE /api/v1/allmon3/files/menu.ini?hash=           remove the custom menu
    GET    /api/v1/allmon3/nodes                          allmon3.ini's nodes, local nodes, AMI users
    POST   /api/v1/allmon3/nodes/plan  {"op": "set"|"remove"|"add_local", ...}  -> plan id
    POST   /api/v1/allmon3/web/plan    {"values": {KEY: value|null}}           -> plan id
    POST   /api/v1/allmon3/plans/{id}/apply  {"confirm_errors"}  write, restart Allmon3
    GET    /api/v1/allmon3/users                          users and their node restrictions
    POST   /api/v1/allmon3/users       {"user", "password"}  add a user or set a password
    DELETE /api/v1/allmon3/users/{user}
    PUT    /api/v1/allmon3/users/{user}/nodes  {"nodes": [...]|null}

The files belong to root or allmon3, so they are read and written through
the privileged helper; the users file only through its allmon3.* commands,
which never return the password hashes. Every change restarts Allmon3 (its
reload signal does not reload node, web or menu settings) and is recorded in
the audit log. Planned contents stay on the server: a plan is applied by id.
"""

import asyncio
import difflib
import logging
import re
import secrets
import time

from aiohttp import web
from aiohttp_session import get_session

from .. import allmon3conf as conf
from ..configengine.model import load
from ..nodes.info import node_numbers
from ..privileged import PRIV_KEY, PrivError
from ..security import SETTINGS_KEY, USER_KEY
from ..systemd import unit_state
from .auth import recently_authenticated
from .changes import STORE_KEY, error, read_json
from .control import SYSTEMCTL_KEY, systemctl

log = logging.getLogger("asl-web-ui.allmon3")
routes = web.RouteTableDef()

UNIT = "allmon3.service"
PLAN_LIFETIME = 900
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
USER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,63}$")
PLANS_KEY = web.AppKey("allmon3_plans", dict)


class Problem(Exception):
    def __init__(self, status: int, code: str, message: str, field: str | None = None):
        super().__init__(message)
        self.response = error(status, code, message, field=field)


def _priv_error(exc: PrivError) -> web.Response:
    status = {"not_found": 404, "invalid": 400, "conflict": 409, "denied": 403, "unavailable": 503}.get(exc.code, 500)
    return error(status, exc.code, exc.message)


async def _priv(request: web.Request, command: str, args: dict | None = None) -> dict:
    return await request.app[PRIV_KEY].call(command, args or {}, request[USER_KEY])


def _name(request: web.Request) -> str:
    name = request.match_info["name"]
    if name not in conf.FILES:
        raise web.HTTPNotFound(text="No such Allmon3 file")
    return name


async def _read(request: web.Request, name: str) -> dict:
    return await _priv(request, "file.read", {"path": conf.path(name)})


def _audit(request: web.Request, action: str, result: str, detail: list[str], files: list[str]) -> None:
    request.app[STORE_KEY].record(request[USER_KEY], action, result, detail, files=files)
    log.info("%s: %s (%s) %s", request[USER_KEY], action, result, " ".join(detail))


async def _reauth(request: web.Request) -> web.Response | None:
    session = await get_session(request)
    if not recently_authenticated(session, request.app[SETTINGS_KEY]):
        return error(403, "reauth_required", "Enter your password again to continue.")
    return None


async def _restart(request: web.Request) -> list[str]:
    if request.app[SETTINGS_KEY].dev:
        return []
    state = await unit_state(UNIT, request.app[SYSTEMCTL_KEY])
    if state.get("ActiveState") not in ("active", "activating", "reloading"):
        return ["Allmon3 is not running, so it was not restarted. Start it to use the new settings."]
    code, output = await systemctl(request.app[SYSTEMCTL_KEY], "restart", UNIT, timeout=60)
    if code != 0:
        return [f"The settings were saved, but Allmon3 could not be restarted: {output[-200:]}"]
    return []


# ---- what the local Asterisk offers --------------------------------------------------------


def _asterisk(request: web.Request) -> dict:
    """Local node numbers, AMI users with their secrets, and the AMI port."""
    config_dir = request.app[SETTINGS_KEY].config_dir
    try:
        local = node_numbers(load("rpt.conf", config_dir=config_dir))
    except OSError:
        local = []
    users, port = {}, "5038"
    try:
        manager = load("manager.conf", config_dir=config_dir)
        for cat in manager.categories:
            if cat.template:
                continue
            if cat.name.lower() == "general":
                port = cat.value("port") or port
            elif cat.value("secret"):
                users[cat.name] = cat.value("secret")
    except OSError:
        pass
    return {"local": local, "ami": users, "port": port}


def _escape(value: str) -> str:
    # Allmon3's configparser reads % as the start of a variable.
    return value.replace("%", "%%")


# ---- plans -------------------------------------------------------------------------------


def _diff(name: str, old: str, new: str) -> str:
    lines = difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a{conf.path(name)}",
                                 f"b{conf.path(name)}")
    out = "".join(lines)
    if name == "allmon3.ini":
        # The review shows that a password changes, not the password.
        out = re.sub(r"(?m)^([-+ ]\s*pass\s*[=:]\s*)\S.*$", r"\1••••••••", out)
    return out


def _plan(request: web.Request, name: str, current: dict, content: str, action: str) -> web.Response:
    plans = request.app[PLANS_KEY]
    now = time.monotonic()
    for key in [k for k, p in plans.items() if p["expires"] < now]:
        del plans[key]
    old = current["content"] if current["exists"] else ""
    findings = conf.check(name, content)
    if current["exists"] and content == old:
        return web.json_response({"unchanged": True, "findings": findings})
    plan_id = secrets.token_urlsafe(12)
    plans[plan_id] = {"user": request[USER_KEY], "name": name, "content": content, "hash": current["hash"],
                      "action": action, "errors": sum(f["severity"] == "error" for f in findings),
                      "expires": now + PLAN_LIFETIME}
    return web.json_response({"id": plan_id, "name": name, "action": action, "diff": _diff(name, old, content),
                              "created": not current["exists"], "findings": findings})


@routes.post("/api/v1/allmon3/plans/{id}/apply")
async def apply(request: web.Request) -> web.Response:
    body = await read_json(request)
    plan = request.app[PLANS_KEY].pop(request.match_info["id"], None)
    if plan is None or plan["user"] != request[USER_KEY]:
        return error(404, "not_found", "That change is no longer available. Review it again.")
    if plan["errors"] and not body.get("confirm_errors"):
        request.app[PLANS_KEY][request.match_info["id"]] = plan
        return error(409, "has_errors", "Allmon3 would not load the file as it is. Confirm to save it anyway.")
    path = conf.path(plan["name"])
    try:
        res = await _priv(request, "file.write", {"path": path, "content": plan["content"],
                                                  "expected_hash": plan["hash"]})
    except PrivError as exc:
        _audit(request, plan["action"], "failed", [exc.message], [path])
        return _priv_error(exc)
    warnings = await _restart(request)
    _audit(request, plan["action"], "applied", warnings, [path])
    return web.json_response({"hash": res["hash"], "warnings": warnings})


# ---- overview and files --------------------------------------------------------------------


@routes.get("/api/v1/allmon3")
async def overview(request: web.Request) -> web.Response:
    try:
        reads = await asyncio.gather(*(_read(request, n) for n in conf.FILES))
    except PrivError as exc:
        return _priv_error(exc)
    files = []
    for name, f in zip(conf.FILES, reads):
        findings = conf.check(name, f["content"]) if f["exists"] else []
        files.append({"name": name, "description": conf.FILES[name], "exists": f["exists"],
                      "optional": name in conf.OPTIONAL,
                      "errors": sum(x["severity"] == "error" for x in findings),
                      "warnings": sum(x["severity"] == "warning" for x in findings)})
    installed = reads[0]["exists"]
    state = await unit_state(UNIT, request.app[SYSTEMCTL_KEY]) if installed else {}
    nodes = [n["node"] for n in conf.nodes(reads[0]["content"])] if installed else []
    return web.json_response({
        "installed": installed,
        "service": {"active": state.get("ActiveState"), "sub": state.get("SubState"),
                    "since": state.get("ActiveEnterTimestamp"), "enabled": state.get("UnitFileState")},
        "url": "/allmon3/",
        "nodes": nodes,
        "files": files,
    })


@routes.post("/api/v1/allmon3/service/{action}")
async def service(request: web.Request) -> web.Response:
    action = request.match_info["action"]
    if action not in ("start", "stop", "restart"):
        raise web.HTTPNotFound()
    code, output = await systemctl(request.app[SYSTEMCTL_KEY], action, UNIT, timeout=60)
    _audit(request, f"Allmon3: {action}", "applied" if code == 0 else "failed", [output[-200:]] if code else [], [])
    if code != 0:
        return error(500, "failed", f"systemctl {action} {UNIT} failed: {output[-300:]}")
    state = await unit_state(UNIT, request.app[SYSTEMCTL_KEY])
    return web.json_response({"active": state.get("ActiveState"), "sub": state.get("SubState")})


@routes.get("/api/v1/allmon3/files/{name}")
async def read_file(request: web.Request) -> web.Response:
    name = _name(request)
    try:
        f = await _read(request, name)
    except PrivError as exc:
        return _priv_error(exc)
    return web.json_response({**f, "name": name, "path": conf.path(name), "optional": name in conf.OPTIONAL,
                              "findings": conf.check(name, f["content"]) if f["exists"] else []})


@routes.post("/api/v1/allmon3/files/{name}/check")
async def check_file(request: web.Request) -> web.Response:
    name = _name(request)
    body = await read_json(request)
    content = body.get("content")
    if not isinstance(content, str):
        return error(400, "invalid", "content is required.")
    return web.json_response({"findings": conf.check(name, content)})


@routes.post("/api/v1/allmon3/files/{name}/plan")
async def plan_file(request: web.Request) -> web.Response:
    name = _name(request)
    body = await read_json(request)
    content, expected = body.get("content"), body.get("hash")
    if not isinstance(content, str) or not isinstance(expected, str):
        return error(400, "invalid", "content and hash are required.")
    try:
        current = await _read(request, name)
    except PrivError as exc:
        return _priv_error(exc)
    if not current["exists"] and name not in conf.OPTIONAL:
        return error(404, "not_found", f"{conf.path(name)} does not exist. Is Allmon3 installed?")
    if current["hash"] != expected:
        return error(409, "conflict", f"{conf.path(name)} changed since you opened it. Reload it first.")
    return _plan(request, name, current, content, f"Allmon3: edit {name}")


@routes.delete("/api/v1/allmon3/files/{name}")
async def delete_file(request: web.Request) -> web.Response:
    name = _name(request)
    if name not in conf.OPTIONAL:
        return error(400, "invalid", f"{name} cannot be removed.")
    try:
        res = await _priv(request, "file.delete", {"path": conf.path(name), "expected_hash": request.query.get("hash", "")})
    except PrivError as exc:
        return _priv_error(exc)
    warnings = await _restart(request) if res["removed"] else []
    _audit(request, f"Allmon3: remove {name}", "applied", warnings, [conf.path(name)])
    return web.json_response({"warnings": warnings})


# ---- nodes (allmon3.ini) ---------------------------------------------------------------------


async def _nodes_file(request: web.Request) -> dict:
    f = await _read(request, "allmon3.ini")
    if not f["exists"]:
        raise Problem(404, "not_installed", "Allmon3 is not installed (/etc/allmon3/allmon3.ini is missing).")
    return f


@routes.get("/api/v1/allmon3/nodes")
async def list_nodes(request: web.Request) -> web.Response:
    try:
        f = await _nodes_file(request)
    except PrivError as exc:
        return _priv_error(exc)
    except Problem as p:
        return p.response
    ast = _asterisk(request)
    nodes = []
    for n in conf.nodes(f["content"]):
        password = n.pop("pass", None)
        ami_user = n.get("user")
        local = n.get("host", "").strip() in LOCAL_HOSTS
        n["pass_set"] = bool(password)
        n["pass_matches_ami"] = bool(local and password and ami_user in ast["ami"]
                                     and password.replace("%%", "%") == ast["ami"][ami_user])
        n["local_host"] = local
        nodes.append(n)
    listed = {n["node"] for n in nodes} | {m.strip() for n in nodes for m in n.get("multinodes", "").split(",")}
    return web.json_response({
        "nodes": nodes,
        "local": [{"number": num, "listed": num in listed} for num in ast["local"]],
        "ami_users": list(ast["ami"]),
        "ami_port": ast["port"],
        "findings": conf.check("allmon3.ini", f["content"]),
    })


def _node_values(body: dict, ast: dict) -> dict[str, str | None]:
    values: dict[str, str | None] = {}
    for key in ("host", "port", "user", "multinodes", "voters", "pollinterval", "vpollinterval", "retryinterval",
                "retrycount", "iframepre", "iframepost"):
        if key not in body:
            continue
        v = body[key]
        if v is not None and not isinstance(v, (str, int, float)):
            raise Problem(400, "invalid", f"{key} must be text.", key)
        v = str(v).strip() if v is not None else ""
        if "\n" in v:
            raise Problem(400, "invalid", f"{key} must be one line.", key)
        values[key] = _escape(v) if v else None
    for key in ("host", "user"):
        if not values.get(key):
            raise Problem(400, "invalid", f"{key} is required.", key)
    mode = body.get("pass_mode", "keep")
    if mode == "ami":
        user = (values["user"] or "").replace("%%", "%")
        if user not in ast["ami"]:
            raise Problem(400, "invalid", f"manager.conf has no AMI user {user} with a secret.", "user")
        values["pass"] = _escape(ast["ami"][user])
    elif mode == "value":
        password = body.get("pass")
        if not isinstance(password, str) or not password.strip() or "\n" in password:
            raise Problem(400, "invalid", "Enter the AMI secret.", "pass")
        values["pass"] = _escape(password.strip())
    elif mode != "keep":
        raise Problem(400, "invalid", "pass_mode must be keep, ami or value.", "pass_mode")
    return values


@routes.post("/api/v1/allmon3/nodes/plan")
async def plan_nodes(request: web.Request) -> web.Response:
    body = await read_json(request)
    op = body.get("op")
    try:
        f = await _nodes_file(request)
        text = f["content"]
        existing = {n["node"]: n for n in conf.nodes(text)}
        ast = _asterisk(request)
        if op == "set":
            node = str(body.get("node", "")).strip()
            if not node.isdigit():
                raise Problem(400, "invalid", "The node number must be digits.", "node")
            original = str(body.get("original") or node)
            if original != node and node in existing:
                raise Problem(409, "exists", f"Node {node} is already in allmon3.ini.", "node")
            values = _node_values(body, ast)
            if original not in existing and "pass" not in values:
                raise Problem(400, "invalid", "Choose the AMI secret for the new node.", "pass")
            if original != node and original in existing:
                text = re.sub(rf"(?m)^(\s*\[){re.escape(original)}(\])", rf"\g<1>{node}\g<2>", text)
            text = conf.set_values(text, node, values)
            action = f"Allmon3: {'add' if original not in existing else 'change'} node {node}"
        elif op == "remove":
            node = str(body.get("node", ""))
            if node not in existing:
                raise Problem(404, "not_found", f"Node {node} is not in allmon3.ini.", "node")
            text = conf.remove_section(text, node)
            action = f"Allmon3: remove node {node}"
        elif op == "add_local":
            if "admin" not in ast["ami"]:
                raise Problem(409, "requirement", "manager.conf has no [admin] user with a secret for Allmon3 to use.")
            missing = [n for n in ast["local"] if n not in existing]
            if not missing:
                raise Problem(409, "unchanged", "Every local node is already in allmon3.ini.")
            for n in missing:
                text = conf.set_values(text, n, {"host": "127.0.0.1", "port": ast["port"], "user": "admin",
                                                 "pass": _escape(ast["ami"]["admin"])})
            action = f"Allmon3: add node{'s' if len(missing) > 1 else ''} {', '.join(missing)}"
        else:
            raise Problem(400, "invalid", "op must be set, remove or add_local.", "op")
    except PrivError as exc:
        return _priv_error(exc)
    except Problem as p:
        return p.response
    return _plan(request, "allmon3.ini", f, text, action)


# ---- web settings (web.ini [web]) ------------------------------------------------------------


@routes.get("/api/v1/allmon3/web")
async def web_settings(request: web.Request) -> web.Response:
    try:
        f = await _read(request, "web.ini")
    except PrivError as exc:
        return _priv_error(exc)
    if not f["exists"]:
        return error(404, "not_installed", "/etc/allmon3/web.ini is missing. Is Allmon3 installed?")
    return web.json_response({"values": conf.web_settings(f["content"]), "findings": conf.check("web.ini", f["content"])})


@routes.post("/api/v1/allmon3/web/plan")
async def plan_web(request: web.Request) -> web.Response:
    body = await read_json(request)
    values = body.get("values")
    if not isinstance(values, dict) or not all(k in conf.WEB_KEYS for k in values):
        return error(400, "invalid", "values must map web.ini [web] settings to text or null.")
    out: dict[str, str | None] = {}
    for key, value in values.items():
        if value is not None and (not isinstance(value, str) or "\n" in value):
            return error(400, "invalid", f"{key} must be one line of text.", field=key)
        if key in ("HTTP_PORT", "WS_PORT_START") and value and not value.strip().isdigit():
            return error(400, "invalid", f"{key} must be a number.", field=key)
        out[key] = _escape(value.strip()) if value and value.strip() else None
    if "CONFIG_HEADER_LOGO" in values and out["CONFIG_HEADER_LOGO"] is None:
        out["CONFIG_HEADER_LOGO"] = '""'  # Allmon3's way of saying "the AllStarLink logo"
    try:
        f = await _read(request, "web.ini")
    except PrivError as exc:
        return _priv_error(exc)
    if not f["exists"]:
        return error(404, "not_installed", "/etc/allmon3/web.ini is missing. Is Allmon3 installed?")
    return _plan(request, "web.ini", f, conf.set_values(f["content"], "web", out), "Allmon3: web settings")


# ---- users and restrictions ----------------------------------------------------------------


def _user(request: web.Request) -> str:
    user = request.match_info["user"]
    if not USER_RE.match(user):
        raise web.HTTPNotFound(text="No such user")
    return user


async def _write_restriction(request: web.Request, user: str, node_list: list[str] | None) -> list[str]:
    """Change USER's line in user-restrictions; returns the files changed."""
    f = await _read(request, "user-restrictions")
    if not f["exists"]:
        if node_list is None:
            return []
        raise PrivError("/etc/allmon3/user-restrictions is missing. Is Allmon3 installed?", "not_found")
    new = conf.set_restriction(f["content"], user, node_list)
    if new == f["content"]:
        return []
    await _priv(request, "file.write", {"path": conf.path("user-restrictions"), "content": new,
                                        "expected_hash": f["hash"]})
    return [conf.path("user-restrictions")]


@routes.get("/api/v1/allmon3/users")
async def list_users(request: web.Request) -> web.Response:
    try:
        users, restrict, nodes_file = await asyncio.gather(
            _priv(request, "allmon3.users"), _read(request, "user-restrictions"), _read(request, "allmon3.ini"))
    except PrivError as exc:
        return _priv_error(exc)
    limits = conf.restrictions(restrict["content"]) if restrict["exists"] else {}
    return web.json_response({
        "users": [{"name": u, "nodes": limits.get(u)} for u in users["users"]],
        "orphan_restrictions": [u for u in limits if u not in users["users"]],
        "nodes": [n["node"] for n in conf.nodes(nodes_file["content"])],
    })


@routes.post("/api/v1/allmon3/users")
async def set_password(request: web.Request) -> web.Response:
    denied = await _reauth(request)
    if denied is not None:
        return denied
    body = await read_json(request)
    user, password = body.get("user"), body.get("password")
    if not isinstance(user, str) or not USER_RE.match(user) or user == "user":
        return error(400, "invalid", 'A user name may contain letters, numbers, _ . @ and - (and cannot be "user").',
                     field="user")
    if not isinstance(password, str) or len(password) < 8:
        return error(400, "invalid", "The password must have at least 8 characters.", field="password")
    try:
        res = await _priv(request, "allmon3.set_password", {"user": user, "password": password})
    except PrivError as exc:
        return _priv_error(exc)
    action = f"Allmon3: {'add user' if res['created'] else 'set the password of'} {user}"
    warnings = await _restart(request)
    _audit(request, action, "applied", warnings, ["/etc/allmon3/users"])
    return web.json_response({"created": res["created"], "warnings": warnings})


@routes.delete("/api/v1/allmon3/users/{user}")
async def delete_user(request: web.Request) -> web.Response:
    denied = await _reauth(request)
    if denied is not None:
        return denied
    user = _user(request)
    files = ["/etc/allmon3/users"]
    try:
        await _priv(request, "allmon3.delete_user", {"user": user})
        files += await _write_restriction(request, user, None)
    except PrivError as exc:
        return _priv_error(exc)
    warnings = await _restart(request)
    _audit(request, f"Allmon3: remove user {user}", "applied", warnings, files)
    return web.json_response({"warnings": warnings})


@routes.put("/api/v1/allmon3/users/{user}/nodes")
async def set_user_nodes(request: web.Request) -> web.Response:
    denied = await _reauth(request)
    if denied is not None:
        return denied
    user = _user(request)
    body = await read_json(request)
    node_list = body.get("nodes")
    if node_list is not None and (not isinstance(node_list, list) or not node_list
                                  or not all(isinstance(n, str) and n.isdigit() for n in node_list)):
        return error(400, "invalid", "nodes must be a list of node numbers, or null for every node.", field="nodes")
    try:
        files = await _write_restriction(request, user, node_list)
    except PrivError as exc:
        return _priv_error(exc)
    warnings = await _restart(request) if files else []
    if files:
        what = f"nodes {', '.join(node_list)}" if node_list else "every node"
        _audit(request, f"Allmon3: {user} may command {what}", "applied", warnings, files)
    return web.json_response({"warnings": warnings})


def setup(app: web.Application) -> None:
    app[PLANS_KEY] = {}
    app.add_routes(routes)
