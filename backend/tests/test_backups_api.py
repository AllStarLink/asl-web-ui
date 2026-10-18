"""Backups, Allmon3 updates and ownership fixes through the API.

The privileged commands run in-process on a temporary root (the --dev
client), and the AllStarLink backup server is a local fake.
"""

import asyncio
import base64
import io
import os
import tarfile

import pytest
from aiohttp import DummyCookieJar, FormData, web

from asl_web_ui import config, security
from asl_web_ui.app import create_app
from asl_web_ui.auth.fake import FakeTransport
from asl_web_ui.modules import control, status
from asl_web_ui.privileged import PRIV_KEY, InProcessClient
from test_asterisk import FakeCLI, unit
from test_nodes_api import FILES


def archive_bytes(names=("etc/asterisk/rpt_http_registrations.conf", "etc/asterisk/rpt.conf")) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name in names:
            data = b"[x]\n"
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture
async def cloud(aiohttp_server):
    """A stand-in for backup.allstarlink.org."""
    store = {"20261001120000.tgz": archive_bytes()}
    uploads = []

    def authorized(request):
        expected = "Basic " + base64.b64encode(b"2701:secret1").decode()
        if request.headers.get("Authorization") != expected:
            raise web.HTTPUnauthorized()

    async def index(request):
        authorized(request)
        links = "".join(f'<a href="getfile.cgi?{n}">{n}</a>' for n in store)
        return web.Response(text=f"<html>{links}<a href='other.cgi'>x</a></html>", content_type="text/html")

    async def getfile(request):
        authorized(request)
        return web.Response(body=store[request.query_string])

    async def savenode(request):
        authorized(request)
        uploads.append(await request.read())
        return web.Response(text="ok")

    app = web.Application(client_max_size=10 << 20)
    app.router.add_get("/", index)
    app.router.add_get("/getfile.cgi", getfile)
    app.router.add_post("/savenode.cgi", savenode)
    server = await aiohttp_server(app)
    return str(server.make_url("")), uploads


@pytest.fixture
async def env(aiohttp_client, tmp_path, monkeypatch, cloud):
    monkeypatch.setattr(security, "is_group_member", lambda user, group: True)
    root = tmp_path / "root"
    etc = root / "etc" / "asterisk"
    etc.mkdir(parents=True)
    for name, content in FILES.items():
        (etc / name).write_text(content)
    (etc / "savenode.conf").write_text("NODE=2701\nPASSWORD=secret1\nENABLE=1\n")
    (root / "etc" / "allmon3").mkdir()
    (root / "etc" / "allmon3" / "allmon3.ini").write_text("[1999]\nhost=127.0.0.1\nuser=admin\npass=make4An1ce-secret\n")
    (root / "var" / "lib" / "asl-web-ui" / "staging").mkdir(parents=True)
    systemctl = tmp_path / "systemctl"
    systemctl.write_text(f"#!/bin/sh\necho \"$@\" >> {tmp_path}/systemctl.log\n")
    systemctl.chmod(0o755)
    server, uploads = cloud

    async def connect():
        return FakeTransport()

    async def make(recent_auth=600, cli=None, **more):
        settings = config.Settings(config_dir=str(etc), state_dir=str(tmp_path / "state"), recent_auth=recent_auth,
                                   backup_dir=str(root / "var" / "asl-backups"),
                                   staging_dir=str(root / "var" / "lib" / "asl-web-ui" / "staging"),
                                   backup_server=server, **more)
        app = create_app(settings, auth_connect=connect, overrides={
            status.CLI_KEY: cli or FakeCLI(), status.UNIT_STATE_KEY: unit("active"), control.SYSTEMCTL_KEY: str(systemctl),
            PRIV_KEY: InProcessClient(str(root))})
        client = await aiohttp_client(app, cookie_jar=DummyCookieJar())

        async def login():
            base = {"X-Forwarded-Proto": "https", "Origin": f"https://{client.server.host}:{client.server.port}"}
            r = await client.post("/api/v1/auth/login", json={"user": "dev"}, headers=base)
            step = await r.json()
            r = await client.post(f"/api/v1/auth/login/{step['id']}", json={"answer": "dev"}, headers=base)
            body = await r.json()
            headers = {**base, "Cookie": f"asl_web_ui_session={r.cookies['asl_web_ui_session'].value}",
                       "X-CSRF-Token": body["session"]["csrf"]}

            class Api:
                client_ = client

                async def another(self):
                    """A second browser session on the same server."""
                    return await login()

                async def call(self, method, path, payload=None, data=None):
                    resp = await client.request(method, "/api/v1/" + path, json=payload, data=data, headers=headers)
                    body = await resp.json() if resp.content_type == "application/json" else await resp.read()
                    return resp.status, body

                async def job(self, method, path, payload=None):
                    status_, body = await self.call(method, path, payload)
                    assert status_ == 202, body
                    for _ in range(200):
                        _, state = await self.call("GET", f"jobs/{body['job']}")
                        if state["done"]:
                            return state
                        await asyncio.sleep(0.02)
                    raise AssertionError("job did not finish")

            return Api()

        return await login()

    class Env:
        pass

    e = Env()
    e.root, e.etc, e.make, e.uploads, e.log = root, etc, make, uploads, tmp_path / "systemctl.log"
    return e


async def test_create_list_download_delete(env):
    a = await env.make()
    job = await a.job("POST", "backups", {})
    assert job["ok"], job
    name = job["result"]["name"]
    _, listing = await a.call("GET", "backups")
    assert [b["name"] for b in listing["local"]] == [name]
    assert listing["cloud"] == {"configured": True, "node": "2701", "reason": None, "sync": None}
    status_, data = await a.call("GET", f"backups/local/{name}/download")
    assert status_ == 200
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        assert "etc/asterisk/rpt.conf" in tar.getnames()
    status_, _ = await a.call("DELETE", f"backups/local/{name}")
    assert status_ == 200
    _, listing = await a.call("GET", "backups")
    assert listing["local"] == []


async def test_create_and_upload_to_allstarlink(env):
    a = await env.make()
    job = await a.job("POST", "backups", {"upload": True})
    assert job["ok"] and job["result"]["uploaded"], job
    assert len(env.uploads) == 1 and env.uploads[0][:2] == b"\x1f\x8b"


async def test_restore_needs_password_then_runs(env):
    a = await env.make()
    made = (await a.job("POST", "backups", {}))["result"]["name"]
    (env.etc / "rpt.conf").write_text("changed\n")
    status_, body = await (await env.make(recent_auth=0)).call("POST", f"backups/local/{made}/restore", {})
    assert status_ == 403 and body["error"] == "reauth_required"
    _, contents = await a.call("GET", f"backups/local/{made}/contents")
    assert "etc/asterisk/rpt.conf" in contents["files"]
    job = await a.job("POST", f"backups/local/{made}/restore", {})
    assert job["ok"], job
    assert (env.etc / "rpt.conf").read_text() == FILES["rpt.conf"]
    assert job["result"]["before"].endswith("_before-restore.tgz")


async def test_import_upload(env):
    a = await env.make()
    form = FormData()
    form.add_field("file", archive_bytes(), filename="ASL_2026-09-01_0800.tgz", content_type="application/gzip")
    status_, body = await a.call("POST", "backups/import", data=form)
    assert status_ == 200 and body["name"] == "ASL_2026-09-01_0800.tgz"
    bad = FormData()
    bad.add_field("file", b"hello", filename="x.tgz")
    status_, body = await a.call("POST", "backups/import", data=bad)
    assert status_ == 400


async def test_cloud_list_and_fetch(env):
    a = await env.make()
    status_, body = await a.call("POST", "backups/cloud/list", {})
    assert status_ == 200 and body == {"node": "2701", "backups": ["20261001120000.tgz"]}
    status_, body = await a.call("POST", "backups/cloud/list", {"node": "2702", "password": "wrong12"})
    assert status_ == 502 and body["error"] == "cloud_auth"
    job = await a.job("POST", "backups/cloud/fetch", {"name": "20261001120000.tgz"})
    assert job["ok"] and job["result"]["name"] == "ASL_2026-10-01_120000.tgz", job
    assert (env.root / "var" / "asl-backups" / "ASL_2026-10-01_120000.tgz").exists()


async def test_cloud_needs_savenode(env):
    (env.etc / "savenode.conf").write_text("NODE=1999\nPASSWORD=12345\nENABLE=0\n")
    a = await env.make()
    _, listing = await a.call("GET", "backups")
    assert listing["cloud"]["configured"] is False
    status_, body = await a.call("POST", "backups/cloud/list", {})
    assert status_ == 409 and body["error"] == "not_configured"


async def test_include_list(env):
    a = await env.make()
    _, current = await a.call("GET", "backups/include-list")
    assert "/etc/asterisk" in current["content"]
    status_, _ = await a.call("PUT", "backups/include-list", {"content": "/etc/asterisk\n", "hash": current["hash"]})
    assert status_ == 200
    status_, body = await a.call("PUT", "backups/include-list", {"content": "/", "hash": current["hash"]})
    assert status_ == 409


async def test_factory_reset_is_refused_in_dev_mode(env):
    a = await env.make()
    job = await a.job("POST", "backups/factory-reset", {})
    assert not job["ok"] and job["code"] == "dev_mode"


async def test_ami_secret_updates_allmon3(env):
    a = await env.make()
    status_, plan = await a.call("POST", "nodes/plan", {"op": "ami_secret", "secret": "NewSecret-12345"})
    assert status_ == 200
    names = [f["name"] for f in plan["files"]]
    assert "/etc/allmon3/allmon3.ini" in names and plan["allmon3"] == []
    status_, res = await a.call("POST", f"changes/{plan['id']}/apply", {})
    assert status_ == 200 and res["warnings"] == []
    assert "pass=NewSecret-12345" in (env.root / "etc" / "allmon3" / "allmon3.ini").read_text()
    assert env.log.read_text() == "--no-ask-password restart allmon3.service\n"


async def test_rename_updates_allmon3(env):
    a = await env.make()
    status_, plan = await a.call("POST", "nodes/plan", {"op": "rename", "node": "1999", "number": "1005"})
    status_, res = await a.call("POST", f"changes/{plan['id']}/apply", {})
    assert status_ == 200
    assert (env.root / "etc" / "allmon3" / "allmon3.ini").read_text().startswith("[1005]\n")


async def test_fix_ownership(env):
    a = await env.make()
    status_, body = await a.call("POST", "config/fix-ownership", {"files": ["rpt.conf"]})
    assert status_ == 200 and body["fixed"] == ["rpt.conf"]
    status_, body = await a.call("POST", "config/fix-ownership", {"files": ["../allmon3/allmon3.ini"]})
    assert status_ == 400
    status_, body = await (await env.make(recent_auth=0)).call("POST", "config/fix-ownership", {"files": ["rpt.conf"]})
    assert status_ == 403


def registered_node(env, password="newpass1", started_after=True, iax=None):
    """Node 63001, which FakeCLI shows as registered, with its registration
    (HTTP unless password is None) and an active IAX registration (iax)."""
    with open(env.etc / "rpt.conf", "a") as f:
        f.write("\n[63001](node-main)\n")
    http = f"register => 63001:{password}@register.allstarlink.org\n" if password else ""
    (env.etc / "rpt_http_registrations.conf").write_text(f"[general]\n\n[registrations]\n{http}")
    if iax:
        (env.etc / "iax.conf").write_text(f"[general]\nregister => 63001:{iax}@register.allstarlink.org\n"
                                          "bindport = 4569\n")
    if started_after:  # Asterisk started after the files were written
        for p in env.etc.iterdir():
            os.utime(p, (1_000_000_000, 1_000_000_000))


IAX_REGISTRY = (
    "Host                                           dnsmgr  Username    Perceived                                      Refresh  State\n"
    "52.21.169.197:4569                             N       63001       203.0.113.24:4569                              60       Registered\n"
    "1 IAX2 registration.\n"
)


class IaxCLI(FakeCLI):
    """Node 63001 registered by IAX only."""
    OUTPUT = {**FakeCLI.OUTPUT, "rpt show registrations": "Host Username Perceived Refresh State\n"
              "0 HTTP registrations.\n", "iax2 show registry": IAX_REGISTRY}


class BothCLI(FakeCLI):
    """Node 63001 registered by HTTP and IAX."""
    OUTPUT = {**FakeCLI.OUTPUT, "iax2 show registry": IAX_REGISTRY}


async def test_savenode_takes_the_registration_password(env):
    (env.etc / "savenode.conf").write_text("# config file for /usr/sbin/savenode\nNODE=63001\nPASSWORD=oldpass1\n"
                                           "ENABLE=1\n")
    registered_node(env)
    a = await env.make()
    _, listing = await a.call("GET", "backups")
    assert listing["cloud"]["sync"] == "63001"
    status_, plan = await a.call("POST", "nodes/plan", {"op": "savenode", "node": "63001"})
    assert status_ == 200 and [f["name"] for f in plan["files"]] == ["savenode.conf"] and not plan["restart"], plan
    status_, _ = await a.call("POST", f"changes/{plan['id']}/apply", {})
    assert status_ == 200
    assert (env.etc / "savenode.conf").read_text() == \
        "# config file for /usr/sbin/savenode\nNODE=63001\nPASSWORD=newpass1\nENABLE=1\n"
    _, listing = await a.call("GET", "backups")
    assert listing["cloud"] == {"configured": True, "node": "63001", "reason": None, "sync": None}


async def test_savenode_is_created_when_missing(env):
    (env.etc / "savenode.conf").unlink()
    registered_node(env)
    a = await env.make()
    status_, plan = await a.call("POST", "nodes/plan", {"op": "savenode", "node": "63001"})
    assert status_ == 200, plan
    status_, _ = await a.call("POST", f"changes/{plan['id']}/apply", {})
    assert status_ == 200
    assert (env.etc / "savenode.conf").read_text() == "NODE=63001\nPASSWORD=newpass1\nENABLE=1\n"


async def test_savenode_needs_a_live_registration(env):
    registered_node(env, started_after=False)
    a = await env.make()
    status_, body = await a.call("POST", "nodes/plan", {"op": "savenode", "node": "63001"})
    assert status_ == 409 and "changed since Asterisk started" in body["message"]
    # 2701 has a registration line but Asterisk does not show it registered.
    with open(env.etc / "rpt.conf", "a") as f:
        f.write("\n[2701](node-main)\n")
    with open(env.etc / "rpt_http_registrations.conf", "a") as f:
        f.write("register => 2701:secret1@register.allstarlink.org\n")
    for p in env.etc.iterdir():
        os.utime(p, (1_000_000_000, 1_000_000_000))
    status_, body = await (await env.make()).call("POST", "nodes/plan", {"op": "savenode", "node": "2701"})
    assert status_ == 409 and body["error"] == "requirement" and "not registered" in body["message"]
    assert (env.etc / "savenode.conf").read_text() == "NODE=2701\nPASSWORD=secret1\nENABLE=1\n"


async def test_savenode_takes_the_iax_registration_password(env):
    registered_node(env, password=None, iax="iaxpass1")
    a = await env.make(cli=IaxCLI())
    _, listing = await a.call("GET", "backups")
    assert listing["cloud"]["sync"] == "63001"
    status_, plan = await a.call("POST", "nodes/plan", {"op": "savenode", "node": "63001"})
    assert status_ == 200, plan
    status_, _ = await a.call("POST", f"changes/{plan['id']}/apply", {})
    assert status_ == 200
    assert (env.etc / "savenode.conf").read_text() == "NODE=63001\nPASSWORD=iaxpass1\nENABLE=1\n"
    _, listing = await a.call("GET", "backups")
    assert listing["cloud"]["sync"] is None


async def test_savenode_uses_only_the_live_registration(env):
    registered_node(env, password="httppass1", iax="iaxpass1")
    # Only the IAX registration is live: its password is the right one.
    status_, plan = await (await env.make(cli=IaxCLI())).call("POST", "nodes/plan", {"op": "savenode",
                                                                                    "node": "63001"})
    assert status_ == 200 and "PASSWORD=iaxpass1" in plan["files"][0]["diff"], plan
    # Both live with different passwords: refused rather than guessed.
    status_, body = await (await env.make(cli=BothCLI())).call("POST", "nodes/plan", {"op": "savenode",
                                                                                     "node": "63001"})
    assert status_ == 409 and "different passwords" in body["message"]
