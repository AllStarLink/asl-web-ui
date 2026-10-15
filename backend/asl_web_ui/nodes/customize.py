"""Node customizations: the ";MENU:" options in /etc/asterisk/custom.

Port of node-setup's check_customization, get_customization_settings and
do_update_customizations. Each custom file may carry lines like

    ;MENU:shari-pixx:events,duplex=1,rxchannel=SimpleUSB:*Kits4Hams* SHARI PiXX

naming a template (shari-pixx), what it customizes (the node itself, its
events/functions/morse/telemetry/wait-times stanza, or its channel driver
section) and a description. Options with the same description in rpt and
in a channel driver's directory are one option. Those that also give
duplex= and rxchannel= describe a device, offered when adding a node.

Selecting options adds their templates to the node's sections, creating
[<kind>-<node>] stanzas (inheriting <kind>-main plus the options) that the
node's events = / functions = ... keys point to.
"""

import glob
import os
import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field

from ..configengine.edit import (
    Section, Workspace, append_section, comment_out, find_headers, remove_section, section_end,
)
from ..configengine.text import ConfigText
from .info import REFERENCE_KEYS, NodeInfo, node_info
from .planner import RPT, Effects, PlanError

ENABLER = "/usr/share/asterisk/menu-lib/update-configuration-files.py"
KINDS = list(REFERENCE_KEYS)  # events, functions, morse, telemetry, wait-times
CHANNELS = {"SimpleUSB": "simpleusb", "USBRadio": "usbradio"}
# Default tune values node-setup comments out when a channel customization
# takes over (do_node_clean_interface_defaults).
CHANNEL_DEFAULTS = {
    "simpleusb": {"rxmixerset": "500", "txmixaset": "500", "txmixbset": "500"},
    "usbradio": {"rxmixerset": "500", "txmixaset": "500", "txmixbset": "500", "rxvoiceadj": "0.5",
                 "rxctcssadj": "0.5", "txctcssadj": "200", "rxsquelchadj": "500"},
}
NOT_SET_UP = 'The configuration files are not set up for customization.'


@dataclass
class Option:
    name: str
    description: str
    files: list[str] = field(default_factory=list)  # rpt, simpleusb, usbradio
    types: list[str] = field(default_factory=list)
    duplex: int | None = None
    interface: str | None = None  # node-setup's interface names

    @property
    def device(self) -> bool:
        return self.duplex is not None and self.interface is not None


def _menu_lines(path: str) -> list[tuple[str, str, str]]:
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith(";MENU:"):
                    parts = line.rstrip("\r\n")[len(";MENU:"):].split(":", 2)
                    if len(parts) == 3:
                        out.append((parts[0], parts[1], parts[2]))
    except OSError:
        pass
    return out


def options(config_dir: str, channel: str | None) -> list[Option]:
    """Options for a node whose channel driver is ``channel`` ("*" for all)."""
    custom = os.path.join(config_dir, "custom")
    paths = [os.path.join(custom, "rpt.conf")] + sorted(glob.glob(os.path.join(custom, "rpt", "*.conf")))
    if channel == "*":
        paths += sorted(glob.glob(os.path.join(custom, "*.conf"))) + sorted(glob.glob(os.path.join(custom, "*", "*.conf")))
    elif channel:
        paths += [os.path.join(custom, f"{channel}.conf")] + sorted(glob.glob(os.path.join(custom, channel, "*.conf")))
    seen_lines = set()
    by_desc: dict[str, Option] = {}
    for path in dict.fromkeys(paths):
        rel = os.path.relpath(path, custom)
        source = rel.split("/", 1)[0].removesuffix(".conf")
        for name, types, desc in _menu_lines(path):
            if (path, name, types, desc) in seen_lines:
                continue
            seen_lines.add((path, name, types, desc))
            opt = by_desc.setdefault(desc, Option(name, desc))
            if source not in opt.files:
                opt.files.append(source)
            for t in types.split(","):
                m = re.match(r"^duplex=([0-4])$", t)
                if m:
                    opt.duplex = int(m.group(1))
                    continue
                m = re.match(r"^rxchannel=(SimpleUSB|USBRadio|Voter|Pseudo|USRP)$", t)
                if m:
                    opt.interface = m.group(1)
                    continue
                if t and t not in opt.types:
                    opt.types.append(t)
    return sorted(by_desc.values(), key=lambda o: o.description.encode())


def device_presets(config_dir: str) -> list[dict]:
    return [asdict(o) for o in options(config_dir, "*") if o.device]


# ---- state of a node ---------------------------------------------------------------


def _has_tryinclude(text: ConfigText, channel: str) -> bool:
    return any(l.kind == "directive" and l.directive == "tryinclude" and l.argument == f"custom/{channel}/*.conf"
               for l in text.lines)


def _has_template_structure(text: ConfigText, kind: str) -> bool:
    main = f"{kind}-main"
    user = any(l.kind == "section" and l.options[:1] == [main] for l in text.lines)
    template = any(l.kind == "section" and l.name == main and l.options == ["!"] for l in text.lines)
    return user and template


def _channel(info: NodeInfo) -> str | None:
    return CHANNELS.get(info.interface or "")


def stanzas(info: NodeInfo) -> dict[str, list[str]]:
    """The templates of the node's sections (node-setup's CURRENT_*_STANZAS)."""
    out = {"node": info.templates}
    for kind in KINDS:
        ref = info.references[kind]
        out[kind] = ref.templates if ref.exists else []
    out["channel"] = info.channel_templates or []
    return out


def structure_reason(ws: Workspace, channel: str | None) -> str | None:
    """Why the files cannot take customizations (for any node on ``channel``), or None."""
    custom = os.path.join(ws.config_dir, "custom")
    if not os.path.isdir(custom):
        return "No customizations are available."
    rpt = ws.text(RPT)
    chan_text = ws.text(f"{channel}.conf") if channel and ws.exists(f"{channel}.conf") else None
    if not (_has_tryinclude(rpt, "rpt") or (chan_text is not None and _has_tryinclude(chan_text, channel))):
        return NOT_SET_UP
    for kind in ["node"] + KINDS:
        if not _has_template_structure(rpt, kind):
            return NOT_SET_UP
    if chan_text is not None and not _has_template_structure(chan_text, "node"):
        return NOT_SET_UP
    dirs = ["rpt"] + ([channel] if channel else [])
    if not any(_menu_lines(p) for d in dirs for p in glob.glob(os.path.join(custom, d, "*.conf"))):
        return "No customizations are available."
    return None


def unavailable_reason(ws: Workspace, info: NodeInfo) -> str | None:
    if not os.path.isdir(os.path.join(ws.config_dir, "custom")):
        return "No customizations are available."
    for kind, templates in stanzas(info).items():
        if not templates:
            continue
        main = "node-main" if kind in ("node", "channel") else f"{kind}-main"
        if main not in templates:
            return f"Node {info.number} does not use the standard templates, so it cannot be customized."
    return structure_reason(ws, _channel(info))


def selected(info: NodeInfo, opts: list[Option]) -> list[str]:
    current = stanzas(info)
    out = []
    for opt in opts:
        in_rpt = "rpt" in opt.files and (
            opt.name in current["node"] or any(f"{k}-{opt.name}" in current[k] for k in KINDS))
        in_chan = _channel(info) in opt.files and opt.name in current["channel"]
        if in_rpt or in_chan:
            out.append(opt.name)
    return out


def status(ws: Workspace, number: str) -> dict:
    info = node_info(ws, number)
    reason = unavailable_reason(ws, info)
    opts = options(ws.config_dir, _channel(info)) if reason is None else []
    chosen = selected(info, opts)
    defaults = all(t == ["node-main" if k in ("node", "channel") else f"{k}-main"]
                   for k, t in stanzas(info).items() if t)
    return {
        "state": "unavailable" if reason else ("active" if not defaults else "available"),
        "reason": reason,
        "can_enable": reason == NOT_SET_UP and os.access(ENABLER, os.X_OK),
        "options": [asdict(o) | {"device": o.device} for o in opts],
        "selected": chosen,
    }


# ---- changing them ----------------------------------------------------------------


def apply(ws: Workspace, number: str, names: list[str], effects: Effects) -> None:
    info = node_info(ws, number)
    reason = unavailable_reason(ws, info)
    if reason:
        raise PlanError(reason, code="requirement")
    channel = _channel(info)
    opts = {o.name: o for o in options(ws.config_dir, channel)}
    unknown = [n for n in names if n not in opts]
    if unknown:
        raise PlanError(f"Unknown customization: {', '.join(unknown)}", "customizations")
    devices = [opts[n].description for n in names if opts[n].device]
    if len(devices) > 1:
        raise PlanError("Only one device configuration can be selected at a time: " + ", ".join(devices),
                        "customizations")
    chosen = [opts[n] for n in names]
    known = list(opts.values())
    current = stanzas(info)

    def keep(templates: list[str], prefix: str = "") -> list[str]:
        """Templates that are not customization options (left as they are)."""
        names_ = {prefix + o.name for o in known}
        return [t for t in templates if t not in names_]

    # The node section's own templates.
    new_node = keep(current["node"]) + [o.name for o in chosen if "rpt" in o.files and "node" in o.types]
    if new_node != current["node"]:
        Section(ws, RPT, number).set_templates(new_node)
        effects.restart = True

    # events/functions/morse/telemetry/wait-times stanzas.
    for kind in KINDS:
        key = REFERENCE_KEYS[kind]
        base = current[kind] or [f"{kind}-main"]
        new = keep(base, f"{kind}-") + [f"{kind}-{o.name}" for o in chosen if "rpt" in o.files and kind in o.types]
        if new == base:
            continue
        section = f"{kind}-{number}"
        rpt = ws.model(RPT)
        old = rpt.get(section)
        if old is not None:
            text = ws.text(old.file)
            remove_section(text, find_headers(text, section)[0])
        if new == [f"{kind}-main"]:
            Section(ws, RPT, number).unset(key)
        else:
            Section(ws, RPT, number).set(key, section)
            node_cat = ws.model(RPT).get(number)
            text = ws.text(node_cat.file)
            append_section(text, section, new, before=node_cat.line)
        effects.restart = True

    # The channel driver section (simpleusb.conf / usbradio.conf).
    if channel and info.channel_templates is not None:
        cur = current["channel"]
        new = keep(cur) + [o.name for o in chosen if channel in o.files]
        if new != cur:
            name = f"{channel}.conf"
            if cur == ["node-main"]:
                _comment_defaults(ws, name, number, channel)
            Section(ws, name, number).set_templates(new)
            effects.restart = True


def _comment_defaults(ws: Workspace, filename: str, number: str, channel: str) -> None:
    """Comment out the stock tune values so the customization's apply."""
    text = ws.text(filename)
    headers = find_headers(text, number)
    if not headers:
        return
    defaults = CHANNEL_DEFAULTS[channel]
    for i in range(headers[0] + 1, section_end(text, headers[0])):
        line = text.lines[i]
        if line.kind == "variable" and line.simple and defaults.get(line.key) == line.value:
            comment_out(text, i)


def enable(ws: Workspace) -> list[str]:
    """D4: run asl3-menu's update-configuration-files.py on copies, so the
    result can be reviewed as a diff before anything is written."""
    if not os.access(ENABLER, os.X_OK):
        raise PlanError("asl3-menu's customization helper is not installed.", code="requirement")
    names = ["rpt.conf", "simpleusb.conf", "usbradio.conf"]
    with tempfile.TemporaryDirectory(prefix="asl-web-ui-") as tmp:
        for name in names:
            if ws.exists(name):
                with open(os.path.join(tmp, name), "wb") as f:
                    f.write(ws.text(name).to_bytes())
        proc = subprocess.run([ENABLER, "--dir-in", tmp, "--dir-out", tmp], capture_output=True, text=True,
                              timeout=60)
        if proc.returncode != 0:
            raise PlanError("The configuration files could not be updated for customization: "
                            + (proc.stderr or proc.stdout).strip()[:500], code="requirement")
        changed = []
        for name in names:
            path = os.path.join(tmp, name)
            if not ws.exists(name) or not os.path.exists(path):
                continue
            with open(path, "rb") as f:
                data = f.read()
            text = ws.text(name)
            if data != text.to_bytes():
                text.lines = ConfigText(data, text.path).lines
                text.relex()
                changed.append(name)
    return changed


def check_enabled(ws: Workspace, number: str) -> None:
    info = node_info(ws, number)
    reason = unavailable_reason(ws, info)
    if reason:
        raise PlanError("The files were updated, but customizations are still not available: " + reason,
                        code="requirement")

