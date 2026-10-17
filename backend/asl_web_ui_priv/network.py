"""Network interfaces and the ASL3 appliance's fallback access point.

The interface list comes from "ip -details -json address" (it needs
AF_NETLINK, which the web service's sandbox does not allow, so it runs
here). Loopback interfaces, loopback and link-local addresses, and
deprecated addresses (expired IPv6 privacy addresses) are left out; an
interface is listed when it is up and has an address left. Stable addresses
come before temporary ones.

The fallback AP belongs to the asl3-appliance-pc and asl3-appliance-pi
packages (/usr/libexec/asl3/fallback-ap-watchdog.py, run every minute by
fallback-ap.timer). It is off until the timer is enabled. While the host
has no usable connection, the watchdog starts a Wi-Fi access point named
AP_SSID_PREFIX plus the Wi-Fi adapter's MAC address, and it turns off
autoconnect on the adapter's other profiles (remembered in STATE_FILE) until
the connection is back. Disabling here does what the watchdog does when the
connection returns: take the AP down and turn autoconnect back on.
"""

import glob
import ipaddress
import json
import os
import subprocess

TIMER = "fallback-ap.timer"
WATCHDOGS = "/usr/libexec/asl3/fallback-ap*"
DEFAULTS = "/etc/default/fallback-ap"
STATE_FILE = "/run/fallback-ap-watchdog/suppressed-connections.json"
SYS_NET = "/sys/class/net"

# Programs, replaceable for tests.
BIN = {
    "ip": "/usr/sbin/ip",
    "systemctl": "/usr/bin/systemctl",
    "nmcli": "/usr/bin/nmcli",
}
ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"}

# linkinfo.info_kind from "ip -details" for virtual interfaces.
KINDS = {"bridge": "Bridge", "bond": "Bond", "vlan": "VLAN", "wireguard": "WireGuard", "tun": "Tunnel (TUN/TAP)",
         "veth": "Virtual Ethernet", "macvlan": "MACVLAN", "ipvlan": "IPVLAN", "vxlan": "VXLAN", "dummy": "Dummy",
         "gre": "GRE tunnel", "sit": "IPv6-in-IPv4 tunnel", "ipip": "IP-in-IP tunnel"}
LINK_TYPES = {"ether": "Ethernet", "ppp": "PPP", "none": "Tunnel", "infiniband": "InfiniBand"}


class NetworkError(Exception):
    def __init__(self, message: str, code: str = "failed"):
        super().__init__(message)
        self.message = message
        self.code = code


def _path(root: str, abs_path: str) -> str:
    return os.path.join(root, abs_path.lstrip("/"))


def run(name: str, *args: str, timeout: float = 60) -> tuple[int, str]:
    try:
        proc = subprocess.run([BIN[name], *args], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              env=ENV, timeout=timeout)
    except FileNotFoundError:
        raise NetworkError(f"{BIN[name]} is not installed.", "unavailable")
    except subprocess.TimeoutExpired:
        raise NetworkError(f"{name} did not finish in time.")
    return proc.returncode, (proc.stdout + proc.stderr).strip()


# ---- Interfaces ---------------------------------------------------------------------------


def _wireless(root: str, ifname: str) -> bool:
    base = _path(root, f"{SYS_NET}/{ifname}")
    return os.path.exists(os.path.join(base, "wireless")) or os.path.exists(os.path.join(base, "phy80211"))


def _kind(root: str, link: dict) -> str:
    if _wireless(root, link["ifname"]):
        return "Wi-Fi"
    kind = (link.get("linkinfo") or {}).get("info_kind")
    if kind:
        return KINDS.get(kind, kind)
    link_type = link.get("link_type", "")
    return LINK_TYPES.get(link_type, link_type or "Unknown")


def _shown(addr: dict) -> bool:
    try:
        ip = ipaddress.ip_address(addr.get("local", ""))
    except ValueError:
        return False
    return (addr.get("scope") != "host" and not addr.get("deprecated") and not ip.is_loopback
            and not ip.is_link_local)


def interfaces(links: list[dict], root: str = "/") -> list[dict]:
    """The active interfaces in LINKS (ip -json output), without local-only addresses."""
    shown = []
    for link in links:
        flags = link.get("flags", [])
        if "LOOPBACK" in flags or link.get("link_type") == "loopback" or "UP" not in flags:
            continue
        if link.get("operstate") not in ("UP", "UNKNOWN"):
            continue
        addrs = sorted((a for a in link.get("addr_info", []) if _shown(a)), key=lambda a: bool(a.get("temporary")))
        ipv4 = [f"{a['local']}/{a['prefixlen']}" for a in addrs if a.get("family") == "inet"]
        ipv6 = [f"{a['local']}/{a['prefixlen']}" for a in addrs if a.get("family") == "inet6"]
        if not ipv4 and not ipv6:
            continue
        mac = link.get("address") if link.get("link_type") == "ether" else None
        shown.append({"name": link["ifname"], "type": _kind(root, link), "mac": mac, "ipv4": ipv4, "ipv6": ipv6})
    return shown


# ---- Fallback AP ---------------------------------------------------------------------------


def _defaults(root: str) -> dict[str, str]:
    """KEY=VALUE lines of /etc/default/fallback-ap (as systemd's EnvironmentFile= reads them)."""
    values = {}
    try:
        with open(_path(root, DEFAULTS)) as f:
            for line in f:
                key, sep, value = line.strip().partition("=")
                if sep and not key.startswith("#"):
                    values[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return values


def _ssid(root: str, prefix: str) -> str | None:
    """The watchdog's SSID: the prefix and the first Wi-Fi adapter's MAC address."""
    try:
        names = sorted(n for n in os.listdir(_path(root, SYS_NET)) if os.path.exists(
            os.path.join(_path(root, SYS_NET), n, "wireless")))
    except OSError:
        return None
    if not names:
        return None
    try:
        with open(os.path.join(_path(root, SYS_NET), names[0], "address")) as f:
            mac = f.read().strip()
    except OSError:
        return None
    return prefix + mac.replace(":", "").upper()


def available(root: str = "/") -> bool:
    return bool(glob.glob(_path(root, WATCHDOGS)))


def _ap_active(conn_name: str) -> bool:
    try:
        code, out = run("nmcli", "-t", "-f", "NAME", "connection", "show", "--active")
    except NetworkError:
        return False
    return code == 0 and conn_name in out.splitlines()


def fallback_ap(root: str = "/") -> dict:
    if not available(root):
        return {"available": False}
    cfg = _defaults(root)
    _, out = run("systemctl", "is-enabled", TIMER)
    conn_name = cfg.get("AP_CONN_NAME") or "asl-fallback-ap"
    return {
        "available": True,
        "enabled": out.splitlines()[-1:] == ["enabled"],
        "active": _ap_active(conn_name),
        "ssid": _ssid(root, cfg.get("AP_SSID_PREFIX", "AllStarLink_")),
        "open": cfg.get("AP_PSK", "") == "",
    }


def status(root: str = "/") -> dict:
    code, out = run("ip", "-details", "-json", "address", "show")
    if code != 0:
        raise NetworkError(f"ip address show failed: {out[-300:]}")
    try:
        links = json.loads(out)
    except ValueError:
        raise NetworkError("ip address show returned something unexpected.")
    return {"interfaces": interfaces(links, root), "fallback_ap": fallback_ap(root)}


def set_fallback_ap(root: str, enable: bool) -> dict:
    if not available(root):
        raise NetworkError("The fallback AP is not installed (asl3-appliance-pc or asl3-appliance-pi).", "not_found")
    code, out = run("systemctl", "enable" if enable else "disable", "--now", TIMER)
    if code != 0:
        raise NetworkError(f"systemctl {'enable' if enable else 'disable'} {TIMER} failed: {out[-300:]}")
    if not enable:
        _stop_ap(root)
    return fallback_ap(root)


def _stop_ap(root: str) -> None:
    """Take the AP down and give the adapter's other profiles their autoconnect back."""
    conn_name = _defaults(root).get("AP_CONN_NAME") or "asl-fallback-ap"
    if _ap_active(conn_name):
        run("nmcli", "connection", "down", conn_name)
    state = _path(root, STATE_FILE)
    try:
        with open(state) as f:
            names = json.load(f)
    except (OSError, ValueError):
        return
    for name in names if isinstance(names, list) else []:
        if isinstance(name, str):
            run("nmcli", "connection", "modify", name, "connection.autoconnect", "yes")
    try:
        os.unlink(state)
    except OSError:
        pass
