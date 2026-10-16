"""Diagnostics: asl-menu's System Diagnostics Menu and the connectivity check.

    GET  /api/v1/diagnostics                       cached connectivity result, node list service, packages
    POST /api/v1/diagnostics/connectivity          run asl-node-auth-check (job, about 30 s)
    POST /api/v1/diagnostics/ping                  ping 8.8.8.8 four times (job)
    POST /api/v1/diagnostics/registration-server   is register.allstarlink.org reachable?
    POST /api/v1/diagnostics/nodelist/restart      restart asl3-update-nodelist.service
    GET  /api/v1/diagnostics/log?lines=N           the last N lines of Asterisk's messages.log
    GET  /api/v1/diagnostics/log/download          the whole log, as a file

Asterisk's version and registrations are on the Asterisk page; starting,
stopping and restarting it are in modules/control.py.
"""

import asyncio
import json
import logging
import os
import re
import socket
import time

import aiohttp
from aiohttp import web

from .. import authcheck
from ..security import SETTINGS_KEY, USER_KEY
from ..systemd import unit_state
from .changes import STORE_KEY, error
from .control import SYSTEMCTL_KEY, systemctl
from .jobs import start as start_job

log = logging.getLogger("asl-web-ui.diagnostics")
routes = web.RouteTableDef()

NODELIST = "asl3-update-nodelist"
REGISTRATION_SERVER = "http://register.allstarlink.org"
PACKAGE_PATTERNS = ["asl-apt-repos", "asl3*", "dahdi*", "allmon3*", "cockpit*", "asl-web-ui"]
AUTHCHECK_KEY = web.AppKey("authcheck_tool", str)
CACHE = "connectivity.json"
MAX_LINES = 10000
MAX_TAIL_BYTES = 8 << 20


def _cache_path(request: web.Request) -> str:
    return os.path.join(request.app[SETTINGS_KEY].state_dir, CACHE)


def cached(state_dir: str) -> dict | None:
    try:
        with open(os.path.join(state_dir, CACHE)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


async def packages() -> list[dict]:
    """Installed AllStarLink packages, as asl-show-version lists them."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "dpkg-query", "--show", "--showformat=${db:Status-Abbrev}\t${binary:Package}\t${Version}\n",
            *PACKAGE_PATTERNS, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), 20)
    except (OSError, asyncio.TimeoutError):
        return []
    rows = []
    for line in out.decode(errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].startswith("ii"):
            rows.append({"name": parts[1], "version": parts[2]})
    return sorted(rows, key=lambda r: r["name"])


async def nodelist_state() -> dict:
    try:
        service = await unit_state(f"{NODELIST}.service")
        timer = await unit_state(f"{NODELIST}.timer")
    except (OSError, asyncio.TimeoutError):
        service, timer = {}, {}
    installed = service.get("LoadState") == "loaded"
    return {"installed": installed, "enabled": service.get("UnitFileState") == "enabled",
            "timer_active": timer.get("ActiveState") == "active", "last_result": service.get("Result")}


@routes.get("/api/v1/diagnostics")
async def overview(request: web.Request) -> web.Response:
    state, pkgs = await asyncio.gather(nodelist_state(), packages())
    return web.json_response({"connectivity": cached(request.app[SETTINGS_KEY].state_dir),
                              "nodelist": state, "packages": pkgs})


@routes.post("/api/v1/diagnostics/connectivity")
async def connectivity(request: web.Request) -> web.Response:
    tool = request.app[AUTHCHECK_KEY]
    if not os.path.exists(tool):
        return error(501, "not_installed", "asl-node-auth-check is not installed (package asl3).")
    path = _cache_path(request)

    async def work(job):
        job.output("Checking the configuration, your public address and each node's registration. "
                   "This takes about 30 seconds…")
        result = await authcheck.run(tool)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(result, f)
        os.replace(tmp, path)
        request.app[STORE_KEY].record(request[USER_KEY], "connectivity check", result["result"], [])
        return result

    return await start_job(request, "Node connectivity check", work)


@routes.post("/api/v1/diagnostics/ping")
async def ping(request: web.Request) -> web.Response:
    async def work(job):
        proc = await asyncio.create_subprocess_exec("ping", "-c", "4", "-W", "3", "8.8.8.8",
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        assert proc.stdout is not None
        while line := await proc.stdout.readline():
            job.output(line.decode(errors="replace").rstrip())
        code = await proc.wait()
        return {"ok": code == 0}

    return await start_job(request, "Ping 8.8.8.8 (Google DNS)", work)


@routes.post("/api/v1/diagnostics/registration-server")
async def registration_server(request: web.Request) -> web.Response:
    """asl-menu's "Check registration server" (wget --spider, 5 s)."""
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10, connect=5)) as http:
            async with http.get(REGISTRATION_SERVER) as resp:
                ok = resp.status < 400
                return web.json_response({"available": ok, "status": resp.status,
                                          "message": "The AllStarLink registration server is available." if ok else
                                          f"The registration server answered with HTTP {resp.status}."})
    except (aiohttp.ClientError, TimeoutError) as exc:
        return web.json_response({"available": False, "status": None,
                                  "message": f"The AllStarLink registration server is not reachable: {exc}"})


@routes.post("/api/v1/diagnostics/nodelist/restart")
async def restart_nodelist(request: web.Request) -> web.Response:
    if request.app[SETTINGS_KEY].dev:
        return error(501, "dev_mode", "Development mode does not touch the system's services.")
    code, output = await systemctl(request.app[SYSTEMCTL_KEY], "restart", f"{NODELIST}.service", timeout=120)
    request.app[STORE_KEY].record(request[USER_KEY], "restart node list service", "done" if code == 0 else "failed",
                                  [output[-200:]] if code else [])
    if code != 0:
        return error(500, "failed", f"The node list service could not be restarted: {output[-300:]}")
    return web.json_response({"done": True, "state": await nodelist_state()})


# ---- Asterisk's log ----------------------------------------------------------------------


def tail(path: str, lines: int) -> tuple[str, bool]:
    """The last ``lines`` lines of a file (at most MAX_TAIL_BYTES of them), and
    whether the file has more before them."""
    block = 64 << 10
    with open(path, "rb") as f:
        end = f.seek(0, os.SEEK_END)
        pos, data = end, b""
        # One newline more than wanted, as the file normally ends with one.
        while pos > 0 and data.count(b"\n") <= lines and end - pos < MAX_TAIL_BYTES:
            step = min(block, pos)
            pos -= step
            f.seek(pos)
            data = f.read(step) + data
    parts = data.splitlines(keepends=True)
    if pos > 0:
        parts = parts[1:]  # it starts in the middle of a line
    return b"".join(parts[-lines:]).decode("utf-8", "replace"), pos > 0 or len(parts) > lines


@routes.get("/api/v1/diagnostics/log")
async def log_tail(request: web.Request) -> web.Response:
    path = request.app[SETTINGS_KEY].asterisk_log
    try:
        lines = int(request.query.get("lines", "200"))
    except ValueError:
        return error(400, "invalid", "lines must be a number.")
    lines = max(1, min(lines, MAX_LINES))
    try:
        st = os.stat(path)
        text, more = await asyncio.to_thread(tail, path, lines)
    except FileNotFoundError:
        return web.json_response({"path": path, "exists": False})
    except OSError as exc:
        return error(500, "unreadable", f"Cannot read {path}: {exc.strerror}")
    return web.json_response({"path": path, "exists": True, "size": st.st_size, "modified": int(st.st_mtime),
                              "lines": lines, "text": text, "more": more})


@routes.get("/api/v1/diagnostics/log/download")
async def log_download(request: web.Request) -> web.StreamResponse:
    path = request.app[SETTINGS_KEY].asterisk_log
    if not os.path.isfile(path):
        raise web.HTTPNotFound(text=f"{path} does not exist")
    if not os.access(path, os.R_OK):
        raise web.HTTPForbidden(text=f"Cannot read {path}")
    stem, ext = os.path.splitext(os.path.basename(path))
    host = re.sub(r"[^A-Za-z0-9.-]", "", socket.gethostname()) or "asl"
    name = f"{stem}-{host}-{time.strftime('%Y%m%d-%H%M')}{ext}"
    request.app[STORE_KEY].record(request[USER_KEY], "download Asterisk log", "done", [path])
    return web.FileResponse(path, headers={"Content-Disposition": f'attachment; filename="{name}"',
                                           "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"})


def setup(app: web.Application) -> None:
    if AUTHCHECK_KEY not in app:
        app[AUTHCHECK_KEY] = authcheck.TOOL
    app.add_routes(routes)
