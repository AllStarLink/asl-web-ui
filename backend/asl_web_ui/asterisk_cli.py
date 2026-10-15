"""Running Asterisk CLI commands (``asterisk -rx``) and parsing their output.

Commands are fixed strings chosen by the backend, never user input, and run
without a shell. A semaphore limits how many run at once.
"""

import asyncio
import re
from dataclasses import dataclass

ASTERISK = "/usr/sbin/asterisk"
NOT_RUNNING = "Unable to connect to remote asterisk"


class AsteriskUnavailable(Exception):
    """Asterisk is not running or did not answer."""


class AsteriskCLI:
    def __init__(self, binary: str = ASTERISK, concurrency: int = 4, timeout: float = 10.0,
                 extra_args: list[str] | None = None):
        self.binary = binary
        self.extra_args = extra_args or []  # e.g. ["-C", path] for a test instance
        self.timeout = timeout
        self._slots = asyncio.Semaphore(concurrency)

    async def run(self, command: str) -> str:
        async with self._slots:
            try:
                proc = await asyncio.create_subprocess_exec(
                    self.binary, *self.extra_args, "-rx", command,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
            except OSError as exc:
                raise AsteriskUnavailable(str(exc)) from exc
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), self.timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise AsteriskUnavailable(f"'{command}' timed out")
        text = out.decode("utf-8", errors="replace")
        if proc.returncode != 0 or NOT_RUNNING in text:
            raise AsteriskUnavailable(text.strip() or f"'{command}' failed")
        return text


# ---- parsers --------------------------------------------------------------


def parse_core_version(text: str) -> str | None:
    """'Asterisk 22.10.1+asl3-3.10.5-1.deb13 built by …' -> '22.10.1+asl3-3.10.5-1.deb13'"""
    m = re.search(r"^Asterisk (\S+)", text, re.M)
    return m.group(1) if m else None


def parse_rpt_version(text: str) -> str | None:
    """'app_rpt version: 3.10.5' -> '3.10.5'"""
    m = re.search(r"app_rpt version:\s*(\S+)", text)
    return m.group(1) if m else None


def parse_uptime_seconds(text: str) -> tuple[int | None, int | None]:
    """'core show uptime seconds' -> (seconds since start, seconds since last reload)"""
    up = re.search(r"System uptime:\s*(\d+)", text)
    reload = re.search(r"Last reload:\s*(\d+)", text)
    return (int(up.group(1)) if up else None, int(reload.group(1)) if reload else None)


def parse_localnodes(text: str) -> list[str]:
    """'rpt localnodes': a 'Node' heading, a dashed rule, one node per line."""
    lines = [line.strip() for line in text.splitlines()]
    try:
        start = lines.index("----") + 1
    except ValueError:
        return []
    return [line for line in lines[start:] if line.isdigit()]


@dataclass(frozen=True)
class Registration:
    host: str
    username: str
    perceived: str
    refresh: int | None
    state: str


def parse_rpt_registrations(text: str) -> list[Registration]:
    """'rpt show registrations': Host Username Perceived Refresh State(…)."""
    regs = []
    for line in text.splitlines()[1:]:
        if not line.strip() or re.match(r"^\d+ HTTP registrations?\.", line.strip()):
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        refresh = int(parts[3]) if parts[3].isdigit() else None
        regs.append(Registration(parts[0], parts[1], parts[2], refresh, " ".join(parts[4:])))
    return regs


def parse_iax_registry(text: str) -> list[Registration]:
    """'iax2 show registry': Host dnsmgr Username Perceived Refresh State(…)."""
    regs = []
    for line in text.splitlines()[1:]:
        if not line.strip() or re.match(r"^\d+ IAX2 registrations?\.", line.strip()):
            continue
        parts = line.split()
        if len(parts) < 6:
            continue
        refresh = int(parts[4]) if parts[4].isdigit() else None
        regs.append(Registration(parts[0], parts[2], parts[3], refresh, " ".join(parts[5:])))
    return regs
