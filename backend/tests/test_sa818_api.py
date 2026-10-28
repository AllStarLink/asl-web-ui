"""SA818 through the API: the helper's commands run in-process on a temporary
root, with a stand-in sa818 that prints what the real one logs."""

import os
import pty
import threading

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


async def test_edit_the_file_as_text(module):
    module.install()
    a = await module.make()
    status_, _ = await a.call("GET", "sa818/file")
    assert status_ == 404  # nothing saved yet
    await a.call("PUT", "sa818", {"settings": WANTED})
    _, f = await a.call("GET", "sa818/file")
    assert f["findings"] == [] and f["path"] == "/etc/sa818.conf"
    new = f["content"].replace("CURRENT_VOLUME=6", "CURRENT_VOLUME=7") + "# note\n"
    _, plan = await a.call("POST", "sa818/file/plan", {"content": new, "hash": f["hash"]})
    assert "+CURRENT_VOLUME=7" in plan["diff"]
    status_, _ = await a.call("POST", f"sa818/file/plans/{plan['id']}/apply", {})
    assert status_ == 200 and module.conf.read_text() == new
    _, body = await a.call("GET", "config/system-files")
    assert body["sa818"]["path"] == "/etc/sa818.conf" and body["sa818"]["writable"]


async def test_text_that_the_shell_could_run_is_refused(module):
    module.install()
    a = await module.make()
    await a.call("PUT", "sa818", {"settings": WANTED})
    _, f = await a.call("GET", "sa818/file")
    for bad in ("CURRENT_VOLUME=$(reboot)\n", "touch /tmp/x\n", "CURRENT_BAND=VHF\x0b;id\n"):
        _, check = await a.call("POST", "sa818/file/check", {"content": f["content"] + bad})
        assert check["findings"][-1]["severity"] == "error", bad
        _, plan = await a.call("POST", "sa818/file/plan", {"content": f["content"] + bad, "hash": f["hash"]})
        status_, body = await a.call("POST", f"sa818/file/plans/{plan['id']}/apply", {"confirm_errors": True})
        assert status_ == 400 and "Nothing was written" in body["message"], bad
    assert module.conf.read_text() == f["content"]


class FakeModule:
    """An SA818 at the far end of a pseudo-terminal: answers what the one on
    node40608 answered (SA818S firmware V1.1)."""

    def __init__(self):
        # The far end stays open: the master reads EIO once no one has the port open.
        self.master, self.slave = pty.openpty()
        self.path = os.ttyname(self.slave)
        self.heard = []
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        buf = b""
        while True:
            try:
                buf += os.read(self.master, 256)
            except OSError:
                return
            while b"\r\n" in buf:
                line, buf = buf.split(b"\r\n", 1)
                self.heard.append(line.decode())
                reply = {b"AT+DMOCONNECT": b"+DMOCONNECT:0", b"AT+VERSION": b"+VERSION:SA818S_V1.1"}.get(line)
                if reply:
                    os.write(self.master, reply + b"\r\n")

    def close(self):
        os.close(self.master)
        os.close(self.slave)


@pytest.fixture
def ports(module, monkeypatch):
    """/dev/ttyUSB0 is the module, /dev/serial0 -> ttyAMA0 a quiet port."""
    monkeypatch.setattr(sa818, "PROBE_TIMEOUT", 0.2)
    dev = module.root / "dev"
    dev.mkdir()
    fake, (quiet, quiet_slave) = FakeModule(), pty.openpty()
    (dev / "ttyUSB0").symlink_to(fake.path)
    (dev / "ttyAMA0").symlink_to(os.ttyname(quiet_slave))
    (dev / "serial0").symlink_to("ttyAMA0")
    module.fake = fake
    yield module
    fake.close()
    os.close(quiet)
    os.close(quiet_slave)


def test_probe_finds_the_module_and_nothing_else(tmp_path):
    fake = FakeModule()
    try:
        assert sa818.probe(fake.path, "9600") == "SA818S_V1.1"
        assert fake.heard == ["AT+DMOCONNECT", "AT+VERSION"]
    finally:
        fake.close()
    master, slave = pty.openpty()
    try:
        assert sa818.probe(os.ttyname(slave), "9600", timeout=0.1) is None  # silence
    finally:
        os.close(master)
        os.close(slave)
    (tmp_path / "file").write_text("")
    assert sa818.probe(str(tmp_path / "file"), "9600") is None  # not a terminal
    assert sa818.probe(str(tmp_path / "missing"), "9600") is None


async def test_detect(ports):
    ports.install()
    a = await ports.make()
    status_, body = await a.call("GET", "sa818/detect")
    assert status_ == 200, body
    # serial0 and ttyAMA0 are the same device: asked once, under the first name.
    assert body == {"found": [{"port": "/dev/ttyUSB0", "speed": "9600", "firmware": "SA818S_V1.1"}],
                    "probed": ["/dev/serial0", "/dev/ttyUSB0"], "reachable": True, "saved": False}
    assert ports.fake.heard == ["AT+DMOCONNECT", "AT+VERSION"]
    _, again = await a.call("GET", "sa818/detect")
    assert again == body and len(ports.fake.heard) == 2  # kept, not asked again
    await a.call("POST", "sa818/detect")
    assert len(ports.fake.heard) == 4


async def test_detect_checks_the_saved_port_and_speed(ports):
    ports.install()
    a = await ports.make()
    await a.call("GET", "sa818/detect")
    # Saved on the wrong port and speed, as node40608 was: found, but not reachable.
    await a.call("PUT", "sa818", {"settings": {**WANTED, "CURRENT_PORT": "/dev/ttyAMA0", "CURRENT_SPEED": "115200"}})
    _, body = await a.call("GET", "sa818/detect")  # saving forgets what was found
    assert body["saved"] and body["found"][0]["port"] == "/dev/ttyUSB0" and not body["reachable"]
    await a.call("PUT", "sa818", {"settings": {**WANTED, "CURRENT_PORT": "/dev/ttyUSB0", "CURRENT_SPEED": "9600"}})
    _, body = await a.call("GET", "sa818/detect")
    assert body["reachable"]
