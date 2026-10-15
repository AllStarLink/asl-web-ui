"""Server-side sessions kept in memory.

The cookie holds only a random ID. Sessions end when the service restarts,
on logout, or when their absolute or idle limit passes (longer limits when
"Keep me signed in" was chosen).
"""

import secrets
import time
from dataclasses import dataclass, field

from aiohttp import web
from aiohttp_session import AbstractStorage, Session

from ..config import Settings

COOKIE_NAME = "asl_web_ui_session"


@dataclass
class _Entry:
    created: float
    last_seen: float
    data: dict = field(default_factory=dict)


class MemoryStorage(AbstractStorage):
    def __init__(self, settings: Settings, clock=time.time):
        super().__init__(
            cookie_name=COOKIE_NAME,
            path=settings.url_prefix.rstrip("/") + "/",
            httponly=True,
            secure=not (settings.allow_insecure_http or settings.dev),
            samesite="Strict",
        )
        self.settings = settings
        self._clock = clock
        self._entries: dict[str, _Entry] = {}

    def _limits(self, entry: _Entry) -> tuple[int, int]:
        if entry.data.get("keep"):
            return self.settings.keep_max_age, self.settings.keep_idle
        return self.settings.session_max_age, self.settings.session_idle

    def _expired(self, entry: _Entry, now: float) -> bool:
        max_age, idle = self._limits(entry)
        return now - entry.created > max_age or now - entry.last_seen > idle

    def prune(self) -> None:
        now = self._clock()
        for key in [k for k, e in self._entries.items() if self._expired(e, now)]:
            del self._entries[key]

    def is_active(self, key: str | None) -> bool:
        """True if the session exists and has not expired. Does not count as
        activity, so an open page cannot keep a session alive by itself."""
        entry = self._entries.get(key) if key else None
        return entry is not None and not self._expired(entry, self._clock())

    def forget(self, key: str | None) -> None:
        if key:
            self._entries.pop(key, None)

    def forget_user(self, user: str) -> None:
        for key in [k for k, e in self._entries.items() if e.data.get("user") == user]:
            del self._entries[key]

    async def load_session(self, request: web.Request) -> Session:
        key = self.load_cookie(request)
        entry = self._entries.get(key) if key else None
        now = self._clock()
        if entry is None or self._expired(entry, now):
            self.forget(key)
            return Session(None, data=None, new=True)
        entry.last_seen = now
        return Session(key, data={"created": int(entry.created), "session": dict(entry.data)}, new=False)

    async def save_session(self, request: web.Request, response: web.StreamResponse, session: Session) -> None:
        key = session.identity
        if session.empty:
            self.forget(key)
            self.save_cookie(response, "")
            return
        now = self._clock()
        if key is None or key not in self._entries:
            key = secrets.token_urlsafe(32)
            session.set_new_identity(key)
            self._entries[key] = _Entry(created=now, last_seen=now)
            self.prune()
        entry = self._entries[key]
        entry.data = dict(session)
        max_age = self.settings.keep_max_age if entry.data.get("keep") else None
        self.save_cookie(response, key, max_age=max_age)
