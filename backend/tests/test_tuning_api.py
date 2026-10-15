"""Tuning API with a stand-in for chan_simpleusb's CLI."""

import pytest

from asl_web_ui.modules import status
from test_backups_api import cloud, env  # noqa: F401 (fixtures)
from test_tuning import SIMPLEUSB_CSV


class FakeDriverCLI:
    binary, extra_args, timeout = "/bin/false", [], 10.0

    def __init__(self, conf):
        self.values = [int(v) for v in SIMPLEUSB_CSV.strip().split(",")]
        self.conf = conf
        self.commands = []

    async def run(self, command):
        self.commands.append(command)
        if command.startswith("susb active show"):
            return "Device [1999] is assigned to device=1-1.4:1.0 card=1\n"
        if command.startswith("susb active "):
            return "Active (command) Simple USB Radio device set to [1999]\n"
        arg = command.removeprefix("susb tune menu-support ")
        if arg == "1":
            return "1999\n"
        if arg == "0+4":
            return ",".join(map(str, self.values)) + "\n"
        if arg == "j":
            # Like Asterisk's config writer: the file and everything it includes.
            self.conf.write_text(f'#tryinclude "custom.conf"\n[1999]\nrxboost = {"yes" if self.values[3] else "no"}\n')
            custom = self.conf.parent / "custom.conf"
            if custom.exists():
                custom.write_text(custom.read_text() + "\n")
            return "Saved radio tuning settings to simpleusb.conf\n"
        if arg.startswith("m"):
            self.values[3] = int(arg[1:])
            return "RxBoost changed\n"
        if arg.startswith("c"):
            self.values[12] = int(arg[1:])
            return "Channel 1999: Changed setting on RX Channel\n"
        return "Invalid Command\n"


@pytest.fixture
def driver(env, monkeypatch):
    fake = FakeDriverCLI(env.etc / "simpleusb.conf")
    (env.etc / "simpleusb.conf").write_text('#tryinclude "custom.conf"\n[1999]\nrxboost = no\n')
    (env.etc / "custom.conf").write_text("[x](!)\n")
    real = status.setup

    def setup(app):
        app[status.CLI_KEY] = fake
        real(app)
    monkeypatch.setattr(status, "setup", setup)
    return fake


async def test_tuning_session(env, driver):
    a = await env.make()
    _, state = await a.call("GET", "tuning/1999")
    assert state["interface"] == "SimpleUSB" and state["usb"] == "1-1.4:1.0" and not state["locked"]
    status_, res = await a.call("POST", "tuning/1999/set", {"name": "rxboost", "value": True})
    assert status_ == 200 and res["unsaved"]
    status_, res = await a.call("POST", "tuning/1999/set", {"name": "rxmixerset", "value": 650})
    assert {s["name"]: s["value"] for s in res["settings"]}["rxmixerset"] == 650
    status_, saved = await a.call("POST", "tuning/1999/save", {})
    assert status_ == 200 and "+rxboost = yes" in saved["diff"]
    assert saved["files"] == ["simpleusb.conf", "custom.conf"] and "b/custom.conf" in saved["diff"]
    status_, reverted = await a.call("POST", "tuning/1999/revert", {})
    assert status_ == 200 and "+rxboost = no" in reverted["diff"]
    assert {s["name"]: s["value"] for s in reverted["settings"]}["rxmixerset"] == 500
    _, overview = await a.call("GET", "status")


async def test_second_session_is_locked_out(env, driver):
    first = await env.make()
    second = await first.another()
    status_, _ = await first.call("POST", "tuning/1999/set", {"name": "rxboost", "value": True})
    assert status_ == 200
    status_, body = await second.call("POST", "tuning/1999/set", {"name": "rxboost", "value": False})
    assert status_ == 409 and body["error"] == "locked"
    _, state = await second.call("GET", "tuning/1999")
    assert state["locked"] and "dev is tuning" in state["locked_message"]
    await first.call("POST", "tuning/1999/release", {})
    status_, _ = await second.call("POST", "tuning/1999/set", {"name": "rxboost", "value": False})
    assert status_ == 200


async def test_invalid_values_and_nodes(env, driver):
    a = await env.make()
    status_, body = await a.call("POST", "tuning/1999/set", {"name": "rxmixerset", "value": 5000})
    assert status_ == 400
    status_, _ = await a.call("GET", "tuning/4242")
    assert status_ == 404
