"""SA818 through the API: the helper's commands run in-process on a temporary
root, with a stand-in sa818 that prints what the real one logs."""

import pytest

from asl_web_ui_priv import commands, sa818
from test_backups_api import cloud, env  # noqa: F401 (fixtures)

FAKE = """#!/bin/sh
echo "$@" >> {log}
case "$*" in
  *version*) echo "SA818: INFO: Firmware SA868S, version: V1.3" >&2 ;;
  *radio*) {radio} ;;
  *volume*) echo "SA818: INFO: +DMOSETVOLUME:0 Volume level: 6, OK" >&2 ;;
  *filters*) echo "SA818: INFO: +DMOSETFILTER:0 filters ..." >&2 ;;
esac
"""
OK = 'echo "SA818: INFO: +DMOSETGROUP:0, BW: Wide, OK" >&2'
REJECTED = 'echo "SA818: ERROR: SA818 programming error" >&2'
NO_MODULE = 'echo "Connection error" >&2; exit 1'

WANTED = {**sa818.DEFAULTS, "CURRENT_FREQ_RX": "146.52", "CURRENT_FREQ_TX": "146.52", "CURRENT_VOLUME": "6",
          "CURRENT_TONE": "CTCSS", "CURRENT_CTCSS_RX": "100.0", "CURRENT_CTCSS_TX": "100.0"}


@pytest.fixture
def module(env, monkeypatch):  # noqa: F811
    def install(radio=OK):
        tool = env.log.parent / "sa818"
        tool.write_text(FAKE.format(log=env.log.parent / "sa818.log", radio=radio))
        tool.chmod(0o755)
        monkeypatch.setattr(commands, "SA818_TOOL", str(tool))
        return env.log.parent / "sa818.log"
    env.install = install
    env.conf = env.root / "etc" / "sa818.conf"
    return env


async def test_defaults_before_anything_is_saved(module):
    module.install()
    a = await module.make()
    status_, body = await a.call("GET", "sa818")
    assert status_ == 200 and body["saved"] is False and body["settings"] == sa818.DEFAULTS
    assert body["choices"]["ctcss"][0] == "None" and "754N" in body["choices"]["dcs"]


async def test_save_and_program(module):
    calls = module.install()
    a = await module.make()
    status_, body = await a.call("PUT", "sa818", {"settings": WANTED})
    assert status_ == 200 and body["programmed"] and body["saved"], body
    text = module.conf.read_text()
    assert text.startswith("CURRENT_BAND=VHF\nCURRENT_BANDWIDTH=Wide\nCURRENT_FREQ_RX=146.5200\n")
    assert "CURRENT_PORT=\nCURRENT_SPEED=\n" in text
    assert calls.read_text().splitlines() == [
        "radio --bw 1 --frequency 146.5200 --squelch 1 --ctcss 100.0,100.0 --tail close",
        "volume --level 6",
        "filters --emphasis disable --highpass disable --lowpass disable"]
    _, body = await a.call("GET", "sa818")
    assert body["saved"] and body["settings"]["CURRENT_VOLUME"] == "6"

    status_, body = await a.call("POST", "sa818/program")
    assert status_ == 200 and body["programmed"] and not body["saved"]  # same settings: file untouched


async def test_module_errors_are_reported(module):
    module.install(radio=REJECTED)
    a = await module.make()
    _, body = await a.call("PUT", "sa818", {"settings": WANTED})
    assert body["programmed"] is False and any("programming error" in line for line in body["log"])
    assert module.conf.exists()  # saved first, as sa818-menu does
    module.install(radio=NO_MODULE)
    _, body = await a.call("POST", "sa818/program")
    assert body["programmed"] is False and body["log"][-1] == "Connection error"
    assert not any(line.startswith("# sa818 volume") for line in body["log"])  # stops at the first failure


async def test_validation(module):
    module.install()
    a = await module.make()
    for change, field in (({"CURRENT_FREQ_RX": "152.0000"}, "CURRENT_FREQ_RX"),
                          ({"CURRENT_FREQ_TX": "446.0000"}, "CURRENT_FREQ_TX"),
                          ({"CURRENT_CTCSS_RX": "100"}, "CURRENT_CTCSS_RX"),
                          ({"CURRENT_PORT": "/dev/ttyUSB9"}, "CURRENT_PORT"),
                          ({"CURRENT_PORT": "/dev/x;reboot"}, "CURRENT_PORT"),
                          ({"CURRENT_SQUELCH": "9"}, "CURRENT_SQUELCH")):
        status_, body = await a.call("PUT", "sa818", {"settings": {**WANTED, **change}})
        assert status_ == 400 and body["field"] == field, (change, body)
    assert not module.conf.exists()


async def test_version(module):
    module.install()
    a = await module.make()
    _, body = await a.call("POST", "sa818/version")
    assert body == {**body, "ok": True, "firmware": "SA868S, version: V1.3"}


def test_hand_edited_file_is_read_like_the_shell_does():
    s = sa818.parse('CURRENT_FREQ_RX="446.1000"\nCURRENT_SQUELCH=\n# comment\nCURRENT_PORT=/dev/ttyUSB0\nOTHER=1\n')
    assert s["CURRENT_FREQ_RX"] == "446.1000" and s["CURRENT_SQUELCH"] == "1" and s["CURRENT_PORT"] == "/dev/ttyUSB0"


def test_ports(tmp_path):
    (tmp_path / "dev").mkdir()
    for name in ("serial0", "ttyUSB0", "ttyUSB1", "tty1"):
        (tmp_path / "dev" / name).touch()
    assert sa818.ports(str(tmp_path)) == ["/dev/serial0", "/dev/ttyUSB0", "/dev/ttyUSB1"]
