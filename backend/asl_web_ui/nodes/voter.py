"""voter.conf as chan_voter reads it (app_rpt channels/chan_voter.c).

- [general]: port, bindaddr and utos are read once when the module loads
  (changing them needs an Asterisk restart); password (the host password
  every RTCM/VOTER board is set to), buflen, sanity and puckit are reread
  by "module reload chan_voter.so".
- [NODE], one per voter instance: the instance settings below, and every
  other line is a client: NAME = PASSWORD[,transmit][,master][,nodeemp]
  [,noplfilter][,gpsid[=ID]][,prio=N].
- chan_voter tells settings from clients by name: the instance keys exactly
  (case-sensitive), and anything starting with transmit, master, gpsid,
  buflen, nodeemp, hostdeemp, noplfilter or prio (any case). A client named
  like that is silently ignored.
- A client is recognized by its password, so passwords must differ across
  all instances, and the server may have one master timing source in all.
- Names and passwords are at most 49 characters.
"""

import re
from dataclasses import dataclass, field

FILE = "voter.conf"
INSTANCE_KEYS = ["plfilter", "hostdeemp", "mixminus", "linger", "buflen", "txctcss", "txctcsslevel", "txtoctype",
                 "gtxgain", "thresholds"]
GENERAL_KEYS = ["port", "bindaddr", "utos", "buflen"]
RESTART_KEYS = {"port", "bindaddr", "utos"}
NOT_CLIENTS = ("transmit", "master", "gpsid", "buflen", "nodeemp", "hostdeemp", "noplfilter", "prio")
FLAGS = ["transmit", "master", "nodeemp", "noplfilter"]
BOOLEANS = {"plfilter", "hostdeemp", "mixminus", "utos"}
MAX_LEN = 49
_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
_SECRET = re.compile(r"^[^\s,;=\[\]]+$")
TRUE = {"yes", "y", "true", "t", "1", "on"}


class VoterError(Exception):
    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.message = message
        self.field = field


def is_client(key: str) -> bool:
    return key not in INSTANCE_KEYS and not key.lower().startswith(NOT_CLIENTS)


@dataclass
class Client:
    name: str
    password: str
    transmit: bool = False
    master: bool = False
    nodeemp: bool = False
    noplfilter: bool = False
    gpsid: str | None = None  # None: no gpsid; "": gpsid without a value
    prio: int | None = None
    other: list[str] = field(default_factory=list)  # options chan_voter ignores, kept as they are

    @classmethod
    def parse(cls, name: str, value: str) -> "Client":
        parts = [p.strip() for p in value.split(",")]
        c = cls(name, parts[0])
        for opt in parts[1:]:
            low = opt.lower()
            if low in FLAGS:
                setattr(c, low, True)
            elif low.startswith("gpsid"):
                c.gpsid = opt.split("=", 1)[1] if "=" in opt else ""
            elif low.startswith("prio") and "=" in opt and re.fullmatch(r"-?\d+", opt.split("=", 1)[1].strip()):
                c.prio = int(opt.split("=", 1)[1])
            elif opt:
                c.other.append(opt)
        return c

    def value(self) -> str:
        parts = [self.password] + [f for f in FLAGS if getattr(self, f)]
        if self.gpsid is not None:
            parts.append(f"gpsid={self.gpsid}" if self.gpsid else "gpsid")
        if self.prio is not None:
            parts.append(f"prio={self.prio}")
        return ",".join(parts + self.other)

    def public(self) -> dict:
        return {"name": self.name, "transmit": self.transmit, "master": self.master, "nodeemp": self.nodeemp,
                "noplfilter": self.noplfilter, "gpsid": self.gpsid, "prio": self.prio, "other": self.other}


def clients(cat) -> list[Client]:
    return [Client.parse(v.key, v.value) for v in cat.vars if v.inherited_from is None and is_client(v.key)]


def status(cfg, number: str) -> dict:
    """The voter view of node NUMBER (cfg: voter.conf's model). Passwords are not included."""
    cat = cfg.get(number)
    general = cfg.get("general")
    others = []
    for c in cfg.categories:
        if c.name not in ("general", number) and not c.template:
            others += [{"node": c.name, "name": cl.name, "master": cl.master} for cl in clients(c)]
    return {
        "configured": cat is not None,
        "clients": [c.public() for c in clients(cat)] if cat else [],
        "settings": {k: cat.value(k) for k in INSTANCE_KEYS if cat and cat.value(k) is not None},
        "general": {k: general.value(k) for k in GENERAL_KEYS if general and general.value(k) is not None},
        "host_password_set": bool(general and general.value("password")),
        "master_elsewhere": [f"{o['name']} (node {o['node']})" for o in others if o["master"]],
    }


# ---- checking a wanted state -----------------------------------------------------------


def _number(value: str, key: str, kind=int, low=None, high=None) -> str:
    try:
        n = kind(value)
    except ValueError:
        raise VoterError(f"{key} must be a number.", key)
    if (low is not None and n < low) or (high is not None and n > high):
        raise VoterError(f"{key} must be between {low} and {high}.", key)
    return value


def check_setting(key: str, value: str) -> str:
    value = value.strip()
    if key in BOOLEANS:
        return "y" if value.lower() in TRUE else "n"
    if key == "linger":
        return _number(value, key, int, 0, 65535)
    if key == "buflen":
        return _number(value, key, int, 40, 10000)
    if key == "txctcsslevel":
        return _number(value, key, int, 0, 250)
    if key in ("txctcss", "gtxgain"):
        return _number(value, key, float)
    if key == "port":
        return _number(value, key, int, 1, 65535)
    if key == "txtoctype":
        if value.lower() not in ("none", "phase", "notone"):
            raise VoterError("txtoctype must be none, phase or notone.", key)
        return value.lower()
    if key == "thresholds":
        if not re.fullmatch(r"\d+(=\d*(:\d+)?)?(\s*,\s*\d+(=\d*(:\d+)?)?)*", value):
            raise VoterError("thresholds is a list like 255,110=5 (RSSI[=REASSESS[:LINGER]], comma separated).",
                             key)
        return value
    if key == "bindaddr":
        if not re.fullmatch(r"[0-9A-Fa-f.:]+", value):
            raise VoterError("bindaddr must be an IP address.", key)
        return value
    raise VoterError(f"Unknown setting {key}.", key)


def check_clients(wanted: list[Client], number: str, others: list[tuple[str, Client]]) -> None:
    """others: (node, client) of every other instance."""
    seen = set()
    for c in wanted:
        if not c.name or len(c.name) > MAX_LEN or not _NAME.match(c.name):
            raise VoterError("A client name may contain letters, numbers, _ . and - (at most 49).", "clients")
        if not is_client(c.name):
            raise VoterError(f'chan_voter would read "{c.name}" as a setting, not a client: names must not '
                             f"start with {', '.join(NOT_CLIENTS)}.", "clients")
        if c.name.lower() in seen:
            raise VoterError(f"There are two clients named {c.name}.", "clients")
        seen.add(c.name.lower())
        if not c.password or len(c.password) > MAX_LEN or not _SECRET.match(c.password):
            raise VoterError(f"{c.name}'s password must be 1 to 49 characters without spaces, commas or "
                             "semicolons.", "clients")
        if c.prio is not None and c.prio < -1:
            raise VoterError(f"{c.name}'s priority must be -1 (locked out) or more.", "clients")
    everyone = [(number, c) for c in wanted] + others
    secrets: dict[str, str] = {}
    for node, c in everyone:
        other = secrets.get(c.password)
        if other is not None:
            raise VoterError(f"{c.name} (node {node}) has the same password as {other}; chan_voter tells clients "
                             "apart by their password, so each needs its own.", "clients")
        secrets[c.password] = f"{c.name} (node {node})"
    masters = [f"{c.name} (node {node})" for node, c in everyone if c.master]
    if len(masters) > 1:
        raise VoterError(f"Only one client on the whole server may be the master timing source; "
                         f"{' and '.join(masters)} are.", "clients")
