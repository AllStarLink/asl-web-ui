"""Entry point for the asl-web-ui service.

In production the API socket is created by systemd (asl-web-ui.socket) and
passed in with socket activation. For development:

    --unix PATH     bind a Unix socket directly
    --dev           serve the built frontend and the API on 127.0.0.1 with a
                    fake login (user "dev", password "dev"); refuses to run
                    from the installed package or as the asterisk user
"""

import argparse
import asyncio
import dataclasses
import logging
import os
import pwd
import shlex
import shutil
import signal
import socket
from pathlib import Path

from aiohttp import web

from . import VERSION, config
from .app import create_app
from .asterisk_cli import ASTERISK, AsteriskCLI
from .modules import console, status
from .privileged import PRIV_KEY, InProcessClient

log = logging.getLogger("asl-web-ui")

SD_LISTEN_FDS_START = 3
INSTALLED_PREFIX = Path("/usr/share/asl-web-ui")
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def systemd_socket() -> socket.socket | None:
    """Return the socket passed by systemd socket activation, if any."""
    if os.environ.get("LISTEN_PID") != str(os.getpid()):
        return None
    if int(os.environ.get("LISTEN_FDS", "0")) != 1:
        raise SystemExit("asl-web-ui expects exactly one socket from systemd")
    for name in ("LISTEN_PID", "LISTEN_FDS", "LISTEN_FDNAMES"):
        os.environ.pop(name, None)
    return socket.socket(fileno=SD_LISTEN_FDS_START)


def refuse_dev_if_installed() -> None:
    here = Path(__file__).resolve()
    if INSTALLED_PREFIX in here.parents:
        raise SystemExit("--dev is for development checkouts only, not the installed package")
    if pwd.getpwuid(os.getuid()).pw_name == "asterisk":
        raise SystemExit("--dev must not run as the asterisk user")


def dev_root(settings: config.Settings) -> str:
    """A sandbox for the privileged commands in --dev: a copy of the
    configuration under <state>/dev-root, never the real system."""
    root = os.path.join(settings.state_dir, "dev-root")
    etc = os.path.join(root, "etc", "asterisk")
    if not os.path.isdir(etc):
        def unreadable(directory: str, names: list[str]) -> list[str]:
            return [n for n in names if not os.access(os.path.join(directory, n), os.R_OK)]
        shutil.copytree(settings.config_dir, etc, symlinks=True, ignore=unreadable)
    os.makedirs(os.path.join(root, "var", "lib", "asl-web-ui", "staging"), exist_ok=True)
    return root


def dev_app(settings: config.Settings, asterisk_conf: str | None, asterisk_cmd: list[str] | None = None) -> web.Application:
    overrides: dict = {PRIV_KEY: InProcessClient(dev_root(settings))}
    cmd = asterisk_cmd or [ASTERISK]
    extra = cmd[1:] + (["-C", asterisk_conf] if asterisk_conf else [])
    if asterisk_conf or asterisk_cmd:
        overrides[status.CLI_KEY] = AsteriskCLI(binary=cmd[0], extra_args=extra)
        overrides[console.COMMAND_KEY] = [cmd[0], *extra, "-rvvv"]
    app = create_app(settings, overrides=overrides)
    index = FRONTEND_DIST / "index.html"

    async def page(request: web.Request) -> web.FileResponse:
        if not index.exists():
            raise web.HTTPNotFound(text="Build the frontend first: make frontend")
        return web.FileResponse(index)

    app.router.add_get("/", page)
    if FRONTEND_DIST.is_dir():
        app.router.add_static("/", FRONTEND_DIST)
    return app


async def serve(app: web.Application, sock: socket.socket | None, unix_path: str | None, tcp_port: int | None) -> None:
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    if sock is not None:
        site: web.BaseSite = web.SockSite(runner, sock)
    elif unix_path:
        site = web.UnixSite(runner, unix_path)
    elif tcp_port:
        site = web.TCPSite(runner, "127.0.0.1", tcp_port)
    else:
        raise SystemExit("No socket: start via systemd, or pass --unix PATH or --dev")
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
    parser.add_argument("--dev", action="store_true", help="development server with a fake login")
    parser.add_argument("--port", type=int, default=8099, help="--dev: TCP port on 127.0.0.1")
    parser.add_argument("--asterisk-conf", metavar="FILE", help="--dev: asterisk.conf of a private test instance")
    parser.add_argument("--asterisk-cmd", metavar="CMD",
                        help='--dev: how to run asterisk, e.g. "sudo -n /usr/sbin/asterisk" (test machines)')
    parser.add_argument("--state-dir", metavar="DIR", help="--dev: where to keep state (default next to --asterisk-conf)")
    args = parser.parse_args()

    settings = config.load(args.config)
    logging.basicConfig(level=settings.log_level.upper(), format="%(name)s: %(message)s")
    if args.dev:
        refuse_dev_if_installed()
        settings = dataclasses.replace(settings, dev=True, url_prefix="")
        if args.asterisk_conf:
            # Use the test instance's configuration, and keep snapshots next to it.
            etc = os.path.dirname(os.path.abspath(args.asterisk_conf))
            settings = dataclasses.replace(settings, config_dir=etc, state_dir=os.path.join(os.path.dirname(etc), "web-ui-state"))
        if args.state_dir:
            settings = dataclasses.replace(settings, state_dir=os.path.abspath(args.state_dir))
        elif not args.asterisk_conf:
            raise SystemExit("--dev needs --asterisk-conf or --state-dir")
        root = os.path.join(settings.state_dir, "dev-root")
        settings = dataclasses.replace(settings, backup_dir=os.path.join(root, "var", "asl-backups"),
                                       staging_dir=os.path.join(root, "var", "lib", "asl-web-ui", "staging"))
        log.warning("DEVELOPMENT MODE: fake login (dev/dev) on http://127.0.0.1:%d/", args.port)
        cmd = shlex.split(args.asterisk_cmd) if args.asterisk_cmd else None
        asyncio.run(serve(dev_app(settings, args.asterisk_conf, cmd), None, None, args.port))
        return
    asyncio.run(serve(create_app(settings), systemd_socket(), args.unix, None))


if __name__ == "__main__":
    main()
