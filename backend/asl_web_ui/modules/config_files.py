"""Manual Config Edit: the raw configuration files, with lint and safe saves.

    GET  /api/v1/config/files                 the editable files and their status
    GET  /api/v1/config/files/{name}          content, hash and findings
    POST /api/v1/config/files/{name}/check    {"content"}  -> findings (no write)
    POST /api/v1/config/files/{name}/plan     {"content", "base_hash"} -> plan
    POST /api/v1/changes/{plan_id}/apply      (modules/changes.py)

Only the files listed in FILES can be named. A file that is not valid UTF-8
is shown but cannot be edited in the browser (the editor would change its
bytes). Saving keeps the file's CRLF line endings when it used them.
"""

import logging
import os
import pwd
from dataclasses import dataclass

from aiohttp import web
from aiohttp_session import get_session

from ..configengine.lint import Finding, counts, lint
from ..configengine.model import load
from ..configengine.store import FileChange, Store, digest
from ..configengine.text import ConfigText
from ..security import SETTINGS_KEY, USER_KEY
from .changes import STORE_KEY

log = logging.getLogger("asl-web-ui.config")

FILES = [
    ("rpt.conf", "Nodes, telemetry, functions and macros (app_rpt)"),
    ("rpt_http_registrations.conf", "Registration with AllStarLink"),
    ("iax.conf", "IAX2: listening port and node-to-node connections"),
    ("extensions.conf", "Dialplan"),
    ("modules.conf", "Which Asterisk modules are loaded"),
    ("manager.conf", "Asterisk Manager Interface (AMI) accounts"),
    ("echolink.conf", "EchoLink"),
    ("usbradio.conf", "USBRadio interfaces"),
    ("simpleusb.conf", "SimpleUSB interfaces"),
    ("voter.conf", "RTCM / voter clients"),
    ("savenode.conf", "Credentials for AllStarLink cloud backups"),
]
NAMES = {name for name, _ in FILES}
# Not read by Asterisk (shell syntax, used by the backup tools): no Asterisk lint.
NOT_ASTERISK = {"savenode.conf"}

routes = web.RouteTableDef()


@dataclass
class FileInfo:
    name: str
    path: str
    data: bytes | None
    owner: str | None
    writable: bool
    utf8: bool


def _info(config_dir: str, name: str) -> FileInfo:
    path = os.path.join(config_dir, name)
    data = Store.read(path)
    owner = None
    writable = False
    if data is not None:
        st = os.stat(path)
        try:
            owner = pwd.getpwuid(st.st_uid).pw_name
        except KeyError:
            owner = str(st.st_uid)
        writable = os.access(path, os.W_OK) and os.access(config_dir, os.W_OK)
    try:
        (data or b"").decode("utf-8")
        utf8 = True
    except UnicodeDecodeError:
        utf8 = False
    return FileInfo(name, path, data, owner, writable, utf8)


def _findings(config_dir: str, name: str, override: bytes | None = None) -> list[Finding]:
    if name in NOT_ASTERISK:
        return []
    target = os.path.join(config_dir, name)

    def reader(path: str) -> bytes:
        if override is not None and path == target:
            return override
        with open(path, "rb") as f:
            return f.read()

    return lint(load(name, config_dir=config_dir, reader=reader), config_dir)


def _name(request: web.Request) -> str:
    name = request.match_info["name"]
    if name not in NAMES:
        raise web.HTTPNotFound(text=f"Unknown configuration file: {name}")
    return name


async def _json(request: web.Request) -> dict:
    try:
        body = await request.json()
    except ValueError:
        raise web.HTTPBadRequest(text="Invalid JSON")
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="Expected a JSON object")
    return body


def _restore_newlines(original: bytes | None, new_text: str) -> bytes:
    """The editor normalizes line endings to \\n; keep a CRLF file CRLF."""
    if original is not None and ConfigText(original).newline == "\r\n":
        new_text = new_text.replace("\r\n", "\n").replace("\n", "\r\n")
    return new_text.encode("utf-8")


@routes.get("/api/v1/config/files")
async def list_files(request: web.Request) -> web.Response:
    config_dir = request.app[SETTINGS_KEY].config_dir
    out = []
    for name, purpose in FILES:
        info = _info(config_dir, name)
        entry = {"name": name, "purpose": purpose, "exists": info.data is not None, "owner": info.owner,
                 "writable": info.writable, "utf8": info.utf8, "counts": None, "modified": None}
        if info.data is not None:
            entry["modified"] = int(os.stat(info.path).st_mtime)
            entry["counts"] = counts(_findings(config_dir, name))
        out.append(entry)
    return web.json_response({"files": out})


@routes.get("/api/v1/config/files/{name}")
async def get_file(request: web.Request) -> web.Response:
    name = _name(request)
    config_dir = request.app[SETTINGS_KEY].config_dir
    info = _info(config_dir, name)
    if info.data is None:
        raise web.HTTPNotFound(text=f"{name} does not exist")
    return web.json_response({
        "name": name,
        "content": info.data.decode("utf-8", "replace"),
        "hash": digest(info.data),
        "owner": info.owner,
        "writable": info.writable,
        "utf8": info.utf8,
        "findings": [f.as_dict() for f in _findings(config_dir, name)],
    })


@routes.post("/api/v1/config/files/{name}/check")
async def check_file(request: web.Request) -> web.Response:
    name = _name(request)
    body = await _json(request)
    content = body.get("content")
    if not isinstance(content, str):
        raise web.HTTPBadRequest(text="content must be a string")
    config_dir = request.app[SETTINGS_KEY].config_dir
    original = Store.read(os.path.join(config_dir, name))
    findings = _findings(config_dir, name, _restore_newlines(original, content))
    return web.json_response({"findings": [f.as_dict() for f in findings], "counts": counts(findings)})


@routes.post("/api/v1/config/files/{name}/plan")
async def plan_file(request: web.Request) -> web.Response:
    name = _name(request)
    body = await _json(request)
    content, base = body.get("content"), body.get("base_hash")
    if not isinstance(content, str) or not isinstance(base, str):
        raise web.HTTPBadRequest(text="content and base_hash are required")
    config_dir = request.app[SETTINGS_KEY].config_dir
    info = _info(config_dir, name)
    if not info.utf8:
        raise web.HTTPForbidden(text=f"{name} is not valid UTF-8 and cannot be edited in the browser")
    if info.data is not None and not info.writable:
        return web.json_response({"error": "not_writable", "message":
            f"{name} is owned by {info.owner}, so the web interface cannot change it.",
            "files": [info.path]}, status=409)
    new = _restore_newlines(info.data, content)
    session = await get_session(request)
    store = request.app[STORE_KEY]
    plan = store.plan(session.identity or "", request[USER_KEY], f"edit {name}", [FileChange(info.path, base, new)])
    findings = _findings(config_dir, name, new)
    plan.errors = counts(findings)["error"]
    return web.json_response({
        "id": plan.id,
        "diff": plan.changes[0].diff(name),
        "unchanged": new == info.data,
        "stale": digest(info.data) != base,
        "findings": [f.as_dict() for f in findings],
        "counts": counts(findings),
    })


@routes.post("/api/v1/config/fix-ownership")
async def fix_ownership(request: web.Request) -> web.Response:
    """Give files back to the asterisk user (after editing them with sudo)."""
    from ..privileged import PRIV_KEY, PrivError
    from .auth import recently_authenticated
    from .changes import error

    body = await _json(request)
    files = body.get("files")
    if not isinstance(files, list) or not files or not all(isinstance(f, str) for f in files) or len(files) > 50:
        return error(400, "invalid", "files must be a list of paths inside /etc/asterisk.")
    session = await get_session(request)
    if not recently_authenticated(session, request.app[SETTINGS_KEY]):
        return error(403, "reauth_required", "Enter your password again to fix file ownership.")
    config_dir = request.app[SETTINGS_KEY].config_dir
    fixed = []
    for name in files:
        rel = os.path.relpath(name, config_dir) if name.startswith("/") else name
        try:
            await request.app[PRIV_KEY].call("asterisk.fix_ownership", {"path": rel}, request[USER_KEY])
        except PrivError as exc:
            return error(502 if exc.code == "unavailable" else 400, exc.code, f"{rel}: {exc.message}", fixed=fixed)
        fixed.append(rel)
    request.app[STORE_KEY].record(request[USER_KEY], "fix file ownership", "done", fixed)
    log.info("%s: fixed ownership of %s", request[USER_KEY], " ".join(fixed))
    return web.json_response({"fixed": fixed})


def setup(app: web.Application) -> None:
    app.add_routes(routes)
