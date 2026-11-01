"""Host information for the Overview page.

    GET /api/v1/system

"certificate" is the one Apache presents for the name the browser uses
(when it is self-signed, the page warns before it expires), or null.
"""

import asyncio
import platform
import socket
from pathlib import Path

from aiohttp import web

from asl_web_ui_priv import https

from .. import VERSION
from ..security import public_host

routes = web.RouteTableDef()


def os_name(path: Path = Path("/etc/os-release")) -> str:
    try:
        for line in path.read_text().splitlines():
            key, _, value = line.partition("=")
            if key == "PRETTY_NAME":
                return value.strip().strip('"')
    except OSError:
        pass
    return platform.system()


def uptime_seconds(path: Path = Path("/proc/uptime")) -> int | None:
    try:
        return int(float(path.read_text().split()[0]))
    except (OSError, ValueError, IndexError):
        return None


def certificate_summary(name: str | None) -> dict | None:
    info = https.served_certificate(name)
    if not info:
        return None
    return {k: info[k] for k in ("expires", "self_signed", "apple_problems", "names", "ips")}


@routes.get("/api/v1/system")
async def system(request: web.Request) -> web.Response:
    name = https.browser_name(public_host(request))
    try:
        cert = await asyncio.wait_for(asyncio.to_thread(certificate_summary, name), 10)
    except (asyncio.TimeoutError, OSError):
        cert = None
    return web.json_response({
        "hostname": socket.gethostname(),
        "os": os_name(),
        "kernel": platform.release(),
        "uptime": uptime_seconds(),
        "asl_web_ui": VERSION,
        "certificate": cert,
    })


def setup(app: web.Application) -> None:
    app.add_routes(routes)
