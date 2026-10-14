"""The aiohttp application."""

from aiohttp import web

from . import config
from .modules import MODULES

SETTINGS_KEY = web.AppKey("settings", config.Settings)


def create_app(settings: config.Settings | None = None) -> web.Application:
    app = web.Application()
    app[SETTINGS_KEY] = settings or config.Settings()
    for module in MODULES:
        module.setup(app)
    return app
