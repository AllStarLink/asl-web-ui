"""Login conversations with the auth helper.

A browser login can take several round trips (password, then perhaps a
verification code), so each conversation is kept open here between HTTP
requests, identified by a random ID, until it finishes or times out.
"""

import asyncio
import json
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field

TIMEOUT = 120  # seconds, matches the helper's limit
READ_TIMEOUT = 30


@dataclass
class Step:
    """What the browser sees after each round trip."""

    state: str  # "prompt", "success" or "failure"
    prompt: dict | None = None  # {"echo": bool, "text": str}
    messages: list[dict] = field(default_factory=list)  # [{"kind": "info"|"error", "text"}]
    user: str | None = None
    reason: str | None = None


class Transport:
    """A JSON-lines connection to one helper process."""

    async def send(self, msg: dict) -> None:
        raise NotImplementedError

    async def receive(self) -> dict:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError


class SocketTransport(Transport):
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer

    @classmethod
    async def connect(cls, path: str) -> "SocketTransport":
        reader, writer = await asyncio.open_unix_connection(path, limit=8192)
        return cls(reader, writer)

    async def send(self, msg: dict) -> None:
        self.writer.write(json.dumps(msg).encode() + b"\n")
        await self.writer.drain()

    async def receive(self) -> dict:
        line = await asyncio.wait_for(self.reader.readline(), READ_TIMEOUT)
        if not line:
            raise ConnectionError("auth helper closed the connection")
        msg = json.loads(line)
        if not isinstance(msg, dict):
            raise ValueError("bad message from auth helper")
        return msg

    async def close(self) -> None:
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except (ConnectionError, OSError):
            pass


class Conversation:
    def __init__(self, transport: Transport, user: str, client_ip: str):
        self.id = secrets.token_urlsafe(24)
        self.transport = transport
        self.user = user
        self.client_ip = client_ip
        self.started = time.monotonic()
        self.lock = asyncio.Lock()
        self.done = False
        self.keep = False  # "Keep me signed in", remembered until success

    @property
    def expired(self) -> bool:
        return time.monotonic() - self.started > TIMEOUT

    async def _advance(self) -> Step:
        """Read helper messages until the next prompt or the result."""
        messages: list[dict] = []
        while True:
            msg = await self.transport.receive()
            op = msg.get("op")
            if op in ("info", "error"):
                messages.append({"kind": op, "text": str(msg.get("text", ""))})
            elif op == "prompt":
                return Step("prompt", {"echo": bool(msg.get("echo")), "text": str(msg.get("text", ""))}, messages)
            elif op == "result":
                self.done = True
                if msg.get("ok") is True and msg.get("user") == self.user:
                    return Step("success", messages=messages, user=self.user)
                return Step("failure", messages=messages, reason=str(msg.get("reason", "denied")))
            else:
                raise ValueError(f"unexpected message from auth helper: {op!r}")

    async def start(self) -> Step:
        await self.transport.send({"op": "start", "user": self.user, "rhost": self.client_ip})
        return await self._advance()

    async def answer(self, value: str) -> Step:
        await self.transport.send({"op": "answer", "value": value})
        return await self._advance()

    async def close(self) -> None:
        self.done = True
        await self.transport.close()


class Conversations:
    """Open conversations, by ID."""

    def __init__(self, connect: Callable[[], object]):
        self._connect = connect  # async callable returning a Transport
        self._open: dict[str, Conversation] = {}

    async def begin(self, user: str, client_ip: str) -> tuple[Conversation, Step]:
        self.prune()
        transport = await self._connect()  # type: ignore[misc]
        conv = Conversation(transport, user, client_ip)
        try:
            step = await conv.start()
        except Exception:
            await conv.close()
            raise
        await self._settle(conv, step)
        return conv, step

    def get(self, conv_id: str) -> Conversation | None:
        self.prune()
        return self._open.get(conv_id)

    async def answer(self, conv_id: str, client_ip: str, value: str) -> Step | None:
        """Continue a conversation; None if it does not exist (or expired)."""
        self.prune()
        conv = self._open.get(conv_id)
        if conv is None or conv.client_ip != client_ip:
            return None
        async with conv.lock:
            try:
                step = await conv.answer(value)
            except Exception:
                await self._drop(conv)
                raise
        await self._settle(conv, step)
        return step

    async def _settle(self, conv: Conversation, step: Step) -> None:
        if step.state == "prompt":
            self._open[conv.id] = conv
        else:
            await self._drop(conv)

    async def _drop(self, conv: Conversation) -> None:
        self._open.pop(conv.id, None)
        await conv.close()

    def prune(self) -> None:
        for conv in [c for c in self._open.values() if c.expired]:
            self._open.pop(conv.id, None)
            asyncio.ensure_future(conv.close())

    async def close_all(self) -> None:
        for conv in list(self._open.values()):
            await self._drop(conv)
