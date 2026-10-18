"""Backups: asl-backup-menu's functions, through the privileged helper.

    GET    /api/v1/backups                               local archives, cloud settings
                                                         (cloud.sync: a node whose registration
                                                         password savenode.conf could take; the
                                                         change is planned with nodes/plan "savenode")
    POST   /api/v1/backups                {"upload"}     create (job), optionally upload
    GET    /api/v1/backups/local/{name}/contents          what a restore would write
    POST   /api/v1/backups/local/{name}/restore           restore (job; password re-entry)
    POST   /api/v1/backups/local/{name}/upload            copy to the AllStarLink server (job)
    GET    /api/v1/backups/local/{name}/download
    DELETE /api/v1/backups/local/{name}
    POST   /api/v1/backups/import         (multipart "file")   add an archive from this computer
    POST   /api/v1/backups/cloud/list     {"node", "password"} (optional; savenode.conf otherwise)
    POST   /api/v1/backups/cloud/fetch    {"name", "restore", "node", "password"}  (job)
    GET    /api/v1/backups/include-list
    PUT    /api/v1/backups/include-list   {"content", "hash"}
    POST   /api/v1/backups/factory-reset  (job; password re-entry)

Archives live in /var/asl-backups like asl-backup-menu's, so both tools see
the same backups. The AllStarLink backup server is used as asl-backup-menu
uses it: HTTP basic authentication with the node number and password from
savenode.conf, savenode.cgi to upload, getfile.cgi?NAME to download, and
the server's index page listing the node's archives.
"""

import logging
import os
import re
import secrets
from urllib.parse import quote

import aiohttp
from aiohttp import web
from aiohttp_session import get_session

from ..configengine.edit import Workspace
from ..nodes import savenode
from ..nodes.info import PRIVATE_LIMIT, node_numbers, registration_passwords
from ..privileged import PRIV_KEY, PrivError
from ..security import SETTINGS_KEY, USER_KEY
from .auth import recently_authenticated
from .changes import STORE_KEY, error, read_json
from .jobs import start as start_job

log = logging.getLogger("asl-web-ui.backups")
routes = web.RouteTableDef()

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,100}\.tgz$")
CLOUD_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$")
CLOUD_LINK_RE = re.compile(r"""<a [^>]*href=["']getfile\.cgi\?([^"']+)["']""", re.I)
CLOUD_MAX = 2_000_000  # asl-backup-menu's BACKUP_MAXSIZE for the AllStarLink server
UPLOAD_MAX = 64 << 20
CLOUD_TIMEOUT = aiohttp.ClientTimeout(total=90, connect=30)


class CloudError(Exception):
    def __init__(self, message: str, code: str = "cloud"):
        super().__init__(message)
        self.message = message
        self.code = code


def _settings(request: web.Request):
    return request.app[SETTINGS_KEY]


def _name(request: web.Request) -> str:
    name = request.match_info["name"]
    if not NAME_RE.match(name):
        raise web.HTTPNotFound(text="No such backup")
    return name


def _priv_error(exc: PrivError) -> web.Response:
    status = {"not_found": 404, "invalid": 400, "conflict": 409, "denied": 403, "unavailable": 503,
              "dev_mode": 501}.get(exc.code, 500)
    return error(status, exc.code, exc.message)


async def _priv(request: web.Request, command: str, args: dict | None = None, on_output=None) -> dict:
    return await request.app[PRIV_KEY].call(command, args or {}, request[USER_KEY], on_output)


def _audit(request: web.Request, action: str, result: str, detail: list[str]) -> None:
    request.app[STORE_KEY].record(request[USER_KEY], action, result, detail)
    log.info("%s: %s (%s) %s", request[USER_KEY], action, result, " ".join(detail))


async def _reauth(request: web.Request) -> web.Response | None:
    session = await get_session(request)
    if not recently_authenticated(session, _settings(request)):
        return error(403, "reauth_required", "Enter your password again to continue.")
    return None


def local_backups(backup_dir: str) -> list[dict]:
    out = []
    try:
        names = os.listdir(backup_dir)
    except OSError:
        return []
    for name in names:
        if not NAME_RE.match(name):
            continue
        try:
            st = os.lstat(os.path.join(backup_dir, name))
        except OSError:
            continue
        out.append({"name": name, "size": st.st_size, "modified": int(st.st_mtime)})
    return sorted(out, key=lambda b: b["modified"], reverse=True)


# ---- the AllStarLink backup server -------------------------------------------------------


def cloud_credentials(config_dir: str, body: dict | None = None) -> tuple[str, str]:
    """Node and password: given in the request, or from savenode.conf (asl-backup-menu's checks)."""
    node = (body or {}).get("node")
    password = (body or {}).get("password")
    if node or password:
        if not isinstance(node, str) or not re.fullmatch(r"[0-9]{4,6}", node) or int(node) < 2000 \
                or node.startswith("1"):
            raise CloudError("Enter a registered node number (2000 or higher, not starting with 1).", "invalid")
        if not isinstance(password, str) or not re.fullmatch(r"[0-9a-zA-Z_-]{6,}", password):
            raise CloudError("Enter the node's password.", "invalid")
        return node, password
    save = savenode.read(Workspace(config_dir))
    node, password, enable = save.get("NODE", ""), save.get("PASSWORD", ""), save.get("ENABLE", "0")
    if enable in ("", "0") or not node or not password:
        raise CloudError("No node is set up for AllStarLink backups yet (savenode.conf). Set a public node's "
                         "password, or enter a node number and password.", "not_configured")
    if not node.isdigit() or int(node) < 2000 or node.startswith("1"):
        raise CloudError("Backups to AllStarLink need a registered node number (2000 or higher, not starting "
                         "with 1).", "not_configured")
    return node, password


def sync_candidate(config_dir: str) -> str | None:
    """The public node whose registration password savenode.conf lacks: the
    node it names, or else the first registered one. None when they agree."""
    ws = Workspace(config_dir)
    try:
        registered = []
        for number in node_numbers(ws.model("rpt.conf")):
            passwords = registration_passwords(ws, number)
            if int(number) >= PRIVATE_LIMIT and (passwords["http"] or passwords["iax"]):
                registered.append((number, passwords["http"] | passwords["iax"]))
    except (OSError, ValueError):
        return None
    save = savenode.read(ws)
    for number, passwords in registered:
        if number == save.get("NODE"):
            in_step = save.get("PASSWORD") in passwords and save.get("ENABLE", "0") not in ("", "0")
            return None if in_step else number
    return registered[0][0] if registered else None


async def _cloud(method: str, url: str, node: str, password: str, data: bytes | None = None) -> bytes:
    auth = aiohttp.BasicAuth(node, password)
    headers = {"Content-Type": "application/x-www-form-urlencoded"} if data is not None else {}
    try:
        async with aiohttp.ClientSession(timeout=CLOUD_TIMEOUT) as http:
            async with http.request(method, url, auth=auth, data=data, headers=headers) as resp:
                if resp.status in (401, 403):
                    raise CloudError(f"The AllStarLink backup server did not accept the password for node {node}.",
                                     "cloud_auth")
                if resp.status >= 400:
                    raise CloudError(f"The AllStarLink backup server answered with HTTP {resp.status}.")
                return await resp.read()
    except aiohttp.ClientError as exc:
        raise CloudError(f"Could not reach the AllStarLink backup server: {exc}")
    except TimeoutError:
        raise CloudError("The AllStarLink backup server did not answer in time.")


async def cloud_list(server: str, node: str, password: str) -> list[str]:
    page = (await _cloud("GET", server.rstrip("/") + "/", node, password)).decode("utf-8", "replace")
    return [n for n in dict.fromkeys(CLOUD_LINK_RE.findall(page)) if CLOUD_NAME_RE.match(n)]


def local_name_for(cloud_name: str) -> str:
    """asl-backup-menu's mapping: 20261014213000.tgz -> ASL_2026-10-14_213000.tgz."""
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})(\d{6})\.tgz", cloud_name)
    if m:
        return f"ASL_{m.group(1)}-{m.group(2)}-{m.group(3)}_{m.group(4)}.tgz"
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", cloud_name).removesuffix(".tgz")
    return f"ASL_cloud_{safe}.tgz"


async def cloud_upload(server: str, node: str, password: str, data: bytes) -> None:
    if len(data) > CLOUD_MAX:
        raise CloudError(f"The backup is too large for the AllStarLink backup server ({len(data)} bytes; "
                         f"the limit is {CLOUD_MAX}).", "too_large")
    await _cloud("POST", server.rstrip("/") + "/savenode.cgi", node, password, data)


# ---- routes ----------------------------------------------------------------------------------


@routes.get("/api/v1/backups")
async def list_backups(request: web.Request) -> web.Response:
    settings = _settings(request)
    try:
        node, _ = cloud_credentials(settings.config_dir)
        cloud = {"configured": True, "node": node, "reason": None}
    except CloudError as exc:
        cloud = {"configured": False, "node": None, "reason": exc.message}
    cloud["sync"] = sync_candidate(settings.config_dir)
    return web.json_response({"local": local_backups(settings.backup_dir), "cloud": cloud,
                              "cloud_max": CLOUD_MAX, "server": settings.backup_server,
                              "directory": "/var/asl-backups"})


@routes.post("/api/v1/backups")
async def create_backup(request: web.Request) -> web.Response:
    body = await read_json(request)
    upload = body.get("upload") is True
    settings = _settings(request)

    async def work(job):
        job.output("Creating the backup…")
        made = await _priv(request, "backup.create")
        job.output(f"Created {made['name']} ({made['size']} bytes).")
        _audit(request, "create backup", "done", [made["name"]])
        if upload:
            node, password = cloud_credentials(settings.config_dir)
            job.output(f"Copying it to the AllStarLink backup server as node {node}…")
            with open(os.path.join(settings.backup_dir, made["name"]), "rb") as f:
                await cloud_upload(settings.backup_server, node, password, f.read())
            job.output("Copied to the AllStarLink backup server.")
            _audit(request, "upload backup", "done", [made["name"]])
        return {"name": made["name"], "uploaded": upload}

    return await start_job(request, "Create backup", work)


@routes.get("/api/v1/backups/local/{name}/contents")
async def contents(request: web.Request) -> web.Response:
    try:
        return web.json_response(await _priv(request, "backup.read", {"name": _name(request)}))
    except PrivError as exc:
        return _priv_error(exc)


@routes.post("/api/v1/backups/local/{name}/restore")
async def restore(request: web.Request) -> web.Response:
    name = _name(request)
    denied = await _reauth(request)
    if denied is not None:
        return denied

    async def work(job):
        job.output(f"Restoring {name}…")
        res = await _priv(request, "backup.restore", {"name": name})
        job.output(f"Wrote {res['written']} files. The previous configuration is saved as {res['before']}.")
        for s in res["skipped"]:
            job.output(f"Skipped {s['name']}: {s['reason']}")
        _audit(request, "restore backup", "done", [name, f"before={res['before']}"])
        return res

    return await start_job(request, f"Restore {name}", work)


@routes.post("/api/v1/backups/local/{name}/upload")
async def upload(request: web.Request) -> web.Response:
    name = _name(request)
    settings = _settings(request)
    path = os.path.join(settings.backup_dir, name)
    if not os.path.isfile(path):
        raise web.HTTPNotFound(text="No such backup")

    async def work(job):
        node, password = cloud_credentials(settings.config_dir)
        job.output(f"Copying {name} to the AllStarLink backup server as node {node}…")
        with open(path, "rb") as f:
            await cloud_upload(settings.backup_server, node, password, f.read())
        job.output("Done.")
        _audit(request, "upload backup", "done", [name])
        return {"name": name}

    return await start_job(request, f"Copy {name} to AllStarLink", work)


@routes.get("/api/v1/backups/local/{name}/download")
async def download(request: web.Request) -> web.StreamResponse:
    name = _name(request)
    path = os.path.join(_settings(request).backup_dir, name)
    if not os.path.isfile(path) or os.path.islink(path):
        raise web.HTTPNotFound(text="No such backup")
    _audit(request, "download backup", "done", [name])
    return web.FileResponse(path, headers={"Content-Disposition": f'attachment; filename="{name}"',
                                           "Content-Type": "application/gzip", "Cache-Control": "no-store"})


@routes.delete("/api/v1/backups/local/{name}")
async def delete(request: web.Request) -> web.Response:
    name = _name(request)
    try:
        await _priv(request, "backup.delete", {"name": name})
    except PrivError as exc:
        return _priv_error(exc)
    _audit(request, "delete backup", "done", [name])
    return web.json_response({"deleted": name})


def _stage(settings, data: bytes) -> str:
    os.makedirs(settings.staging_dir, mode=0o700, exist_ok=True)
    staged = secrets.token_hex(8)
    with open(os.path.join(settings.staging_dir, staged), "wb") as f:
        f.write(data)
    return staged


def _unstage(settings, staged: str) -> None:
    try:
        os.unlink(os.path.join(settings.staging_dir, staged))
    except FileNotFoundError:
        pass


@routes.post("/api/v1/backups/import")
async def import_backup(request: web.Request) -> web.Response:
    settings = _settings(request)
    reader = await request.multipart()
    part = await reader.next()
    if part is None or getattr(part, "name", None) != "file":
        return error(400, "invalid", "Send the archive as the form field \"file\".")
    data = bytearray()
    while chunk := await part.read_chunk(1 << 16):
        data += chunk
        if len(data) > UPLOAD_MAX:
            return error(413, "too_large", "The file is too large to be a backup.")
    filename = os.path.basename(getattr(part, "filename", "") or "upload.tgz")
    name = filename if NAME_RE.match(filename) else "ASL_uploaded.tgz"
    staged = _stage(settings, bytes(data))
    try:
        res = await _priv(request, "backup.import", {"staged": staged, "name": name})
    except PrivError as exc:
        _unstage(settings, staged)
        return _priv_error(exc)
    _audit(request, "import backup", "done", [res["name"]])
    return web.json_response(res)


@routes.post("/api/v1/backups/cloud/list")
async def list_cloud(request: web.Request) -> web.Response:
    body = await read_json(request)
    settings = _settings(request)
    try:
        node, password = cloud_credentials(settings.config_dir, body)
        names = await cloud_list(settings.backup_server, node, password)
    except CloudError as exc:
        return error(400 if exc.code == "invalid" else 409 if exc.code == "not_configured" else 502,
                     exc.code, exc.message)
    return web.json_response({"node": node, "backups": names})


@routes.post("/api/v1/backups/cloud/fetch")
async def fetch_cloud(request: web.Request) -> web.Response:
    body = await read_json(request)
    settings = _settings(request)
    name = body.get("name")
    if not isinstance(name, str) or not CLOUD_NAME_RE.match(name):
        return error(400, "invalid", "Choose a backup.")
    then_restore = body.get("restore") is True
    if then_restore:
        denied = await _reauth(request)
        if denied is not None:
            return denied
    try:
        node, password = cloud_credentials(settings.config_dir, body)
    except CloudError as exc:
        return error(400, exc.code, exc.message)

    async def work(job):
        job.output(f"Downloading {name} from the AllStarLink backup server…")
        data = await _cloud("GET", settings.backup_server.rstrip("/") + "/getfile.cgi?" + quote(name, safe=".-_"),
                            node, password)
        staged = _stage(settings, data)
        try:
            res = await _priv(request, "backup.import", {"staged": staged, "name": local_name_for(name)})
        except PrivError:
            _unstage(settings, staged)
            raise
        job.output(f"Saved as {res['name']} on this server.")
        _audit(request, "download backup from AllStarLink", "done", [name, res["name"]])
        out = {"name": res["name"]}
        if then_restore:
            job.output(f"Restoring {res['name']}…")
            restored = await _priv(request, "backup.restore", {"name": res["name"]})
            job.output(f"Wrote {restored['written']} files. The previous configuration is saved as "
                       f"{restored['before']}.")
            _audit(request, "restore backup", "done", [res["name"], f"before={restored['before']}"])
            out["restored"] = restored
        return out

    return await start_job(request, f"Get {name} from AllStarLink", work)


@routes.get("/api/v1/backups/include-list")
async def get_include_list(request: web.Request) -> web.Response:
    try:
        return web.json_response(await _priv(request, "backup.read_include_list"))
    except PrivError as exc:
        return _priv_error(exc)


@routes.put("/api/v1/backups/include-list")
async def put_include_list(request: web.Request) -> web.Response:
    body = await read_json(request)
    content, expected = body.get("content"), body.get("hash")
    if not isinstance(content, str) or not isinstance(expected, str):
        return error(400, "invalid", "content and hash are required.")
    try:
        res = await _priv(request, "backup.write_include_list", {"content": content, "expected_hash": expected})
    except PrivError as exc:
        return _priv_error(exc)
    _audit(request, "change backup include list", "done", [])
    return web.json_response(res)


@routes.post("/api/v1/backups/factory-reset")
async def factory_reset(request: web.Request) -> web.Response:
    denied = await _reauth(request)
    if denied is not None:
        return denied

    async def work(job):
        res = await _priv(request, "factory.restore", {}, on_output=job.output)
        _audit(request, "restore default configuration", "done", [f"before={res['before']}"])
        return res

    return await start_job(request, "Restore the default configuration", work)


def setup(app: web.Application) -> None:
    app.add_routes(routes)
