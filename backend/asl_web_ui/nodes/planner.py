"""Node operations, planned as file edits.

Each method mirrors a node-setup operation (asl3-menu bin/node-setup) and
makes the smallest edits to a Workspace; nothing is written until the
resulting plan is applied. Where this deliberately differs from node-setup,
the comment names the decision (D1-D9, docs/design-notes.md).

Changes that are not file edits (AstDB access lists, Allmon3) are collected
in ``effects`` for the caller.
"""

import re
from dataclasses import dataclass, field

from ..configengine.edit import (
    EditError, Section, Workspace, append_section, delete, find_headers, header_line, insert, last_var,
    remove_section,
    replace_value, section_end, section_vars, set_module, set_raw, var_line,
)
from ..configengine.text import ConfigText
from . import savenode
from .info import (
    ALL_CHANNEL_MODULES, CHANNEL_FILES, CHANNEL_MODULES, DEFAULT_IAX_PORT, INTERFACES, PRIVATE_LIMIT,
    REFERENCE_KEYS, REGISTRATION_HOST, STATPOST_URL, NodeInfo, iax_port, node_info, node_numbers, registrations,
)

RPT = "rpt.conf"
HTTP_REG = "rpt_http_registrations.conf"
IAX = "iax.conf"
EXTENSIONS = "extensions.conf"
MANAGER = "manager.conf"

# Placeholders in the stock files that node-setup turns into real entries.
HTTP_PLACEHOLDER = "1234:abcdef@"
IAX_PLACEHOLDER = "1998:12345@"

SIMPLEUSB_TUNE = ["devstr =", "rxmixerset = 500", "txmixaset = 500", "txmixbset = 500"]
USBRADIO_TUNE = SIMPLEUSB_TUNE + ["rxvoiceadj = 0.5", "rxctcssadj = 0.5", "txctcssadj = 200", "rxsquelchadj = 500"]
# Settings node-setup writes when the file has no [node-main] template.
SIMPLEUSB_DEFAULTS = ["eeprom = 0", "hdwtype = 0", "rxboost = no", "carrierfrom = usbinvert", "ctcssfrom = usbinvert",
                      "deemphasis = no", "plfilter = yes", "rxondelay = 0", "txoffdelay = 0", "txmixa = voice",
                      "txmixb = no", "invertptt = no", "preemphasis = no"]
USBRADIO_DEFAULTS = ["eeprom = 0", "hdwtype = 0", "rxboost = yes", "rxctcssrelax = 1", "rxsqhyst = 3000",
                     "txctcssdefault = 100.0", "rxctcssfreqs = 100.0,91.5", "txctcssfreqs = 100.0,91.5",
                     "rxctcssoverride = no", "carrierfrom = dsp", "ctcssfrom = dsp", "rxdemod = flat",
                     "rxsquelchdelay = 30", "rxondelay = 0", "txoffdelay = 0", "txboost = no", "txprelim = yes",
                     "txlimonly = yes", "txtoctype = notone", "txmixa = composite", "txmixb = no", "rxlpf = 0",
                     "rxhpf = 0", "txlpf = 0", "txhpf = 0", "invertptt = no", "duplex = 0", "duplex3 = 0"]
VOTER_SAMPLES = [";NORTH = password_1,transmit", ";SOUTH = Password_2,transmit", ";EAST = password_3,nodeemp",
                 ";WEST = Password_4,transmit,noplfilter"]

_NODE_NUMBER = re.compile(r"^[0-9]{4,6}$")
_PASSWORD = re.compile(r"^[0-9a-zA-Z_-]{6,}$")
_CALLSIGN = re.compile(r"^[0-9A-Za-z/-]{3,}$")
_SECRET = re.compile(r"^[0-9a-zA-Z_-]{12,}$")


class PlanError(Exception):
    def __init__(self, message: str, field: str | None = None, code: str = "invalid"):
        super().__init__(message)
        self.message = message
        self.field = field
        self.code = code


@dataclass
class Note:
    severity: str  # info | warning
    text: str


@dataclass
class Effects:
    notes: list[Note] = field(default_factory=list)
    astdb: list[tuple[str, ...]] = field(default_factory=list)
    # Changes Allmon3 needs too: {"kind": "rename"|"secret", "old", "new", "text"}.
    allmon3: list[dict] = field(default_factory=list)
    restart: bool = False
    tune: bool = False

    def note(self, text: str, severity: str = "info") -> None:
        if not any(n.text == text for n in self.notes):
            self.notes.append(Note(severity, text))


# ---- validation (node-setup's rules) ----------------------------------------


def check_node_number(number: str, existing: list[str], allow: str | None = None) -> str:
    number = number.strip()
    if not _NODE_NUMBER.match(number):
        raise PlanError("The node number must have 4 to 6 digits.", "number")
    if int(number) < 1000:
        raise PlanError("Private node numbers start at 1000.", "number")
    if int(number) >= PRIVATE_LIMIT and number.startswith("1"):
        raise PlanError('Registered node numbers cannot start with a "1".', "number")
    if number != allow and number in existing:
        raise PlanError(f"Node {number} is already defined. Choose another number.", "number")
    return number


def check_password(password: str) -> str:
    if not _PASSWORD.match(password):
        raise PlanError("The node password may only contain letters, numbers, underscore and dash, "
                        "and must be at least 6 characters long.", "password")
    return password


def check_callsign(callsign: str) -> str:
    if not _CALLSIGN.match(callsign.strip()):
        raise PlanError("A call sign may contain only letters, numbers, / and -, and must be at least "
                        "3 characters long.", "callsign")
    return callsign.strip().upper()


def check_secret(secret: str) -> str:
    if not _SECRET.match(secret):
        raise PlanError("The AMI secret may only contain letters, numbers, underscore and dash, and must be "
                        "at least 12 characters long.", "secret")
    return secret


def check_port(port) -> int:
    try:
        value = int(port)
    except (TypeError, ValueError):
        value = 0
    if not 0 < value < 65536:
        raise PlanError("The port must be a number between 1 and 65535 (the default is 4569).", "port")
    return value


# ---- raw line helpers -----------------------------------------------------------


def _register_re(prefix: str, commented: bool = True) -> re.Pattern:
    lead = ";*" if commented else ""
    return re.compile(rf"^{lead}\s*register\s*=>?\s*{re.escape(prefix)}")


def _lines_matching(text: ConfigText, pattern: re.Pattern, section: str | None = None) -> list[int]:
    if section is not None:
        headers = find_headers(text, section)
        if not headers:
            return []
        span = range(headers[0] + 1, section_end(text, headers[0]))
    else:
        span = range(len(text.lines))
    return [i for i in span if pattern.match(text.lines[i].text)]


def _replace_in_line(text: ConfigText, index: int, old: str, new: str) -> None:
    line = text.lines[index]
    set_raw(text, index, line.text.replace(old, new, 1) + (line.ending or text.newline))


def _swap_number(value: str, old: str, new: str) -> str:
    return re.sub(rf"(?<!\d){re.escape(old)}(?!\d)", new, value)


def _rewrite_key(text: ConfigText, index: int, key: str) -> None:
    line = text.lines[index]
    raw = line.raw
    at = raw.find(line.key)
    set_raw(text, index, raw[:at] + key + raw[at + len(line.key):])


def _nodes_entry(host_value: str, port: int) -> str:
    """radio@HOST[:PORT]/NODE,... with the port node-setup writes: none for 4569."""
    m = re.match(r"^(radio@[^/:]+)(?::\d+)?(/.*)$", host_value)
    if not m:
        return host_value
    return m.group(1) + (f":{port}" if port != DEFAULT_IAX_PORT else "") + m.group(2)


class Planner:
    def __init__(self, ws: Workspace):
        self.ws = ws
        self.effects = Effects()

    # ---- reading -------------------------------------------------------------

    def nodes(self) -> list[str]:
        return node_numbers(self.ws.model(RPT))

    def info(self, number: str) -> NodeInfo:
        try:
            return node_info(self.ws, number)
        except KeyError:
            raise PlanError(f"Node {number} is not configured.", "number", "not_found")

    def section(self, number: str) -> Section:
        return Section(self.ws, RPT, number)

    # ---- callsign ------------------------------------------------------------

    def set_callsign(self, number: str, callsign: str, replace_custom: bool = False) -> None:
        info = self.info(number)
        call = check_callsign(callsign)
        if not info.id_simple and not replace_custom:
            # D2: node-setup overwrites any idrecording; here the user decides.
            raise PlanError(f"Node {number} identifies with a custom ID ({info.idrecording}). Replacing it with "
                            f"the call sign removes that setting.", "callsign", "custom_id")
        if info.callsign == call and info.id_simple:
            return
        self.section(number).set("idrecording", f"|i{call}")
        self.effects.restart = True

    # ---- duplex --------------------------------------------------------------

    def set_duplex(self, number: str, duplex: int, linktolink: str | None = None) -> None:
        if duplex not in (0, 1, 2, 3, 4):
            raise PlanError("Duplex type must be a number between 0 and 4.", "duplex")
        info = self.info(number)
        sec = self.section(number)
        cur_duplex = info.duplex if info.duplex is not None else 2
        cur_l2l, cur_hang = info.linktolink, info.hangtime
        new_l2l = (linktolink or cur_l2l).lower() if duplex == 0 else cur_l2l
        if new_l2l not in ("yes", "no"):
            raise PlanError("linktolink must be yes (full duplex) or no (half duplex).", "linktolink")
        if cur_duplex == duplex and cur_l2l == new_l2l:
            return
        hang: int | None = cur_hang  # what the node-specific hangtime should end up as (None: template)
        if duplex == 0:
            if cur_l2l != new_l2l:
                sec.set("linktolink", new_l2l)
            if cur_hang == 2000 or (cur_duplex == 1 and cur_hang == 400):
                hang = 100
        elif cur_duplex == 0:
            if cur_l2l == "yes":
                sec.unset("linktolink")
            if cur_hang == 100:
                hang = None
        if duplex == 1:
            if cur_hang == 2000 or (cur_duplex == 0 and cur_hang == 100):
                hang = 400
        elif cur_duplex == 1 and cur_hang == 400 and hang == cur_hang:
            # D8: node-setup also deletes the "hangtime = 100" it has just
            # added when going from duplex 1 to 0; that is not repeated here.
            hang = None
        if hang is None:
            sec.unset("hangtime")
        elif hang != cur_hang:
            sec.set("hangtime", str(hang))
        sec.set("duplex", str(duplex))
        self.effects.restart = True

    # ---- status posting ------------------------------------------------------

    def set_statpost(self, number: str, enabled: bool) -> None:
        info = self.info(number)
        if enabled and info.private:
            raise PlanError("Status posting cannot be enabled for private nodes.", "statpost")
        if info.statpost == enabled and not info.statpost_inherited:
            return
        sec = self.section(number)
        if enabled:
            sec.set("statpost_url", STATPOST_URL)
        else:
            sec.unset("statpost_url")
            if self.info(number).statpost:
                self.effects.note(f"Node {number} still posts status: statpost_url comes from a template "
                                  f"({', '.join(info.templates)}), which this page does not change.", "warning")
        self.effects.restart = True

    # ---- link at startup ---------------------------------------------------------

    def set_startup_link(self, number: str, target: str | None, mode: str = "transceive",
                         permanent: bool = False, replace_custom: bool = False) -> None:
        """Connect to ``target`` when the node starts (startup_macro), or not at all."""
        from .info import link_codes
        info = self.info(number)
        current = info.startup
        if current["custom"] and not replace_custom:
            raise PlanError(f"Node {number} runs a custom startup macro ({current['macro']}). Replacing it removes "
                            "whatever else it does.", "startup", "custom_macro")
        sec = self.section(number)
        if target is None:
            if info.startup["macro"]:
                sec.unset("startup_macro")
                if self.info(number).startup["macro"]:
                    self.effects.note("startup_macro also comes from a template, which this page does not change.",
                                      "warning")
                self.effects.restart = True
            return
        target = target.strip()
        if not re.fullmatch(r"[0-9]{4,7}", target):
            raise PlanError("Enter the node number to connect to (4 to 7 digits).", "target")
        if target == number:
            raise PlanError(f"Node {number} cannot connect to itself.", "target")
        if mode not in ("transceive", "monitor"):
            raise PlanError("The link must be transceive or monitor only.", "mode")
        rpt = self.ws.model(RPT)
        codes = link_codes(rpt, rpt.get(number))
        code = codes.get((mode, permanent))
        if code is None:
            kind = ("permanent " if permanent else "") + mode
            raise PlanError(f"The node's function table has no {kind} link command"
                            + (" (the permanent link commands 812/813 are commented out in the stock rpt.conf)."
                               if permanent else "."), "permanent" if permanent else "mode", "requirement")
        macro = f"{current['funcchar']}{code}{target}"
        if current["macro"] == macro:
            return
        sec.set("startup_macro", macro)
        self.effects.note(f"When Asterisk starts, node {number} connects to node {target} "
                          f"({'transceive' if mode == 'transceive' else 'monitor only'}"
                          f"{', kept up' if permanent else ''}). Restarting Asterisk makes that link right away.")
        self.effects.restart = True

    # ---- registration and password ----------------------------------------------

    def _remove_registrations(self, number: str) -> None:
        if self.ws.exists(HTTP_REG):
            text = self.ws.text(HTTP_REG)
            delete(text, _lines_matching(text, _register_re(f"{number}:"), "registrations"))
        if self.ws.exists(IAX):
            text = self.ws.text(IAX)
            delete(text, _lines_matching(text, _register_re(f"{number}:"), "general"))

    def _http_registration(self, number: str, password: str) -> None:
        value = f"{number}:{password}@"
        mine = [r for r in registrations(self.ws) if r["node"] == number]
        if mine:
            reg = mine[-1]
            text = self.ws.text(reg["file"])
            line = text.lines[reg["line"]]
            set_raw(text, reg["line"], replace_value(line, value + reg["host"], text.newline))
            return
        text = self.ws.text(HTTP_REG, create=True)
        placeholder = _lines_matching(text, _register_re(HTTP_PLACEHOLDER, commented=False))
        if placeholder:
            _replace_in_line(text, placeholder[0], HTTP_PLACEHOLDER, value)
            return
        headers = find_headers(text, "registrations")
        line = f"register => {value}{REGISTRATION_HOST}"
        if not headers:
            append_section(text, "registrations", [], [line])
            return
        after = last_var(text, headers[0])
        insert(text, after + 1, [line + text.newline])

    def _iax_registration(self, number: str, password: str) -> None:
        """Keep the (commented) IAX registration line in step, as node-setup does."""
        if not self.ws.exists(IAX):
            return
        text = self.ws.text(IAX)
        mine = _lines_matching(text, _register_re(f"{number}:"))
        if mine:
            for i in mine:
                line = text.lines[i]
                new = re.sub(rf"({re.escape(number)}:)[^@]*@", rf"\g<1>{password}@", line.text, count=1)
                set_raw(text, i, new + (line.ending or text.newline))
            return
        placeholder = _lines_matching(text, _register_re(IAX_PLACEHOLDER))
        if placeholder:
            _replace_in_line(text, placeholder[0], IAX_PLACEHOLDER, f"{number}:{password}@")
            return
        headers = find_headers(text, "general")
        if headers:
            regs = _lines_matching(text, _register_re(""), "general")
            after = regs[-1] if regs else last_var(text, headers[0])
            insert(text, after + 1, [f";register => {number}:{password}@{REGISTRATION_HOST}{text.newline}"])

    def set_password(self, number: str, password: str) -> None:
        info = self.info(number)
        if info.private:
            # node-setup: private nodes are never registered.
            self._remove_registrations(number)
            self.effects.restart = True
            return
        password = check_password(password)
        if info.password == password:
            return
        self._http_registration(number, password)
        self._iax_registration(number, password)
        save = savenode.read(self.ws)
        if save.get("NODE") == "0":
            savenode.set_value(self.ws, "NODE", number)
            save["NODE"] = number
        if save.get("NODE") == number:
            savenode.set_value(self.ws, "PASSWORD", password)
            savenode.set_value(self.ws, "ENABLE", "1")
        self.effects.restart = True

    # ---- radio interface -----------------------------------------------------------

    def update_channel_modules(self) -> None:
        """Load the channel drivers the nodes use and no others (node-setup's
        do_update_chan_modules; D7: unused drivers really are set to noload)."""
        if not self.ws.exists("modules.conf"):
            return
        needed = set()
        for number in self.nodes():
            iface = self.info(number).interface
            if iface in CHANNEL_MODULES:
                needed.add(CHANNEL_MODULES[iface])
        for module in ALL_CHANNEL_MODULES:
            set_module(self.ws, module, module in needed)

    def _channel_section(self, number: str, interface: str) -> None:
        name = CHANNEL_FILES[interface]
        text = self.ws.text(name, create=True)
        cfg = self.ws.model(name)
        templated = cfg.get("node-main", include_templates=True) is not None and interface != "Voter"
        headers = find_headers(text, number)
        if not headers:
            # D6: an existing section (from an earlier interface) is reused as is.
            append_section(text, number, ["node-main"] if templated else [])
            headers = find_headers(text, number)
        header = headers[0]
        if interface == "Voter":
            samples = [i for i in range(header + 1, section_end(text, header))
                       if re.match(r"^;(NORTH|SOUTH|EAST|WEST)\s*=", text.lines[i].text)]
            delete(text, samples)
            insert(text, header + 1, [text.newline] + [s + text.newline for s in VOTER_SAMPLES])
            return
        if section_vars(text, header, "devstr"):
            return
        tune = SIMPLEUSB_TUNE if interface == "SimpleUSB" else USBRADIO_TUNE
        keys = {t.split("=")[0].strip() for t in tune}
        old = [i for i in range(header + 1, section_end(text, header))
               if (text.lines[i].kind == "variable" and text.lines[i].key in keys)
               or re.match(r"^;;;;; .*Tune settings", text.lines[i].text)]
        delete(text, old)
        body = [""]
        if not templated:
            body += (SIMPLEUSB_DEFAULTS if interface == "SimpleUSB" else USBRADIO_DEFAULTS) + [""]
        body += [";;;;; Tune settings ;;;;;"] + tune
        insert(text, header + 1, [b + text.newline for b in body])

    def set_interface(self, number: str, interface: str) -> None:
        if interface not in INTERFACES:
            raise PlanError(f"{interface} is not a known radio interface.", "interface")
        info = self.info(number)
        if info.interface == interface:
            return
        self.section(number).set("rxchannel", INTERFACES[interface].format(node=number))
        self.update_channel_modules()
        if interface in CHANNEL_FILES:
            self._channel_section(number, interface)
        if info.interface in CHANNEL_FILES and info.interface != interface:
            self.effects.note(f"The node's {CHANNEL_FILES[info.interface]} settings are kept, in case you switch back.")
            if interface in CHANNEL_FILES:
                self._carry_over(number, info.interface, interface)
        self.effects.restart = True
        self.effects.tune = interface in ("SimpleUSB", "USBRadio")

    def _driver_value(self, interface: str, number: str, key: str) -> str | None:
        name = CHANNEL_FILES[interface]
        if not self.ws.exists(name):
            return None
        cat = self.ws.model(name).get(number)
        return cat.value(key) if cat else None

    def _carry_over(self, number: str, old: str, new: str) -> None:
        """What the old driver did with the radio's lines, compared with what
        the new driver will do. A different PTT polarity keys the transmitter
        as soon as Asterisk starts (and USBRadio offers no command to change
        it), so it is carried over; detection differences are only reported,
        because the new driver may rightly detect differently (USBRadio's DSP)."""
        def truth(value: str | None) -> bool:
            return (value or "no").strip().lower() in ("yes", "y", "true", "1", "on")

        old_ptt = truth(self._driver_value(old, number, "invertptt"))
        new_ptt = truth(self._driver_value(new, number, "invertptt"))
        if old_ptt != new_ptt:
            Section(self.ws, CHANNEL_FILES[new], number).set("invertptt", "yes" if old_ptt else "no")
            self.effects.note(f"PTT polarity carried over from {CHANNEL_FILES[old]}: invertptt = "
                              f"{'yes' if old_ptt else 'no'}. With the {new} default "
                              f"({'yes' if new_ptt else 'no'}) the transmitter would key as soon as Asterisk "
                              "restarts.", "warning")
        for key, label in (("carrierfrom", "Carrier (COS) detection"), ("ctcssfrom", "CTCSS detection")):
            before = (self._driver_value(old, number, key) or "no").strip().lower()
            after = (self._driver_value(new, number, key) or "no").strip().lower()
            if before != after:
                self.effects.note(f"{label} changes from \"{before}\" ({old}) to \"{after}\" ({new}'s settings). "
                                  "Check it on the Tuning tab after the restart; a full-duplex node repeats "
                                  "whatever it detects as a signal.", "warning")

    # ---- rename --------------------------------------------------------------------

    def rename(self, old: str, new: str) -> None:
        info = self.info(old)
        new = check_node_number(new, self.nodes(), allow=old)
        if new == old:
            return
        rpt = self.ws.model(RPT)
        # Customization stanzas named after the node, and the node's references
        # to them (D9: node-setup leaves them under the old number).
        for kind, key in REFERENCE_KEYS.items():
            ref = info.references[kind]
            if ref.section == f"{kind}-{old}":
                if rpt.get(f"{kind}-{new}") is None and ref.exists:
                    Section(self.ws, RPT, ref.section).rename(f"{kind}-{new}")
                self.section(old).set(key, f"{kind}-{new}")
        sec = self.section(old)
        rx = rpt.get(old).effective("rxchannel")
        if rx is not None and rx.inherited_from is None and re.match(rf"^(SimpleUSB|Radio|Voter)/{old}$", rx.value, re.I):
            sec.set("rxchannel", _swap_number(rx.value, old, new))
        sec.rename(new)
        nodes = self.ws.model(RPT).get("nodes")
        if nodes is not None:
            for v in [v for v in nodes.own() if v.key == old]:
                text = self.ws.text(v.file)
                _rewrite_key(text, v.line, new)
                line = text.lines[v.line]
                set_raw(text, v.line, replace_value(line, _swap_number(line.value, old, new), text.newline))
        if int(new) < PRIVATE_LIMIT and info.statpost:
            self.set_statpost(new, False)
        if int(new) >= PRIVATE_LIMIT:
            # As node-setup: the node's registration lines follow the new
            # number; without one, the stock placeholder becomes "<new>:" and
            # gets its password when the password is set.
            for name, section, placeholder in ((HTTP_REG, "registrations", HTTP_PLACEHOLDER),
                                               (IAX, "general", IAX_PLACEHOLDER)):
                if not self.ws.exists(name):
                    continue
                text = self.ws.text(name)
                mine = _lines_matching(text, _register_re(f"{old}:"), section)
                for i in mine:
                    _replace_in_line(text, i, f"{old}:", f"{new}:")
                if not mine:
                    for i in _lines_matching(text, _register_re(placeholder), section)[:1]:
                        _replace_in_line(text, i, placeholder, f"{new}:@")
        else:
            self._remove_registrations(old)
            if self.ws.exists(HTTP_REG):
                text = self.ws.text(HTTP_REG)
                delete(text, _lines_matching(text, _register_re(HTTP_PLACEHOLDER, commented=False), "registrations"))
        self._primary_node(old, new)
        save = savenode.read(self.ws)
        if save.get("NODE") == old:
            savenode.set_value(self.ws, "NODE", new)
        for name in ("simpleusb.conf", "usbradio.conf", "voter.conf"):
            if self.ws.exists(name):
                text = self.ws.text(name)
                for header in find_headers(text, old):
                    line = text.lines[header]
                    set_raw(text, header, header_line(new, line.options, line, text.newline))
        self.effects.astdb.append(("rename", old, new))
        self.effects.allmon3.append({"kind": "rename", "old": old, "new": new,
                                     "text": f"Rename node {old} to {new} in /etc/allmon3/allmon3.ini, if it is listed there."})
        self.effects.restart = True
        self.effects.tune = info.interface in ("SimpleUSB", "USBRadio")

    def _primary_node(self, old: str, new: str) -> None:
        """extensions.conf's NODE = <number> (older configurations)."""
        if not self.ws.exists(EXTENSIONS):
            return
        cfg = self.ws.model(EXTENSIONS)
        for cat in cfg.categories:
            for v in cat.own():
                if v.key == "NODE" and v.value == old:
                    text = self.ws.text(v.file)
                    set_raw(text, v.line, replace_value(text.lines[v.line], new, text.newline))

    # ---- add and remove ----------------------------------------------------------------

    def add(self, number: str, *, password: str | None = None, interface: str | None = None,
            duplex: int | None = None, linktolink: str | None = None, callsign: str | None = None,
            statpost: bool | None = None) -> None:
        """node-setup's do_node_add: a new [number](node-main) section and its
        [nodes] entry, then the chosen settings."""
        number = check_node_number(number, self.nodes())
        self._check_defaults(number, password, callsign)
        rpt_text = self.ws.text(RPT)
        rpt = self.ws.model(RPT)
        if rpt.get("node-main", include_templates=True) is None:
            raise PlanError("rpt.conf has no [node-main] template, so a node cannot be added here. "
                            "Add it in Manual Config Edit.", code="requirement")
        nodes = find_headers(rpt_text, "nodes")
        if not nodes:
            raise PlanError("rpt.conf has no [nodes] section.", code="requirement")
        append_section(rpt_text, number, ["node-main"])
        nodes = find_headers(rpt_text, "nodes")
        entry = _nodes_entry(f"radio@127.0.0.1/{number},NONE", iax_port(self.ws))
        after = last_var(rpt_text, nodes[0])
        insert(rpt_text, after + 1, [var_line(rpt_text, number, entry, near=after)])
        self._defaults(number, password, interface, duplex, linktolink, callsign, statpost)

    def first_run(self, number: str, *, password: str | None = None, interface: str | None = None,
                  duplex: int | None = None, linktolink: str | None = None, callsign: str | None = None,
                  statpost: bool | None = None) -> None:
        """node-setup's first run: the stock node 1999 becomes the user's node."""
        number = check_node_number(number, self.nodes(), allow="1999")
        self._check_defaults(number, password, callsign)
        self.info("1999")
        if number != "1999":
            self.rename("1999", number)
        self._defaults(number, password, interface, duplex, linktolink, callsign, statpost)

    def _check_defaults(self, number: str, password: str | None, callsign: str | None) -> None:
        if int(number) >= PRIVATE_LIMIT:
            if not password:
                raise PlanError("Enter the node password from the AllStarLink portal.", "password")
            check_password(password)
        if callsign:
            check_callsign(callsign)

    def _defaults(self, number, password, interface, duplex, linktolink, callsign, statpost) -> None:
        """node-setup's do_node_set_defaults."""
        public = int(number) >= PRIVATE_LIMIT
        if interface:
            # As node-setup (CURRENT_INTERFACE_TYPE="?"): the interface's
            # channel section and driver are ensured even when the node
            # already had this interface.
            self.set_interface(number, interface)
            if interface in CHANNEL_FILES:
                self._channel_section(number, interface)
        self.update_channel_modules()
        if duplex is not None:
            self.set_duplex(number, duplex, linktolink)
        if public and password:
            self.set_password(number, password)
        if callsign:
            self.set_callsign(number, callsign, replace_custom=True)
        if statpost is None:
            statpost = public and (interface is not None or duplex is not None)
        if public and statpost != self.info(number).statpost:
            self.set_statpost(number, statpost)
        self._primary_node("0", number)
        self.effects.restart = True
        self.effects.tune = interface in ("SimpleUSB", "USBRadio")

    def remove(self, number: str) -> None:
        info = self.info(number)
        keep = lambda comment: number not in comment  # D5
        text = self.ws.text(info.file)
        remove_section(text, find_headers(text, number)[0], keep)
        for kind in REFERENCE_KEYS:
            cat = self.ws.model(RPT).get(f"{kind}-{number}")
            if cat is not None:
                t = self.ws.text(cat.file)
                remove_section(t, find_headers(t, cat.name)[0], keep)
        nodes = self.ws.model(RPT).get("nodes")
        if nodes is not None:
            by_file: dict[str, list[int]] = {}
            for v in nodes.own():
                if v.key == number:
                    by_file.setdefault(v.file, []).append(v.line)
            for path, lines in by_file.items():
                delete(self.ws.text(path), lines)
        self._remove_registrations(number)
        for name in ("simpleusb.conf", "usbradio.conf", "voter.conf"):
            if self.ws.exists(name):
                t = self.ws.text(name)
                headers = find_headers(t, number)
                if headers:
                    remove_section(t, headers[0], keep)
        remaining = self.nodes()
        replacement = remaining[0] if remaining else "0"
        self._primary_node(number, replacement)
        save = savenode.read(self.ws)
        if save.get("NODE") == number:
            if not remaining:
                savenode.set_value(self.ws, "PASSWORD", "")
                savenode.set_value(self.ws, "ENABLE", "0")
            savenode.set_value(self.ws, "NODE", replacement)
        self.update_channel_modules()
        self.effects.restart = True

    # ---- customizations ----------------------------------------------------------------

    def customize(self, number: str, names: list[str]) -> None:
        from . import customize
        customize.apply(self.ws, number, names, self.effects)

    # ---- server-wide settings ------------------------------------------------------------

    def set_iax_port(self, port) -> None:
        port = check_port(port)
        if port == iax_port(self.ws):
            return
        Section(self.ws, IAX, "general").set("bindport", str(port))
        nodes = self.ws.model(RPT).get("nodes")
        local = set(self.nodes())
        if nodes is not None:
            for v in nodes.own():
                if v.key in local and v.value.lower().startswith("radio@"):
                    text = self.ws.text(v.file)
                    new = _nodes_entry(v.value, port)
                    if new != v.value:
                        set_raw(text, v.line, replace_value(text.lines[v.line], new, text.newline))
        self.effects.note("Other nodes reach yours on the new port only after your router forwards it.")
        self.effects.restart = True

    def ami_users(self) -> list[str]:
        if not self.ws.exists(MANAGER):
            return []
        return [c.name for c in self.ws.model(MANAGER).categories if c.name.lower() != "general" and not c.template]

    def set_ami_secret(self, secret: str) -> None:
        secret = check_secret(secret)
        cfg = self.ws.model(MANAGER) if self.ws.exists(MANAGER) else None
        if cfg is None or cfg.get("admin") is None:
            raise PlanError("manager.conf has no [admin] user.", code="requirement")
        old_secret = cfg.value("admin", "secret")
        if old_secret == secret:
            return
        # D3: only the [admin] user, which Allmon3 uses; node-setup changes
        # every user that shares the old secret.
        Section(self.ws, MANAGER, "admin").set("secret", secret)
        others = [u for u in self.ami_users() if u.lower() != "admin"]
        if others:
            self.effects.note(f"Other AMI users are not changed: {', '.join(others)}.")
        self.effects.allmon3.append({"kind": "secret", "old": old_secret or "", "new": secret,
                                     "text": "Set the new AMI secret as \"pass\" in /etc/allmon3/allmon3.ini, "
                                             "then restart Allmon3."})
        self.effects.restart = True


def run(ws: Workspace, fn, *args, **kwargs) -> Effects:
    planner = Planner(ws)
    try:
        fn(planner, *args, **kwargs)
    except EditError as exc:
        raise PlanError(str(exc), code="requirement") from exc
    return planner.effects
