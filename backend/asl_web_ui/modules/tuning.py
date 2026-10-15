"""Tuning a node's radio interface (SimpleUSB, USBRadio).

    GET  /api/v1/tuning/{node}                    settings, device, lock, TUI warning
    POST /api/v1/tuning/{node}/set     {"name", "value"}   change a setting (not yet saved)
    POST /api/v1/tuning/{node}/tone               three 1 s test tone bursts
    POST /api/v1/tuning/{node}/save               save to simpleusb.conf/usbradio.conf -> diff
    POST /api/v1/tuning/{node}/revert             back to the settings at the start of this session (saved)
    POST /api/v1/tuning/{node}/calibrate {"name"} USBRadio calibrations (job)
    POST /api/v1/tuning/{node}/release            end the session (frees the lock)
    GET  /api/v1/ws/tune/{node}/{meter|status}     live receive level or COS/CTCSS/PTT status
    GET  /api/v1/ws/tune-menu/{node}               the classic tune menu in a terminal

A driver tunes one device at a time ("active" device, global in Asterisk), so
one browser session at a time holds a driver's tuning lock; it expires after
five idle minutes. The settings at the start of the session are kept so they
can be restored, saved or not.
"""

import asyncio
import contextlib
import difflib
import logging
import os
import re
import time
from dataclasses import dataclass, field

from aiohttp import WSMsgType, web
from aiohttp_session import get_session

from .. import restart, tuning
from ..asterisk_cli import AsteriskUnavailable
from ..configengine.edit import Workspace
from ..configengine.store import Store
from ..nodes.info import node_info
from ..security import SETTINGS_KEY, USER_KEY
from .changes import STORE_KEY, error, read_json
from .console import terminal
from .jobs import start as start_job
from .status import CLI_KEY

log = logging.getLogger("asl-web-ui.tuning")
routes = web.RouteTableDef()
LOCK_IDLE = 300
TUI_NAMES = ("simpleusb-tune-", "radio-tune-menu")  # /proc/*/comm is cut at 15 characters


@dataclass
class Session:
    owner: str
    user: str
    node: str
    touched: float = field(default_factory=time.monotonic)
    original: dict | None = None  # settings when the session started
    unsaved: bool = False


LOCKS_KEY = web.AppKey("tuning_locks", dict)


def _driver(request: web.Request, number: str) -> tuple[tuning.Driver, str]:
    if not re.fullmatch(r"[0-9]{1,7}", number):
        raise web.HTTPNotFound(text="No such node")
    try:
        info = node_info(Workspace(request.app[SETTINGS_KEY].config_dir), number)
    except KeyError:
        raise web.HTTPNotFound(text=f"Node {number} is not configured")
    driver = tuning.DRIVERS.get(info.interface or "")
    if driver is None:
        raise web.HTTPConflict(text=f"Node {number}'s interface ({info.interface or 'none'}) is not tuned here.")
    return driver, number


async def _cli(request: web.Request, driver: tuning.Driver, device: str, arg: str, timeout: float | None = None) -> str:
    cli = request.app[CLI_KEY]
    await cli.run(f"{driver.prefix} active {device}")
    command = f"{driver.prefix} tune menu-support {arg}"
    if timeout is None:
        return await cli.run(command)
    # Test tones and calibrations take longer than the CLI's usual limit.
    proc = await asyncio.create_subprocess_exec(cli.binary, *cli.extra_args, "-rx", command,
                                                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise AsteriskUnavailable(f"'{command}' timed out")
    return out.decode(errors="replace")


async def _values(request, driver, device) -> dict:
    return tuning.parse_settings(driver, await _cli(request, driver, device, driver.csv))


def tui_running() -> bool:
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/comm") as f:
                if f.read().strip().startswith(TUI_NAMES):
                    return True
        except OSError:
            continue
    return False


def _busy_message(current: Session, driver: tuning.Driver) -> str:
    return (f"{current.user} is tuning {driver.interface} node {current.node} right now. "
            "Try again when they are done (or in five minutes).")


async def _lock(request: web.Request, driver: tuning.Driver, number: str, take: bool) -> Session | web.Response:
    """The caller's tuning session for this driver, or an error response."""
    session = await get_session(request)
    owner = session.identity or ""
    locks: dict = request.app[LOCKS_KEY]
    current: Session | None = locks.get(driver.interface)
    now = time.monotonic()
    if current and (now - current.touched > LOCK_IDLE):
        current = None
    if current and current.owner != owner:
        return error(409, "locked", _busy_message(current, driver))
    if current and current.node != number:
        current = None if take else current
    if current is None:
        if not take:
            return Session(owner, request[USER_KEY], number)
        current = Session(owner, request[USER_KEY], number)
        locks[driver.interface] = current
    current.touched = now
    return current


def _unavailable(exc: AsteriskUnavailable) -> web.Response:
    return error(503, "asterisk_unavailable", f"Asterisk is not answering: {exc}")


@routes.get("/api/v1/tuning/{node}")
async def get_tuning(request: web.Request) -> web.Response:
    driver, number = _driver(request, request.match_info["node"])
    lock = await _lock(request, driver, number, take=False)
    holder = request.app[LOCKS_KEY].get(driver.interface)
    locked_message = None if isinstance(lock, Session) or holder is None else _busy_message(holder, driver)
    try:
        devices = tuning.device_list(await _cli(request, driver, number, "1"))
        if number not in devices:
            return error(409, "no_device_section",
                         f"The {driver.interface} driver has no device {number}. Restart Asterisk after changing the "
                         "radio interface, then try again.")
        values = await _values(request, driver, number)
        show = await request.app[CLI_KEY].run(f"{driver.prefix} active show")
    except AsteriskUnavailable as exc:
        return _unavailable(exc)
    m = re.search(rf"Device \[{number}\] is assigned to device=(\S+)", show)
    assigned = m.group(1) if m and m.group(1) != "unassigned" else None
    return web.json_response({
        "interface": driver.interface,
        "device": number,
        "usb": assigned,
        "settings": tuning.present(driver, values),
        "values": values,
        "calibrations": [{"name": k, "description": v[1]} for k, v in driver.calibrations.items()],
        "locked": locked_message is not None,
        "locked_message": locked_message,
        "session": isinstance(lock, Session) and lock.original is not None,
        "unsaved": isinstance(lock, Session) and lock.unsaved,
        "tui_running": tui_running(),
        "classic_menu": os.path.exists(driver.tune_menu),
        "meter_marks": tuning.METER_MARKS,
    })


@routes.post("/api/v1/tuning/{node}/set")
async def set_setting(request: web.Request) -> web.Response:
    driver, number = _driver(request, request.match_info["node"])
    lock = await _lock(request, driver, number, take=True)
    if not isinstance(lock, Session):
        return lock
    body = await read_json(request)
    try:
        arg = tuning.command_for(driver, str(body.get("name")), body.get("value"))
    except ValueError as exc:
        return error(400, "invalid", str(exc))
    try:
        if lock.original is None:
            lock.original = await _values(request, driver, number)
        reply = await _cli(request, driver, number, arg)
        values = await _values(request, driver, number)
    except AsteriskUnavailable as exc:
        return _unavailable(exc)
    if tuning.UNASSIGNED.search(reply):
        return error(409, "no_device", "The node's USB sound card is not connected (or not found).")
    if "Error" in reply:
        return error(400, "rejected", reply.strip())
    lock.unsaved = True
    return web.json_response({"reply": reply.strip(), "settings": tuning.present(driver, values), "values": values,
                              "unsaved": True})


@routes.post("/api/v1/tuning/{node}/tone")
async def tone(request: web.Request) -> web.Response:
    driver, number = _driver(request, request.match_info["node"])
    lock = await _lock(request, driver, number, take=True)
    if not isinstance(lock, Session):
        return lock
    try:
        reply = await _cli(request, driver, number, "l", timeout=20)
    except AsteriskUnavailable as exc:
        return _unavailable(exc)
    if tuning.UNASSIGNED.search(reply):
        return error(409, "no_device", "The node's USB sound card is not connected (or not found).")
    return web.json_response({"reply": reply.strip()})


async def _save(request: web.Request, driver: tuning.Driver, number: str, action: str) -> dict:
    path = os.path.join(request.app[SETTINGS_KEY].config_dir, driver.file)
    before = Store.read(path) or b""
    reply = await _cli(request, driver, number, "j")
    after = Store.read(path) or b""
    restart.record_driver_save(request.app[SETTINGS_KEY].state_dir, path)
    diff = "".join(difflib.unified_diff(before.decode(errors="replace").splitlines(True),
                                        after.decode(errors="replace").splitlines(True),
                                        f"a/{driver.file}", f"b/{driver.file}"))
    request.app[STORE_KEY].record(request[USER_KEY], f"node {number}: {action}", "done", [path])
    return {"reply": reply.strip(), "diff": diff, "file": driver.file}


@routes.post("/api/v1/tuning/{node}/save")
async def save(request: web.Request) -> web.Response:
    driver, number = _driver(request, request.match_info["node"])
    lock = await _lock(request, driver, number, take=True)
    if not isinstance(lock, Session):
        return lock
    try:
        res = await _save(request, driver, number, "save tuning")
    except AsteriskUnavailable as exc:
        return _unavailable(exc)
    lock.unsaved = False
    return web.json_response(res)


@routes.post("/api/v1/tuning/{node}/revert")
async def revert(request: web.Request) -> web.Response:
    """Put back the settings from the start of this tuning session, and save them."""
    driver, number = _driver(request, request.match_info["node"])
    lock = await _lock(request, driver, number, take=True)
    if not isinstance(lock, Session):
        return lock
    if lock.original is None:
        return error(409, "nothing_to_revert", "Nothing was changed in this tuning session.")
    try:
        current = await _values(request, driver, number)
        for s in driver.settings:
            old, new = lock.original.get(s.name), current.get(s.name)
            if old is None or old == new:
                continue
            value = bool(old) if s.kind == "bool" else int(old) * (tuning.MS_PER_FRAME if s.kind == "delay" else 1)
            await _cli(request, driver, number, tuning.command_for(driver, s.name, value))
        res = await _save(request, driver, number, "revert tuning")
        values = await _values(request, driver, number)
    except AsteriskUnavailable as exc:
        return _unavailable(exc)
    lock.unsaved = False
    return web.json_response({**res, "settings": tuning.present(driver, values), "values": values})


@routes.post("/api/v1/tuning/{node}/calibrate")
async def calibrate(request: web.Request) -> web.Response:
    driver, number = _driver(request, request.match_info["node"])
    lock = await _lock(request, driver, number, take=True)
    if not isinstance(lock, Session):
        return lock
    body = await read_json(request)
    name = body.get("name")
    if name not in driver.calibrations:
        return error(400, "invalid", "Unknown calibration.")
    letter, description = driver.calibrations[name]

    async def work(job):
        if lock.original is None:
            lock.original = await _values(request, driver, number)
        job.output(description)
        reply = await _cli(request, driver, number, letter, timeout=120)
        for line in reply.splitlines():
            if line.strip():
                job.output(line.rstrip())
        lock.unsaved = True
        if tuning.UNASSIGNED.search(reply):
            raise RuntimeError("The node's USB sound card is not connected (or not found).")
        if "FAILED" in reply or "ERROR" in reply:
            raise RuntimeError("The calibration did not succeed; see the output.")
        return {"settings": tuning.present(driver, await _values(request, driver, number))}

    return await start_job(request, f"Calibrate: {name}", work)


@routes.post("/api/v1/tuning/{node}/release")
async def release(request: web.Request) -> web.Response:
    driver, number = _driver(request, request.match_info["node"])
    lock = await _lock(request, driver, number, take=False)
    if isinstance(lock, Session) and request.app[LOCKS_KEY].get(driver.interface) is lock:
        del request.app[LOCKS_KEY][driver.interface]
    return web.json_response({"released": True})


@routes.get("/api/v1/ws/tune/{node}/{display}")
async def live(request: web.Request) -> web.StreamResponse:
    display = request.match_info["display"]
    if display not in ("meter", "status"):
        raise web.HTTPNotFound()
    driver, number = _driver(request, request.match_info["node"])
    lock = await _lock(request, driver, number, take=True)
    if not isinstance(lock, Session):
        return lock
    ws = web.WebSocketResponse(heartbeat=30, max_msg_size=4096)
    await ws.prepare(request)
    cli = request.app[CLI_KEY]
    try:
        await cli.run(f"{driver.prefix} active {number}")
    except AsteriskUnavailable as exc:
        await ws.send_json({"error": "asterisk_unavailable", "message": str(exc)})
        await ws.close()
        return ws
    letter = "b" if display == "meter" else "v"
    proc = await asyncio.create_subprocess_exec(
        cli.binary, *cli.extra_args, "-rx", f"{driver.prefix} tune menu-support {letter}",
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    parser = tuning.DisplayParser("meter" if display == "meter" else "status")

    async def pump() -> None:
        assert proc.stdout is not None
        while chunk := await proc.stdout.read(4096):
            lock.touched = time.monotonic()
            for reading in parser.feed(chunk.decode(errors="replace")):
                await ws.send_json(reading)
        await ws.close()

    pumper = asyncio.create_task(pump())
    try:
        async for msg in ws:
            if msg.type == WSMsgType.CLOSE:
                break
    finally:
        pumper.cancel()
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
    return ws


@routes.get("/api/v1/ws/tune-menu/{node}")
async def classic(request: web.Request) -> web.StreamResponse:
    driver, number = _driver(request, request.match_info["node"])
    lock = await _lock(request, driver, number, take=True)
    if not isinstance(lock, Session):
        return lock
    return await terminal(request, [driver.tune_menu, "-n", number], "the classic tune menu")


def setup(app: web.Application) -> None:
    if LOCKS_KEY not in app:
        app[LOCKS_KEY] = {}
    app.add_routes(routes)
