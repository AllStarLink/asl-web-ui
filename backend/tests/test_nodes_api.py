"""Nodes API: listing, planning and applying node changes, access lists, Asterisk control.

The node operations themselves are checked against node-setup in
tests/parity; these tests cover the HTTP layer on a small configuration.
"""

import os
import stat

import pytest
from aiohttp import DummyCookieJar

from asl_web_ui import config, security
from asl_web_ui.app import create_app
from asl_web_ui.auth.fake import FakeTransport
from asl_web_ui.modules import control, status
from test_asterisk import FakeCLI, unit

FILES = {
    "rpt.conf": """[general]

[nodes]
1999 = radio@127.0.0.1/1999,NONE

[node-main](!)
rxchannel = Local/pseudo
duplex = 2
hangtime = 2000
idrecording = |iNOTSET
events = events
functions = functions
morse = morse
telemetry = telemetry
wait_times = wait-times

[functions-main](!)
[functions](functions-main)
[telemetry-main](!)
[telemetry](telemetry-main)
[morse-main](!)
[morse](morse-main)
[wait-times-main](!)
[wait-times](wait-times-main)
[events-main](!)
[events](events-main)

[1999](node-main)
rxchannel = SimpleUSB/1999      ; SimpleUSB
""",
    "rpt_http_registrations.conf": "[general]\n\n[registrations]\nregister => 1234:abcdef@register.allstarlink.org\n",
    "iax.conf": "[general]\n;register => 1999:12345@register.allstarlink.org\nbindport = 4569\n",
    "modules.conf": "[modules]\nautoload = no\nload = chan_simpleusb.so\nnoload = chan_usbradio.so\n",
    "manager.conf": "[general]\nenabled = yes\n\n[admin]\nsecret = make4An1ce-secret\n",
    "simpleusb.conf": "[general]\n\n[node-main](!)\nrxmixerset = 500\n\n[1999](node-main)\n",
    "savenode.conf": "NODE=1999\nPASSWORD=12345\nENABLE=0\n",
}


class RecordingCLI(FakeCLI):
    def __init__(self):
        super().__init__()
        self.commands = []
        self.db: dict[str, str] = {}

    async def run(self, command):
        self.commands.append(command)
        if command.startswith("database put "):
            family, key, value = command[len("database put "):].split(" ", 2)
            self.db[f"/{family}/{key}"] = value.strip('"')
            return "Updated database successfully"
        if command.startswith("database show "):
            prefix = "/" + "/".join(command.split()[2:])
            rows = [f"{k:<50}: {v}" for k, v in sorted(self.db.items()) if k.startswith(prefix + "/")]
            return "\n".join(rows + [f"{len(rows)} results found."])
        if command.startswith("database del "):
            family, key = command.split()[2:4]
            self.db.pop(f"/{family}/{key}", None)
            return "Database entry removed."
        if command.startswith("database deltree "):
            prefix = "/" + "/".join(command.split()[2:]) + "/"
            for k in [k for k in self.db if k.startswith(prefix)]:
                del self.db[k]
            return "removed"
        return await super().run(command) if command in self.OUTPUT else ""


@pytest.fixture
async def api(aiohttp_client, tmp_path, monkeypatch):
    monkeypatch.setattr(security, "is_group_member", lambda user, group: True)
    etc = tmp_path / "etc"
    etc.mkdir()
    for name, content in FILES.items():
        (etc / name).write_text(content)
    systemctl = tmp_path / "systemctl"
    systemctl.write_text(f"#!/bin/sh\necho \"$@\" >> {tmp_path}/systemctl.log\n")
    systemctl.chmod(0o755)
    cli = RecordingCLI()

    async def connect():
        return FakeTransport()

    async def make(recent_auth=600):
        settings = config.Settings(config_dir=str(etc), state_dir=str(tmp_path / "state"), recent_auth=recent_auth)
        app = create_app(settings, auth_connect=connect,
                         overrides={status.CLI_KEY: cli, status.UNIT_STATE_KEY: unit("active"),
                                    control.SYSTEMCTL_KEY: str(systemctl)})
        client = await aiohttp_client(app, cookie_jar=DummyCookieJar())
        base = {"X-Forwarded-Proto": "https", "Origin": f"https://{client.server.host}:{client.server.port}"}
        r = await client.post("/api/v1/auth/login", json={"user": "dev"}, headers=base)
        step = await r.json()
        r = await client.post(f"/api/v1/auth/login/{step['id']}", json={"answer": "dev"}, headers=base)
        body = await r.json()
        headers = {**base, "Cookie": f"asl_web_ui_session={r.cookies['asl_web_ui_session'].value}",
                   "X-CSRF-Token": body["session"]["csrf"]}

        class Api:
            async def call(self, method, path, payload=None):
                resp = await client.request(method, "/api/v1/" + path, json=payload, headers=headers)
                data = await resp.json() if resp.content_type == "application/json" else await resp.text()
                return resp.status, data

            async def get(self, path):
                return await self.call("GET", path)

            async def post(self, path, payload):
                return await self.call("POST", path, payload)

            async def delete(self, path):
                return await self.call("DELETE", path)

            async def change(self, payload, **apply):
                status_, plan = await self.post("nodes/plan", payload)
                assert status_ == 200, plan
                status_, res = await self.post(f"changes/{plan['id']}/apply", apply)
                return plan, status_, res

        return Api()

    class Env:
        pass

    env = Env()
    env.etc, env.cli, env.make, env.log = etc, cli, make, tmp_path / "systemctl.log"
    return env


async def test_list_nodes_first_run(api):
    a = await api.make()
    status_, body = await a.get("nodes")
    assert status_ == 200
    assert body["first_run"] is True
    assert [n["number"] for n in body["nodes"]] == ["1999"]
    node = body["nodes"][0]
    assert node["interface"] == "SimpleUSB" and node["duplex"] == 2 and node["callsign"] is None
    assert "password" not in node and node["password_set"] is False


async def test_first_run_plan_and_apply(api):
    a = await api.make()
    plan, status_, res = await a.change({"op": "first_run", "number": "2701", "password": "secret1",
                                         "interface": "SimpleUSB", "duplex": 1, "callsign": "w1aw"})
    assert status_ == 200 and res["applied"] and res["restart"]
    names = {f["name"] for f in plan["files"]}
    assert {"rpt.conf", "rpt_http_registrations.conf", "savenode.conf", "simpleusb.conf"} <= names
    rpt = (api.etc / "rpt.conf").read_text()
    assert "[2701](node-main)" in rpt and "idrecording = |iW1AW" in rpt and "2701 = radio@127.0.0.1/2701,NONE" in rpt
    assert "register => 2701:secret1@register.allstarlink.org" in (api.etc / "rpt_http_registrations.conf").read_text()
    assert "NODE=2701\nPASSWORD=secret1\nENABLE=1\n" == (api.etc / "savenode.conf").read_text()
    _, body = await a.get("nodes")
    assert body["first_run"] is False


async def test_validation_errors_name_the_field(api):
    a = await api.make()
    status_, body = await a.post("nodes/plan", {"op": "add", "number": "12345", "password": "x"})
    assert status_ == 400 and body["field"] == "number" and "cannot start" in body["message"]
    status_, body = await a.post("nodes/plan", {"op": "callsign", "node": "1999", "callsign": "x"})
    assert status_ == 400 and body["field"] == "callsign"


async def test_unchanged_plan(api):
    a = await api.make()
    status_, body = await a.post("nodes/plan", {"op": "duplex", "node": "1999", "duplex": 2})
    assert status_ == 200 and body["unchanged"] is True


async def test_remove_needs_recent_password(api):
    a = await api.make(recent_auth=0)
    await (await api.make()).change({"op": "add", "number": "1001"})
    plan, status_, res = await a.change({"op": "remove", "node": "1001"})
    assert plan["reauth"] is True
    assert status_ == 403 and res["error"] == "reauth_required"
    assert "[1001]" in (api.etc / "rpt.conf").read_text()


async def test_remove(api):
    a = await api.make()
    await a.change({"op": "add", "number": "1001"})
    plan, status_, res = await a.change({"op": "remove", "node": "1001"})
    assert status_ == 200
    assert "1001" not in (api.etc / "rpt.conf").read_text()


async def test_rename_moves_access_list(api):
    a = await api.make()
    status_, body = await a.post("nodes/1999/access", {"list": "allow", "entry": "2000", "reason": "friend"})
    assert status_ == 200 and body["mode"] == "allow" and body["allow"] == [{"entry": "2000", "reason": "friend"}]
    plan, status_, res = await a.change({"op": "rename", "node": "1999", "number": "1005"})
    assert status_ == 200 and res["warnings"] == []
    _, moved = await a.get("nodes/1005/access")
    assert moved["allow"] == [{"entry": "2000", "reason": "friend"}]
    assert "/allowlist/1999/2000" not in api.cli.db


async def test_access_list_validation_and_removal(api):
    a = await api.make()
    status_, body = await a.post("nodes/1999/access", {"list": "deny", "entry": "1999", "reason": ""})
    assert status_ == 400 and "itself" in body["message"]
    status_, body = await a.post("nodes/1999/access", {"list": "deny", "entry": "w1aw", "reason": 'say "hi"'})
    assert status_ == 400 and body["field"] == "reason"
    await a.post("nodes/1999/access", {"list": "deny", "entry": "w1aw", "reason": "noisy"})
    status_, body = await a.delete("nodes/1999/access/deny/W1AW")
    assert status_ == 200 and body["mode"] == "open"
    status_, _ = await a.get("nodes/4242/access")
    assert status_ == 404


async def test_unwritable_file_is_reported(api):
    a = await api.make()
    os.chmod(api.etc / "iax.conf", stat.S_IRUSR)
    try:
        status_, body = await a.post("nodes/plan", {"op": "iax_port", "port": 4570})
    finally:
        os.chmod(api.etc / "iax.conf", 0o644)
    if os.geteuid() == 0:
        pytest.skip("root can write anything")
    assert status_ == 409 and body["error"] == "not_writable" and "chown" in body["message"]


async def test_ami_secret_changes_admin_only(api):
    a = await api.make()
    plan, status_, _ = await a.change({"op": "ami_secret", "secret": "NewSecret-12345"})
    assert status_ == 200
    assert "secret = NewSecret-12345" in (api.etc / "manager.conf").read_text()
    assert any("allmon3.ini" in m for m in plan["allmon3"])


async def test_restart_checks_rpt_conf(api):
    a = await api.make()
    status_, _ = await a.post("asterisk/restart", {})
    assert status_ == 200 and api.log.read_text() == "--no-ask-password restart asterisk.service\n"
    (api.etc / "rpt.conf").write_text(FILES["rpt.conf"] + '#include "missing.conf"\n')
    status_, body = await a.post("asterisk/restart", {})
    assert status_ == 409 and body["error"] == "rpt_errors" and body["first_error"]
    status_, _ = await a.post("asterisk/restart", {"confirm_errors": True})
    assert status_ == 200


async def test_stop_and_reboot_need_recent_password(api):
    a = await api.make(recent_auth=0)
    for path in ("asterisk/stop", "system/reboot"):
        status_, body = await a.post(path, {})
        assert status_ == 403 and body["error"] == "reauth_required"
    assert not api.log.exists()
