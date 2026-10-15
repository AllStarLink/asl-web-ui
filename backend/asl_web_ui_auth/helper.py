"""One login conversation over newline-delimited JSON.

Client to helper:
    {"op": "start", "user": "...", "rhost": "..."}
    {"op": "answer", "value": "..."}          (after each prompt)
Helper to client:
    {"op": "prompt", "echo": false, "text": "Password: "}
    {"op": "info", "text": "..."} / {"op": "error", "text": "..."}
    {"op": "result", "ok": true, "user": "..."}
    {"op": "result", "ok": false, "reason": "denied" | "not_permitted" |
                                            "expired" | "protocol"}

"denied" covers every failure before the password is known to be correct,
so the browser cannot tell an unknown user from a wrong password. The other
reasons are only sent after PAM accepted the credentials.
"""

import configparser
import grp
import json
import os
import pwd
import re
import signal
import sys
from collections.abc import Callable
from typing import IO

from . import pam

SERVICE = "asl-web-ui"
LOGIN_GROUP = "asl-web-ui"
CONFIG_PATH = "/etc/asl-web-ui/asl-web-ui.ini"
TIME_LIMIT = 120  # seconds for the whole conversation
MAX_LINE = 4096

USER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$")
RHOST_RE = re.compile(r"^[0-9A-Fa-f.:]{1,45}$")


class ProtocolError(Exception):
    pass


def log(text: str) -> None:
    print(f"asl-web-ui-auth: {text}", file=sys.stderr, flush=True)


def is_group_member(user: str, group: str = LOGIN_GROUP) -> bool:
    try:
        gid = grp.getgrnam(group).gr_gid
        primary = pwd.getpwnam(user).pw_gid
    except KeyError:
        return False
    return gid in os.getgrouplist(user, primary)


def is_root(user: str) -> bool:
    try:
        return pwd.getpwnam(user).pw_uid == 0
    except KeyError:
        return False


def root_login_allowed(path: str = CONFIG_PATH) -> bool:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path)
    return parser.getboolean("auth", "allow_root_login", fallback=False)


class Channel:
    def __init__(self, rfile: IO[bytes], wfile: IO[bytes]):
        self.rfile = rfile
        self.wfile = wfile

    def send(self, **msg) -> None:
        self.wfile.write(json.dumps(msg).encode() + b"\n")
        self.wfile.flush()

    def receive(self) -> dict:
        line = self.rfile.readline(MAX_LINE + 1)
        if not line:
            raise ProtocolError("connection closed")
        if len(line) > MAX_LINE:
            raise ProtocolError("message too long")
        try:
            msg = json.loads(line)
        except ValueError as exc:
            raise ProtocolError("invalid JSON") from exc
        if not isinstance(msg, dict):
            raise ProtocolError("message is not an object")
        return msg


def converse(
    channel: Channel,
    authenticate: Callable[..., pam.Outcome] = pam.authenticate,
    is_member: Callable[[str], bool] = is_group_member,
    root_allowed: Callable[[], bool] = root_login_allowed,
    is_root_user: Callable[[str], bool] = is_root,
) -> None:
    start = channel.receive()
    user, rhost = start.get("user"), start.get("rhost", "")
    if start.get("op") != "start" or not isinstance(user, str) or not isinstance(rhost, str):
        raise ProtocolError("expected start")
    if not USER_RE.match(user) or (rhost and not RHOST_RE.match(rhost)):
        log(f"login refused: invalid user name or address from rhost={rhost!r:.50}")
        channel.send(op="result", ok=False, reason="denied")
        return
    if is_root_user(user) and not root_allowed():
        log(f"login refused for user={user} rhost={rhost} reason=root-login-disabled")
        channel.send(op="result", ok=False, reason="denied")
        return

    def respond(message: pam.Message) -> str | None:
        if message.style in (pam.PAM_PROMPT_ECHO_OFF, pam.PAM_PROMPT_ECHO_ON):
            channel.send(op="prompt", echo=message.style == pam.PAM_PROMPT_ECHO_ON, text=message.text)
            reply = channel.receive()
            value = reply.get("value")
            if reply.get("op") != "answer" or not isinstance(value, str):
                return None
            return value
        channel.send(op="error" if message.style == pam.PAM_ERROR_MSG else "info", text=message.text)
        return None

    outcome = authenticate(SERVICE, user, rhost, respond)
    if outcome.ok:
        if is_member(user):
            log(f"login accepted for user={user} rhost={rhost}")
            channel.send(op="result", ok=True, user=user)
        else:
            log(f"login refused for user={user} rhost={rhost} reason=not-in-group-{LOGIN_GROUP}")
            channel.send(op="result", ok=False, reason="not_permitted")
        return
    if outcome.stage == "account" and outcome.code == pam.PAM_NEW_AUTHTOK_REQD:
        reason = "expired"
    else:
        reason = "denied"
    log(f"login refused for user={user} rhost={rhost} reason={outcome.stage}: {outcome.detail}")
    channel.send(op="result", ok=False, reason=reason)


def main() -> None:
    signal.signal(signal.SIGALRM, lambda *_: os._exit(2))
    signal.alarm(TIME_LIMIT)
    channel = Channel(sys.stdin.buffer, sys.stdout.buffer)
    try:
        converse(channel)
    except ProtocolError as exc:
        log(f"protocol error: {exc}")
        try:
            channel.send(op="result", ok=False, reason="protocol")
        except OSError:
            pass
    except (BrokenPipeError, ConnectionResetError):
        log("client went away")
