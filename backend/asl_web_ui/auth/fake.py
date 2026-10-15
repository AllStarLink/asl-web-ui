"""A fake auth helper for --dev mode and tests.

Accepts one user with a fixed password, and optionally asks for a
verification code afterwards to exercise multi-prompt logins. Never used by
the packaged service: --dev refuses to run from the installed location.
"""

import asyncio

from .conversation import Transport

DEV_USER = "dev"
DEV_PASSWORD = "dev"
DEV_CODE = "123456"


class FakeTransport(Transport):
    def __init__(self, with_code: bool = False):
        self.with_code = with_code
        self.outbox: asyncio.Queue[dict] = asyncio.Queue()
        self.user: str | None = None
        self.stage = "start"

    async def send(self, msg: dict) -> None:
        if msg.get("op") == "start":
            self.user = msg.get("user")
            await self.outbox.put({"op": "prompt", "echo": False, "text": "Password: "})
            self.stage = "password"
        elif msg.get("op") == "answer" and self.stage == "password":
            if self.user == DEV_USER and msg.get("value") == DEV_PASSWORD:
                if self.with_code:
                    self.stage = "code"
                    await self.outbox.put({"op": "prompt", "echo": True, "text": "Verification code: "})
                else:
                    await self.outbox.put({"op": "result", "ok": True, "user": self.user})
            else:
                await self.outbox.put({"op": "result", "ok": False, "reason": "denied"})
        elif msg.get("op") == "answer" and self.stage == "code":
            ok = msg.get("value") == DEV_CODE
            await self.outbox.put({"op": "result", "ok": ok, "user": self.user} if ok else {"op": "result", "ok": False, "reason": "denied"})

    async def receive(self) -> dict:
        return await self.outbox.get()

    async def close(self) -> None:
        pass
