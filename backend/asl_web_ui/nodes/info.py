"""What the configuration says about each node.

The same facts node-setup's get_node_settings collects, but read from
Asterisk's view of the files (includes, templates, last value wins) rather
than with grep, so hand-edited files are understood the way Asterisk
understands them.
"""

import re
from dataclasses import asdict, dataclass, field

from ..configengine.edit import Workspace
from ..configengine.model import Category, Config
from . import savenode

PRIVATE_LIMIT = 2000
REGISTRATION_HOST = "register.allstarlink.org"
STATPOST_URL = "http://stats.allstarlink.org/uhandler"
DEFAULT_IAX_PORT = 4569

# Interface name -> rxchannel. node-setup's names, used throughout the UI.
INTERFACES = {
    "SimpleUSB": "SimpleUSB/{node}",
    "USBRadio": "Radio/{node}",
    "Voter": "Voter/{node}",
    "Pseudo": "Local/pseudo",
    "USRP": "USRP/127.0.0.1:34001:32001",
}
INTERFACE_LABELS = {
    "SimpleUSB": "SimpleUSB: CM1xx USB sound card without DSP (URIx, RA-40 ...)",
    "USBRadio": "USBRadio: CM1xx USB sound card with DSP (URIx, RA-40 ...)",
    "Voter": "RTCM: Radio Thin Client or voter boards",
    "Pseudo": "No radio interface (hub node)",
    "USRP": "USRP",
}
# Interface -> the channel driver it needs, and the file holding its settings.
CHANNEL_MODULES = {"SimpleUSB": "chan_simpleusb", "USBRadio": "chan_usbradio", "Voter": "chan_voter", "USRP": "chan_usrp"}
CHANNEL_FILES = {"SimpleUSB": "simpleusb.conf", "USBRadio": "usbradio.conf", "Voter": "voter.conf"}
# Every app_rpt channel driver node-setup manages (chan_pi included).
ALL_CHANNEL_MODULES = ["chan_simpleusb", "chan_usbradio", "chan_usrp", "chan_voter", "chan_pi"]

DUPLEX_LABELS = {
    0: "Half duplex, no telemetry (link)",
    1: "Half duplex with telemetry (hotspot)",
    2: "Full duplex with telemetry (repeater)",
    3: "Full duplex with telemetry, in-cabinet repeat",
    4: "Full duplex with telemetry, no repeat, with autopatch",
}

# Per-node customization references: kind -> rpt.conf key in the node section.
REFERENCE_KEYS = {"events": "events", "functions": "functions", "morse": "morse",
                  "telemetry": "telemetry", "wait-times": "wait_times"}

_SIMPLE_ID = re.compile(r"^\|i([0-9A-Za-z/-]+)$")
_REGISTER = re.compile(r"^(?P<node>\d+):(?P<password>[^@]*)@(?P<host>.+)$")


def interface_of(rxchannel: str | None) -> str | None:
    if not rxchannel:
        return None
    tech = rxchannel.split("/", 1)[0].lower()
    if rxchannel.lower() in ("dahdi/pseudo", "local/pseudo"):
        return "Pseudo"
    return {"simpleusb": "SimpleUSB", "radio": "USBRadio", "voter": "Voter", "usrp": "USRP"}.get(tech)


def node_numbers(rpt: Config) -> list[str]:
    """Local nodes: the numeric, non-template sections of rpt.conf, in file order."""
    seen = []
    for cat in rpt.categories:
        if cat.name.isdigit() and not cat.template and cat.name not in seen:
            seen.append(cat.name)
    return seen


def _int(value: str | None, default: int | None = None) -> int | None:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


def registrations(ws: Workspace) -> list[dict]:
    """Active ``register =>`` lines in rpt_http_registrations.conf [registrations]."""
    if not ws.exists("rpt_http_registrations.conf"):
        return []
    cat = ws.model("rpt_http_registrations.conf").get("registrations")
    out = []
    for v in cat.vars if cat else []:
        if v.key.lower() != "register":
            continue
        m = _REGISTER.match(v.value)
        if m:
            out.append({**m.groupdict(), "file": v.file, "line": v.line})
    return out


def iax_port(ws: Workspace) -> int:
    value = ws.model("iax.conf").value("general", "bindport") if ws.exists("iax.conf") else None
    return _int(value, DEFAULT_IAX_PORT) or DEFAULT_IAX_PORT


@dataclass
class Reference:
    """A node's events/functions/... stanza and the templates it uses."""
    kind: str
    section: str | None  # the [section] the node's key points at
    templates: list[str] = field(default_factory=list)
    exists: bool = False


@dataclass
class NodeInfo:
    number: str
    private: bool
    file: str  # where the [node] header is
    line: int
    templates: list[str]
    callsign: str | None  # from a simple "|iCALL" idrecording
    idrecording: str | None
    id_simple: bool
    duplex: int | None
    linktolink: str
    hangtime: int
    statpost: bool
    statpost_inherited: bool  # comes from a template, so it can't be removed here
    rxchannel: str | None
    interface: str | None
    password: str | None
    registered: bool
    nodes_entry: str | None  # this node's [nodes] line
    channel_templates: list[str] | None  # the node's section in simpleusb.conf/usbradio.conf
    references: dict[str, Reference]

    def as_dict(self) -> dict:
        d = asdict(self)
        d.pop("password")
        d["password_set"] = self.password is not None
        return d


def _templates_of(cat: Category | None) -> list[str]:
    return list(cat.templates) if cat else []


def references(rpt: Config, node: Category) -> dict[str, Reference]:
    out = {}
    for kind, key in REFERENCE_KEYS.items():
        section = node.value(key)
        target = rpt.get(section) if section else None
        out[kind] = Reference(kind, section, _templates_of(target), target is not None)
    return out


def node_info(ws: Workspace, number: str, rpt: Config | None = None) -> NodeInfo:
    rpt = rpt or ws.model("rpt.conf")
    cat = rpt.get(number)
    if cat is None:
        raise KeyError(number)
    idrec = cat.value("idrecording")
    simple = _SIMPLE_ID.match(idrec or "")
    statpost = cat.effective("statpost_url")
    rxchannel = cat.value("rxchannel")
    interface = interface_of(rxchannel)
    regs = [r for r in registrations(ws) if r["node"] == number]
    nodes = rpt.get("nodes")
    channel_templates = None
    if interface in ("SimpleUSB", "USBRadio") and ws.exists(CHANNEL_FILES[interface]):
        chan = ws.model(CHANNEL_FILES[interface]).get(number)
        channel_templates = _templates_of(chan) if chan else None
    return NodeInfo(
        number=number,
        private=int(number) < PRIVATE_LIMIT,
        file=cat.file,
        line=cat.line,
        templates=list(cat.templates),
        callsign=simple.group(1) if simple and simple.group(1) != "NOTSET" else None,
        idrecording=idrec,
        id_simple=bool(simple) or idrec in (None, "", "|iNOTSET"),
        duplex=_int(cat.value("duplex")),
        linktolink=(cat.value("linktolink") or "no").lower(),
        hangtime=_int(cat.value("hangtime"), 5000) or 5000,
        statpost=statpost is not None and bool(statpost.value),
        statpost_inherited=statpost is not None and statpost.inherited_from is not None,
        rxchannel=rxchannel,
        interface=interface,
        password=regs[0]["password"] if regs else None,
        registered=bool(regs),
        nodes_entry=nodes.value(number) if nodes else None,
        channel_templates=channel_templates,
        references=references(rpt, cat),
    )


def all_nodes(ws: Workspace) -> list[NodeInfo]:
    rpt = ws.model("rpt.conf")
    return [node_info(ws, n, rpt) for n in node_numbers(rpt)]


def is_untouched_template(info: NodeInfo) -> bool:
    """The stock node 1999, before anyone set it up (node-setup's first run)."""
    return info.number == "1999" and info.password is None and info.callsign in (None, "NOTSET")


def server_settings(ws: Workspace) -> dict:
    save = savenode.read(ws)
    return {"iax_port": iax_port(ws), "savenode": {k: v for k, v in save.items() if k != "PASSWORD"}}
