"""Host information for the Overview page.

    GET /api/v1/system
"""

import platform
import socket
from pathlib import Path

from aiohttp import web

from .. import VERSION

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


@routes.get("/api/v1/system")
async def system(request: web.Request) -> web.Response:
    return web.json_response({
        "hostname": socket.gethostname(),
        "os": os_name(),
        "kernel": platform.release(),
        "uptime": uptime_seconds(),
        "asl_web_ui": VERSION,
    })


def setup(app: web.Application) -> None:
    app.add_routes(routes)
