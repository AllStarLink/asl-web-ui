"""asl-web-ui's privileged helper: one request per connection, as root.

Started by asl-web-ui-priv@.service (socket activation, Accept=yes) with the
connection on stdin/stdout; only the asterisk user can reach the socket.

Request (one JSON line):
    {"op": "<command>", "args": {...}, "user": "<web user, for the log only>"}
Replies (JSON lines):
    {"op": "output", "text": "..."}            progress (factory restore)
    {"op": "result", "ok": true, "data": ...}
    {"op": "result", "ok": false, "error": "...", "code": "..."}

Every request is authorized with polkit: the caller's process (from the
socket's SO_PEERCRED) must hold org.allstarlink.asl-web-ui.<command>, checked
with pkcheck. The shipped rule grants the actions to the asterisk user;
admins may tighten it. The web user name is only written to the log.

Standard library only; it never imports the web application.
"""

import json
import os
import re
import signal
import socket
import struct
import subprocess
import sys
from collections.abc import Callable
from typing import IO

from . import commands

PKCHECK = "/usr/bin/pkcheck"
ACTION_PREFIX = "org.allstarlink.asl-web-ui."
TIME_LIMIT = 900  # factory restore runs apt-get
MAX_REQUEST = 1 << 20
WEB_USER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$")


class RequestError(Exception):
    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.code = code


def log(text: str) -> None:
    print(f"asl-web-ui-priv: {text}", file=sys.stderr, flush=True)


def peer(sock: socket.socket) -> tuple[int, int, int]:
    """(pid, uid, gid) of the process at the other end of a Unix socket."""
    data = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    return struct.unpack("3i", data)


def start_time(pid: int) -> str:
    """The process start time pkcheck needs to identify a process safely."""
    with open(f"/proc/{pid}/stat") as f:
        stat = f.read()
    # The command name may contain spaces and parentheses; fields follow the last ")".
    fields = stat[stat.rindex(")") + 2:].split()
    return fields[19]


def authorized(command: str, pid: int, uid: int, pkcheck: str = PKCHECK) -> bool:
    action = ACTION_PREFIX + command.replace(".", "-").replace("_", "-")
    try:
        proc = subprocess.run([pkcheck, "--action-id", action, "--process", f"{pid},{start_time(pid)},{uid}"],
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        log(f"pkcheck failed: {exc}")
        return False
    return proc.returncode == 0


class Channel:
    def __init__(self, rfile: IO[bytes], wfile: IO[bytes]):
        self.rfile = rfile
        self.wfile = wfile

    def send(self, **msg) -> None:
        self.wfile.write(json.dumps(msg).encode() + b"\n")
        self.wfile.flush()

    def request(self) -> dict:
        line = self.rfile.readline(MAX_REQUEST + 1)
        if not line or len(line) > MAX_REQUEST:
            raise RequestError("missing or oversized request", "protocol")
        try:
            msg = json.loads(line)
        except ValueError as exc:
            raise RequestError("invalid JSON", "protocol") from exc
        if not isinstance(msg, dict) or not isinstance(msg.get("op"), str) or not isinstance(msg.get("args", {}), dict):
            raise RequestError("malformed request", "protocol")
        return msg


def handle(channel: Channel, caller: tuple[int, int, int] | None,
           is_authorized: Callable[[str, int, int], bool] = authorized,
           table: dict | None = None) -> None:
    table = table if table is not None else commands.COMMANDS
    msg = channel.request()
    command, args = msg["op"], msg.get("args", {})
    user = msg.get("user") if isinstance(msg.get("user"), str) and WEB_USER_RE.match(msg.get("user", "")) else "?"
    if command not in table:
        raise RequestError(f"unknown command {command!r:.40}")
    if caller is None:
        raise RequestError("caller unknown", "denied")
    pid, uid, _gid = caller
    if not is_authorized(command, pid, uid):
        log(f"denied {command} for uid={uid} web-user={user}")
        raise RequestError("not authorized by polkit", "denied")
    log(f"{command} for web-user={user}")

    def output(text: str) -> None:
        channel.send(op="output", text=text)

    try:
        data = table[command](args, output)
    except commands.CommandError as exc:
        log(f"{command} failed: {exc}")
        channel.send(op="result", ok=False, error=str(exc), code=exc.code)
        return
    channel.send(op="result", ok=True, data=data)


def main() -> None:
    signal.signal(signal.SIGALRM, lambda *_: os._exit(2))
    signal.alarm(TIME_LIMIT)
    os.umask(0o022)
    channel = Channel(sys.stdin.buffer, sys.stdout.buffer)
    try:
        caller = peer(socket.socket(fileno=os.dup(sys.stdin.fileno())))
    except OSError:
        caller = None
    try:
        handle(channel, caller)
    except RequestError as exc:
        log(f"refused: {exc}")
        try:
            channel.send(op="result", ok=False, error=str(exc), code=exc.code)
        except OSError:
            pass
    except (BrokenPipeError, ConnectionResetError):
        log("client went away")
