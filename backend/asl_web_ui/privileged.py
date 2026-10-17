"""Client for the privileged helper (asl-web-ui-priv), see asl_web_ui_priv.

Each call opens a connection, sends one request and reads the replies;
progress lines go to ``on_output``. In --dev mode the commands run inside
this process instead, on a sandbox copy of the configuration (never as root
and never on the real system).
"""

import asyncio
import json
from collections.abc import Callable

from aiohttp import web


class PrivError(Exception):
    def __init__(self, message: str, code: str = "failed"):
        super().__init__(message)
        self.message = message
        self.code = code


Output = Callable[[str], None] | None


class PrivClient:
    def __init__(self, socket_path: str):
        self.socket_path = socket_path

    async def call(self, command: str, args: dict | None = None, user: str = "", on_output: Output = None,
                   timeout: float = 960) -> dict:
        try:
            reader, writer = await asyncio.open_unix_connection(self.socket_path, limit=4 << 20)
        except OSError as exc:
            raise PrivError(f"The privileged helper is not available ({exc}).", "unavailable")
        try:
            writer.write(json.dumps({"op": command, "args": args or {}, "user": user}).encode() + b"\n")
            await writer.drain()
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout)
                if not line:
                    raise PrivError("The privileged helper closed the connection.", "protocol")
                msg = json.loads(line)
                if msg.get("op") == "output":
                    if on_output:
                        on_output(str(msg.get("text", "")))
                    continue
                if msg.get("op") == "result":
                    if msg.get("ok"):
                        return msg.get("data") or {}
                    raise PrivError(str(msg.get("error", "failed")), str(msg.get("code", "failed")))
                raise PrivError("Unexpected reply from the privileged helper.", "protocol")
        except asyncio.TimeoutError:
            raise PrivError("The privileged helper did not answer in time.", "timeout")
        finally:
            writer.close()


class InProcessClient:
    """--dev only: the same commands, unprivileged, under a sandbox root."""

    def __init__(self, root: str):
        from asl_web_ui_priv import commands
        commands.ROOT = root
        self.commands = commands

    async def call(self, command: str, args: dict | None = None, user: str = "", on_output: Output = None,
                   timeout: float = 960) -> dict:
        fn = self.commands.COMMANDS.get(command)
        if fn is None:
            raise PrivError(f"unknown command {command}", "invalid")
        if command in ("factory.restore", "dahdi.remove"):
            raise PrivError("Development mode cannot reinstall or remove packages.", "dev_mode")
        loop = asyncio.get_running_loop()

        def output(text: str) -> None:
            if on_output:
                loop.call_soon_threadsafe(on_output, text)

        try:
            return await asyncio.to_thread(fn, args or {}, output)
        except self.commands.CommandError as exc:
            raise PrivError(str(exc), exc.code)


PRIV_KEY = web.AppKey("privileged", object)
