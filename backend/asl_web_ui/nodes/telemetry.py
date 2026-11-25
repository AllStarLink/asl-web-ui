"""A node's telemetry: its ID, courtesy tones, tone definitions and Morse code.

How app_rpt uses them (apps/app_rpt/rpt_telemetry.c, rpt_config.c):

- The node section holds the ID (idrecording, idtalkover, idtime, politeid)
  and which courtesy tone plays when: unlinkedct, remotect, linkunkeyct and
  linkunkeyct_<node> name an entry of the telemetry stanza (an empty value
  means no tone). nounkeyct turns courtesy tones off; nolocallinkct sends
  unlinkedct when the only links are to nodes on the same server.
- The telemetry stanza (the node's "telemetry =" key, default [telemetry])
  defines the tones by name. A name it does not define falls back to the
  built-in tone in app_rpt (tele_defs), if there is one.
- The Morse stanza ("morse =", default [morse]) sets the speed, tone and
  level of |m and |i Morse.
- A telemetry value is a tone sequence (|t(f1,f2,ms,amplitude)...), Morse
  (|m text, or |i text at the ID tone and level) or a sound file.

The stock files give every node the same [telemetry] and [morse] stanzas.
Changing a node's tones or Morse code gives the node a stanza of its own
first ([telemetry-<node>], as customizations do), a copy of the one it
used, so that the other nodes keep theirs.
"""

import re

from ..configengine.edit import Section, Workspace, append_section, find_headers
from ..configengine.model import Category, Config
from .info import node_numbers

RPT = "rpt.conf"
KINDS = ("telemetry", "morse")

# app_rpt's tele_defs: what a name sounds like when the stanza does not define it.
BUILTIN = {
    "ct1": "|t(350,0,100,3072)(500,0,100,3072)(660,0,100,3072)",
    "ct2": "|t(660,880,150,3072)",
    "ct3": "|t(440,0,150,3072)",
    "ct4": "|t(550,0,150,3072)",
    "ct5": "|t(660,0,150,3072)",
    "ct6": "|t(880,0,150,3072)",
    "ct7": "|t(660,440,150,3072)",
    "ct8": "|t(700,1100,150,3072)",
    "remotemon": "|t(1600,0,75,2048)",
    "remotetx": "|t(2000,0,75,2048)(0,0,75,0)(1600,0,75,2048)",
    "cmdmode": "|t(900,904,200,2048)",
    "functcomplete": "|t(1000,0,100,2048)(0,0,100,0)(1000,0,100,2048)",
    "remcomplete": "|t(650,0,100,2048)(0,0,100,0)(650,0,100,2048)(0,0,100,0)(650,0,100,2048)",
    "pfxtone": "|t(350,440,30000,3072)",
}
# The names app_rpt plays by itself (telem_lookup with a fixed name), in the stock file's order.
STOCK_TONES = {
    **{f"ct{i}": "Courtesy tone" for i in range(1, 10)},
    "remotemon": "Courtesy tone when the links are monitor only",
    "remotetx": "Courtesy tone when a link is transceive",
    "cmdmode": "In command mode",
    "functcomplete": "After a DTMF command",
    "remcomplete": "Remote base command complete",
    "pfxtone": "Autopatch dial tone",
    "patchup": "Autopatch call starts",
    "patchdown": "Autopatch call ends",
}

# Node section settings: key -> (kind, app_rpt's default, range).
NODE_KEYS = {
    "idrecording": ("telemetry", None, None),
    "idtalkover": ("telemetry", None, None),
    "idtime": ("int", "300000", (60000, 2400000, True)),  # 0 is allowed too
    "politeid": ("int", "30000", (30000, 300000, False)),
    "unlinkedct": ("tone", None, None),
    "remotect": ("tone", None, None),
    "linkunkeyct": ("tone", None, None),
    "nounkeyct": ("bool", None, None),
    "nolocallinkct": ("bool", None, None),
}
# Morse stanza settings: key -> (app_rpt's default, min, max).
MORSE_KEYS = {
    "speed": ("20", 5, 35),
    "frequency": ("800", 300, 3000),
    "amplitude": ("4096", 200, 8192),
    "idfrequency": ("330", 300, 3000),
    "idamplitude": ("2048", 200, 8192),
}
TRUE = {"yes", "true", "y", "t", "1", "on"}  # ast_true

_TONE_SEQ = re.compile(r"^(\((\d+),(\d+),(\d+),(\d+)\))+$")
_TONE_ITEM = re.compile(r"\((\d+),(\d+),(\d+),(\d+)\)")
_MORSE = re.compile(r"^[A-Za-z0-9 /.,?=+-]+$")
_FILE = re.compile(r"^[A-Za-z0-9_./-]+$")
_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
_LINK = re.compile(r"^linkunkeyct_(.+)$", re.IGNORECASE)


class TelemetryError(Exception):
    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.message = message
        self.field = field


# ---- checking values -------------------------------------------------------------------


def check_value(value: str, what: str, field: str) -> str:
    """A telemetry value as app_rpt's telem_any plays it, tidied (spaces in a
    tone sequence removed). Empty means silence."""
    value = value.strip()
    if not value:
        return ""
    if value[0] == "|":
        mode = value[1:2].upper()
        rest = value[2:]
        if mode == "T":
            seq = re.sub(r"\s+", "", rest)
            if not _TONE_SEQ.match(seq):
                raise TelemetryError(f"{what}: a tone sequence is |t followed by (tone 1,tone 2,milliseconds,"
                                     "amplitude) groups, for example |t(660,880,150,2048).", field)
            for f1, f2, ms, amp in _TONE_ITEM.findall(seq):
                if int(f1) > 4000 or int(f2) > 4000:
                    raise TelemetryError(f"{what}: tones go up to 4000 Hz.", field)
                if not 1 <= int(ms) <= 60000:
                    raise TelemetryError(f"{what}: each part lasts 1 to 60000 milliseconds.", field)
                if int(amp) > 32767:
                    raise TelemetryError(f"{what}: the amplitude goes up to 32767.", field)
            return value[:2] + seq
        if mode in ("M", "I"):
            if not _MORSE.match(rest.strip()):
                raise TelemetryError(f"{what}: Morse code can send letters, digits, spaces and / . , ? = + -.",
                                     field)
            return value[:2] + rest.strip()
        raise TelemetryError(f"{what}: start with |t for tones, |m for Morse code or |i for a Morse ID, "
                             "or give a sound file.", field)
    if not _FILE.match(value):
        raise TelemetryError(f"{what}: a sound file name may contain letters, numbers and _ . / -, "
                             "without an extension (for example rpt/callproceeding).", field)
    return value


def _check_int(value: str, what: str, field: str, low: int, high: int, zero: bool = False) -> str:
    try:
        number = int(str(value).strip())
    except ValueError:
        number = None
    if number is None or not (low <= number <= high or (zero and number == 0)):
        raise TelemetryError(f"{what} must be a whole number from {low} to {high}" + (" (or 0)" if zero else "") + ".",
                             field)
    return str(number)


# ---- reading ------------------------------------------------------------------------------


def stanza_name(node: Category, kind: str) -> str:
    """The section app_rpt reads (RPT_CONFIG_VAR_DEFAULT: "telemetry", "morse")."""
    return node.value(kind) or kind


def users(rpt: Config, kind: str, name: str) -> list[str]:
    return [n for n in node_numbers(rpt) if stanza_name(rpt.get(n), kind).lower() == name.lower()]


def private_name(kind: str, number: str) -> str:
    return f"{kind}-{number}"


def editable_in_place(rpt: Config, number: str, kind: str) -> bool:
    """The node's stanza is its own, so changes go there (not into a copy)."""
    name = stanza_name(rpt.get(number), kind)
    cat = rpt.get(name)
    return cat is not None and name.lower() != kind and users(rpt, kind, name) == [number]


def _setting(cat: Category | None, key: str, default: str | None) -> dict:
    found = [v for v in cat.vars if v.key.lower() == key.lower()] if cat else []
    inherited = [v for v in found if v.inherited_from is not None]
    return {
        "value": found[-1].value if found else default,
        "own": any(v.inherited_from is None for v in found),
        # What it is without the section's own lines: a template's value, or app_rpt's default.
        "fallback": inherited[-1].value if inherited else default,
        "from": inherited[-1].inherited_from if inherited else None,
    }


def tone_names(stanza: Category | None) -> list[str]:
    """Every name the node can use: the stock ones, then the stanza's others, as they appear."""
    names = list(STOCK_TONES)
    known = {n.lower() for n in names}
    for v in stanza.vars if stanza else []:
        if v.key.lower() not in known:
            known.add(v.key.lower())
            names.append(v.key)
    return names


def status(ws: Workspace, number: str) -> dict:
    rpt = ws.model(RPT)
    node = rpt.get(number)
    if node is None:
        raise KeyError(number)
    out: dict = {"node": {k: _setting(node, k, NODE_KEYS[k][1]) for k in NODE_KEYS}}
    links = {}
    for v in node.vars:
        m = _LINK.match(v.key)
        if m:
            links[m.group(1)] = _setting(node, v.key, None)
    out["per_link"] = links
    for kind in KINDS:
        name = stanza_name(node, kind)
        cat = rpt.get(name)
        info = {"section": name, "exists": cat is not None, "users": users(rpt, kind, name),
                "in_place": editable_in_place(rpt, number, kind), "copy": private_name(kind, number)}
        if kind == "telemetry":
            info["tones"] = [{"name": n, "description": STOCK_TONES.get(n, ""),
                              **_setting(cat, n, BUILTIN.get(n.lower()))} for n in tone_names(cat)]
        else:
            info["settings"] = {k: _setting(cat, k, d[0]) for k, d in MORSE_KEYS.items()}
        out[kind] = info
    return out


# ---- changing ------------------------------------------------------------------------------


def own_stanza(ws: Workspace, number: str, kind: str) -> tuple[str, str | None]:
    """The section to change for the node's ``kind``, made if need be:
    (its name, a note on what was done or None)."""
    rpt = ws.model(RPT)
    node = rpt.get(number)
    current = stanza_name(node, kind)
    if editable_in_place(rpt, number, kind):
        return current, None
    name = private_name(kind, number)
    if rpt.get(name, include_templates=True) is not None:
        raise TelemetryError(f"[{name}] already exists but node {number} uses [{current}]. Point the node's "
                             f"{kind} = setting at one of them in Manual Config Edit first.", kind)
    source = rpt.get(current)
    if source is not None:
        templates = list(source.templates)
        own = [v for v in source.vars if v.inherited_from is None]
        body = [ws.text(v.file).lines[v.line].raw for v in own]
        what = f"a copy of [{current}]"
    else:
        main = rpt.get(f"{kind}-main", include_templates=True)
        templates = [main.name] if main is not None and main.template else []
        body = []
        what = (f"based on [{templates[0]}]" if templates else "empty") + f" ([{current}] does not exist)"
    text = ws.text(node.file)
    append_section(text, name, templates, body, before=find_headers(text, node.name)[0])
    Section(ws, RPT, number).set(kind, name)
    others = [n for n in users(rpt, kind, current) if n != number]
    return name, (f"Node {number} gets its own {kind} settings, [{name}], {what}"
                  + (f"; node{'s' if len(others) > 1 else ''} {', '.join(others)} keep{'' if len(others) > 1 else 's'} "
                     f"[{current}]." if others else "."))


def _set(sec: Section, key: str, value: str | None) -> bool:
    """Set the section's own line (None: remove it). Whether anything changed."""
    def state():
        return [(v.key, v.value, v.inherited_from) for v in sec.require().vars]
    before = state()
    if value is None:
        sec.unset(key)
    elif not _unchanged(sec.require(), key, value):
        sec.set(key, value)
    return state() != before


def _checked_node_value(key: str, value) -> str:
    kind, _default, limits = NODE_KEYS[key]
    if kind == "bool":
        if not isinstance(value, bool):
            raise TelemetryError(f"{key} must be true or false.", key)
        return "1" if value else "0"
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise TelemetryError(f"{key} must be text.", key)
    value = str(value)
    if kind == "telemetry":
        return check_value(value, "The ID" if key == "idrecording" else "The talkover ID", key)
    if kind == "int":
        low, high, zero = limits
        return _check_int(value, {"idtime": "The ID interval", "politeid": "The polite ID time"}[key],
                          key, low, high, zero)
    value = value.strip()  # a tone name, or "" for none
    if value and not _NAME.match(value):
        raise TelemetryError(f"{key}: a tone name may contain letters, numbers, _ and -.", key)
    return value


def _defined(rpt: Config, number: str) -> set[str]:
    """The tone names node NUMBER can play (lower case)."""
    stanza = rpt.get(stanza_name(rpt.get(number), "telemetry"))
    return ({v.key.lower() for v in stanza.vars} if stanza else set()) | set(BUILTIN)


def apply(ws: Workspace, number: str, node: dict, per_link: dict, tones: dict,
          morse: dict) -> tuple[bool, list[tuple[str, str]]]:
    """Make the changes: {key: value, or None to remove the node's own setting}.
    Returns whether anything changed, and notes (severity, text) on what else was done."""
    for name, d in (("node", node), ("per_link", per_link), ("tones", tones), ("morse", morse)):
        if not isinstance(d, dict):
            raise TelemetryError(f"{name} must be an object.", name)
    unknown = [k for k in node if k not in NODE_KEYS] + [k for k in morse if k not in MORSE_KEYS]
    if unknown:
        raise TelemetryError(f"Unknown setting: {', '.join(unknown)}.", unknown[0])

    # Check everything before changing anything.
    node_values = {k: None if v is None else _checked_node_value(k, v) for k, v in node.items()}
    link_values = {}
    for link, v in per_link.items():
        if not _NAME.match(link):
            raise TelemetryError(f"{link}: a node is named by its number (or letters, numbers, _ and -).", "per_link")
        if v is not None and (not isinstance(v, str) or (v.strip() and not _NAME.match(v.strip()))):
            raise TelemetryError(f"The tone for node {link} must be a tone name.", "per_link")
        link_values[f"linkunkeyct_{link}"] = None if v is None else v.strip()
    tone_values = {}
    for name, v in tones.items():
        if not _NAME.match(name):
            raise TelemetryError(f"{name}: a tone name may contain letters, numbers, _ and -.", "tones")
        if v is not None and not isinstance(v, str):
            raise TelemetryError(f"The value of {name} must be text.", "tones")
        tone_values[name] = None if v is None else check_value(v, name, "tones")
    morse_values = {}
    for key, v in morse.items():
        _default, low, high = MORSE_KEYS[key]
        morse_values[key] = None if v is None else _check_int(v, f"Morse {key}", "morse", low, high)

    before = _defined(ws.model(RPT), number)
    notes: list[tuple[str, str]] = []
    changed = False
    for kind, values in (("telemetry", tone_values), ("morse", morse_values)):
        rpt = ws.model(RPT)
        current = rpt.get(stanza_name(rpt.get(number), kind))
        if all(_unchanged(current, k, v) for k, v in values.items()):
            continue
        name, note = own_stanza(ws, number, kind)
        if note:
            notes.append(("info", note))
        target = Section(ws, RPT, name)
        for key, v in values.items():
            _set(target, key, v)
        changed = True
    sec = Section(ws, RPT, number)
    for key, v in {**node_values, **link_values}.items():
        changed |= _set(sec, key, v)

    # A courtesy tone must name a tone the node has: one just chosen, or one
    # that was there before these changes.
    rpt = ws.model(RPT)
    cat = rpt.get(number)
    after = _defined(rpt, number)
    for v in cat.vars:
        key = v.key.lower()
        if key not in ("unlinkedct", "remotect", "linkunkeyct") and not _LINK.match(key):
            continue
        value = cat.value(v.key)
        if value and value.lower() not in after and (v.key in node_values or v.key in link_values
                                                      or value.lower() in before):
            raise TelemetryError(f"{v.key} names the tone {value}, which node {number} does not have.",
                                 "per_link" if _LINK.match(key) else v.key)
    if "idrecording" in node_values and changed and not cat.value("idrecording"):
        notes.append(("warning", f"Node {number} will not identify. Most countries require a station to identify "
                                 "regularly."))
    return changed, notes


def _unchanged(cat: Category | None, key: str, value: str | None) -> bool:
    found = [v for v in cat.vars if v.key.lower() == key.lower()] if cat else []
    own = any(v.inherited_from is None for v in found)
    if value is None:
        return not own
    return own and found[-1].value == value
