"""asl-node-auth-check: run it and read its results.

The --json mode (docs/upstream-changes.md, section 1) is used when the
installed version has it. Older versions' text output is parsed into the same
structure: sections (run, config, public_ip, node), findings with a level, the
original message, a stable id and the values behind the message.
"""

import asyncio
import json
import re
import time
from dataclasses import dataclass, field

TOOL = "/usr/bin/asl-node-auth-check"
TIMEOUT = 180

_LINE = re.compile(r"^\s*(Error|Warning|Info|OK):\s?(.*)$")
_NODE_HEADING = re.compile(r"^Testing node (\d+):\s*$")

# (id, pattern, data names for the groups[, fixed data]). Order matters: first
# match wins. Fixed data fills in the values --json gives that the text only
# implies, such as a reason or status.
PATTERNS: list[tuple] = [
    ("run.permission_denied", r"Access denied: script must run as root or asterisk(?: \(current user: (\S+)\))?", ("user",)),
    ("config.nodes", r"rpt\.conf has configuration for: ?(.*)", ("nodes",)),
    ("config.no_nodes", r"NO NODE ARE CONFIGURED IN rpt\.conf", ()),
    ("config.private_node_skipped", r"Skipping evaluation of private node (\d+)", ("node",)),
    ("config.include_missing", r"Include target not found: (.*) \(from (.*)\)", ("target", "from")),
    ("config.file_unreadable", r"Config file not found: (.*)", ("file",), {"reason": "not_found"}),
    ("config.file_unreadable", r"Permission denied reading: (.*)", ("file",), {"reason": "permission_denied"}),
    ("config.file_unreadable", r"Error reading (\S+): ", ("file",), {"reason": "error"}),
    ("config.registration_lines", r"(\S+) contains (no|\d+) registration line", ("file", "count")),
    ("config.registration_invalid", r"Invalid registration >> (.*) << in (\S+)", ("value", "file")),
    ("config.no_registrations", r"NO VALID REGISTRATIONS EXIST", ()),
    ("config.registrations", r"Registrations present for configured node\(s\): ?(.*)", ("nodes",)),
    ("config.duplicate_registrations", r"Duplicated HTTP and IAX registrations for: ?(.*)", ("nodes",)),
    ("config.missing_registration", r"No registration present for configured node\(s\): ?(.*)", ("nodes",)),
    ("config.missing_configuration", r"No configuration present for registrations for node\(s\): ?(.*)", ("nodes",)),
    ("config.cannot_continue", r"Cannot continue; reconcile configuration", ()),
    ("config.run_asl_menu", r"RUN asl-menu OR INSPECT THE CONFIG FILES", ()),
    ("public_ip.http_probe", r"IP from (https?://\S+) reports: (\S+)", ("url", "ip")),
    ("public_ip.iax_probe", r"IP from (udp://\S+) reports: (\S+)", ("host", "ip")),
    ("public_ip.http_probe", r"IP test to (https?://\S+) failed", ("url",), {"ip": None}),
    ("public_ip.iax_probe", r"IP test to (udp://\S+) failed", ("host",), {"ip": None}),
    ("public_ip.http_consensus", r"HTTP IP probes (?:have|DO NOT have) consensus", ()),
    ("public_ip.iax_consensus", r"IAX IP probes (?:have|DO NOT have) consensus", ()),
    ("public_ip.http_iax_match", r"HTTP and IAX probes perceive different IPs \((\S+) != (\S+)\)", ("http_ip", "iax_ip")),
    ("public_ip.http_iax_match", r"HTTP \((\S+)\) and IAX \((\S+)\) perceived IPs not compared", ("http_ip", "iax_ip")),
    ("public_ip.http_iax_match", r"HTTP and IAX probes perceive the same IP \((\S+)\)", ("http_ip",)),
    ("node.well_formed", r"Node registration config is well-formed", ()),
    ("node.well_formed", r"Node (\S+) is outside the numeric range", ("node",)),
    ("node.well_formed", r"Registration has \"node\" (\S+) which is not a number", ("node",)),
    ("node.well_formed", r"Registration has a reghost of '(.*)' which is not", ("reghost",)),
    ("node.registration_type", r"Node registration type is (\S+)", ("type",)),
    ("node.regserver_reachable", r"register\.allstarlink\.org is (?:reachable|unreachable)", ()),
    ("node.registration_state", r"There is no apparent (HTTP|IAX) registration attempt", ("type",), {"state": None}),
    ("node.registration_state", r"(HTTP|IAX) registration state is (.*)", ("type", "state")),
    ("node.perceived_address", r"Perceived (?:HTTP|IAX) IP:PORT for this node is: (\S+)", ("address",)),
    ("node.registrar", r"Registered to (.*) - (\S+)", ("name", "ip")),
    ("node.udp_port", r"Server-set UDP port matches bindport", ()),
    ("node.udp_port", r"Registered UDP port does not match bindport in iax\.conf: (\S+) != (\S+)", ("registered_port", "bindport")),
    ("node.udp_port_note", r"(?:Mismatched IAX information|perform the external->internal|can be used to confirm inbound)", ()),
    ("node.bindport_missing", r"binddport does not appear to be set", ()),
    ("node.stats_unavailable", r"No stats available", (), {"reason": "no_stats"}),
    ("node.stats_unavailable", r"Node stats are unavailable", (), {"reason": "no_node"}),
    ("node.stats_unavailable", r"Node server stats are unavailable", (), {"reason": "no_server"}),
    ("node.stats_unavailable", r"UDP port is missing", (), {"reason": "no_udpport"}),
    ("node.stats_unavailable", r"No registration information available", (), {"reason": "no_registration_info"}),
    ("node.stats_unavailable", r"Registration information is missing", (), {"reason": "no_regseconds"}),
    ("node.registered_recently", r"Node (?:registration within|not registered in last) 10 minutes: (.*)", ("registered_at",)),
    ("node.ip_last_changed", r"Last time IP changed was (.*) UTC", ("changed_at",)),
    ("node.ip_last_changed", r"Last time IP change is unavailable", ()),
    ("node.inbound_reachability", r"Nodeping is not responding", (), {"status": "nodeping_unavailable"}),
    ("node.inbound_reachability", r"Node is not perceived as registered; not tested", (), {"status": "not_registered"}),
    ("node.inbound_reachability", r"Incoming connections to IAX from other nodes failed", (), {"status": "unreachable"}),
    ("node.inbound_reachability", r"Incoming connections to IAX from other nodes is successful", (), {"status": "ok"}),
    ("node.inbound_reachability", r"IAX ping test has a roundtrip time of (\d+)ms", ("rtt_ms",)),
    ("node.inbound_reachability", r"Nodeping is returning something", (), {"status": "unknown"}),
    ("node.checks_stopped", r"Stopping node checks due to registration failure", ()),
    ("node.checks_stopped_note", r"as further information will be unreliable", ()),
    ("node.summary", r"Node (\d+) has (\d+) (error|warning)\(s\)", ("node", "count", "kind")),
    ("node.summary", r"Warnings may or may not be problems", ()),
    ("node.summary", r"No problems detected with node (\d+)", ("node",)),
]
_COMPILED = [(p[0], re.compile(rf"^{p[1]}"), p[2], p[3] if len(p) > 3 else {}) for p in PATTERNS]
LEVELS = {"Error": "error", "Warning": "warning", "Info": "info", "OK": "ok"}
RANK = {"ok": 0, "info": 0, "warning": 1, "error": 2}


@dataclass
class Section:
    id: str
    node: str | None = None
    complete: bool = True
    findings: list[dict] = field(default_factory=list)


def _classify(message: str) -> tuple[str, dict]:
    for fid, rx, names, fixed in _COMPILED:
        m = rx.match(message)
        if m:
            data = {name: m.group(i + 1) for i, name in enumerate(names) if m.group(i + 1) is not None}
            if "nodes" in data:
                data["nodes"] = [n.strip() for n in data["nodes"].split(",") if n.strip()]
            if fid == "config.registration_lines":
                data["count"] = 0 if data["count"] == "no" else int(data["count"])
            if fid == "public_ip.http_iax_match" and "iax_ip" not in data:
                data["iax_ip"] = data.get("http_ip")  # "the same IP" names it once
            return fid, {**data, **fixed}
    return "unknown", {}


def parse_text(text: str) -> dict:
    sections = [Section("config")]
    for raw in text.splitlines():
        heading = _NODE_HEADING.match(raw.strip())
        if heading:
            sections.append(Section("node", heading.group(1)))
            continue
        m = _LINE.match(raw)
        if not m:
            continue
        level, message = LEVELS[m.group(1)], m.group(2).strip()
        fid, data = _classify(message)
        if fid.startswith("public_ip.") and sections[-1].id != "public_ip":
            sections.append(Section("public_ip"))
        if fid.startswith("run.") and sections[-1].id != "run":
            sections.append(Section("run"))
        if fid in ("node.checks_stopped",):
            sections[-1].complete = False
        if fid in ("public_ip.http_consensus", "public_ip.iax_consensus"):
            probe = fid.replace("_consensus", "_probe")
            data["ips"] = sorted({f["data"]["ip"] for f in sections[-1].findings if f["id"] == probe and f["data"].get("ip")})
        sections[-1].findings.append({"id": fid, "level": level, "message": message, "data": data})
    result = _summarize([s.__dict__ for s in sections])
    if result["result"] == "aborted":
        # the section the run stopped in, as --json marks it
        [s for s in result["sections"] if s["findings"]][-1]["complete"] = False
    return result


def _summarize(sections: list[dict]) -> dict:
    counts = {"error": 0, "warning": 0, "ok": 0, "info": 0}
    for s in sections:
        for f in s["findings"]:
            counts[f["level"]] = counts.get(f["level"], 0) + 1
    ids = {f["id"] for s in sections for f in s["findings"]}
    aborted = bool(ids & {"config.cannot_continue", "config.no_nodes", "config.no_registrations",
                          "run.permission_denied"})
    worst = max((RANK[f["level"]] for s in sections for f in s["findings"]), default=0)
    result = "aborted" if aborted else {0: "ok", 1: "warning", 2: "error"}[worst]
    return {"schema": 1, "result": result, "counts": counts, "sections": sections}


def supports_json(tool: str = TOOL) -> bool:
    """Look for the option in the installed script rather than asking it.

    Versions without --json take no arguments, so "--help" runs a full check; the real
    run right after it then trips nodeping's rate limit (issue #27).
    """
    try:
        with open(tool, "rb") as f:
            return b"--json" in f.read()
    except OSError:
        return False


async def run(tool: str = TOOL, node: str | None = None) -> dict:
    """Run the check and return the structured result (plus the raw text)."""
    started = time.time()
    use_json = supports_json(tool)
    args = [tool] + (["--json"] if use_json else []) + (["--node", node] if node and use_json else [])
    proc = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.DEVNULL,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("The connectivity check did not finish in time.")
    text = out.decode("utf-8", "replace")
    result = None
    if use_json:
        try:
            result = json.loads(text)
        except ValueError:
            result = None
    if result is None:
        result = parse_text(text)
        result["raw"] = text
    result["checked_at"] = int(started)
    result["duration"] = round(time.time() - started, 1)
    result["exit_code"] = proc.returncode
    return result
