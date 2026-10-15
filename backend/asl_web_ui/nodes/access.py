"""Node access lists in the Asterisk database (no restart needed).

The stock dialplan (extensions.conf) admits a connection to node N from node
or call X when allowlist/N/X exists, or, with no allowlist for N, when
denylist/N/X does not. node-setup's "Node access list" edits these entries
with "database put/del/deltree"; so does this module.
"""

import re

from ..asterisk_cli import AsteriskCLI
from .planner import PlanError

LISTS = {"allow": "allowlist", "deny": "denylist"}
_ENTRY = re.compile(r"^(?:[0-9]+|[0-9A-Za-z/-]{3,})$")
_REASON = re.compile(r'^[^"\\\r\n]{0,100}$')
_LINE = re.compile(r"^/(?P<list>allowlist|denylist)/(?P<node>[^/\s]+)/(?P<entry>\S+?)\s*:\s?(?P<reason>.*?)\s*$")


def check_entry(entry: str) -> str:
    entry = entry.strip().upper()
    if not _ENTRY.match(entry):
        raise PlanError("Enter a node number or a call sign.", "entry")
    return entry


def check_reason(reason: str) -> str:
    reason = reason.strip()
    if not _REASON.match(reason):
        raise PlanError('The reason can be up to 100 characters, without quotes (") or backslashes.', "reason")
    return reason


def parse(text: str, number: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {"allow": [], "deny": []}
    for line in text.splitlines():
        m = _LINE.match(line)
        if m and m.group("node") == number:
            kind = "allow" if m.group("list") == "allowlist" else "deny"
            out[kind].append({"entry": m.group("entry"), "reason": m.group("reason")})
    for entries in out.values():
        entries.sort(key=lambda e: (not e["entry"].isdigit(), int(e["entry"]) if e["entry"].isdigit() else 0,
                                    e["entry"]))
    return out


async def lists(cli: AsteriskCLI, number: str) -> dict[str, list[dict]]:
    text = await cli.run(f"database show allowlist {number}")
    text += "\n" + await cli.run(f"database show denylist {number}")
    return parse(text, number)


def mode(entries: dict[str, list[dict]]) -> str:
    """What the dialplan does: "allow" (only listed), "deny" (all but listed) or "open"."""
    if entries["allow"]:
        return "allow"
    if entries["deny"]:
        return "deny"
    return "open"


async def add(cli: AsteriskCLI, number: str, kind: str, entry: str, reason: str) -> None:
    if kind not in LISTS:
        raise PlanError("The list must be allow or deny.", "list")
    entry = check_entry(entry)
    if entry == number:
        raise PlanError(f"Node {number} cannot {kind} itself.", "entry")
    reason = check_reason(reason)
    await cli.run(f'database put {LISTS[kind]}/{number} {entry} "{reason}"')


async def remove(cli: AsteriskCLI, number: str, kind: str, entry: str) -> None:
    if kind not in LISTS:
        raise PlanError("The list must be allow or deny.", "list")
    await cli.run(f"database del {LISTS[kind]}/{number} {check_entry(entry)}")


async def clear(cli: AsteriskCLI, number: str, kind: str) -> None:
    if kind not in LISTS:
        raise PlanError("The list must be allow or deny.", "list")
    await cli.run(f"database deltree {LISTS[kind]} {number}")


async def rename(cli: AsteriskCLI, old: str, new: str) -> None:
    """Move a node's lists to its new number (node-setup's do_node_rename)."""
    current = await lists(cli, old)
    for kind, entries in current.items():
        for e in entries:
            await cli.run(f'database put {LISTS[kind]}/{new} {e["entry"]} "{e["reason"]}"')
    if current["allow"] or current["deny"]:
        await cli.run(f"database deltree allowlist {old}")
        await cli.run(f"database deltree denylist {old}")
