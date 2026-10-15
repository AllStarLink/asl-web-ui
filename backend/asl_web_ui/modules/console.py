"""The Asterisk console in the browser.

    GET /api/v1/ws/console     WebSocket

Runs ``asterisk -rvvv`` (as the service's user, asterisk) on a pseudo
terminal. Browser to server: text frames {"type": "input", "data": "..."} and
{"type": "resize", "cols": N, "rows": N}. Server to browser: binary frames of
terminal output. There is no system shell: only the Asterisk CLI runs here.
"""

import asyncio
import contextlib
import fcntl
import json
import logging
import os
import re
import signal
import struct
import termios

from aiohttp import WSMsgType, web

from ..asterisk_cli import ASTERISK
from ..security import USER_KEY

log = logging.getLogger("asl-web-ui.console")

COMMAND_KEY = web.AppKey("console_command", list)
DEFAULT_COMMAND = [ASTERISK, "-rvvv"]
MAX_PER_USER = 3
ENV = {
    "TERM": "xterm-256color",
    "LANG": "C.UTF-8",
    "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
    "HOME": "/var/lib/asterisk",
}

# Asterisk announces every remote CLI connection to verbose consoles. The
# status poller connects several times a second, so drop exactly these
# messages. Asterisk clears the prompt line ("\r\x1b[0K"), prints the
# message in color, then redraws the prompt; removing only the message and
# its newline leaves the prompt redrawn cleanly in place.
_SGR = rb"(?:\x1b\[[0-9;]*m)*"
NOISE = re.compile(_SGR + rb"[ \t]*--[ \t]*" + _SGR + rb"Remote UNIX connection(?: disconnected)?" + _SGR + rb"[ \t]*\r?\n")


def strip_noise(data: bytes) -> bytes:
    return NOISE.sub(b"", data)


_NOISE_PLAIN = b"-- Remote UNIX connection disconnected\r\n"
_SGR_RE = re.compile(_SGR)
_PARTIAL_ESC = re.compile(rb"\x1b(?:\[[0-9;]*)?$")


def _could_be_noise_start(fragment: bytes) -> bool:
    """True if fragment may be the beginning of a noise line cut off by a read."""
    plain = _PARTIAL_ESC.sub(b"", _SGR_RE.sub(b"", fragment)).lstrip(b" \t")
    return bool(fragment) and (not plain or _NOISE_PLAIN.startswith(plain) or plain.startswith(b"-- Remote UNIX connection"))


class NoiseFilter:
    """Streaming version of strip_noise: a noise line split across two reads
    is held back until the rest arrives (the caller flushes after a short
    delay, so prompts and typed characters are never held for long)."""

    def __init__(self) -> None:
        self.pending = b""

    def feed(self, data: bytes) -> bytes:
        text = strip_noise(self.pending + data)
        self.pending = b""
        # A noise line starts after a newline or after the line-clear sequence.
        clear = text.rfind(b"\x1b[0K")
        cut = max(text.rfind(b"\n"), clear + 3 if clear >= 0 else -1)
        tail = text[cut + 1:]
        if tail and _could_be_noise_start(tail):
            self.pending = tail
            return text[: cut + 1]
        # Never split an escape sequence: hold an incomplete one at the end.
        partial = _PARTIAL_ESC.search(text)
        if partial:
            self.pending = text[partial.start():]
            return text[: partial.start()]
        return text

    def flush(self) -> bytes:
        out, self.pending = self.pending, b""
        return out


_open: dict[str, int] = {}
routes = web.RouteTableDef()


def _set_size(fd: int, cols: int, rows: int) -> None:
    cols = max(10, min(int(cols), 500))
    rows = max(5, min(int(rows), 200))
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _make_controlling_tty() -> None:
    # Runs in the child: the pty slave is stdin; make it the controlling
    # terminal so Ctrl-C and line editing behave as in a real console.
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


@routes.get("/api/v1/ws/console")
async def console(request: web.Request) -> web.WebSocketResponse:
    user = request[USER_KEY]
    if _open.get(user, 0) >= MAX_PER_USER:
        raise web.HTTPTooManyRequests(text="Too many open consoles")

    ws = web.WebSocketResponse(heartbeat=30, max_msg_size=64 * 1024)
    await ws.prepare(request)

    master, slave = os.openpty()
    _set_size(master, 80, 24)
    try:
        proc = await asyncio.create_subprocess_exec(
            *request.app[COMMAND_KEY],
            stdin=slave, stdout=slave, stderr=slave,
            env=ENV, start_new_session=True, preexec_fn=_make_controlling_tty,
        )
    except OSError as exc:
        os.close(master)
        os.close(slave)
        await ws.send_bytes(f"Could not start the Asterisk console: {exc}\r\n".encode())
        await ws.close()
        return ws
    os.close(slave)
    os.set_blocking(master, False)
    _open[user] = _open.get(user, 0) + 1
    log.info("console opened by %s", user)

    loop = asyncio.get_running_loop()
    output: asyncio.Queue[bytes | None] = asyncio.Queue()

    def readable() -> None:
        try:
            data = os.read(master, 65536)
        except BlockingIOError:
            return
        except OSError:  # EIO: the process exited
            data = b""
        if not data:
            loop.remove_reader(master)
            output.put_nowait(None)
        else:
            output.put_nowait(data)

    loop.add_reader(master, readable)

    async def pump() -> None:
        noise = NoiseFilter()
        while True:
            try:
                data = await asyncio.wait_for(output.get(), 0.2 if noise.pending else None)
            except asyncio.TimeoutError:
                data = b""
                held = noise.flush()
                if held:
                    await ws.send_bytes(held)
                continue
            if data is None:
                break
            data = noise.feed(data)
            if data:
                await ws.send_bytes(data)
        held = noise.flush()
        if held:
            await ws.send_bytes(held)
        await ws.close()

    pumper = asyncio.create_task(pump())
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                event = json.loads(msg.data)
            except ValueError:
                continue
            if event.get("type") == "input" and isinstance(event.get("data"), str):
                os.write(master, event["data"].encode("utf-8"))
            elif event.get("type") == "resize":
                with contextlib.suppress(TypeError, ValueError, OSError):
                    _set_size(master, event.get("cols"), event.get("rows"))
    finally:
        loop.remove_reader(master)
        pumper.cancel()
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGHUP)
            try:
                await asyncio.wait_for(proc.wait(), 2)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
                await proc.wait()
        os.close(master)
        _open[user] -= 1
        log.info("console closed by %s", user)
    return ws


def setup(app: web.Application) -> None:
    if COMMAND_KEY not in app:
        app[COMMAND_KEY] = DEFAULT_COMMAND
    app.add_routes(routes)
