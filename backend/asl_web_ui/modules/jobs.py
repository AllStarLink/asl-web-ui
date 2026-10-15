"""Long-running operations (restore, factory reset, cloud transfers) as jobs.

    GET /api/v1/jobs/{id}?from=N   -> {"title", "lines" (from line N), "done", "ok", "result", "error"}

A job belongs to the session that started it. Requests return at once with
the job id, so web servers' proxy timeouts (60 s in nginx) never cut a long
operation short; the page polls for progress.
"""

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass, field

from aiohttp import web
from aiohttp_session import get_session

log = logging.getLogger("asl-web-ui.jobs")
routes = web.RouteTableDef()
KEEP = 3600  # seconds a finished job stays readable


@dataclass
class Job:
    id: str
    owner: str
    title: str
    lines: list[str] = field(default_factory=list)
    done: bool = False
    ok: bool = False
    result: dict | None = None
    error: str | None = None
    code: str | None = None
    finished: float = 0.0
    task: asyncio.Task | None = None

    def output(self, text: str) -> None:
        self.lines.append(text)


class Jobs:
    def __init__(self):
        self.jobs: dict[str, Job] = {}

    def start(self, owner: str, title: str, work) -> Job:
        """``work(job)`` is a coroutine function returning the result dict;
        raising an exception with ``message``/``code`` attributes fails the job."""
        now = time.monotonic()
        for jid in [j for j, job in self.jobs.items() if job.done and now - job.finished > KEEP]:
            del self.jobs[jid]
        job = Job(secrets.token_urlsafe(12), owner, title)

        async def run() -> None:
            try:
                job.result = await work(job)
                job.ok = True
            except Exception as exc:  # reported to the page
                job.error = getattr(exc, "message", None) or str(exc)
                job.code = getattr(exc, "code", None)
                if job.code is None:
                    log.exception("job %s failed", title)
            finally:
                job.done = True
                job.finished = time.monotonic()

        job.task = asyncio.create_task(run())
        self.jobs[job.id] = job
        return job


JOBS_KEY = web.AppKey("jobs", Jobs)


async def start(request: web.Request, title: str, work) -> web.Response:
    session = await get_session(request)
    job = request.app[JOBS_KEY].start(session.identity or "", title, work)
    return web.json_response({"job": job.id}, status=202)


@routes.get("/api/v1/jobs/{job_id}")
async def get_job(request: web.Request) -> web.Response:
    session = await get_session(request)
    job = request.app[JOBS_KEY].jobs.get(request.match_info["job_id"])
    if job is None or job.owner != (session.identity or ""):
        raise web.HTTPNotFound(text="No such job")
    try:
        start_at = max(0, int(request.query.get("from", "0")))
    except ValueError:
        start_at = 0
    return web.json_response({"title": job.title, "lines": job.lines[start_at:], "next": len(job.lines),
                              "done": job.done, "ok": job.ok, "result": job.result, "error": job.error,
                              "code": job.code})


def setup(app: web.Application) -> None:
    if JOBS_KEY not in app:
        app[JOBS_KEY] = Jobs()

    async def stop(app: web.Application) -> None:
        for job in app[JOBS_KEY].jobs.values():
            if job.task and not job.task.done():
                job.task.cancel()

    app.on_cleanup.append(stop)
    app.add_routes(routes)
