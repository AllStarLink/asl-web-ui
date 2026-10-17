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


APT_PLAN = """\
NOTE: This is only a simulation!
      apt-get needs root privileges for real execution.
Inst libssl3t64 [3.5.1-1] (3.5.1-1+deb13u1 Debian-Security:13/stable-security [amd64])
Inst asl3-asterisk [2:22.8.2+asl3-3.8.3-1.deb13] (2:22.8.3+asl3-3.8.4-1.deb13 . trixie:trixie [amd64])
Inst linux-image-6.12.48+deb13-amd64 (6.12.48-1 Debian:13.2/stable, Debian-Security:13/stable-security [amd64])
Conf libssl3t64 (3.5.1-1+deb13u1 Debian-Security:13/stable-security [amd64])
"""


def test_pending_updates():
    assert diagnostics.pending_updates(APT_PLAN) == [
        {"name": "asl3-asterisk", "installed": "2:22.8.2+asl3-3.8.3-1.deb13",
         "available": "2:22.8.3+asl3-3.8.4-1.deb13", "security": False},
        {"name": "libssl3t64", "installed": "3.5.1-1", "available": "3.5.1-1+deb13u1", "security": True},
    ]
    assert diagnostics.pending_updates("NOTE: This is only a simulation!\n") == []


async def test_updates_endpoint(env, tmp_path, monkeypatch):
    tool = tmp_path / "apt-get"
    tool.write_text("#!/bin/sh\n[ \"$4\" = dist-upgrade ] || exit 100\ncat <<'EOF'\n" + APT_PLAN + "EOF\n")
    tool.chmod(0o755)
    real_setup = diagnostics.setup

    def setup(app):
        app[diagnostics.APT_GET_KEY] = str(tool)
        real_setup(app)
    monkeypatch.setattr(diagnostics, "setup", setup)
    a = await env.make()
    status_, body = await a.call("GET", "diagnostics/updates")
    assert status_ == 200, body
    assert [u["name"] for u in body["updates"]] == ["asl3-asterisk", "libssl3t64"]
    assert isinstance(body["cockpit"], bool)
    tool.write_text("#!/bin/sh\necho 'E: broken' ; exit 100\n")
    status_, body = await a.call("GET", "diagnostics/updates")
    assert status_ == 500 and "E: broken" in body["message"], body


async def test_refreshing_package_lists_is_refused_in_dev_mode(env):
    a = await env.make()
    job = await a.job("POST", "diagnostics/updates/refresh", {})
    assert not job["ok"] and job["code"] == "dev_mode", job
