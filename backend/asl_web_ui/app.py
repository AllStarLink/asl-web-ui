"""The aiohttp application."""

import os
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp_session
from aiohttp import web

from . import config
from .auth.conversation import Conversations, SocketTransport, Transport
from .auth.fake import FakeTransport
from .auth.ratelimit import LoginThrottle
from .auth.sessions import MemoryStorage
from .modules import MODULES
from .modules.auth import CONVERSATIONS_KEY, REAUTH_KEY, STORAGE_KEY, THROTTLE_KEY
from .security import SETTINGS_KEY, security_middleware

Connect = Callable[[], Awaitable[Transport]]


def _auth_connector(settings: config.Settings) -> Connect:
    if settings.dev:
        with_code = bool(os.environ.get("ASL_WEB_UI_DEV_CODE"))

        async def fake() -> Transport:
            return FakeTransport(with_code=with_code)

        return fake

    async def real() -> Transport:
        return await SocketTransport.connect(settings.auth_socket)

    return real


def create_app(
    settings: config.Settings | None = None,
    auth_connect: Connect | None = None,
    overrides: dict[web.AppKey, Any] | None = None,
) -> web.Application:
    """Build the app. ``overrides`` presets app keys (tests substitute the
    Asterisk CLI, the systemd query and the console command this way)."""
    settings = settings or config.Settings()
    app = web.Application(client_max_size=1024 * 1024)
    app[SETTINGS_KEY] = settings
    for key, value in (overrides or {}).items():
        app[key] = value

    storage = MemoryStorage(settings)
    aiohttp_session.setup(app, storage)
    app.middlewares.append(security_middleware)

    connect = auth_connect or _auth_connector(settings)
    app[STORAGE_KEY] = storage
    app[CONVERSATIONS_KEY] = Conversations(connect)
    app[REAUTH_KEY] = Conversations(connect)
    app[THROTTLE_KEY] = LoginThrottle()

    async def close_conversations(app: web.Application) -> None:
        await app[CONVERSATIONS_KEY].close_all()
        await app[REAUTH_KEY].close_all()

    app.on_cleanup.append(close_conversations)

    for module in MODULES:
        module.setup(app)
    return app
