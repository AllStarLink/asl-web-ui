"""SA818 RF modules, as sa818-menu (asl3 package) handles them.

The module cannot be read back, so the settings live in /etc/sa818.conf,
the file sa818-menu keeps: KEY=VALUE lines that sa818-menu loads with the
shell's "." as root. Every value written here comes from a fixed list or a
strict pattern, so the file stays safe to source. The module is programmed
by running the sa818 command three times (radio, volume, filters) with the
arguments sa818-menu builds; sa818 exits 0 even when the module rejects a
command, so its log lines are checked for errors too.
"""

import glob
import os
import re
import subprocess

CONF = "/etc/sa818.conf"
TOOL = "/usr/bin/sa818"
PORT_PATTERNS = ["/dev/serial[0-9]", "/dev/ttyAMA[0-9]*", "/dev/ttyUSB[0-9]*", "/dev/ttyACM[0-9]*", "/dev/ttyS0"]
SPEEDS = ["300", "1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200"]

CTCSS = ["None", "67.0", "71.9", "74.4", "77.0", "79.7", "82.5", "85.4", "88.5", "91.5", "94.8", "97.4", "100.0",
         "103.5", "107.2", "110.9", "114.8", "118.8", "123.0", "127.3", "131.8", "136.5", "141.3", "146.2", "151.4",
         "156.7", "162.2", "167.9", "173.8", "179.9", "186.2", "192.8", "203.5", "210.7", "218.1", "225.7", "233.6",
         "241.8", "250.3"]
DCS = ["023", "025", "026", "031", "032", "036", "043", "047", "051", "053", "054", "065", "071", "072", "073",
       "074", "114", "115", "116", "125", "131", "132", "134", "143", "152", "155", "156", "162", "165", "172",
       "174", "205", "223", "226", "243", "244", "245", "251", "261", "263", "265", "271", "306", "311", "315",
       "331", "343", "346", "351", "364", "365", "371", "411", "412", "413", "423", "431", "432", "445", "464",
       "465", "466", "503", "506", "516", "532", "546", "565", "606", "612", "624", "627", "631", "632", "654",
       "662", "664", "703", "712", "723", "731", "732", "734", "743", "754"]
DCS_CODES = ["None"] + [c + d for c in DCS for d in "IN"]

# sa818-menu's keys, order and defaults (do_settings_load / do_settings_store).
DEFAULTS = {
    "CURRENT_BAND": "VHF",
    "CURRENT_BANDWIDTH": "Wide",
    "CURRENT_FREQ_RX": "000.0000",
    "CURRENT_FREQ_TX": "000.0000",
    "CURRENT_SQUELCH": "1",
    "CURRENT_VOLUME": "1",
    "CURRENT_TONE": "None",
    "CURRENT_CTCSS_RX": "None",
    "CURRENT_CTCSS_TX": "None",
    "CURRENT_DCS_RX": "None",
    "CURRENT_DCS_TX": "None",
    "CURRENT_TAIL_TONE": "Closed",
    "CURRENT_EMPHASIS": "Disabled",
    "CURRENT_FILTER_HIGH_PASS": "Disabled",
    "CURRENT_FILTER_LOW_PASS": "Disabled",
    "CURRENT_PORT": "",
    "CURRENT_SPEED": "",
}
CHOICES = {
    "CURRENT_BAND": ["VHF", "UHF"],
    "CURRENT_BANDWIDTH": ["Narrow", "Wide"],
    "CURRENT_SQUELCH": [str(i) for i in range(0, 9)],
    "CURRENT_VOLUME": [str(i) for i in range(1, 9)],
    "CURRENT_TONE": ["None", "CTCSS", "DCS"],
    "CURRENT_CTCSS_RX": CTCSS,
    "CURRENT_CTCSS_TX": CTCSS,
    "CURRENT_DCS_RX": DCS_CODES,
    "CURRENT_DCS_TX": DCS_CODES,
    "CURRENT_TAIL_TONE": ["Opened", "Closed"],
    "CURRENT_EMPHASIS": ["Enabled", "Disabled"],
    "CURRENT_FILTER_HIGH_PASS": ["Enabled", "Disabled"],
    "CURRENT_FILTER_LOW_PASS": ["Enabled", "Disabled"],
    "CURRENT_SPEED": [""] + SPEEDS,
}
# sa818-menu's limits for each band (set_band_limits); whole MHz are compared.
BAND_LIMITS = {"VHF": (134, 174), "UHF": (400, 480)}
_FREQ = re.compile(r"^[0-9]{3}\.[0-9]*$")
_PORT = re.compile(r"^/dev/[A-Za-z0-9_./-]+$")


class Invalid(Exception):
    def __init__(self, message: str, field: str):
        super().__init__(message)
        self.message = message
        self.field = field


def parse(text: str) -> dict[str, str]:
    """The settings in a sa818.conf, with sa818-menu's defaults for anything missing."""
    found = {}
    for line in text.splitlines():
        m = re.match(r"^\s*(CURRENT_[A-Z_]+)=(.*)$", line)
        if m and m.group(1) in DEFAULTS:
            value = m.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            found[m.group(1)] = value
    settings = {k: found.get(k) or v for k, v in DEFAULTS.items()}
    for key in ("CURRENT_PORT", "CURRENT_SPEED"):
        settings[key] = found.get(key, "")
    return settings


def render(settings: dict[str, str]) -> str:
    return "".join(f"{k}={settings[k]}\n" for k in DEFAULTS)


def _mhz(value: str) -> int:
    return int(value.split(".")[0])


def check(settings: dict, ports_exist=os.path.exists) -> dict[str, str]:
    """Validate wanted settings; returns them normalized as sa818-menu stores them."""
    out = {}
    for key, default in DEFAULTS.items():
        value = settings.get(key, default)
        if not isinstance(value, str):
            raise Invalid(f"{key} must be text.", key)
        value = value.strip()
        if key in CHOICES and value not in CHOICES[key]:
            raise Invalid(f"{value!r} is not a valid choice for {key}.", key)
        out[key] = value
    low, high = BAND_LIMITS[out["CURRENT_BAND"]]
    for key, what in (("CURRENT_FREQ_RX", "receive"), ("CURRENT_FREQ_TX", "transmit")):
        value = out[key]
        if not _FREQ.match(value) or not low <= _mhz(value) <= high:
            raise Invalid(f"The {what} frequency must be between {low}.0000 and {high}.0000 MHz "
                          f"({out['CURRENT_BAND']}), as xxx.xxxx.", key)
        out[key] = f"{float(value):08.4f}"
    rx = float(out["CURRENT_FREQ_RX"])
    if not (144 < rx < 148 or 420 < rx < 450):
        # The sa818 command itself refuses other receive frequencies.
        raise Invalid("sa818 programs receive frequencies in the amateur bands only: above 144 and below 148 MHz, "
                      "or above 420 and below 450 MHz.", "CURRENT_FREQ_RX")
    port = out["CURRENT_PORT"]
    if port and (not _PORT.match(port) or ".." in port or not ports_exist(port)):
        raise Invalid(f"{port} is not a serial device on this server.", "CURRENT_PORT")
    return out


def tool_args(s: dict[str, str]) -> list[list[str]]:
    """The sa818 commands sa818-menu runs (do_sa818_update), in order."""
    base = []
    if s["CURRENT_PORT"]:
        base += ["--port", s["CURRENT_PORT"]]
    if s["CURRENT_SPEED"]:
        base += ["--speed", s["CURRENT_SPEED"]]
    radio = base + ["radio", "--bw", "0" if s["CURRENT_BANDWIDTH"] == "Narrow" else "1",
                    "--frequency", s["CURRENT_FREQ_RX"]]
    if s["CURRENT_FREQ_RX"] != s["CURRENT_FREQ_TX"]:
        radio += ["--offset", f"{float(s['CURRENT_FREQ_TX']) - float(s['CURRENT_FREQ_RX']):.4f}"]
    radio += ["--squelch", s["CURRENT_SQUELCH"]]
    if s["CURRENT_TONE"] == "CTCSS":
        if s["CURRENT_CTCSS_RX"] != "None" or s["CURRENT_CTCSS_TX"] != "None":
            radio += ["--ctcss", f"{s['CURRENT_CTCSS_TX']},{s['CURRENT_CTCSS_RX']}",
                      "--tail", "open" if s["CURRENT_TAIL_TONE"] == "Opened" else "close"]
        else:
            radio += ["--ctcss", "None,None"]
    elif s["CURRENT_TONE"] == "DCS":
        if s["CURRENT_DCS_RX"] != "None" or s["CURRENT_DCS_TX"] != "None":
            radio += ["--dcs", f"{s['CURRENT_DCS_TX']},{s['CURRENT_DCS_RX']}"]
        else:
            radio += ["--dcs", "None,None"]
    # No tone: sa818 sends tone code 0000 (none) when neither option is given.
    volume = base + ["volume", "--level", s["CURRENT_VOLUME"]]
    filters = base + ["filters"] + [
        a for key, opt in (("CURRENT_EMPHASIS", "--emphasis"), ("CURRENT_FILTER_HIGH_PASS", "--highpass"),
                           ("CURRENT_FILTER_LOW_PASS", "--lowpass"))
        for a in (opt, "enable" if s[key] == "Enabled" else "disable")]
    return [radio, volume, filters]


def ports(root: str = "/") -> list[str]:
    found = []
    for pattern in PORT_PATTERNS:
        for path in sorted(glob.glob(os.path.join(root, pattern.lstrip("/")))):
            found.append("/" + os.path.relpath(path, root))
    return found


def run(tool: str, args: list[str], timeout: float = 30) -> tuple[bool, list[str]]:
    """Run sa818; returns (ok, log lines). Failure: a non-zero exit or an ERROR line."""
    try:
        proc = subprocess.run([tool, *args], capture_output=True, text=True, timeout=timeout,
                              env={"PATH": "/usr/bin:/bin", "LOGLEVEL": "INFO"})
    except FileNotFoundError:
        return False, [f"{tool} is not installed (it comes with the asl3 package)."]
    except subprocess.TimeoutExpired:
        return False, ["sa818 did not finish within 30 seconds."]
    lines = [line for line in (proc.stdout + proc.stderr).splitlines() if line.strip()]
    ok = proc.returncode == 0 and not any(": ERROR:" in line or "Traceback" in line for line in lines)
    return ok, lines
