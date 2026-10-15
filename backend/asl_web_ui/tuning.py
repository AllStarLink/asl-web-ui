"""Radio interface tuning through the drivers' "tune menu-support" commands.

This is the interface the drivers provide for the classic tune menus
(simpleusb-tune-menu, radio-tune-menu), in app_rpt's chan_simpleusb.c and
chan_usbradio.c (tune_menusupport):

- "<driver> active NAME" selects the device the commands act on (one per
  driver, shared by everyone, so a page holds a lock while tuning);
- "menu-support 0+4" (SimpleUSB) / "0+10" (USBRadio) returns the settings as
  comma-separated values, in an order the drivers promise to keep;
- a letter with a value changes a setting (in memory), "j" saves them to the
  driver's .conf file, "l" sends a test tone (three 1 s bursts);
- "b" (RX level bars) and "v" (COS/CTCSS/PTT status) are live displays that
  run until the CLI connection sends input or closes: the backend streams
  them with "asterisk -rx" and kills the client to stop.
Numeric one-shot variants are requested upstream (docs/upstream-changes.md).
"""

import re
from dataclasses import dataclass, field

MS_PER_FRAME = 20
UNASSIGNED = re.compile(r"Device (\S+) is selected, the associated USB device string (\S*) ?was not found")


@dataclass
class Setting:
    name: str
    label: str
    kind: str  # level | bool | choice | delay
    letter: str
    options: dict[int, str] = field(default_factory=dict)
    help: str = ""
    needs_device: bool = False


@dataclass
class Driver:
    interface: str
    prefix: str  # CLI command prefix
    csv: str  # menu-support form returning all settings
    fields: list[str]  # names of the CSV values, in order
    file: str
    tune_menu: str
    settings: list[Setting]
    calibrations: dict[str, tuple[str, str]] = field(default_factory=dict)  # name -> (letter, description)

    def setting(self, name: str) -> Setting | None:
        return next((s for s in self.settings if s.name == name), None)


SIMPLEUSB = Driver(
    interface="SimpleUSB",
    prefix="susb",
    csv="0+4",
    fields=["txmixaset", "txmixbset", "echomode", "rxboost", "preemphasis", "deemphasis", "plfilter", "invertptt",
            "rxcdtype", "rxsdtype", "rxondelay", "txoffdelay", "rxmixerset", "sidetone_max", "tx_max", "rx_max"],
    file="simpleusb.conf",
    tune_menu="/usr/sbin/simpleusb-tune-menu",
    settings=[
        Setting("rxmixerset", "Receive level", "level", "c", help="Audio level from the radio (0-999).",
                needs_device=True),
        Setting("txmixaset", "Transmit level, channel A", "level", "f", help="Audio level to the radio (0-999).",
                needs_device=True),
        Setting("txmixbset", "Transmit level, channel B", "level", "g", needs_device=True),
        Setting("rxboost", "Receive boost", "bool", "m", help="Extra receive gain for low-level radios."),
        Setting("preemphasis", "Transmit pre-emphasis", "bool", "n"),
        Setting("deemphasis", "Receive de-emphasis", "bool", "o"),
        Setting("plfilter", "Receive CTCSS (PL) filter", "bool", "p", help="Removes sub-audible tones from received audio."),
        Setting("invertptt", "Invert PTT", "bool", "q", help="Key the transmitter by opening the PTT line instead of grounding it."),
        Setting("rxcdtype", "Carrier detect (COS) from", "choice", "r",
                {0: "Not used", 3: "USB input", 4: "USB input, inverted", 5: "Parallel port", 6: "Parallel port, inverted"}),
        Setting("rxsdtype", "CTCSS detect from", "choice", "s",
                {0: "Not used", 1: "USB input", 2: "USB input, inverted", 4: "Parallel port", 5: "Parallel port, inverted"}),
        Setting("rxondelay", "Receive on delay", "delay", "t", help="Ignore carrier detect for this long (debounce)."),
        Setting("txoffdelay", "Transmit off delay", "delay", "u", help="Ignore received audio this long after transmitting."),
        Setting("echomode", "Echo mode", "bool", "k", help="Repeat received audio back (testing)."),
    ],
)

USBRADIO = Driver(
    interface="USBRadio",
    prefix="radio",
    csv="0+10",
    fields=["flatrx", "txhasctcss", "echomode", "rxboost", "txboost", "rxcdtype", "rxsdtype", "rxondelay", "txoffdelay",
            "txprelim", "txlimonly", "rxdemod", "txmixa", "txmixb", "rxmixerset", "rxvoiceadj", "rxsquelchadj",
            "txmixaset", "txmixbset", "txctcssadj", "micplaymax", "spkrmax", "micmax", "txslimsp"],
    file="usbradio.conf",
    tune_menu="/usr/sbin/radio-tune-menu",
    settings=[
        Setting("rxvoice", "Receive voice level", "level", "c", needs_device=True,
                help="With flat (discriminator) audio this is the DSP gain; otherwise the sound card's input level."),
        Setting("rxsquelchadj", "Squelch level", "level", "e", needs_device=True, help="Lower opens with weaker signals."),
        Setting("txvoice", "Transmit voice level", "level", "f", needs_device=True),
        Setting("txctcssadj", "Transmit CTCSS level", "level", "h", needs_device=True),
        Setting("rxboost", "Receive boost", "bool", "m"),
        Setting("txboost", "Transmit boost", "bool", "n"),
        Setting("rxcdtype", "Carrier detect (COS) from", "choice", "o",
                {0: "Not used", 1: "DSP (noise squelch)", 2: "VOX", 3: "USB input", 4: "USB input, inverted",
                 5: "Parallel port", 6: "Parallel port, inverted"}),
        Setting("rxsdtype", "CTCSS detect from", "choice", "p",
                {0: "Not used", 1: "USB input", 2: "USB input, inverted", 3: "DSP decoder", 4: "Parallel port",
                 5: "Parallel port, inverted"}),
        Setting("rxdemod", "Receive audio", "choice", "u", {0: "None", 1: "Speaker (de-emphasized)", 2: "Flat (discriminator)"}),
        Setting("txmixa", "Transmit channel A carries", "choice", "w",
                {0: "Nothing", 1: "Voice", 2: "Tone (CTCSS)", 3: "Composite (voice and tone)", 4: "Auxiliary voice"}),
        Setting("txmixb", "Transmit channel B carries", "choice", "x",
                {0: "Nothing", 1: "Voice", 2: "Tone (CTCSS)", 3: "Composite (voice and tone)", 4: "Auxiliary voice"}),
        Setting("txprelim", "Transmit pre-emphasis and limiting", "bool", "s"),
        Setting("txlimonly", "Transmit limiting only", "bool", "t"),
        Setting("rxondelay", "Receive on delay", "delay", "q"),
        Setting("txoffdelay", "Transmit off delay", "delay", "r"),
        Setting("echomode", "Echo mode", "bool", "k"),
    ],
    calibrations={
        "rxnoise": ("a", "Receive noise level: with no signal and the squelch open (unsquelched discriminator noise)."),
        "rxvoice": ("i", "Receive voice level: with an on-channel signal carrying a 1 kHz tone at 3 kHz deviation."),
        "rxctcss": ("d", "Receive CTCSS level: with an on-channel signal carrying the CTCSS tone."),
    },
)

DRIVERS = {"SimpleUSB": SIMPLEUSB, "USBRadio": USBRADIO}


def parse_settings(driver: Driver, text: str) -> dict:
    """The CSV settings line, as a dict (raises ValueError on anything else)."""
    line = next((l for l in text.splitlines() if l.count(",") >= len(driver.fields) - 1), None)
    if line is None:
        raise ValueError(f"unexpected settings reply: {text.strip()[:200]!r}")
    values = line.strip().split(",")
    if len(values) < len(driver.fields):
        raise ValueError(f"expected {len(driver.fields)} values, got {len(values)}")
    out: dict = {}
    for name, raw in zip(driver.fields, values):
        out[name] = float(raw) if "." in raw else int(raw)
    if driver is USBRADIO:
        # What "c" (receive voice) and "f" (transmit voice) set, as the driver reports them.
        out["rxvoice"] = int(out["rxvoiceadj"] * 200 + 0.5) if out["rxdemod"] == 2 else out["rxmixerset"]
        voice_on_a = out["txmixa"] in (1, 3)
        out["txvoice"] = out["txmixaset"] if voice_on_a else out["txmixbset"]
    return out


def present(driver: Driver, values: dict) -> list[dict]:
    """Settings for the page: name, label, kind, value (delays in ms), options."""
    out = []
    for s in driver.settings:
        value = values.get(s.name)
        if s.kind == "delay" and value is not None:
            value = int(value) * MS_PER_FRAME
        if s.kind == "bool" and value is not None:
            value = bool(value)
        out.append({"name": s.name, "label": s.label, "kind": s.kind, "value": value, "help": s.help,
                    "options": [{"value": k, "label": v} for k, v in s.options.items()],
                    "needs_device": s.needs_device})
    return out


def command_for(driver: Driver, name: str, value) -> str:
    """The menu-support argument that sets ``name`` to ``value`` (validated)."""
    s = driver.setting(name)
    if s is None:
        raise ValueError(f"unknown setting {name}")
    if s.kind == "level":
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 999:
            raise ValueError(f"{s.label} must be a whole number from 0 to 999.")
        return f"{s.letter}{value}"
    if s.kind == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"{s.label} must be on or off.")
        return f"{s.letter}{1 if value else 0}"
    if s.kind == "choice":
        if value not in s.options:
            raise ValueError(f"{s.label}: invalid choice.")
        return f"{s.letter}{value}"
    if s.kind == "delay":
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 60000:
            raise ValueError(f"{s.label} must be from 0 to 60000 ms.")
        return f"{s.letter}{value // MS_PER_FRAME}"
    raise ValueError(f"cannot set {name}")


def device_list(text: str) -> list[str]:
    return [n for n in text.strip().split(",") if n] if text.strip() and "No such command" not in text else []


# ---- live displays -----------------------------------------------------------------------

METER_COLUMNS = 75
METER_MARKS = {"3 kHz": 32, "5 kHz": 49}  # columns of the "v -- 3KHz" / "v -- 5KHz" marks
_BAR = re.compile(r"\|([=> ]{%d})\|" % METER_COLUMNS)
_STATUS = re.compile(r"(Keyed|Clear|Off)\s*\|\s*(Keyed|Clear|Off)\s*\|\s*(Keyed|Clear)\s*\|\s*(Keyed|Clear)")


class DisplayParser:
    """Turns the text of the "b" and "v" displays into readings.

    Lines are separated by carriage returns (the display redraws in place).
    """

    def __init__(self, kind: str):
        self.kind = kind
        self.buf = ""

    def feed(self, text: str) -> list[dict]:
        self.buf += text
        parts = re.split(r"[\r\n]", self.buf)
        self.buf = parts.pop()
        out = []
        for part in parts:
            reading = self.parse(part)
            if reading is not None:
                out.append(reading)
        return out

    def parse(self, line: str) -> dict | None:
        if UNASSIGNED.search(line):
            return {"error": "no_device", "message": line.strip()}
        if self.kind == "meter":
            m = _BAR.search(line)
            if m:
                bar = m.group(1)
                level = bar.find(">") if ">" in bar else bar.count("=")
                return {"keyed": True, "level": level, "columns": METER_COLUMNS}
            if line.strip() == "" and len(line) <= 1:
                return {"keyed": False, "level": 0, "columns": METER_COLUMNS}
            return None
        m = _STATUS.search(line)
        if m:
            cos, ctcss, cos_out, ptt = m.groups()
            return {"cos": cos.lower(), "ctcss": ctcss.lower(), "rx_keyed": cos_out == "Keyed", "ptt": ptt == "Keyed"}
        return None
