"""Reading systemd unit state (read-only; no privilege needed)."""

import asyncio

SYSTEMCTL = "/usr/bin/systemctl"


async def unit_state(unit: str, systemctl: str = SYSTEMCTL) -> dict[str, str]:
    """Return ActiveState, SubState, ActiveEnterTimestamp, LoadState, UnitFileState and Result."""
    proc = await asyncio.create_subprocess_exec(
        systemctl, "show", unit,
        "--property=ActiveState,SubState,ActiveEnterTimestamp,LoadState,UnitFileState,Result",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await asyncio.wait_for(proc.communicate(), 10)
    state = {}
    for line in out.decode(errors="replace").splitlines():
        key, sep, value = line.partition("=")
        if sep:
            state[key] = value
    return state
