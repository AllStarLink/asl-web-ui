"""System stats for the Overview page (#61): /proc and /sys parsing, the Pi's throttle flags."""

import subprocess
from pathlib import Path

import pytest

from asl_web_ui import sysstats
from asl_web_ui.modules import status
from asl_web_ui.privileged import PrivError
from asl_web_ui_priv import commands

# Taken from a Raspberry Pi 4 running the ASL3 appliance.
STAT = "cpu  19986803 2283 12904188 1430394605 2551206 0 4496022 0 0 0\ncpu0 1 2 3 4 5 6 7 8 0 0\nintr 1 2 3\n"
MEMINFO = """MemTotal:        3885816 kB
MemFree:          812345 kB
MemAvailable:    3391456 kB
SwapTotal:       2097148 kB
SwapFree:        2047148 kB
"""


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def pi(tmp_path):
    proc, sys = tmp_path / "proc", tmp_path / "sys"
    write(proc / "stat", STAT)
    write(proc / "loadavg", "0.31 0.20 0.12 1/304 1250025\n")
    write(proc / "meminfo", MEMINFO)
    write(proc / "device-tree" / "model", "Raspberry Pi 4 Model B Rev 1.5\x00")
    write(sys / "class" / "thermal" / "thermal_zone0" / "type", "cpu-thermal\n")
    write(sys / "class" / "thermal" / "thermal_zone0" / "temp", "52582\n")
    return proc, sys


def test_cpu_times_and_percent(pi):
    proc, _ = pi
    idle, total = sysstats.cpu_times(proc)
    assert idle == 1430394605 + 2551206
    assert total == 19986803 + 2283 + 12904188 + 1430394605 + 2551206 + 4496022
    assert sysstats.cpu_percent((100, 200), (150, 400)) == 75.0
    assert sysstats.cpu_percent((100, 200), (100, 200)) is None


def test_load_memory_temperature_model(pi):
    proc, sys = pi
    assert sysstats.load_average(proc) == [0.31, 0.20, 0.12]
    assert sysstats.memory(proc) == {
        "total": 3885816 * 1024, "used": (3885816 - 3391456) * 1024,
        "swap_total": 2097148 * 1024, "swap_used": 50000 * 1024,
    }
    assert sysstats.cpu_temperature(sys) == 52.6
    assert sysstats.pi_model(proc) == "Raspberry Pi 4 Model B Rev 1.5"


def test_missing_sources_give_none(tmp_path):
    assert sysstats.cpu_times(tmp_path) is None
    assert sysstats.load_average(tmp_path) is None
    assert sysstats.memory(tmp_path) is None
    assert sysstats.cpu_temperature(tmp_path) is None
    assert sysstats.pi_model(tmp_path) is None
    assert sysstats.disk(str(tmp_path / "nowhere")) is None


def test_temperature_ignores_acpitz_and_uses_hwmon(tmp_path):
    write(tmp_path / "class" / "thermal" / "thermal_zone0" / "type", "acpitz\n")
    write(tmp_path / "class" / "thermal" / "thermal_zone0" / "temp", "27800\n")
    assert sysstats.cpu_temperature(tmp_path) is None
    write(tmp_path / "class" / "hwmon" / "hwmon2" / "name", "k10temp\n")
    write(tmp_path / "class" / "hwmon" / "hwmon2" / "temp1_input", "61250\n")
    assert sysstats.cpu_temperature(tmp_path) == 61.2


def test_non_pi_model_is_none(tmp_path):
    write(tmp_path / "device-tree" / "model", "Some Other Board\x00")
    assert sysstats.pi_model(tmp_path) is None


def test_cpu_percent_needs_a_recent_previous_sample(pi):
    proc, sys = pi
    now = [0.0]
    stats = sysstats.SysStats(proc, sys, clock=lambda: now[0])
    assert stats.collect()["cpu_percent"] is None  # nothing to compare with yet
    write(proc / "stat", "cpu  19986903 2283 12904188 1430394905 2551206 0 4496022 0 0 0\n")
    now[0] = 5.0
    assert stats.collect()["cpu_percent"] == 25.0  # 100 busy of 400
    now[0] = 5.0 + sysstats.CPU_SAMPLE_MAX_AGE + 1
    assert stats.collect()["cpu_percent"] is None  # too old to call "current"


def test_decode_throttled():
    assert sysstats.decode_throttled(0) == {
        "now": dict.fromkeys(sysstats.THROTTLE_BITS, False),
        "since_boot": dict.fromkeys(sysstats.THROTTLE_BITS, False),
    }
    flags = sysstats.decode_throttled(0x50005)
    assert flags["now"] == {"under_voltage": True, "freq_capped": False, "throttled": True, "soft_temp_limit": False}
    assert flags["since_boot"] == {"under_voltage": True, "freq_capped": False, "throttled": True,
                                   "soft_temp_limit": False}
    assert sysstats.decode_throttled(0x80000)["since_boot"]["soft_temp_limit"] is True


class FakePriv:
    def __init__(self, value=0x50000, error=None):
        self.value, self.error, self.calls = value, error, 0

    async def call(self, command, args=None, user="", on_output=None, timeout=960):
        assert command == "pi.throttled"
        self.calls += 1
        if self.error:
            raise PrivError(self.error, "unavailable")
        return {"value": self.value}


def unit(state):
    async def unit_state(name):
        return {"ActiveState": state, "SubState": "dead"}
    return unit_state


async def test_status_includes_system_and_asks_for_pi_flags_once_a_minute(pi):
    proc, sys = pi
    priv = FakePriv()
    hub = status.StatusHub(None, unit_state=unit("inactive"), priv=priv, stats=sysstats.SysStats(proc, sys))
    data = await hub.collect()
    system = data["system"]
    assert system["pi_model"] == "Raspberry Pi 4 Model B Rev 1.5"
    assert system["load_average"] == [0.31, 0.20, 0.12]
    assert system["pi_throttled"]["since_boot"]["under_voltage"] is True
    assert system["pi_throttled"]["now"]["under_voltage"] is False
    await hub.collect()
    assert priv.calls == 1  # cached for PI_THROTTLE_INTERVAL


async def test_pi_flags_unavailable_is_none(pi):
    proc, sys = pi
    hub = status.StatusHub(None, unit_state=unit("inactive"), priv=FakePriv(error="vcgencmd is not installed"),
                           stats=sysstats.SysStats(proc, sys))
    assert (await hub.collect())["system"]["pi_throttled"] is None


async def test_no_pi_no_helper_call(tmp_path):
    priv = FakePriv()
    hub = status.StatusHub(None, unit_state=unit("inactive"), priv=priv, stats=sysstats.SysStats(tmp_path, tmp_path))
    assert (await hub.collect())["system"]["pi_throttled"] is None
    assert priv.calls == 0


def test_pi_throttled_command(monkeypatch):
    def run(argv, **kwargs):
        assert argv == [commands.VCGENCMD, "get_throttled"]
        return subprocess.CompletedProcess(argv, 0, "throttled=0x50005\n", "")
    monkeypatch.setattr(commands.subprocess, "run", run)
    assert commands.pi_throttled({}, None) == {"value": 0x50005}


@pytest.mark.parametrize("returncode,stdout", [(0, "nonsense\n"), (0, "throttled=zz\n"), (255, "")])
def test_pi_throttled_command_bad_output(monkeypatch, returncode, stdout):
    monkeypatch.setattr(commands.subprocess, "run",
                        lambda argv, **kw: subprocess.CompletedProcess(argv, returncode, stdout, "VCHI failed"))
    with pytest.raises(commands.CommandError):
        commands.pi_throttled({}, None)


def test_pi_throttled_command_missing(monkeypatch):
    def run(argv, **kwargs):
        raise FileNotFoundError(argv[0])
    monkeypatch.setattr(commands.subprocess, "run", run)
    with pytest.raises(commands.CommandError) as err:
        commands.pi_throttled({}, None)
    assert err.value.code == "unavailable"
