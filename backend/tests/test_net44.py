"""44Net Connect: the helper's commands run in-process on a temporary root,
with stand-ins for nmcli, firewall-cmd, busctl, wg and systemctl
(fake_net44_host.py) and the API in front of them."""

import base64
import io
import json
import sys
import tarfile
from pathlib import Path

import pytest

from asl_web_ui.modules import net44 as web_net44
from asl_web_ui_priv import commands, net44
from test_backups_api import cloud, env  # noqa: F401 (fixtures)

FAKE = Path(__file__).with_name("fake_net44_host.py")
PRIVATE = base64.b64encode(bytes(range(1, 33))).decode()
PEER = "UGVlcktleUZvclRlc3RzT25seTAxMjM0NTY3ODkwYWI="
# As the 44Net portal hands it out: the private key is a placeholder.
PORTAL = f"""[Interface]
PrivateKey = REPLACE_WITH_YOUR_PRIVATE_KEY
Address = fe80::1234:5678:9abc:def0/128, 44.31.12.34/32
#DNS = 1.1.1.1,1.0.0.1
MTU = 1380

[Peer]
PublicKey = {PEER}
Endpoint = 44.32.0.1:44000
PersistentKeepalive = 20
AllowedIPs = 0.0.0.0/0, ::/0
"""
HOSTS = ["52.20.63.146", "98.86.36.209"]


@pytest.fixture
def host(env, monkeypatch):  # noqa: F811
    state_path = env.root.parent / "host.json"
    state = {"nm_running": True, "connections": {}, "active": [], "checkpoints": [], "checkpoint_log": [],
             "units": {}, "calls": [], "reloads": 0, "reapplied": 0, "default_zone": "allstarlink",
             "runtime_zone": None, "wifi_uuid": "9afa45fb-0000-4000-8000-000000000001",
             "zones": {"allstarlink": {"services": ["ssh", "http", "iax2"], "ports": [], "interfaces": ["wlan0"]},
                       "public": {"services": ["ssh"], "ports": [], "interfaces": []}}}
    state_path.write_text(json.dumps(state))
    bindir = env.root.parent / "bin"
    bindir.mkdir()
    for name in net44.BIN:
        script = bindir / name
        script.write_text(f'#!/bin/sh\nexec {sys.executable} {FAKE} {name} {state_path} "$@"\n')
        script.chmod(0o755)
        monkeypatch.setitem(net44.BIN, name, str(script))
    resolved = list(HOSTS)
    monkeypatch.setattr(net44, "_resolve", lambda: list(resolved))

    def install():
        """The appliance's package and firewalld services."""
        (env.root / "usr" / "share" / "asl3-appliance").mkdir(parents=True)
        services = env.root / "etc" / "firewalld" / "services"
        services.mkdir(parents=True)
        for s in net44.SERVICES:
            (services / f"{s}.xml").write_text("<service/>")

    def read():
        return json.loads(state_path.read_text())

    def update(**changes):
        s = read()
        s.update(changes)
        state_path.write_text(json.dumps(s))

    env.install, env.state, env.update, env.resolved = install, read, update, resolved
    env.keyfile = env.root / net44.KEYFILE.lstrip("/")
    return env


async def ready(host, **make):
    host.install()
    a = await host.make(**make)
    status_, body = await a.call("PUT", "net44/zone", {"echolink": False, "rtcm": False})
    assert status_ == 200, body
    return a


async def configured(host, mode="full"):
    a = await ready(host)
    status_, body = await a.call("POST", "net44/connection", {"config": PORTAL, "private_key": PRIVATE, "mode": mode})
    assert status_ == 200, body
    return a, body


def key_nowhere(host, *texts):
    """The private key is only ever in the keyfile."""
    for text in texts:
        assert PRIVATE not in text
    assert PRIVATE not in json.dumps(host.state()["calls"])
    for f in (host.root.parent / "state").rglob("*"):
        if f.is_file():
            assert PRIVATE not in f.read_text(errors="replace"), f


# ---- availability and the firewall zone ---------------------------------------------------


async def test_needs_the_appliance(host):
    a = await host.make()
    status_, body = await a.call("GET", "net44")
    assert status_ == 200 and body == {"available": False, "reason": "appliance", "message": body["message"]}
    status_, body = await a.call("PUT", "net44/zone", {"echolink": False, "rtcm": False})
    assert status_ == 503, body


async def test_zone_opens_iax_and_what_is_chosen(host):
    host.install()
    a = await host.make()
    _, body = await a.call("GET", "net44")
    assert body["available"] and body["zone"] is None and body["connection"] is None and body["legacy"] is None
    assert body["asterisk"] == {"iax_port": 4569, "echolink": False, "voter_port": None}
    assert body["expected_zone"] == {"services": ["iax2"], "ports": []} and not body["zone_current"]

    status_, body = await a.call("PUT", "net44/zone", {"echolink": True, "rtcm": False})
    assert status_ == 200, body
    assert body["zone"] == {"services": ["echolink", "iax2"], "ports": [], "interfaces": []}
    assert host.state()["reloads"] == 1

    # A port outside the iax2 service's range is opened by number; services
    # added by hand (ssh) are closed again.
    (host.etc / "iax.conf").write_text("[general]\nbindport = 14569\n")
    zones = host.state()["zones"]
    zones["44NetConnect"]["services"].append("ssh")
    host.update(zones=zones)
    _, body = await a.call("GET", "net44")
    assert body["selection"] == {"echolink": True, "rtcm": False} and not body["zone_current"]
    assert body["expected_zone"] == {"services": ["echolink"], "ports": ["14569/udp"]}
    status_, body = await a.call("PUT", "net44/zone", {"echolink": True, "rtcm": False})
    assert body["zone"]["services"] == ["echolink"] and body["zone"]["ports"] == ["14569/udp"]


async def test_rtcm_needs_chan_voter(host):
    host.install()
    a = await host.make()
    status_, body = await a.call("PUT", "net44/zone", {"echolink": False, "rtcm": True})
    assert status_ == 400, body
    (host.etc / "modules.conf").write_text("[modules]\nautoload = no\nload = chan_voter.so\n")
    (host.etc / "voter.conf").write_text("[general]\nport = 1700\n")
    status_, body = await a.call("PUT", "net44/zone", {"echolink": False, "rtcm": True})
    assert status_ == 200 and body["zone"]["ports"] == ["1700/udp"], body


async def test_iax_port_change_moves_the_zone(host):
    a = await ready(host)
    status_, plan = await a.call("POST", "nodes/plan", {"op": "iax_port", "port": 14569})
    assert status_ == 200, plan
    status_, body = await a.call("POST", f"changes/{plan['id']}/apply", {})
    assert status_ == 200 and body["warnings"] == [], body
    assert host.state()["zones"]["44NetConnect"] == {"services": [], "ports": ["14569/udp"], "interfaces": []}


async def test_changes_refused_in_dev_mode(host):
    host.install()
    a = await host.make(dev=True)
    status_, body = await a.call("PUT", "net44/zone", {"echolink": False, "rtcm": False})
    assert status_ == 501, body


# ---- the tunnel's configuration -----------------------------------------------------------


async def test_configuration_needs_the_zone_first(host):
    host.install()
    a = await host.make()
    status_, body = await a.call("POST", "net44/connection", {"config": PORTAL, "private_key": PRIVATE})
    assert status_ == 409 and body["error"] == "order", body
    assert not host.keyfile.exists()


async def test_configuration_writes_the_keyfile_once(host):
    a, body = await configured(host)
    text = host.keyfile.read_text()
    assert host.keyfile.stat().st_mode & 0o777 == 0o600
    assert f"private-key={PRIVATE}\n" in text and "zone=44NetConnect\n" in text and "autoconnect=false\n" in text
    assert "interface-name=wg44net\n" in text and "[ipv6]\nmethod=disabled\n" in text and "fe80" not in text
    assert "allowed-ips=0.0.0.0/0;\n" in text and "mtu=1380\n" in text and "persistent-keepalive=20\n" in text
    assert any("IPv6 address" in n for n in body["notes"])
    c = body["status"]["connection"]
    assert c["address"] == "44.31.12.34/32" and c["endpoint"] == "44.32.0.1:44000" and c["peer_public_key"] == PEER
    assert c["mode"] == "full" and c["state"] is None and c["zone"] == "44NetConnect" and c["autoconnect"] is False
    assert c["public_key"] and c["public_key"] != PRIVATE
    _, status_text = await a.call("GET", "net44")
    key_nowhere(host, json.dumps(body), json.dumps(status_text))


async def test_replacing_needs_a_stopped_tunnel(host):
    a, body = await configured(host)
    uuid = next(iter(host.state()["connections"]))
    await a.call("POST", "net44/start", {})
    status_, body = await a.call("POST", "net44/connection", {"config": PORTAL, "private_key": PRIVATE})
    assert status_ == 409 and body["error"] == "busy", body
    await a.call("POST", "net44/stop")
    status_, body = await a.call("POST", "net44/connection", {"config": PORTAL, "private_key": PRIVATE})
    assert status_ == 200 and list(host.state()["connections"]) == [uuid], body


@pytest.mark.parametrize("config, key, message", [
    (PORTAL, None, "Enter the tunnel's private key"),
    (PORTAL, "not-a-key", "not a WireGuard key"),
    (PORTAL.replace("44.31.12.34", "10.1.2.3"), PRIVATE, "not a 44Net"),
    (PORTAL.replace("44.31.12.34", "44.200.1.2"), PRIVATE, "not a 44Net"),  # sold off in 2019
    (PORTAL.replace("0.0.0.0/0, ", ""), PRIVATE, "must include 0.0.0.0/0"),
    (PORTAL + f"\n[Peer]\nPublicKey = {PEER}\nEndpoint = 44.32.0.2:1\nAllowedIPs = 0.0.0.0/0\n", PRIVATE, "one [Peer]"),
    (PORTAL.replace("Endpoint = 44.32.0.1:44000", "Endpoint = nowhere"), PRIVATE, "host:port"),
    ("PrivateKey = x\n", PRIVATE, "Line 1"),
])
def test_bad_configurations(config, key, message):
    with pytest.raises(net44.Net44Error) as exc:
        net44.tunnel_settings(config, key)
    assert message in exc.value.message and (key is None or key not in exc.value.message)


def test_configuration_notes():
    t = net44.tunnel_settings(PORTAL.replace("MTU = 1380", "MTU = 1380\nPostUp = ip route add x\nTable = off")
                              .replace("PersistentKeepalive = 20\n", ""), PRIVATE)
    assert t["split"] and t["keepalive"] is None and t["private_key"] == PRIVATE
    assert any("postup is not used" in n for n in t["notes"])
    assert any("PersistentKeepalive" in n for n in t["notes"])


# ---- starting, confirming, rollback -------------------------------------------------------


async def test_start_waits_for_confirmation(host):
    a, _ = await configured(host)
    status_, body = await a.call("POST", "net44/start", {})
    assert status_ == 200, body
    state = host.state()
    assert state["checkpoint_log"] == [{"path": "/org/freedesktop/NetworkManager/Checkpoint/1", "rollback": 120,
                                        "flags": net44.DISCONNECT_NEW_DEVICES}]
    c = body["connection"]
    assert c["state"] == "activated" and c["autoconnect"] is False and c["active_zone"] == "44NetConnect"
    assert c["tunnel"]["rx_bytes"] == 1024 and c["tunnel"]["endpoint"] == "44.32.0.1:44000"
    assert body["checkpoint"]["seconds_left"] <= 120 and body["issues"] == []

    status_, body = await a.call("POST", "net44/start", {})
    assert status_ == 409, body
    status_, body = await a.call("POST", "net44/confirm")
    assert status_ == 200 and body["checkpoint"] is None and body["connection"]["autoconnect"] is True, body
    assert host.state()["checkpoints"] == []


async def test_unconfirmed_start_is_rolled_back(host):
    a, _ = await configured(host)
    await a.call("POST", "net44/start", {"rollback": 30})
    host.update(checkpoints=[], active=[])  # NetworkManager's rollback
    status_, body = await a.call("POST", "net44/confirm")
    assert status_ == 410 and body["error"] == "expired", body

    await a.call("POST", "net44/start", {"rollback": 30})
    host.update(checkpoints=[], active=[])
    _, body = await a.call("GET", "net44")
    assert body["checkpoint"] == {"rolled_back": True} and body["connection"]["state"] is None
    _, body = await a.call("GET", "net44")
    assert body["checkpoint"] is None
    status_, body = await a.call("POST", "net44/confirm")
    assert status_ == 404, body


async def test_failed_start_rolls_back_at_once(host):
    a, _ = await configured(host)
    host.update(fail_up=True)
    status_, body = await a.call("POST", "net44/start", {})
    assert status_ == 500 and "did not start" in body["message"], body
    assert host.state()["checkpoints"] == []
    _, body = await a.call("GET", "net44")
    assert body["checkpoint"] is None


async def test_start_refuses_a_rollback_out_of_range(host):
    a, _ = await configured(host)
    status_, body = await a.call("POST", "net44/start", {"rollback": 5})
    assert status_ == 400, body


async def test_start_needs_the_zone(host):
    a, _ = await configured(host)
    zones = host.state()["zones"]
    del zones["44NetConnect"]
    host.update(zones=zones)
    status_, body = await a.call("POST", "net44/start", {})
    assert status_ == 409 and body["error"] == "order", body


# ---- split routing ------------------------------------------------------------------------


async def test_split_routing(host):
    a, body = await configured(host, mode="split")
    c = body["status"]["connection"]
    assert c["mode"] == "split" and c["routes"] == HOSTS
    s = host.state()["connections"][next(iter(host.state()["connections"]))]["settings"]
    assert s["wireguard"]["peer-routes"] is False and s["wireguard"]["ip4-auto-default-route"] == 0
    assert {"dest": "0.0.0.0", "prefix": 0, "table": 44} in s["ipv4"]["route-data"]
    assert s["ipv4"]["routing-rules"] == [{"family": 2, "priority": 4400, "from": "44.31.12.34", "from-len": 32,
                                          "table": 44}]
    assert host.state()["units"][net44.ROUTE_TIMER] == {"enabled": True, "active": True}

    # The timer's job: new addresses go in place, on the running tunnel.
    await a.call("POST", "net44/start", {})
    await a.call("POST", "net44/confirm")
    assert net44.refresh_routes(str(host.root)) == "The routes are up to date."
    host.resolved[:] = ["52.20.63.146", "52.21.169.197"]
    assert "52.21.169.197" in net44.refresh_routes(str(host.root))
    assert host.state()["reapplied"] == 1

    # Back to the full tunnel: a restart, guarded like a start (not a reapply).
    status_, body = await a.call("PUT", "net44/mode", {"mode": "full"})
    assert status_ == 200, body
    assert body["connection"]["mode"] == "full" and body["connection"]["routes"] == []
    assert body["connection"]["state"] == "activated" and "seconds_left" in body["checkpoint"]
    assert host.state()["reapplied"] == 1 and len(host.state()["checkpoint_log"]) == 2
    assert host.state()["units"][net44.ROUTE_TIMER]["enabled"] is False


async def test_split_routing_needs_the_servers_addresses(host, monkeypatch):
    a = await ready(host)
    monkeypatch.setattr(net44, "_resolve", lambda: [])
    status_, body = await a.call("POST", "net44/connection", {"config": PORTAL, "private_key": PRIVATE,
                                                              "mode": "split"})
    assert status_ == 500 and "could not be looked up" in body["message"], body


# ---- a tunnel made by hand, removal --------------------------------------------------------


async def test_migrate_a_wg_quick_tunnel(host):
    a = await ready(host)
    legacy = host.root / "etc" / "wireguard" / "wg0.conf"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(PORTAL.replace("REPLACE_WITH_YOUR_PRIVATE_KEY", PRIVATE).replace("MTU", "Table = off\nMTU"))
    zones = host.state()["zones"]
    zones["44NetConnect"]["interfaces"] = ["wg0"]
    host.update(zones=zones, units={net44.LEGACY_UNIT: {"enabled": True, "active": True}})
    _, body = await a.call("GET", "net44")
    assert body["legacy"] == {"config": "/etc/wireguard/wg0.conf", "unit": net44.LEGACY_UNIT, "enabled": True,
                              "active": True, "interface": "wg0", "zone": "44NetConnect"}

    status_, body = await a.call("POST", "net44/migrate")
    assert status_ == 200, body
    state = host.state()
    assert state["units"][net44.LEGACY_UNIT] == {"enabled": False, "active": False}
    assert state["zones"]["44NetConnect"]["interfaces"] == []
    assert body["status"]["connection"]["mode"] == "split" and legacy.exists()
    assert f"private-key={PRIVATE}\n" in host.keyfile.read_text()
    assert body["status"]["legacy"]["config"] == "/etc/wireguard/wg0.conf"
    key_nowhere(host, json.dumps(body))

    status_, body = await a.call("POST", "net44/migrate")
    assert status_ == 409 and body["error"] == "conflict", body


async def test_remove_needs_the_password_again(host):
    a, _ = await configured(host)
    a = await host.make(recent_auth=0)
    status_, body = await a.call("DELETE", "net44")
    assert status_ == 403 and body["error"] == "reauth_required", body
    assert host.keyfile.exists()


async def test_remove(host):
    a, _ = await configured(host, mode="split")
    await a.call("POST", "net44/start", {})
    status_, body = await a.call("DELETE", "net44?delete_zone=1")
    assert status_ == 200 and body["connection"] is None and body["zone"] is None, body
    state = host.state()
    assert state["connections"] == {} and state["active"] == [] and state["checkpoints"] == []
    assert not host.keyfile.exists() and state["units"][net44.ROUTE_TIMER]["enabled"] is False


# ---- checks, backups ------------------------------------------------------------------------


async def test_check(host, monkeypatch):
    host.install()
    a = await host.make()

    async def public_ip():
        return "44.31.12.34", None
    monkeypatch.setattr(web_net44, "_public_ip", public_ip)
    status_, body = await a.call("GET", "net44/check")
    assert status_ == 200, body
    assert body["public_ip"] == "44.31.12.34" and body["public_ip_on_44net"] is True
    assert body["registrations"][0] == {"node": "63001", "perceived": "203.0.113.24:4569", "state": "Registered",
                                        "on_44net": False}


def test_backups_never_hold_the_keyfile(tmp_path, monkeypatch):
    monkeypatch.setattr(commands, "ROOT", str(tmp_path))
    keyfile = tmp_path / net44.KEYFILE.lstrip("/")
    keyfile.parent.mkdir(parents=True)
    keyfile.write_text(f"[wireguard]\nprivate-key={PRIVATE}\n")
    (keyfile.parent / "Home.nmconnection").write_text("[connection]\n")
    (tmp_path / "etc" / "asterisk").mkdir()
    (tmp_path / "etc" / "asterisk" / "rpt_http_registrations.conf").write_text("[x]\n")
    include = tmp_path / "var" / "asl-backups" / "asl-backup-files"
    include.parent.mkdir(parents=True)
    include.write_text("/etc/asterisk\n/etc/NetworkManager\n")
    made = commands.backup_create({}, lambda _: None)
    with tarfile.open(tmp_path / "var" / "asl-backups" / made["name"]) as tar:
        names = tar.getnames()
    assert "etc/NetworkManager/system-connections/Home.nmconnection" in names
    assert net44.KEYFILE.lstrip("/") not in names

    # A crafted archive with the keyfile: it is not restored.
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name in ("etc/asterisk/rpt_http_registrations.conf", net44.KEYFILE.lstrip("/")):
            info = tarfile.TarInfo(name)
            info.size = 4
            tar.addfile(info, io.BytesIO(b"[x]\n"))
    archive = tmp_path / "crafted.tgz"
    archive.write_bytes(buf.getvalue())
    plan = commands._restore_plan(str(archive))
    assert {"name": net44.KEYFILE.lstrip("/"), "reason": "never restored (holds a private key)"} in plan["skipped"]
