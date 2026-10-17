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


async def test_asterisk_log_tail_and_download(env, tmp_path):
    log = tmp_path / "messages.log"
    log.write_text("".join(f"[Oct 16 10:00:{i % 60:02d}] NOTICE line {i}\n" for i in range(500)))
    a = await env.make(asterisk_log=str(log))
    status_, body = await a.call("GET", "diagnostics/log?lines=3")
    assert status_ == 200 and body["more"] and body["text"].splitlines()[-1].endswith("line 499")
    assert len(body["text"].splitlines()) == 3 and body["size"] == log.stat().st_size
    _, body = await a.call("GET", "diagnostics/log?lines=100000")
    assert body["lines"] == diagnostics.MAX_LINES and not body["more"] and body["text"] == log.read_text()
    status_, _ = await a.call("GET", "diagnostics/log?lines=x")
    assert status_ == 400
    resp = await a.client_.get("/api/v1/diagnostics/log/download")
    assert resp.status == 401 or resp.status == 403  # needs the session
    status_, data = await a.call("GET", "diagnostics/log/download")
    assert status_ == 200 and data == log.read_bytes()
    log.unlink()
    _, body = await a.call("GET", "diagnostics/log")
    assert body["exists"] is False


def test_dahdi_state(tmp_path):
    pkgs = [{"name": "asl3-asterisk", "version": "2:22.8.2+asl3-3.8.3-1.deb12"}]
    assert diagnostics.dahdi_state(pkgs, str(tmp_path)) is None
    pkgs.append({"name": "dahdi-dkms", "version": "1:3.4.0-11"})
    assert diagnostics.dahdi_state(pkgs, str(tmp_path)) == {"version": "1:3.4.0-11", "blockers": []}
    (tmp_path / "rpt.conf").write_text("[1999]\nrxchannel=dahdi/pseudo\n")
    assert diagnostics.dahdi_state(pkgs, str(tmp_path))["blockers"] == ["rpt.conf still uses dahdi/pseudo."]
