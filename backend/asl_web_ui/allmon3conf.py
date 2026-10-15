"""Allmon3's configuration files: reading, checking and line-preserving edits.

Allmon3 (1.11) reads its INI files with Python's configparser and stops, or
silently loses parts of its menu, when one is malformed. The checks here
parse each file the way Allmon3 does and report what would go wrong, by line:

- allmon3.ini: one section per node number with host, user and pass
  (port, pollinterval ... must be numbers);
- web.ini: [web], [syscmds], [node-overrides] and [voter-titles] must exist;
- menu.ini: each section is a menu (type = menu | single); Allmon3 builds
  JSON from it by pasting strings, so quotes and backslashes break the menu,
  and an empty file leaves no menu at all;
- user-restrictions: "USER | NODE[,NODE...]" lines; any other line stops
  Allmon3 when it loads the file.

Edits change only the lines they must, so comments and the order of
everything else stay as they were.
"""

import configparser
import json
import re

DIR = "/etc/allmon3"
FILES = {
    "allmon3.ini": "Nodes Allmon3 monitors and how it reaches their Asterisk manager",
    "web.ini": "Web interface: title, logo, command menu, node labels",
    "menu.ini": "Custom sidebar menu (optional; without it every node is listed)",
    "user-restrictions": "Users who may send commands only to some nodes",
    "custom.css": "Style changes for the web interface",
}
OPTIONAL = {"menu.ini"}
WEB_KEYS = ["CONFIG_HEADER_TITLE", "CONFIG_HEADER_LOGO", "CONFIG_MENU_SINGLE_TARGET", "HOME_BUTTON_URL",
            "HTTP_PORT", "WS_PORT_START", "WS_BIND_ADDR", "USERS_TABLE_LOCATION", "USERS_RESTRICTIONS_LOCATION"]
NODE_KEYS = ["host", "port", "user", "pass", "multinodes", "voters", "pollinterval", "vpollinterval",
             "retryinterval", "retrycount", "iframepre", "iframepost"]
SECTION_RE = re.compile(r"^\s*\[([^\]]*)\]")
KEY_RE = re.compile(r"^\s*([^=:;#\s][^=:]*?)\s*[=:]")


def path(name: str) -> str:
    return f"{DIR}/{name}"


def finding(line: int | None, message: str, severity: str = "error") -> dict:
    return {"line": line, "severity": severity, "message": message}


# ---- reading -----------------------------------------------------------------------------


def _parser(case_sensitive: bool = False) -> configparser.ConfigParser:
    cp = configparser.ConfigParser()
    if case_sensitive:
        cp.optionxform = str  # type: ignore[assignment,method-assign]
    return cp


def _parse(text: str, case_sensitive: bool = False) -> tuple[configparser.ConfigParser | None, list[dict]]:
    cp = _parser(case_sensitive)
    try:
        cp.read_string(text)
    except configparser.MissingSectionHeaderError as exc:
        return None, [finding(exc.lineno, "Settings must come after a [section] line.")]
    except (configparser.DuplicateSectionError, configparser.DuplicateOptionError) as exc:
        what = f"[{exc.section}] appears twice" if isinstance(exc, configparser.DuplicateSectionError) \
            else f"{exc.option} appears twice in [{exc.section}]"
        return None, [finding(exc.lineno, f"{what}; Allmon3 cannot load the file.")]
    except configparser.ParsingError as exc:
        return None, [finding(line, f"Not a setting: {raw.strip()}") for line, raw in exc.errors]
    out = []
    for section in cp.sections():
        for key in cp[section]:
            try:
                cp[section][key]
            except configparser.InterpolationError:
                out.append(finding(_line_of(text, section, key),
                                   f"{key} in [{section}]: a % must be written as %% (Allmon3 reads % as a variable)."))
    return cp, out


def _line_of(text: str, section: str | None, key: str | None = None) -> int | None:
    section = section.strip() if section is not None else None
    current = None
    for i, line in enumerate(text.splitlines(), 1):
        m = SECTION_RE.match(line)
        if m:
            current = m.group(1).strip()
            if key is None and current == section:
                return i
            continue
        k = KEY_RE.match(line)
        if key is not None and current == section and k and k.group(1).strip().lower() == key.lower():
            return i
    return None


def nodes(text: str) -> list[dict]:
    """allmon3.ini's node sections, in file order (pass reported only as set or not)."""
    cp, _ = _parse(text)
    if cp is None:
        return []
    out = []
    for section in cp.sections():
        values = {k: cp[section].get(k, raw=True) for k in NODE_KEYS if k in cp[section]}
        out.append({"node": section, "line": _line_of(text, section), **values})
    return out


def web_settings(text: str) -> dict[str, str]:
    cp, _ = _parse(text)
    if cp is None or not cp.has_section("web"):
        return {}
    return {k: cp["web"].get(k, raw=True).strip().strip("'\"") for k in WEB_KEYS if k.lower() in cp["web"]}


def restrictions(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in text.splitlines():
        user, sep, nodes_ = line.partition("|")
        if not sep or user.lstrip().startswith("#"):
            continue
        out[user.strip()] = [n.strip() for n in nodes_.split(",") if n.strip()]
    return out


# ---- checking ----------------------------------------------------------------------------


def check(name: str, text: str) -> list[dict]:
    if name == "allmon3.ini":
        return _check_nodes(text)
    if name == "web.ini":
        return _check_web(text)
    if name == "menu.ini":
        return _check_menu(text)
    if name == "user-restrictions":
        return _check_restrictions(text)
    return []


def _number(value: str, kind=float) -> bool:
    try:
        kind(value)
        return True
    except ValueError:
        return False


def _check_nodes(text: str) -> list[dict]:
    cp, out = _parse(text)
    if cp is None:
        return out
    if not cp.sections():
        out.append(finding(None, "No nodes are configured, so Allmon3 has nothing to show.", "warning"))
    for section in cp.sections():
        line = _line_of(text, section)
        s = cp[section]
        if not section.isdigit():
            out.append(finding(line, f"[{section}] is not a node number; Allmon3 stops at it."))
            continue
        if "colocated_on" in s:
            out.append(finding(_line_of(text, section, "colocated_on"),
                               "colocated_on is no longer supported; Allmon3 stops at it. Use multinodes."))
        for key in ("host", "user", "pass"):
            if key not in s:
                out.append(finding(line, f"Node {section} has no {key}; Allmon3 stops at it."))
        for key, kind in (("port", int), ("retryinterval", int), ("retrycount", int), ("pollinterval", float),
                          ("vpollinterval", float)):
            if key in s and not _number(s.get(key, raw=True), kind):
                out.append(finding(_line_of(text, section, key), f"{key} must be a number."))
        for key in ("voters", "multinodes"):
            if key in s and not all(v.strip().isdigit() for v in s.get(key, raw=True).split(",")):
                out.append(finding(_line_of(text, section, key), f"{key} must be node numbers separated by commas."))
    return out


def _check_web(text: str) -> list[dict]:
    cp, out = _parse(text)
    if cp is None:
        return out
    for section in ("web", "syscmds", "node-overrides", "voter-titles"):
        if not cp.has_section(section):
            out.append(finding(None, f"The [{section}] section is missing; Allmon3 does not start without it "
                                     "(it may be empty)."))
    if cp.has_section("web"):
        for key in ("HTTP_PORT", "WS_PORT_START"):
            if key.lower() in cp["web"] and not _number(cp["web"].get(key, raw=True), int):
                out.append(finding(_line_of(text, "web", key), f"{key} must be a number."))
    if cp.has_section("voter-titles"):
        for key in cp["voter-titles"]:
            if not key.isdigit():
                out.append(finding(_line_of(text, "voter-titles", key), f"{key} is not a node number."))
    for section in cp.sections():
        if section.startswith("syscmds-") and not section[8:].isdigit():
            out.append(finding(_line_of(text, section), f"[{section}] must name a node: [syscmds-NODE].", "warning"))
    return out


def menu_json(cp: configparser.ConfigParser) -> str:
    """The menu as Allmon3 1.11 builds it for its web page (string pasting, as in /usr/bin/allmon3)."""
    full_menu = "[ "
    for m in cp:
        if m != "DEFAULT":
            menu_string = "["
            for sm in cp[m]:
                menu_string += f"{{\"{sm}\" : \"{cp[m].get(sm, raw=True)}\"}}, "
            menu_string = re.sub(r",\s$", "] ", menu_string)
            full_menu += f"{{ \"{m}\" : {menu_string} }} ,"
    return re.sub(r",$", "]", full_menu)


def _check_menu(text: str) -> list[dict]:
    cp, out = _parse(text, case_sensitive=True)
    if cp is None:
        return out
    if not cp.sections():
        return out + [finding(None, "The menu is empty, which leaves Allmon3 with no menu at all. Remove menu.ini "
                                    "instead to list every node.")]
    for section in cp.sections():
        line = _line_of(text, section)
        s = cp[section]
        if not list(s):
            out.append(finding(line, f"[{section}] is empty, which breaks Allmon3's whole menu."))
            continue
        if s.get("type", raw=True) not in ("menu", "single"):
            out.append(finding(line, f"[{section}] should have type = menu or type = single (otherwise it is "
                                     "shown as single).", "warning"))
        if not [k for k in s if k != "type"]:
            out.append(finding(line, f"[{section}] has no LABEL = TARGET entries.", "warning"))
        for key in [None, *s]:
            what = section if key is None else key + s.get(key, raw=True)
            if re.search(r'["\\]', what):
                out.append(finding(_line_of(text, section, key), 'Quotes (") and backslashes break Allmon3\'s menu.'))
    if not any(f["severity"] == "error" for f in out):
        try:
            json.loads(menu_json(cp))
        except ValueError:
            out.append(finding(None, "Allmon3 would build a menu its web page cannot read from this file."))
    return out


def _check_restrictions(text: str) -> list[dict]:
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        if line.startswith("#"):
            continue
        if line.lstrip().startswith("#"):
            out.append(finding(i, "A comment must start with # at the beginning of the line.", "error"))
            continue
        user, sep, nodes_ = line.partition("|")
        if not sep:
            out.append(finding(i, "Expected USER | NODE[,NODE...]; Allmon3 stops at this line."))
        elif not all(n.strip().isdigit() for n in nodes_.split(",")):
            out.append(finding(i, "List node numbers separated by commas.", "warning"))
    return out


# ---- editing -----------------------------------------------------------------------------


def _sections(lines: list[str]) -> list[tuple[str, int, int]]:
    """(name, header index, end index) for each section; end excludes trailing blank lines."""
    heads = [(i, m.group(1).strip()) for i, line in enumerate(lines) if (m := SECTION_RE.match(line))]
    out = []
    for n, (i, name) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        while end > i + 1 and not lines[end - 1].strip():
            end -= 1
        out.append((name, i, end))
    return out


def set_values(text: str, section: str, values: dict[str, str | None]) -> str:
    """Set (or with None, remove) keys in [section], adding the section at the end if needed."""
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    found = next((s for s in _sections(lines) if s[0] == section), None)
    if found is None:
        new = [f"{k}={v}\n" for k, v in values.items() if v is not None]
        if not new:
            return "".join(lines)
        if lines and lines[-1].strip():
            lines.append("\n")
        return "".join(lines + [f"[{section}]\n", *new])
    _, start, end = found
    pending = dict(values)
    body = []
    for line in lines[start + 1:end]:
        m = KEY_RE.match(line)
        key = next((k for k in pending if m and m.group(1).strip().lower() == k.lower()), None)
        if key is None:
            body.append(line)
        elif pending[key] is not None:
            # Keep the spacing around "=" as it was.
            eq = re.match(r"^(\s*[^=:]*?\s*[=:]\s*)", line)
            body.append(f"{eq.group(1) if eq else key + '='}{pending.pop(key)}\n")
        else:
            pending.pop(key)
    body += [f"{k}={v}\n" for k, v in pending.items() if v is not None]
    return "".join(lines[:start + 1] + body + lines[end:])


def remove_section(text: str, section: str) -> str:
    lines = text.splitlines(keepends=True)
    found = next((s for s in _sections(lines) if s[0] == section), None)
    if found is None:
        return text
    _, start, end = found
    while end < len(lines) and not lines[end].strip():
        end += 1
    return "".join(lines[:start] + lines[end:])


def set_restriction(text: str, user: str, node_list: list[str] | None) -> str:
    """Replace USER's line in user-restrictions; None removes it (no restriction)."""
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    new = f"{user} | {','.join(node_list)}\n" if node_list else None
    out, done = [], False
    for line in lines:
        name, sep, _ = line.partition("|")
        if sep and not name.lstrip().startswith("#") and name.strip() == user:
            if new and not done:
                out.append(new)
            done = True
            continue
        out.append(line)
    if new and not done:
        out.append(new)
    return "".join(out)
