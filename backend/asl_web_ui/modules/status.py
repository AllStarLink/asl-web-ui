"""Live status: one shared poller, pushed to every open page.

    GET /api/v1/status         latest snapshot
    GET /api/v1/ws/events      WebSocket: {"type": "status", "data": snapshot}

The poller runs only while at least one page is connected. Each round asks
Asterisk only for its uptime; the node list is fetched again after a restart
or reload. Registrations cost two more CLI commands, so they are collected
only while a page that shows them asks for the "registrations" topic: as
?topics=registrations on the socket URL, or later with a text frame
{"type": "subscribe", "topics": [...]}. Otherwise the last ones collected are
sent again.

Open pages do not keep a session alive: each push re-checks the session, and
the socket closes (code 4401) once the session has ended.
"""

import asyncio
import contextlib
import json
import logging
import time
from dataclasses import asdict

from aiohttp import WSMsgType, web
from aiohttp_session import get_session

from .. import restart, systemd
from ..asterisk_cli import (
    AsteriskCLI,
    AsteriskUnavailable,
    parse_core_version,
    parse_iax_registry,
    parse_localnodes,
    parse_rpt_registrations,
    parse_rpt_version,
    parse_uptime_seconds,
)
from ..security import SETTINGS_KEY, is_group_member
from .auth import STORAGE_KEY

log = logging.getLogger("asl-web-ui.status")

CLI_KEY = web.AppKey("asterisk_cli", AsteriskCLI)
INTERVAL = 5.0
CLOSE_SESSION_ENDED = 4401
TOPICS = frozenset({"registrations"})
NODES_MAX_AGE = 60.0  # fetch the node list at least this often, even without a reload


class StatusHub:
    def __init__(self, cli: AsteriskCLI, unit_state=systemd.unit_state, interval: float = INTERVAL,
                 config_dir: str = "/etc/asterisk", state_dir: str | None = None):
        self.cli = cli
        self.config_dir = config_dir
        self.state_dir = state_dir
        self.rpt_lint = restart.RptLintCache(config_dir)
        self.unit_state = unit_state
        self.interval = interval
        self.latest: dict | None = None
        self._latest_at = 0.0
        self._latest_has_registrations = False
        self._clients: dict[web.WebSocketResponse, tuple[str, str]] = {}
        self._topics: dict[web.WebSocketResponse, frozenset[str]] = {}
        self._task: asyncio.Task | None = None
        self._versions: dict[str, str | None] = {}
        # (started, reloaded, fetched at, nodes) from the last 'rpt localnodes'
        self._nodes: tuple[float, float | None, float, list[str]] | None = None
        self._registrations: tuple[list[dict], list[dict]] = ([], [])
        self._lock = asyncio.Lock()

    @property
    def wants_registrations(self) -> bool:
        return any("registrations" in t for t in self._topics.values())

    async def _localnodes(self, uptime: int | None, reload: int | None) -> list[str]:
        """'rpt localnodes', run again only after a restart or reload, or once NODES_MAX_AGE has passed."""
        now, mono = time.time(), time.monotonic()
        started = None if uptime is None else now - uptime
        reloaded = None if reload is None else now - reload
        if self._nodes and started is not None:
            was_started, was_reloaded, fetched, nodes = self._nodes
            same_reload = (reloaded is None) == (was_reloaded is None) and (
                reloaded is None or abs(reloaded - was_reloaded) <= 2)
            if abs(started - was_started) <= 2 and same_reload and mono - fetched < NODES_MAX_AGE:
                return nodes
        nodes = parse_localnodes(await self.cli.run("rpt localnodes"))
        self._nodes = None if started is None else (started, reloaded, mono, nodes)
        return nodes

    async def collect(self, registrations: bool = False) -> dict:
        svc = await self.unit_state("asterisk.service")
        running = svc.get("ActiveState") == "active"
        data: dict = {
            "collected_at": int(time.time()),
            "asterisk": {
                "state": svc.get("ActiveState", "unknown"),
                "substate": svc.get("SubState", ""),
                "since": svc.get("ActiveEnterTimestamp", ""),
                "reachable": False,
                "uptime": None,
                "last_reload": None,
            },
            "versions": self._versions,
            "nodes": [],
            "registrations": [],
            "iax_registrations": [],
            "error": None,
            # Restart pending (files changed since Asterisk started) and
            # whether rpt.conf currently has errors (restart/reload warnings).
            "config": {"changed": [], "rpt_errors": 0, "rpt_first_error": None},
        }
        try:
            rpt = await asyncio.to_thread(self.rpt_lint.get)
            data["config"].update(rpt_errors=rpt["errors"], rpt_first_error=rpt["first_error"])
        except OSError:
            pass
        if not running:
            self._forget()
            return data
        try:
            up, reload = parse_uptime_seconds(await self.cli.run("core show uptime seconds"))
            nodes = await self._localnodes(up, reload)
            if registrations:
                regs, iax = await asyncio.gather(self.cli.run("rpt show registrations"),
                                                 self.cli.run("iax2 show registry"))
                self._registrations = ([asdict(r) for r in parse_rpt_registrations(regs)],
                                       [asdict(r) for r in parse_iax_registry(iax)])
            if not self._versions:
                core, rpt = await asyncio.gather(self.cli.run("core show version"), self.cli.run("rpt show version"))
                self._versions = {"asterisk": parse_core_version(core), "app_rpt": parse_rpt_version(rpt)}
        except AsteriskUnavailable as exc:
            self._forget()
            data["error"] = str(exc)
            return data
        data["asterisk"].update(reachable=True, uptime=up, last_reload=reload)
        started = restart.asterisk_started(up)
        if started is not None:
            data["config"]["changed"] = await asyncio.to_thread(restart.changed_since, self.config_dir, started,
                                                                self.state_dir)
        data["versions"] = self._versions
        registrations, iax_registrations = self._registrations
        data["registrations"] = registrations
        data["iax_registrations"] = iax_registrations
        by_user = {r["username"]: r for r in registrations + iax_registrations}
        data["nodes"] = [
            {"node": n, "private": int(n) < 2000, "registration": by_user.get(n, {}).get("state")}
            for n in nodes
        ]
        return data

    def _forget(self) -> None:
        """Drop what was learned from the running Asterisk: it is down or was restarted."""
        self._versions = {}
        self._nodes = None
        self._registrations = ([], [])

    def invalidate(self) -> None:
        """Collect afresh on the next request (after Asterisk was restarted)."""
        self._latest_at = 0.0
        self._forget()

    async def snapshot(self, registrations: bool = False) -> dict:
        async with self._lock:
            stale = self.latest is None or time.monotonic() - self._latest_at > self.interval
            if stale or (registrations and not self._latest_has_registrations):
                self.latest = await self.collect(registrations)
                self._latest_at = time.monotonic()
                self._latest_has_registrations = registrations
            return self.latest

    def add(self, ws: web.WebSocketResponse, session_key: str, user: str, topics: frozenset[str] = frozenset()) -> None:
        self._clients[ws] = (session_key, user)
        self._topics[ws] = topics & TOPICS
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    def subscribe(self, ws: web.WebSocketResponse, topics: frozenset[str]) -> bool:
        """Set a page's topics. True when it asks for something it did not have."""
        old = self._topics.get(ws, frozenset())
        self._topics[ws] = topics & TOPICS
        return bool(self._topics[ws] - old)

    def remove(self, ws: web.WebSocketResponse) -> None:
        self._clients.pop(ws, None)
        self._topics.pop(ws, None)

    async def _run(self) -> None:
        while self._clients:
            try:
                data = await self.snapshot(self.wants_registrations)
                await self.broadcast({"type": "status", "data": data})
            except Exception:  # keep polling; one bad round must not stop updates
                log.exception("status poll failed")
            await asyncio.sleep(self.interval)

    async def broadcast(self, message: dict) -> None:
        for ws in list(self._clients):
            if ws.closed:
                self.remove(ws)
                continue
            with contextlib.suppress(ConnectionError, RuntimeError):
                await ws.send_json(message)

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task


HUB_KEY = web.AppKey("status_hub", StatusHub)
UNIT_STATE_KEY = web.AppKey("unit_state", object)
routes = web.RouteTableDef()


@routes.get("/api/v1/status")
async def status(request: web.Request) -> web.Response:
    return web.json_response(await request.app[HUB_KEY].snapshot(registrations=True))


def _topics(value) -> frozenset[str]:
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, list):
        return frozenset()
    return frozenset(t for t in value if isinstance(t, str))


@routes.get("/api/v1/ws/events")
async def events(request: web.Request) -> web.WebSocketResponse:
    session = await get_session(request)
    hub = request.app[HUB_KEY]
    storage = request.app[STORAGE_KEY]
    settings = request.app[SETTINGS_KEY]
    ws = web.WebSocketResponse(heartbeat=30, max_msg_size=4096)
    await ws.prepare(request)
    user = session.get("user")
    key = session.identity

    async def watch_session() -> None:
        while not ws.closed:
            await asyncio.sleep(hub.interval)
            member = settings.dev or is_group_member(user, settings.login_group)
            if not storage.is_active(key) or not member:
                await ws.close(code=CLOSE_SESSION_ENDED, message=b"session ended")

    hub.add(ws, key, user, _topics(request.query.get("topics", "")))
    watcher = asyncio.create_task(watch_session())
    try:
        await ws.send_json({"type": "status", "data": await hub.snapshot(hub.wants_registrations)})
        async for msg in ws:
            if msg.type == WSMsgType.ERROR:
                break
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                body = json.loads(msg.data)
            except ValueError:
                continue
            if isinstance(body, dict) and body.get("type") == "subscribe":
                if hub.subscribe(ws, _topics(body.get("topics"))):
                    # The page now shows something the last push may not have had.
                    await ws.send_json({"type": "status", "data": await hub.snapshot(hub.wants_registrations)})
    finally:
        watcher.cancel()
        hub.remove(ws)
    return ws


def setup(app: web.Application) -> None:
    if CLI_KEY not in app:
        app[CLI_KEY] = AsteriskCLI()
    app[HUB_KEY] = StatusHub(app[CLI_KEY], unit_state=app.get(UNIT_STATE_KEY, systemd.unit_state),
                             config_dir=app[SETTINGS_KEY].config_dir, state_dir=app[SETTINGS_KEY].state_dir)

    async def stop(app: web.Application) -> None:
        await app[HUB_KEY].close()

    app.on_cleanup.append(stop)
    app.add_routes(routes)
