"""Manual Config Edit: the raw configuration files, with lint and safe saves.

    GET  /api/v1/config/files                 the main files (FILES) and their status
    GET  /api/v1/config/tree                  every file under /etc/asterisk
    GET  /api/v1/config/system-files          the files in /etc/allmon3, and /etc/sa818.conf
    GET  /api/v1/config/files/{name}          content, hash and findings
    POST /api/v1/config/files/{name}/check    {"content"}  -> findings (no write)
    POST /api/v1/config/files/{name}/plan     {"content", "base_hash"} -> plan
    POST /api/v1/changes/{plan_id}/apply      (modules/changes.py)

{name} is a path relative to /etc/asterisk (custom/rpt/x.conf): one of FILES,
or any existing regular file in the tree. Symbolic links are listed but not
opened, and nothing outside the directory can be named. A file that is not
valid UTF-8, or is larger than MAX_EDIT, is shown but cannot be edited in the
browser. Saving keeps the file's CRLF line endings when it used them.

A top-level .conf file is checked as Asterisk loads it. Any other file is
checked through the top-level files that #include it (the custom/ folder),
keeping the findings that are about it; a file nothing includes is not read
by Asterisk, so it is not checked.
"""

import logging
import os
import pwd
import stat
from dataclasses import dataclass

from aiohttp import web
from aiohttp_session import get_session

from ..configengine.lint import Finding, counts, lint
from ..configengine.model import load
from ..configengine.store import FileChange, Store, digest
from ..configengine.text import ConfigText
from ..security import SETTINGS_KEY, USER_KEY
from .changes import STORE_KEY, error

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
MAX_EDIT = 1 << 20
MAX_TREE = 5000
TEMP_PREFIX = ".asl-web-ui-"  # Store._write's temporary files

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


def _top_level(name: str) -> bool:
    """Asterisk reads this file by name (rather than through an #include)."""
    return "/" not in name and name.endswith(".conf") and name not in NOT_ASTERISK


def includers(config_dir: str) -> dict[str, list[str]]:
    """For each file read through #include: the top-level files that include it."""
    out: dict[str, list[str]] = {}
    try:
        names = sorted(os.listdir(config_dir))
    except OSError:
        return out
    for name in names:
        root = os.path.join(config_dir, name)
        if not _top_level(name) or os.path.islink(root) or not os.path.isfile(root):
            continue
        try:
            cfg = load(name, config_dir=config_dir)
        except OSError:
            continue
        for path in cfg.files:
            if path != root:
                out.setdefault(os.path.relpath(path, config_dir), []).append(name)
    return out


def _findings(config_dir: str, name: str, override: bytes | None = None) -> list[Finding]:
    if name in NOT_ASTERISK:
        return []
    target = os.path.join(config_dir, name)

    def reader(path: str) -> bytes:
        if override is not None and path == target:
            return override
        with open(path, "rb") as f:
            return f.read()

    if _top_level(name):
        return lint(load(name, config_dir=config_dir, reader=reader), config_dir)
    found: list[Finding] = []
    for root in includers(config_dir).get(name, []):
        for f in lint(load(root, config_dir=config_dir, reader=reader), config_dir):
            if f.file == name and f not in found:
                found.append(f)
    return found


def _resolve(config_dir: str, name: str) -> str | None:
    """The path of a file named relative to config_dir, or None when the name
    leaves the directory or passes through a symbolic link."""
    if not name or "\0" in name or name.startswith("/") or len(name) > 512:
        return None
    path = os.path.normpath(os.path.join(config_dir, name))
    if os.path.relpath(path, config_dir) != name:
        return None
    real_dir = os.path.realpath(config_dir)
    if os.path.realpath(path) != os.path.join(real_dir, name):
        return None
    return path


def _name(request: web.Request) -> str:
    name = request.match_info["name"]
    if name in NAMES:
        return name
    config_dir = request.app[SETTINGS_KEY].config_dir
    path = _resolve(config_dir, name)
    if path is None or os.path.basename(name).startswith(TEMP_PREFIX) or not os.path.isfile(path):
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


@routes.get("/api/v1/config/tree")
async def tree(request: web.Request) -> web.Response:
    """Every file under the configuration directory (symbolic links too, not followed)."""
    config_dir = request.app[SETTINGS_KEY].config_dir
    read_by = includers(config_dir)
    out = []
    for root, dirs, files in os.walk(config_dir):
        dirs.sort()
        for name in sorted(files) + sorted(d for d in dirs if os.path.islink(os.path.join(root, d))):
            path = os.path.join(root, name)
            rel = os.path.relpath(path, config_dir)
            if name.startswith(TEMP_PREFIX):
                continue
            try:
                st = os.lstat(path)
            except OSError:
                continue
            entry = {"name": rel, "size": st.st_size, "modified": int(st.st_mtime), "main": rel in NAMES,
                     "owner": None, "writable": False, "link": None,
                     "read_by": ["Asterisk"] if _top_level(rel) else read_by.get(rel, [])}
            if stat.S_ISLNK(st.st_mode):
                entry["link"] = os.readlink(path)
            elif not stat.S_ISREG(st.st_mode):
                continue
            else:
                try:
                    entry["owner"] = pwd.getpwuid(st.st_uid).pw_name
                except KeyError:
                    entry["owner"] = str(st.st_uid)
                entry["writable"] = os.access(path, os.W_OK) and os.access(root, os.W_OK)
            out.append(entry)
            if len(out) >= MAX_TREE:
                return web.json_response({"dir": config_dir, "files": out, "truncated": True})
    return web.json_response({"dir": config_dir, "files": out, "truncated": False})


@routes.get("/api/v1/config/system-files")
async def system_files(request: web.Request) -> web.Response:
    """Allmon3's and the SA818 module's files, which only the privileged helper can read.
    They are opened through modules/allmon3.py and modules/sa818.py."""
    from ..privileged import PRIV_KEY, PrivError

    try:
        res = await request.app[PRIV_KEY].call("file.list", {}, request[USER_KEY])
    except PrivError as exc:
        return error(502 if exc.code == "unavailable" else 500, exc.code, exc.message)
    return web.json_response(res)


@routes.get("/api/v1/config/files/{name:.+}")
async def get_file(request: web.Request) -> web.Response:
    name = _name(request)
    config_dir = request.app[SETTINGS_KEY].config_dir
    info = _info(config_dir, name)
    if info.data is None:
        raise web.HTTPNotFound(text=f"{name} does not exist")
    if len(info.data) > MAX_EDIT:
        return error(413, "too_large", f"{name} is larger than {MAX_EDIT >> 20} MB, too large to open in the browser.")
    findings = _findings(config_dir, name)
    return web.json_response({
        "name": name,
        "path": info.path,
        "content": info.data.decode("utf-8", "replace"),
        "hash": digest(info.data),
        "owner": info.owner,
        "writable": info.writable,
        "utf8": info.utf8,
        "read_by": None if _top_level(name) or name in NOT_ASTERISK else includers(config_dir).get(name, []),
        "findings": [f.as_dict() for f in findings],
    })


@routes.post("/api/v1/config/files/{name:.+}/check")
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


@routes.post("/api/v1/config/files/{name:.+}/plan")
async def plan_file(request: web.Request) -> web.Response:
    name = _name(request)
    body = await _json(request)
    content, base = body.get("content"), body.get("base_hash")
    if not isinstance(content, str) or not isinstance(base, str):
        raise web.HTTPBadRequest(text="content and base_hash are required")
    config_dir = request.app[SETTINGS_KEY].config_dir
    info = _info(config_dir, name)
    if info.data is not None and len(info.data) > MAX_EDIT:
        return error(413, "too_large", f"{name} is too large to edit in the browser.")
    if len(content) > MAX_EDIT:
        return error(413, "too_large", "The new content is too large.")
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
