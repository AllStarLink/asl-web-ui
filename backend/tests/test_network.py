"""Network interfaces and the fallback AP: the helper's commands run
in-process on a temporary root, with stand-ins for ip, systemctl and nmcli."""

import json

import pytest

from asl_web_ui_priv import network
from test_backups_api import cloud, env  # noqa: F401 (fixtures)

LINKS = [
    {"ifname": "lo", "flags": ["LOOPBACK", "UP", "LOWER_UP"], "operstate": "UNKNOWN", "link_type": "loopback",
     "address": "00:00:00:00:00:00",
     "addr_info": [{"family": "inet", "local": "127.0.0.1", "prefixlen": 8, "scope": "host"},
                   {"family": "inet6", "local": "::1", "prefixlen": 128, "scope": "host"}]},
    {"ifname": "eth0", "flags": ["BROADCAST", "MULTICAST", "UP", "LOWER_UP"], "operstate": "UP", "link_type": "ether",
     "address": "dc:a6:32:00:00:01",
     "addr_info": [{"family": "inet", "local": "192.168.1.20", "prefixlen": 24, "scope": "global"},
                   {"family": "inet", "local": "169.254.10.1", "prefixlen": 16, "scope": "link"},
                   {"family": "inet6", "local": "2001:db8::a", "prefixlen": 64, "scope": "global", "temporary": True},
                   {"family": "inet6", "local": "2001:db8::b", "prefixlen": 64, "scope": "global", "temporary": True,
                    "deprecated": True},
                   {"family": "inet6", "local": "2001:db8::20", "prefixlen": 64, "scope": "global"},
                   {"family": "inet6", "local": "fe80::1", "prefixlen": 64, "scope": "link"}]},
    {"ifname": "wlan0", "flags": ["BROADCAST", "MULTICAST", "UP", "LOWER_UP"], "operstate": "UP",
     "link_type": "ether", "address": "dc:a6:32:00:00:02",
     "addr_info": [{"family": "inet", "local": "10.0.0.5", "prefixlen": 24, "scope": "global"}]},
    {"ifname": "eth1", "flags": ["BROADCAST", "MULTICAST"], "operstate": "DOWN", "link_type": "ether",
     "address": "dc:a6:32:00:00:03", "addr_info": []},
    {"ifname": "eth2", "flags": ["BROADCAST", "MULTICAST", "UP", "LOWER_UP"], "operstate": "UP", "link_type": "ether",
     "address": "dc:a6:32:00:00:04",
     "addr_info": [{"family": "inet6", "local": "fe80::4", "prefixlen": 64, "scope": "link"}]},
    {"ifname": "wg0", "flags": ["POINTOPOINT", "NOARP", "UP", "LOWER_UP"], "operstate": "UNKNOWN",
     "link_type": "none", "linkinfo": {"info_kind": "wireguard"},
     "addr_info": [{"family": "inet", "local": "10.9.0.2", "prefixlen": 32, "scope": "global"}]},
]


@pytest.fixture
def sysroot(tmp_path):
    net = tmp_path / "sys" / "class" / "net"
    for name, mac in (("eth0", "dc:a6:32:00:00:01"), ("wlan0", "dc:a6:32:00:00:02")):
        (net / name).mkdir(parents=True)
        (net / name / "address").write_text(mac + "\n")
    (net / "wlan0" / "wireless").mkdir()
    return tmp_path


def test_interfaces_leave_out_local_addresses_and_idle_links(sysroot):
    assert network.interfaces(LINKS, str(sysroot)) == [
        {"name": "eth0", "type": "Ethernet", "mac": "dc:a6:32:00:00:01", "ipv4": ["192.168.1.20/24"],
         "ipv6": ["2001:db8::20/64", "2001:db8::a/64"]},
        {"name": "wlan0", "type": "Wi-Fi", "mac": "dc:a6:32:00:00:02", "ipv4": ["10.0.0.5/24"], "ipv6": []},
        {"name": "wg0", "type": "WireGuard", "mac": None, "ipv4": ["10.9.0.2/32"], "ipv6": []},
    ]


@pytest.fixture
def host(env, monkeypatch, sysroot):  # noqa: F811
    """Stand-in programs; ap/enabled files hold what nmcli and systemctl report."""
    bindir = env.log.parent / "bin"
    bindir.mkdir()
    log = bindir / "calls.log"
    (bindir / "links.json").write_text(json.dumps(LINKS))
    scripts = {
        "ip": f"#!/bin/sh\ncat {bindir}/links.json\n",
        "systemctl": f"""#!/bin/sh
echo "systemctl $*" >> {log}
case "$1" in
  is-enabled) if [ -e {bindir}/enabled ]; then echo enabled; else echo disabled; exit 1; fi ;;
  enable) touch {bindir}/enabled ;;
  disable) rm -f {bindir}/enabled ;;
esac
""",
        "nmcli": f"""#!/bin/sh
echo "nmcli $*" >> {log}
case "$*" in
  *--active*) echo "Wired connection 1"; [ -e {bindir}/ap ] && echo asl-fallback-ap ;;
  *down*) rm -f {bindir}/ap ;;
esac
exit 0
""",
    }
    for name, text in scripts.items():
        (bindir / name).write_text(text)
        (bindir / name).chmod(0o755)
        monkeypatch.setitem(network.BIN, name, str(bindir / name))
    # The temporary root of the in-process helper gets the fake /sys too.
    (env.root / "sys").symlink_to(sysroot / "sys")
    env.bindir, env.calls = bindir, log

    def install():
        libexec = env.root / "usr" / "libexec" / "asl3"
        libexec.mkdir(parents=True)
        (libexec / "fallback-ap-watchdog.py").write_text("")
        (env.root / "etc" / "default").mkdir(parents=True)
        (env.root / "etc" / "default" / "fallback-ap").write_text('# x\nAP_SSID_PREFIX="ASL_"\nAP_PSK="secret12"\n')
    env.install = install
    return env


async def test_status_without_the_appliance(host):
    a = await host.make()
    status_, body = await a.call("GET", "network")
    assert status_ == 200, body
    assert [i["name"] for i in body["interfaces"]] == ["eth0", "wlan0", "wg0"]
    assert body["fallback_ap"] == {"available": False}
    status_, body = await a.call("PUT", "network/fallback-ap", {"enable": True})
    assert status_ == 404, body


async def test_enable_and_disable_the_fallback_ap(host):
    host.install()
    a = await host.make()
    _, body = await a.call("GET", "network")
    assert body["fallback_ap"] == {"available": True, "enabled": False, "active": False, "ssid": "ASL_DCA632000002",
                                   "open": False}
    status_, body = await a.call("PUT", "network/fallback-ap", {"enable": True})
    assert status_ == 200 and body["enabled"], body
    assert "systemctl enable --now fallback-ap.timer" in host.calls.read_text()

    # The AP is up, and the watchdog turned off autoconnect on a profile.
    (host.bindir / "ap").touch()
    state = host.root / "run" / "fallback-ap-watchdog" / "suppressed-connections.json"
    state.parent.mkdir(parents=True)
    state.write_text('["Home Wi-Fi"]')
    status_, body = await a.call("PUT", "network/fallback-ap", {"enable": False})
    assert status_ == 200 and body["enabled"] is False and body["active"] is False, body
    calls = host.calls.read_text()
    assert "systemctl disable --now fallback-ap.timer" in calls
    assert "nmcli connection down asl-fallback-ap" in calls
    assert "nmcli connection modify Home Wi-Fi connection.autoconnect yes" in calls
    assert not state.exists()


async def test_fallback_ap_needs_a_boolean(host):
    host.install()
    a = await host.make()
    status_, body = await a.call("PUT", "network/fallback-ap", {"enable": "yes"})
    assert status_ == 400, body


async def test_fallback_ap_refused_in_dev_mode(host):
    host.install()
    a = await host.make(dev=True)
    status_, body = await a.call("PUT", "network/fallback-ap", {"enable": True})
    assert status_ == 501, body
