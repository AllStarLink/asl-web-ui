"""Manual Config Edit API: list, read, check, plan and apply."""

import os

import pytest
from aiohttp import DummyCookieJar

from asl_web_ui import config, security
from asl_web_ui.app import create_app
from asl_web_ui.auth.fake import FakeTransport
from asl_web_ui.modules import status
from test_asterisk import FakeCLI, unit


@pytest.fixture
async def api(aiohttp_client, tmp_path, monkeypatch):
    monkeypatch.setattr(security, "is_group_member", lambda user, group: True)
    etc = tmp_path / "etc"
    etc.mkdir()
    (etc / "rpt.conf").write_text("[node-main](!)\nduplex = 1\n[1999](node-main)\nduplex = 2\n")
    (etc / "iax.conf").write_bytes(b"[general]\r\nbindport = 4569\r\n")

    async def connect():
        return FakeTransport()

    app = create_app(config.Settings(config_dir=str(etc), state_dir=str(tmp_path / "state")), auth_connect=connect,
                     overrides={status.CLI_KEY: FakeCLI(), status.UNIT_STATE_KEY: unit("active")})
    client = await aiohttp_client(app, cookie_jar=DummyCookieJar())
    base = {"X-Forwarded-Proto": "https", "Origin": f"https://{client.server.host}:{client.server.port}"}
    r = await client.post("/api/v1/auth/login", json={"user": "dev"}, headers=base)
    step = await r.json()
    r = await client.post(f"/api/v1/auth/login/{step['id']}", json={"answer": "dev"}, headers=base)
    body = await r.json()
    headers = {**base, "Cookie": f"asl_web_ui_session={r.cookies['asl_web_ui_session'].value}", "X-CSRF-Token": body["session"]["csrf"]}

    class Api:
        async def get(self, path):
            resp = await client.get("/api/v1/" + path, headers=headers)
            return resp.status, await resp.json() if resp.content_type == "application/json" else await resp.text()

        async def post(self, path, payload):
            resp = await client.post("/api/v1/" + path, json=payload, headers=headers)
            return resp.status, await resp.json() if resp.content_type == "application/json" else await resp.text()

    return Api(), etc


async def test_list_files(api):
    a, _ = api
    status_, body = await a.get("config/files")
    files = {f["name"]: f for f in body["files"]}
    assert files["rpt.conf"]["exists"] and files["rpt.conf"]["counts"] == {"error": 0, "warning": 0, "info": 0}
    assert not files["voter.conf"]["exists"]


async def test_edit_round_trip(api):
    a, etc = api
    _, f = await a.get("config/files/rpt.conf")
    new = f["content"].replace("duplex = 2", "duplex = 3")
    status_, plan = await a.post("config/files/rpt.conf/plan", {"content": new, "base_hash": f["hash"]})
    assert status_ == 200 and "-duplex = 2" in plan["diff"] and "+duplex = 3" in plan["diff"]
    status_, res = await a.post(f"changes/{plan['id']}/apply", {})
    assert status_ == 200 and res["applied"]
    assert "duplex = 3" in (etc / "rpt.conf").read_text()


async def test_saving_errors_needs_confirmation(api):
    a, etc = api
    _, f = await a.get("config/files/rpt.conf")
    bad = f["content"].replace("(node-main)\nduplex = 2", "(node-mian)\nduplex = 2")
    _, check = await a.post("config/files/rpt.conf/check", {"content": bad})
    assert check["counts"]["error"] == 1 and "node-main" in check["findings"][0]["message"]
    _, plan = await a.post("config/files/rpt.conf/plan", {"content": bad, "base_hash": f["hash"]})
    status_, res = await a.post(f"changes/{plan['id']}/apply", {})
    assert status_ == 409 and res["error"] == "has_errors"
    status_, res = await a.post(f"changes/{plan['id']}/apply", {"confirm_errors": True})
    assert status_ == 200 and "node-mian" in (etc / "rpt.conf").read_text()


async def test_change_on_disk_is_a_conflict(api):
    a, etc = api
    _, f = await a.get("config/files/rpt.conf")
    _, plan = await a.post("config/files/rpt.conf/plan", {"content": f["content"] + "\n", "base_hash": f["hash"]})
    (etc / "rpt.conf").write_text("[x]\nedited = by hand\n")
    status_, res = await a.post(f"changes/{plan['id']}/apply", {})
    assert status_ == 409 and res["error"] == "conflict"
    assert (etc / "rpt.conf").read_text() == "[x]\nedited = by hand\n"


async def test_crlf_files_stay_crlf(api):
    a, etc = api
    _, f = await a.get("config/files/iax.conf")
    assert f["content"] == "[general]\r\nbindport = 4569\r\n"
    edited = f["content"].replace("\r\n", "\n").replace("4569", "4570")  # what the editor sends
    _, plan = await a.post("config/files/iax.conf/plan", {"content": edited, "base_hash": f["hash"]})
    await a.post(f"changes/{plan['id']}/apply", {})
    assert (etc / "iax.conf").read_bytes() == b"[general]\r\nbindport = 4570\r\n"


async def test_unknown_file_refused(api):
    a, _ = api
    status_, _ = await a.get("config/files/..%2F..%2Fetc%2Fshadow")
    assert status_ == 404
    status_, _ = await a.get("config/files/sip.conf")
    assert status_ == 404


async def test_non_utf8_file_is_read_only(api):
    a, etc = api
    (etc / "voter.conf").write_bytes(b"[x]\nname = caf\xe9\n")
    _, f = await a.get("config/files/voter.conf")
    assert f["utf8"] is False
    status_, _ = await a.post("config/files/voter.conf/plan", {"content": "x", "base_hash": f["hash"]})
    assert status_ == 403


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anything")
async def test_unwritable_file_explains(api):
    a, etc = api
    os.chmod(etc / "rpt.conf", 0o444)
    _, f = await a.get("config/files/rpt.conf")
    status_, res = await a.post("config/files/rpt.conf/plan", {"content": f["content"], "base_hash": f["hash"]})
    assert status_ == 409 and res["error"] == "not_writable" and res["files"][0].endswith("rpt.conf")


async def test_status_reports_rpt_errors(api):
    a, etc = api
    (etc / "rpt.conf").write_text("[1999](nope)\n")
    _, data = await a.get("status")
    assert data["config"]["rpt_errors"] == 1 and data["config"]["rpt_first_error"]["code"] == "undefined_template"


@pytest.fixture
async def custom(api):
    a, etc = api
    (etc / "rpt.conf").write_text("[1999]\nduplex = 2\n#tryinclude custom/rpt/*.conf\n")
    (etc / "custom" / "rpt").mkdir(parents=True)
    (etc / "custom" / "rpt" / "extra.conf").write_text("[1999](+)\nlinktolink = yes\n")
    (etc / "custom" / "README.md").write_text("Put your own files here.\n")
    (etc / "custom" / "link.conf").symlink_to("/etc/passwd")
    (etc / ".asl-web-ui-tmp").write_text("")
    return a, etc


async def test_tree_lists_every_file(custom):
    a, _ = custom
    status_, body = await a.get("config/tree")
    files = {f["name"]: f for f in body["files"]}
    assert status_ == 200 and ".asl-web-ui-tmp" not in files and not body["truncated"]
    assert files["rpt.conf"]["main"] and files["rpt.conf"]["read_by"] == ["Asterisk"]
    assert files["custom/rpt/extra.conf"]["read_by"] == ["rpt.conf"] and files["custom/rpt/extra.conf"]["writable"]
    assert files["custom/README.md"]["read_by"] == []
    assert files["custom/link.conf"]["link"] == "/etc/passwd"


async def test_included_file_is_checked_through_its_includer(custom):
    a, etc = custom
    _, f = await a.get("config/files/custom%2Frpt%2Fextra.conf")
    assert f["read_by"] == ["rpt.conf"] and f["findings"] == [] and f["path"].endswith("custom/rpt/extra.conf")
    bad = "[1998](+)\nlinktolink = yes\n"
    _, check = await a.post("config/files/custom/rpt/extra.conf/check", {"content": bad})
    assert check["counts"]["error"] == 1 and check["findings"][0]["file"] == "custom/rpt/extra.conf"
    _, plan = await a.post("config/files/custom/rpt/extra.conf/plan",
                           {"content": "[1999](+)\nlinktolink = no\n", "base_hash": f["hash"]})
    status_, res = await a.post(f"changes/{plan['id']}/apply", {})
    assert status_ == 200 and "no" in (etc / "custom" / "rpt" / "extra.conf").read_text()


async def test_files_nothing_includes_are_not_checked(custom):
    a, _ = custom
    _, f = await a.get("config/files/custom/README.md")
    assert f["read_by"] == [] and f["findings"] == []
    _, check = await a.post("config/files/custom/README.md/check", {"content": "no section = here\n"})
    assert check["findings"] == []


async def test_names_outside_or_through_links_are_refused(custom):
    a, etc = custom
    (etc.parent / "secret.conf").write_text("[x]\n")
    for name in ("..%2Fsecret.conf", "custom/..%2F..%2Fsecret.conf", "custom/link.conf", "custom", "%2Fetc%2Fpasswd",
                 ".asl-web-ui-tmp", "custom//README.md"):
        status_, _ = await a.get(f"config/files/{name}")
        assert status_ == 404, name


async def test_large_files_are_not_opened(custom):
    a, etc = custom
    (etc / "custom" / "big.conf").write_bytes(b";" * ((1 << 20) + 1))
    status_, body = await a.get("config/files/custom/big.conf")
    assert status_ == 413 and body["error"] == "too_large"
