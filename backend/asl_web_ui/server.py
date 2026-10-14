"""Entry point for the asl-web-ui service.

In production the API socket is created by systemd (asl-web-ui.socket) and
passed in with socket activation. For development, ``--unix PATH`` binds a
socket directly.
"""

import argparse
import asyncio
import logging
import os
import signal
import socket
from pathlib import Path

from aiohttp import web

from . import VERSION, config
from .app import create_app

log = logging.getLogger("asl-web-ui")

SD_LISTEN_FDS_START = 3


def systemd_socket() -> socket.socket | None:
    """Return the socket passed by systemd socket activation, if any."""
    if os.environ.get("LISTEN_PID") != str(os.getpid()):
        return None
    if int(os.environ.get("LISTEN_FDS", "0")) != 1:
        raise SystemExit("asl-web-ui expects exactly one socket from systemd")
    for name in ("LISTEN_PID", "LISTEN_FDS", "LISTEN_FDNAMES"):
        os.environ.pop(name, None)
    return socket.socket(fileno=SD_LISTEN_FDS_START)


async def serve(app: web.Application, sock: socket.socket | None, unix_path: str | None) -> None:
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    if sock is not None:
        site: web.BaseSite = web.SockSite(runner, sock)
    elif unix_path:
        site = web.UnixSite(runner, unix_path)
    else:
        raise SystemExit("No socket: start via systemd or pass --unix PATH")
    await site.start()
    log.info("asl-web-ui %s ready", VERSION)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    log.info("stopping")
    await runner.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(prog="asl-web-ui-server")
    parser.add_argument("--config", type=Path, default=config.DEFAULT_PATH)
    parser.add_argument("--unix", metavar="PATH", help="bind this Unix socket (development)")
    args = parser.parse_args()

    settings = config.load(args.config)
    logging.basicConfig(level=settings.log_level.upper(), format="%(name)s: %(message)s")
    asyncio.run(serve(create_app(settings), systemd_socket(), args.unix))


if __name__ == "__main__":
    main()
