"""Allmon3's settings (/etc/allmon3/allmon3.ini, an INI file).

node-setup keeps Allmon3 in step: renaming a node renames its [node]
section, changing the AMI secret changes "pass" where it held the old
secret. Same edits here, line by line, leaving everything else as it is.
The file belongs to allmon3 (mode 0660), so it is read and written through
the privileged helper.
"""

import re

PATH = "/etc/allmon3/allmon3.ini"


def apply(text: str, actions: list[dict]) -> str:
    lines = text.splitlines(keepends=True)
    for action in actions:
        if action["kind"] == "rename":
            old, new = re.escape(action["old"]), action["new"]
            lines = [re.sub(rf"^(\s*\[){old}(\])", rf"\g<1>{new}\g<2>", line) for line in lines]
        elif action["kind"] == "secret":
            old, new = action["old"], action["new"]
            out = []
            for line in lines:
                m = re.match(r"^(\s*pass\s*=\s*)(\S+)(.*)$", line, re.S)
                if m and m.group(2) == old:
                    line = m.group(1) + new + m.group(3)
                out.append(line)
            lines = out
    return "".join(lines)
