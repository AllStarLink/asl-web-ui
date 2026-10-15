"""Asterisk CLI parsing, the status hub, the events socket and the console."""

import asyncio
import json

import pytest
from aiohttp import DummyCookieJar, WSMsgType

from asl_web_ui import asterisk_cli as cli
from asl_web_ui import config, security
from asl_web_ui.app import create_app
from asl_web_ui.auth.fake import FakeTransport
from asl_web_ui.modules import console, status

# Output captured from asl3 3.10.5 (Asterisk 22.10.1).
CORE_VERSION = "Asterisk 22.10.1+asl3-3.10.5-1.deb13 built by builder @ allstarlink.org on a x86_64 running Linux on 2026-08-29 17:49:54 UTC\n"
RPT_VERSION = "app_rpt version: 3.10.5\n"
UPTIME = "System uptime: 10052\nLast reload: 9000\n"
LOCALNODES = "                         \nNode\n----\n1999\n63001\n\n"
REGISTRATIONS = (
    "Host                                           Username    Perceived                            Refresh  State\n"
    "52.21.169.197:443                              63001       203.0.113.24:4569                        179  Registered\n"
    "52.21.169.197:443                              1234        <Unregistered>                             0  Not Registered\n"
    "2 HTTP registrations.\n"
)
IAX = "Host                                           dnsmgr  Username    Perceived                                      Refresh  State\n0 IAX2 registrations.\n"


def test_parsers():
    assert cli.parse_core_version(CORE_VERSION) == "22.10.1+asl3-3.10.5-1.deb13"
    assert cli.parse_rpt_version(RPT_VERSION) == "3.10.5"
    assert cli.parse_uptime_seconds(UPTIME) == (10052, 9000)
    assert cli.parse_localnodes(LOCALNODES) == ["1999", "63001"]
    regs = cli.parse_rpt_registrations(REGISTRATIONS)
    assert [(r.username, r.state, r.refresh) for r in regs] == [("63001", "Registered", 179), ("1234", "Not Registered", 0)]
    assert cli.parse_iax_registry(IAX) == []


class FakeCLI:
    OUTPUT = {
        "core show version": CORE_VERSION, "rpt show version": RPT_VERSION,
        "core show uptime seconds": UPTIME, "rpt localnodes": LOCALNODES,
        "rpt show registrations": REGISTRATIONS, "iax2 show registry": IAX,
    }

    def __init__(self, down=False):
        self.down = down

    async def run(self, command):
        if self.down:
            raise cli.AsteriskUnavailable("Unable to connect to remote asterisk")
        return self.OUTPUT[command]


def unit(state):
    async def unit_state(name):
        return {"ActiveState": state, "SubState": "running", "ActiveEnterTimestamp": "Wed 2026-10-14 15:21:16 EDT"}
    return unit_state


async def test_status_collects_nodes_and_registrations():
    data = await status.StatusHub(FakeCLI(), unit_state=unit("active")).collect()
    assert data["asterisk"]["reachable"] and data["asterisk"]["uptime"] == 10052
    assert data["versions"] == {"asterisk": "22.10.1+asl3-3.10.5-1.deb13", "app_rpt": "3.10.5"}
    assert data["nodes"] == [
        {"node": "1999", "private": True, "registration": None},
        {"node": "63001", "private": False, "registration": "Registered"},
    ]


async def test_status_when_asterisk_stopped():
    data = await status.StatusHub(FakeCLI(down=True), unit_state=unit("inactive")).collect()
    assert data["asterisk"]["state"] == "inactive" and data["nodes"] == [] and data["error"] is None


async def test_status_when_asterisk_unreachable():
    data = await status.StatusHub(FakeCLI(down=True), unit_state=unit("active")).collect()
    assert data["error"] and not data["asterisk"]["reachable"]


@pytest.fixture
async def logged_in(aiohttp_client, monkeypatch):
    monkeypatch.setattr(security, "is_group_member", lambda user, group: True)

    async def connect():
        return FakeTransport()

    app = create_app(
        config.Settings(dev=False),
        auth_connect=connect,
        overrides={status.CLI_KEY: FakeCLI(), status.UNIT_STATE_KEY: unit("active"), console.COMMAND_KEY: ["/bin/cat"]},
    )
    client = await aiohttp_client(app, cookie_jar=DummyCookieJar())
    origin = f"https://{client.server.host}:{client.server.port}"
    base = {"X-Forwarded-Proto": "https", "Origin": origin}
    r = await client.post("/api/v1/auth/login", json={"user": "dev"}, headers=base)
    step = await r.json()
    r = await client.post(f"/api/v1/auth/login/{step['id']}", json={"answer": "dev"}, headers=base)
    cookie = r.cookies["asl_web_ui_session"].value
    return client, {**base, "Cookie": f"asl_web_ui_session={cookie}"}


async def test_events_socket_sends_status(logged_in):
    client, headers = logged_in
    async with client.ws_connect("/api/v1/ws/events", headers=headers) as ws:
        msg = await asyncio.wait_for(ws.receive_json(), 5)
    assert msg["type"] == "status" and msg["data"]["nodes"][1]["node"] == "63001"


async def test_events_socket_requires_login(logged_in):
    client, headers = logged_in
    headers = {k: v for k, v in headers.items() if k != "Cookie"}
    resp = await client.get("/api/v1/ws/events", headers={**headers, "Upgrade": "websocket", "Connection": "Upgrade", "Sec-WebSocket-Version": "13", "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ=="})
    assert resp.status == 401


async def test_events_socket_refuses_foreign_origin(logged_in):
    client, headers = logged_in
    resp = await client.get("/api/v1/ws/events", headers={**headers, "Origin": "https://evil.example", "Upgrade": "websocket", "Connection": "Upgrade", "Sec-WebSocket-Version": "13", "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ=="})
    assert resp.status == 403


async def test_console_round_trip(logged_in):
    client, headers = logged_in
    async with client.ws_connect("/api/v1/ws/console", headers=headers) as ws:
        await ws.send_str(json.dumps({"type": "resize", "cols": 100, "rows": 30}))
        await ws.send_str(json.dumps({"type": "input", "data": "rpt stats\n"}))
        seen = b""
        while b"rpt stats" not in seen:
            msg = await asyncio.wait_for(ws.receive(), 5)
            assert msg.type == WSMsgType.BINARY
            seen += msg.data


def test_console_drops_remote_connection_noise():
    # Bytes captured from asl3 3.10.5 (asterisk -rvvv on a pty).
    raw = (b"Helium*CLI> \r\x1b[0K\x1b[1;30m    -- \x1b[0mRemote UNIX connection\r\n"
           b"Helium*CLI> \r\x1b[0K\x1b[1;30m    -- \x1b[0mRemote UNIX connection disconnected\r\n"
           b"Helium*CLI> \r\x1b[0K\x1b[1;30m    -- \x1b[0mLink 2000 connected\r\n")
    assert console.strip_noise(raw) == (
        b"Helium*CLI> \r\x1b[0KHelium*CLI> \r\x1b[0K"
        b"Helium*CLI> \r\x1b[0K\x1b[1;30m    -- \x1b[0mLink 2000 connected\r\n"
    )


def test_noise_filter_handles_lines_split_across_reads():
    stream = (b"Helium*CLI> \r\x1b[0K\x1b[1;30m    -- \x1b[0mRemote UNIX connection\r\n"
              b"Helium*CLI> \r\x1b[0K\x1b[1;30m    -- \x1b[0mRemote UNIX connection disconnected\r\n"
              b"Helium*CLI> core show uptime\r\nSystem uptime: 5 minutes\r\nHelium*CLI> ")
    for size in range(1, len(stream) + 1):
        f, out = console.NoiseFilter(), b""
        for i in range(0, len(stream), size):
            out += f.feed(stream[i:i + size])
        out += f.flush()
        assert b"Remote UNIX" not in out, size
        assert out.endswith(b"System uptime: 5 minutes\r\nHelium*CLI> "), size


def test_noise_filter_passes_prompt_and_typing_immediately():
    f = console.NoiseFilter()
    assert f.feed(b"Helium*CLI> ") == b"Helium*CLI> "
    assert f.feed(b"r") == b"r" and f.feed(b"pt") == b"pt"
