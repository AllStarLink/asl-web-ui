"""Applying planned changes, for every page that plans them.

    POST /api/v1/changes/{plan_id}/apply   {"confirm_errors"} -> applied

A plan may carry follow-up actions in ``plan.meta`` (run after the files are
written) and may require a recent password entry (``meta["reauth"]``).
"""

import logging
import os

from aiohttp import web
from aiohttp_session import get_session

from ..configengine.lint import counts, lint
from ..configengine.store import ApplyError, Conflict, Plan, Store
from ..security import SETTINGS_KEY
from .auth import recently_authenticated

log = logging.getLogger("asl-web-ui.changes")

STORE_KEY = web.AppKey("config_store", Store)
AFTER_KEY = web.AppKey("after_apply", dict)  # name -> async fn(request, plan, args) -> list[str] warnings
routes = web.RouteTableDef()


async def read_json(request: web.Request) -> dict:
    try:
        body = await request.json()
    except ValueError:
        raise web.HTTPBadRequest(text="Invalid JSON")
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="Expected a JSON object")
    return body


def error(status: int, code: str, message: str, **extra) -> web.Response:
    return web.json_response({"error": code, "message": message, **extra}, status=status)


def unwritable(paths: list[str]) -> list[str]:
    """Paths the service cannot replace (needs write access to file and directory)."""
    bad = []
    for path in paths:
        directory = os.path.dirname(path) or "."
        if not os.access(directory, os.W_OK) or (os.path.exists(path) and not os.access(path, os.W_OK)):
            bad.append(path)
    return bad


def lint_counts(config_dir: str, roots: list[str], reader) -> dict[str, dict[str, int]]:
    from ..configengine.model import load
    return {name: counts(lint(load(name, config_dir=config_dir, reader=reader), config_dir)) for name in roots}


def register_after(app: web.Application, name: str, fn) -> None:
    app[AFTER_KEY][name] = fn


@routes.post("/api/v1/changes/{plan_id}/apply")
async def apply_plan(request: web.Request) -> web.Response:
    body = await read_json(request)
    session = await get_session(request)
    store = request.app[STORE_KEY]
    plan = store.peek(request.match_info["plan_id"], session.identity or "")
    if plan is not None and plan.errors and body.get("confirm_errors") is not True:
        return error(409, "has_errors", "The new content has errors that make Asterisk reject the file. "
                                        "Confirm to save anyway.")
    if plan is not None and plan.meta.get("reauth") and not recently_authenticated(session, request.app[SETTINGS_KEY]):
        return error(403, "reauth_required", "Enter your password again to make this change.")
    plan = store.take(request.match_info["plan_id"], session.identity or "")
    if plan is None:
        return error(410, "plan_expired", "These changes expired. Review them again.")
    try:
        snapshot = store.apply(plan)
    except Conflict:
        return error(409, "conflict", "A file changed on disk after these changes were prepared, so nothing was "
                                      "written. Review the changes again.")
    except ApplyError as exc:
        log.error("apply failed: %s", exc)
        return error(500, "apply_failed", f"The change could not be saved: {exc}")
    log.info("%s: %s (snapshot %s)", plan.user, plan.action, snapshot)
    warnings = await _after(request, plan)
    return web.json_response({"applied": True, "snapshot": snapshot, "warnings": warnings,
                              "restart": bool(plan.meta.get("restart"))})


async def _after(request: web.Request, plan: Plan) -> list[str]:
    warnings = []
    for name, args in plan.meta.get("after", []):
        fn = request.app[AFTER_KEY].get(name)
        if fn is None:
            continue
        try:
            warnings += await fn(request, plan, args)
        except Exception as exc:  # the files are written; report, don't fail
            log.exception("after-apply step %s failed", name)
            warnings.append(f"A follow-up step failed: {exc}")
    return warnings


def setup(app: web.Application) -> None:
    if STORE_KEY not in app:
        app[STORE_KEY] = Store(app[SETTINGS_KEY].state_dir)
    if AFTER_KEY not in app:
        app[AFTER_KEY] = {}
    app.add_routes(routes)

