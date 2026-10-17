"""The DAHDI kernel modules (dahdi-dkms), which app_rpt no longer needs (issue #29).

Since app_rpt 3.8.3 (asl3-asterisk 22.8.2+asl3-3.8.3-1, the 2026-04-09
release) app_rpt keeps time without DAHDI, and the package scripts move
DAHDI/pseudo channels to Local/pseudo. dahdi-dkms then only rebuilds kernel
modules on every kernel update, which often fails. chan_dahdi is still built
for telephony boards (autopatch), and those need the modules, so they stay
while a DAHDI span is present or a node still uses a DAHDI channel.

Only dahdi-dkms is removed, and only if apt would remove nothing else.
"""

import os
import re
import subprocess

PACKAGE = "dahdi-dkms"
ASTERISK = "asl3-asterisk"
APP_RPT_WITHOUT_DAHDI = (3, 8, 3)
RPT_CONF = "/etc/asterisk/rpt.conf"
PROC_DAHDI = "/proc/dahdi"
APT_GET = "/usr/bin/apt-get"
DPKG_QUERY = "/usr/bin/dpkg-query"
ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8", "DEBIAN_FRONTEND": "noninteractive"}

_APP_RPT_RE = re.compile(r"\+asl3-(\d+)\.(\d+)\.(\d+)")
_RXCHANNEL_RE = re.compile(r"^\s*rxchannel\s*=>?\s*(dahdi/\S+)", re.I | re.M)
_REMV_RE = re.compile(r"^Remv (\S+)", re.M)


class DahdiError(Exception):
    def __init__(self, message: str, code: str = "failed"):
        super().__init__(message)
        self.message = message
        self.code = code


def app_rpt_version(asterisk_version: str | None) -> tuple[int, int, int] | None:
    """app_rpt's version in an asl3-asterisk version such as 22.8.2+asl3-3.8.3-1."""
    m = _APP_RPT_RE.search(asterisk_version or "")
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def spans(proc_dahdi: str) -> list[str]:
    """The DAHDI spans (telephony hardware) the loaded modules know about."""
    try:
        return sorted((n for n in os.listdir(proc_dahdi) if n.isdigit()), key=int)
    except OSError:
        return []


def dahdi_channels(rpt_conf: str) -> list[str]:
    """rxchannel = DAHDI/... lines in rpt.conf, comments left out."""
    try:
        with open(rpt_conf, encoding="utf-8", errors="replace") as f:
            text = "\n".join(line.split(";", 1)[0] for line in f)
    except OSError:
        return []
    return sorted(set(_RXCHANNEL_RE.findall(text)))


def blockers(versions: dict[str, str], rpt_conf: str, proc_dahdi: str) -> list[str]:
    """Why dahdi-dkms should stay installed; empty if it can go.
    ``versions`` maps installed package names to their versions."""
    out = []
    app_rpt = app_rpt_version(versions.get(ASTERISK))
    if app_rpt is None or app_rpt < APP_RPT_WITHOUT_DAHDI:
        out.append(f"This version of {ASTERISK} ({versions.get(ASTERISK, 'not installed')}) still uses DAHDI. "
                   "Update the system first.")
    found = spans(proc_dahdi)
    if found:
        out.append(f"DAHDI telephony hardware is present (span {', '.join(found)}).")
    channels = dahdi_channels(rpt_conf)
    if channels:
        out.append(f"rpt.conf still uses {', '.join(channels)}.")
    return out


def run(argv: list[str], output=None) -> tuple[int, str]:
    """Run a program; stream its output lines to OUTPUT if given."""
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, env=ENV)
    except FileNotFoundError:
        raise DahdiError(f"{argv[0]} is not installed.", "unavailable")
    lines = []
    assert proc.stdout is not None
    for line in proc.stdout:
        lines.append(line.rstrip("\n"))
        if output:
            output(lines[-1])
    return proc.wait(timeout=600), "\n".join(lines)


def installed_versions(names: list[str]) -> dict[str, str]:
    code, text = run([DPKG_QUERY, "--show", "--showformat=${db:Status-Abbrev}\t${binary:Package}\t${Version}\n",
                      *names])
    out = {}
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].startswith("ii"):
            out[parts[1]] = parts[2]
    return out


def remove(root: str, output) -> dict:
    def path(p: str) -> str:
        return os.path.join(root, p.lstrip("/"))

    versions = installed_versions([PACKAGE, ASTERISK])
    if PACKAGE not in versions:
        raise DahdiError(f"{PACKAGE} is not installed.", "not_found")
    reasons = blockers(versions, path(RPT_CONF), path(PROC_DAHDI))
    if reasons:
        raise DahdiError(" ".join(reasons), "conflict")
    code, text = run([APT_GET, "-s", "remove", PACKAGE])
    if code != 0:
        raise DahdiError(f"apt-get could not plan the removal (exit code {code}): {text[-400:]}")
    others = sorted(set(_REMV_RE.findall(text)) - {PACKAGE})
    if others:
        raise DahdiError(f"Removing {PACKAGE} would also remove {', '.join(others)}, so it was left installed.",
                         "conflict")
    code, _ = run([APT_GET, "-y", "remove", PACKAGE], output)
    if code != 0:
        raise DahdiError(f"apt-get failed (exit code {code}).")
    return {"removed": [PACKAGE]}
