"""Diagnostics API: the connectivity check runs as a job and is cached."""

from asl_web_ui.modules import diagnostics
from test_authcheck import FULL
from test_backups_api import cloud, env  # noqa: F401 (fixtures)


async def test_connectivity_check_is_cached(env, tmp_path, monkeypatch):
    tool = tmp_path / "asl-node-auth-check"
    tool.write_text("#!/bin/sh\n[ \"$1\" = --help ] && exit 0\ncat <<'EOF'\n" + FULL + "EOF\n")
    tool.chmod(0o755)
    real_setup = diagnostics.setup

    def setup(app):
        app[diagnostics.AUTHCHECK_KEY] = str(tool)
        real_setup(app)
    monkeypatch.setattr(diagnostics, "setup", setup)
    a = await env.make()
    _, before = await a.call("GET", "diagnostics")
    assert before["connectivity"] is None and isinstance(before["packages"], list)
    job = await a.job("POST", "diagnostics/connectivity", {})
    assert job["ok"] and job["result"]["result"] == "error", job
    _, after = await a.call("GET", "diagnostics")
    assert after["connectivity"]["result"] == "error"
    assert [s["node"] for s in after["connectivity"]["sections"] if s["id"] == "node"] == ["2701", "2702"]
