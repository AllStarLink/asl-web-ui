"""System stats for the Overview page's System Stats card (#61).

Everything here reads /proc, /sys or statvfs: cheap, unprivileged and never
touching Asterisk. The status poller adds collect()'s result to each
snapshot under "system".

On a Raspberry Pi the firmware's throttle flags (under-voltage, frequency
capping, throttling, soft temperature limit) come from `vcgencmd
get_throttled`, which needs /dev/vcio and so runs in the privileged helper
(command pi.throttled); decode_throttled() turns its value into flags.
Kernels from 6.12 on no longer offer them in sysfs.
"""

import os
import time
from pathlib import Path

PROC = Path("/proc")
SYS = Path("/sys")

# Thermal zone and hwmon names that measure the CPU itself. Others (acpitz,
# for one) are often a fixed or unrelated reading, so they are not used.
CPU_THERMAL_ZONES = ("cpu-thermal", "cpu_thermal", "x86_pkg_temp", "soc_thermal", "cpu0-thermal")
CPU_HWMON = ("cpu_thermal", "coretemp", "k10temp", "zenpower")

# How old the previous /proc/stat sample may be and still give a "current" CPU use.
CPU_SAMPLE_MAX_AGE = 30.0

# Bits of the firmware's get_throttled value.
THROTTLE_BITS = {
    "under_voltage": 0,
    "freq_capped": 1,
    "throttled": 2,
    "soft_temp_limit": 3,
}
SINCE_BOOT_SHIFT = 16


def _read(path: Path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None


def cpu_times(proc: Path = PROC) -> tuple[int, int] | None:
    """(idle, total) jiffies from the aggregate "cpu" line of /proc/stat."""
    text = _read(proc / "stat")
    if not text:
        return None
    for line in text.splitlines():
        fields = line.split()
        if fields and fields[0] == "cpu":
            try:
                values = [int(v) for v in fields[1:]]
            except ValueError:
                return None
            # user nice system idle iowait irq softirq steal [guest guest_nice]:
            # guest time is already counted in user and nice.
            values = values[:8]
            if len(values) < 4:
                return None
            idle = values[3] + (values[4] if len(values) > 4 else 0)
            return idle, sum(values)
    return None


def cpu_percent(before: tuple[int, int], after: tuple[int, int]) -> float | None:
    idle = after[0] - before[0]
    total = after[1] - before[1]
    if total <= 0 or idle < 0:
        return None
    return round(100.0 * (total - idle) / total, 1)


def load_average(proc: Path = PROC) -> list[float] | None:
    text = _read(proc / "loadavg")
    try:
        return [float(v) for v in text.split()[:3]] if text else None
    except ValueError:
        return None


def memory(proc: Path = PROC) -> dict | None:
    """Bytes of memory and swap; "used" memory is what is not available to programs."""
    text = _read(proc / "meminfo")
    if not text:
        return None
    kb: dict[str, int] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            kb[key] = int(parts[0])
    if "MemTotal" not in kb or "MemAvailable" not in kb:
        return None
    swap_total = kb.get("SwapTotal", 0)
    return {
        "total": kb["MemTotal"] * 1024,
        "used": (kb["MemTotal"] - kb["MemAvailable"]) * 1024,
        "swap_total": swap_total * 1024,
        "swap_used": (swap_total - kb.get("SwapFree", swap_total)) * 1024,
    }


def disk(path: str = "/") -> dict | None:
    try:
        st = os.statvfs(path)
    except OSError:
        return None
    total = st.f_blocks * st.f_frsize
    # As df counts it: blocks reserved for root are neither used nor available.
    used = (st.f_blocks - st.f_bfree) * st.f_frsize
    available = st.f_bavail * st.f_frsize
    return {"path": path, "total": total, "used": used, "available": available}


def _millidegrees(text: str | None) -> float | None:
    try:
        return round(int(text.strip()) / 1000, 1) if text else None
    except ValueError:
        return None


def cpu_temperature(sys: Path = SYS) -> float | None:
    """Degrees Celsius from the CPU's thermal zone or hwmon sensor, or None (most VMs)."""
    zones = sorted((sys / "class" / "thermal").glob("thermal_zone*"))
    for wanted in CPU_THERMAL_ZONES:
        for zone in zones:
            if (_read(zone / "type") or "").strip() == wanted:
                value = _millidegrees(_read(zone / "temp"))
                if value is not None:
                    return value
    for hwmon in sorted((sys / "class" / "hwmon").glob("hwmon*")):
        if (_read(hwmon / "name") or "").strip() in CPU_HWMON:
            value = _millidegrees(_read(hwmon / "temp1_input"))
            if value is not None:
                return value
    return None


def pi_model(proc: Path = PROC) -> str | None:
    """"Raspberry Pi 4 Model B Rev 1.5" on a Pi, otherwise None."""
    text = _read(proc / "device-tree" / "model")
    model = text.replace("\x00", "").strip() if text else ""
    return model if model.startswith("Raspberry Pi") else None


def decode_throttled(value: int) -> dict:
    """{"now": {flag: bool}, "since_boot": {flag: bool}}."""
    return {
        "now": {name: bool(value >> bit & 1) for name, bit in THROTTLE_BITS.items()},
        "since_boot": {name: bool(value >> (bit + SINCE_BOOT_SHIFT) & 1) for name, bit in THROTTLE_BITS.items()},
    }


class SysStats:
    """Keeps the previous /proc/stat sample so each round reports CPU use since the last."""

    def __init__(self, proc: Path = PROC, sys: Path = SYS, root: str = "/", clock=time.monotonic):
        self.proc = proc
        self.sys = sys
        self.root = root
        self.clock = clock
        self._cpu: tuple[float, tuple[int, int]] | None = None
        self._pi_model: str | None | bool = False  # False: not looked up yet

    @property
    def model(self) -> str | None:
        if self._pi_model is False:
            self._pi_model = pi_model(self.proc)
        return self._pi_model

    def _cpu_percent(self) -> float | None:
        now = self.clock()
        sample = cpu_times(self.proc)
        previous, self._cpu = self._cpu, (None if sample is None else (now, sample))
        if previous is None or sample is None or now - previous[0] > CPU_SAMPLE_MAX_AGE:
            return None
        return cpu_percent(previous[1], sample)

    def collect(self) -> dict:
        return {
            "cpu_percent": self._cpu_percent(),
            "cpu_count": os.cpu_count(),
            "load_average": load_average(self.proc),
            "memory": memory(self.proc),
            "disk": disk(self.root),
            "temperature": cpu_temperature(self.sys),
            "pi_model": self.model,
            "pi_throttled": None,  # filled in by the status poller on a Pi
        }
