"""Core module: service health and version."""

from aiohttp import web

from .. import VERSION

routes = web.RouteTableDef()


@routes.get("/api/v1/health")
async def health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "version": VERSION})


def setup(app: web.Application) -> None:
    app.add_routes(routes)
