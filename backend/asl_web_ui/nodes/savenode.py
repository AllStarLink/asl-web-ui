"""savenode.conf: KEY=VALUE lines read by the backup tools as shell variables.

Edits change only the value of an existing assignment (keeping anything after
it), matching node-setup's ``sed "/^KEY\\s*=/ s/KEY\\s*=.*/KEY=value/"``.
"""

import re

from ..configengine.edit import Workspace, set_raw

NAME = "savenode.conf"
_ASSIGN = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=(?P<value>.*)$")


def read(ws: Workspace) -> dict[str, str]:
    if not ws.exists(NAME):
        return {}
    out = {}
    for line in ws.text(NAME).lines:
        m = _ASSIGN.match(line.text)
        if m:
            value = m.group("value").strip()
            out[m.group("key")] = value.split()[0] if value else ""
    return out


def set_value(ws: Workspace, key: str, value: str) -> None:
    if not ws.exists(NAME):
        return
    text = ws.text(NAME)
    for i, line in enumerate(text.lines):
        m = _ASSIGN.match(line.text)
        if m and m.group("key") == key:
            set_raw(text, i, f"{key}={value}" + (line.ending or text.newline))
