"""44Net Connect: a WireGuard tunnel that gives the node a public 44Net
(AMPRNet) address for inbound AllStarLink calls, the ASL3 appliance's way.

See https://allstarlink.github.io/adv-topics/44net-connect/ for the manual
steps this replaces. Only on the appliance (asl3-appliance-pc or -pi), with
NetworkManager and firewalld:

- The tunnel is a NetworkManager WireGuard connection in KEYFILE, on
  interface IFNAME. The keyfile holds the tunnel's private key: it is written
  once, from the pasted configuration, and never read back. Everything else
  is changed with nmcli and read with NetworkManager's GetSettings, which
  leaves secrets out; the public key is kept in the connection's user data
  for the page. Backups leave the keyfile out (commands.NEVER_BACKED_UP).
- The firewall zone is ZONE, bound by NetworkManager (connection.zone) while
  the tunnel is up, never by a permanent firewalld interface binding. It
  opens only IAX2, EchoLink and VOTER/RTCM, by the appliance's firewalld
  services or by UDP port when the configured port is outside a service's
  range. The keyfile is written only when the zone exists, and the tunnel
  starts only while bound to it.
- Full tunnel: NetworkManager's own default-route handling (wg-quick's
  Table=auto). Split: no default route, host routes for ROUTE_HOSTS through
  the tunnel (resolved again by ROUTE_TIMER), and a rule sending traffic
  from the 44Net address to table TABLE, whose default route is the tunnel,
  so replies to inbound calls go back through it. IPv4 only: the portal's
  IPv6 link-local address and ::/0 are left out.
- Starting is guarded by a NetworkManager checkpoint: unless confirmed
  within the rollback time, NetworkManager takes the tunnel down again (it
  may have cut off the browser). Only a confirmed tunnel starts at boot.
  Switching between full and split on a running tunnel restarts it the same
  way: "nmcli device reapply" of that change crashed NetworkManager 1.52.
  Only the host routes are changed in place.
- A tunnel set up by hand from the documentation (wg-quick@wg0, its
  /etc/wireguard/wg0.conf, wg0 bound to a zone) can be migrated: its
  configuration is copied into the connection, the unit disabled and the
  binding removed. The file is left in place.
"""

import base64
import ipaddress
import json
import os
import re
import socket
import subprocess
import tempfile
import time
import uuid as uuidlib

CONN_ID = "44Net Connect"
IFNAME = "wg44net"
ZONE = "44NetConnect"
KEYFILE = "/etc/NetworkManager/system-connections/44net-connect.nmconnection"
APPLIANCE = "/usr/share/asl3-appliance"
FIREWALLD_SERVICES = "/etc/firewalld/services"
# The appliance's firewalld services and the ports they open (all UDP).
SERVICES = {"iax2": (4560, 4580), "echolink": (5198, 5199), "rtcm": (1667, 1667)}
LEGACY_CONF = "/etc/wireguard/wg0.conf"
LEGACY_UNIT = "wg-quick@wg0.service"
LEGACY_IF = "wg0"
CHECKPOINT = "/run/asl-web-ui-net44/checkpoint.json"
ROUTE_TIMER = "asl-web-ui-net44-routes.timer"
ROUTE_HOSTS = ("register.allstarlink.org", "stats.allstarlink.org", "www.allstarlink.org")
TABLE = 44
RULE_PRIORITY = 4400
ROLLBACK_DEFAULT = 120
ROLLBACK_RANGE = (30, 600)
DISCONNECT_NEW_DEVICES = 0x04  # NMCheckpointCreateFlags
PUBLIC_KEY_DATA = "asl-web-ui.public-key"
PLACEHOLDER = "REPLACE_WITH_YOUR_PRIVATE_KEY"
AMPRNET = (ipaddress.ip_network("44.0.0.0/9"), ipaddress.ip_network("44.128.0.0/10"))
MAX_CONFIG = 16 * 1024

NM = "org.freedesktop.NetworkManager"
NM_PATH = "/org/freedesktop/NetworkManager"

# Programs, replaceable for tests.
BIN = {
    "nmcli": "/usr/bin/nmcli",
    "firewall-cmd": "/usr/bin/firewall-cmd",
    "busctl": "/usr/bin/busctl",
    "wg": "/usr/bin/wg",
    "systemctl": "/usr/bin/systemctl",
}
ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"}

_HOST = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
                   r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")
# Settings that wg-quick reads and NetworkManager has no use for.
_UNUSED = {"preup", "postup", "predown", "postdown", "saveconfig", "fwmark"}


class Net44Error(Exception):
    def __init__(self, message: str, code: str = "failed"):
        super().__init__(message)
        self.message = message
        self.code = code


def _path(root: str, abs_path: str) -> str:
    return os.path.join(root, abs_path.lstrip("/"))


def run(name: str, *args: str, stdin: str | None = None, timeout: float = 60) -> tuple[int, str, str]:
    try:
        proc = subprocess.run([BIN[name], *args], input=stdin, stdin=None if stdin is not None else subprocess.DEVNULL,
                              capture_output=True, text=True, env=ENV, timeout=timeout)
    except FileNotFoundError:
        raise Net44Error(f"{BIN[name]} is not installed.", "unavailable")
    except subprocess.TimeoutExpired:
        raise Net44Error(f"{name} did not finish in time.")
    return proc.returncode, proc.stdout, proc.stderr


def _check(name: str, *args: str, timeout: float = 60) -> str:
    code, out, err = run(name, *args, timeout=timeout)
    if code != 0:
        raise Net44Error(f"{name} {args[0] if args else ''} failed: {(err or out).strip()[-300:]}")
    return out


# ---- the pasted configuration (wg-quick format) ----------------------------------------------


def _key(value: str, what: str) -> str:
    """A WireGuard key (base64 of 32 bytes). Messages never include the value."""
    value = value.strip()
    try:
        raw = base64.b64decode(value, validate=True)
    except ValueError:
        raw = b""
    if len(raw) != 32:
        raise Net44Error(f"{what} is not a WireGuard key (44 characters of base64).", "invalid")
    return value


def _sections(text: str) -> list[tuple[str, dict[str, str]]]:
    sections: list[tuple[str, dict[str, str]]] = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()  # base64 has no "#"
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            name = line[1:-1].strip().lower()
            if name not in ("interface", "peer"):
                raise Net44Error(f"Line {n}: unknown section [{line[1:-1].strip()[:40]}].", "invalid")
            sections.append((name, {}))
            continue
        key, sep, value = line.partition("=")
        if not sep or not sections:
            raise Net44Error(f"Line {n} is not a setting inside [Interface] or [Peer].", "invalid")
        key, value = key.strip().lower(), value.strip()
        current = sections[-1][1]
        if key in current and key in ("address", "allowedips", "dns"):
            current[key] += "," + value
        else:
            current[key] = value
    return sections


def _int(value: str, what: str, low: int, high: int) -> int:
    if not value.isdigit() or not low <= int(value) <= high:
        raise Net44Error(f"{what} must be a number from {low} to {high}.", "invalid")
    return int(value)


def _endpoint(value: str) -> str:
    m = re.match(r"^\[([0-9A-Fa-f:.]+)\]:(\d+)$", value) or re.match(r"^([^:\[\]\s]+):(\d+)$", value)
    if not m:
        raise Net44Error("Endpoint must be host:port.", "invalid")
    host, port = m.groups()
    _int(port, "The endpoint's port", 1, 65535)
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not _HOST.match(host):
            raise Net44Error("The endpoint's host name is not valid.", "invalid")
    return value


def tunnel_settings(text: str, private_key: str | None = None) -> dict:
    """The tunnel from a wg-quick configuration, as written to the keyfile.
    PRIVATE_KEY, when given, replaces the configuration's PrivateKey (the
    portal leaves a placeholder there)."""
    sections = _sections(text)
    interfaces = [s for name, s in sections if name == "interface"]
    peers = [s for name, s in sections if name == "peer"]
    if len(interfaces) != 1:
        raise Net44Error("The configuration needs exactly one [Interface] section.", "invalid")
    if len(peers) != 1:
        raise Net44Error("The configuration needs exactly one [Peer] section (the 44Net Connect server).", "invalid")
    iface, peer = interfaces[0], peers[0]
    notes = []

    key = (private_key or "").strip() or iface.get("privatekey", "")
    if not key or key == PLACEHOLDER:
        raise Net44Error("Enter the tunnel's private key: the 44Net portal shows it once, when the tunnel is "
                         "created.", "invalid")
    key = _key(key, "The private key")

    v4 = []
    for item in filter(None, (a.strip() for a in iface.get("address", "").split(","))):
        try:
            addr = ipaddress.ip_interface(item)
        except ValueError:
            raise Net44Error(f"Address {item[:50]} is not an IP address.", "invalid")
        if addr.version == 6:
            notes.append(f"The IPv6 address {addr} is left out: the tunnel is set up for IPv4 only.")
        else:
            v4.append(addr)
    if len(v4) != 1:
        raise Net44Error("The configuration needs exactly one IPv4 Address (the 44Net address).", "invalid")
    if not any(v4[0].ip in net for net in AMPRNET):
        raise Net44Error(f"{v4[0].ip} is not a 44Net (AMPRNet) address.", "invalid")

    mtu = _int(iface["mtu"], "MTU", 1280, 9000) if "mtu" in iface else None
    listen_port = _int(iface["listenport"], "ListenPort", 1, 65535) if "listenport" in iface else None
    table = iface.get("table", "auto").lower()
    if table not in ("auto", "off"):
        notes.append(f"Table = {table[:20]} is not used; choose full tunnel or split routing instead.")
    if iface.get("dns"):
        notes.append("DNS is not used: the server keeps its own DNS settings.")
    for name in sorted(set(iface) - {"privatekey", "address", "mtu", "listenport", "table", "dns"}):
        notes.append(f"{name} is not used: NetworkManager runs the tunnel." if name in _UNUSED
                     else f"Unknown setting {name[:30]} is left out.")

    peer_key = _key(peer.get("publickey", ""), "The peer's PublicKey")
    preshared = _key(peer["presharedkey"], "PresharedKey") if peer.get("presharedkey") else None
    if not peer.get("endpoint"):
        raise Net44Error("The [Peer] section needs an Endpoint.", "invalid")
    endpoint = _endpoint(peer["endpoint"])
    allowed = []
    for item in filter(None, (a.strip() for a in peer.get("allowedips", "").split(","))):
        try:
            net = ipaddress.ip_network(item, strict=False)
        except ValueError:
            raise Net44Error(f"AllowedIPs {item[:50]} is not a network.", "invalid")
        if net.version == 4:
            allowed.append(str(net))
    if "0.0.0.0/0" not in allowed:
        raise Net44Error("AllowedIPs must include 0.0.0.0/0, so that calls from anywhere are accepted.", "invalid")
    keepalive = None
    if peer.get("persistentkeepalive", "off").lower() != "off":
        keepalive = _int(peer["persistentkeepalive"], "PersistentKeepalive", 0, 65535) or None
    if keepalive is None:
        notes.append("There is no PersistentKeepalive: behind NAT, calls may stop reaching the node. The 44Net "
                     "portal's configuration normally sets it.")
    for name in sorted(set(peer) - {"publickey", "presharedkey", "endpoint", "allowedips", "persistentkeepalive"}):
        notes.append(f"Unknown setting {name[:30]} is left out.")
    return {"private_key": key, "address": str(v4[0]), "mtu": mtu, "listen_port": listen_port,
            "peer_key": peer_key, "preshared_key": preshared, "endpoint": endpoint, "allowed": allowed,
            "keepalive": keepalive, "split": table == "off", "notes": notes}


def _public_key(private_key: str) -> str:
    code, out, _ = run("wg", "pubkey", stdin=private_key + "\n")
    if code != 0:
        raise Net44Error("wg pubkey failed.")
    return _key(out, "wg pubkey's answer")


def keyfile_text(t: dict, conn_uuid: str, public_key: str) -> str:
    lines = ["[connection]", f"id={CONN_ID}", f"uuid={conn_uuid}", "type=wireguard", f"interface-name={IFNAME}",
             "autoconnect=false", f"zone={ZONE}", "", "[wireguard]", f"private-key={t['private_key']}"]
    if t["listen_port"]:
        lines.append(f"listen-port={t['listen_port']}")
    if t["mtu"]:
        lines.append(f"mtu={t['mtu']}")
    lines += ["", f"[wireguard-peer.{t['peer_key']}]", f"endpoint={t['endpoint']}"]
    if t["keepalive"]:
        lines.append(f"persistent-keepalive={t['keepalive']}")
    if t["preshared_key"]:
        lines += [f"preshared-key={t['preshared_key']}", "preshared-key-flags=0"]
    lines.append("allowed-ips=" + "".join(f"{a};" for a in t["allowed"]))
    lines += ["", "[ipv4]", "method=manual", f"address1={t['address']}", "", "[ipv6]", "method=disabled", "",
              "[user]", f"{PUBLIC_KEY_DATA}={public_key}", ""]
    return "\n".join(lines)


def _write_keyfile(root: str, text: str) -> str:
    path = _path(root, KEYFILE)
    os.makedirs(os.path.dirname(path), mode=0o755, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".asl-web-ui-", dir=os.path.dirname(path))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    return path


# ---- NetworkManager ----------------------------------------------------------------------


def _bus(obj: str, iface: str, method: str, *args: str) -> list:
    code, out, err = run("busctl", "--json=short", "call", NM, obj, iface, method, *args)
    if code != 0:
        raise Net44Error(f"NetworkManager {method} failed: {(err or out).strip()[-300:]}")
    return json.loads(out)["data"]


def _plain(sig: str, data):
    if sig == "aa{sv}":
        return [{k: _plain(v["type"], v["data"]) for k, v in d.items()} for d in data]
    return data


def _find(root: str) -> str | None:
    """The UUID of the 44Net Connect connection (the one in KEYFILE)."""
    out = _check("nmcli", "-t", "-f", "UUID,FILENAME", "connection", "show")
    for line in out.splitlines():
        conn_uuid, _, filename = line.partition(":")
        if filename.replace("\\:", ":") == _path(root, KEYFILE):
            return conn_uuid
    return None


def _settings(conn_uuid: str) -> dict:
    """The connection's settings without secrets (GetSettings never returns them)."""
    obj = _bus(f"{NM_PATH}/Settings", f"{NM}.Settings", "GetConnectionByUuid", "s", conn_uuid)[0]
    raw = _bus(obj, f"{NM}.Settings.Connection", "GetSettings")[0]
    return {section: {k: _plain(v["type"], v["data"]) for k, v in keys.items()} for section, keys in raw.items()}


def _summary(s: dict) -> dict:
    con, wg, ip4 = s.get("connection", {}), s.get("wireguard", {}), s.get("ipv4", {})
    peer = (wg.get("peers") or [{}])[0]
    addresses = [f"{a['address']}/{a['prefix']}" for a in ip4.get("address-data", [])]
    return {
        "id": con.get("id"),
        "interface": con.get("interface-name"),
        "zone": con.get("zone") or None,
        "autoconnect": con.get("autoconnect", True),
        "address": addresses[0] if addresses else None,
        "mtu": wg.get("mtu") or None,
        "endpoint": peer.get("endpoint"),
        "peer_public_key": peer.get("public-key"),
        "keepalive": peer.get("persistent-keepalive") or None,
        "public_key": s.get("user", {}).get("data", {}).get(PUBLIC_KEY_DATA),
        "mode": "split" if wg.get("peer-routes", True) is False else "full",
        "routes": [r["dest"] for r in ip4.get("route-data", []) if r.get("prefix") == 32 and "table" not in r],
        "ipv6": s.get("ipv6", {}).get("method"),
    }


def _state(conn_uuid: str) -> str | None:
    """activated, activating, deactivating; None when not active."""
    out = _check("nmcli", "-t", "-f", "UUID,STATE", "connection", "show", "--active")
    for line in out.splitlines():
        u, _, state = line.partition(":")
        if u == conn_uuid:
            return state
    return None


def _nmcli_modify(conn_uuid: str, *settings: str) -> None:
    _check("nmcli", "connection", "modify", conn_uuid, *settings)


def _resolve() -> list[str]:
    """IPv4 addresses of ROUTE_HOSTS (empty if none resolve)."""
    found = set()
    for host in ROUTE_HOSTS:
        try:
            found |= {ai[4][0] for ai in socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_DGRAM)}
        except OSError:
            continue
    return sorted(found, key=ipaddress.ip_address)


def _route_settings(hosts: list[str]) -> list[str]:
    return ["ipv4.routes", ", ".join([f"{h}/32" for h in hosts] + [f"0.0.0.0/0 table={TABLE}"])]


def _mode_settings(mode: str, address: str, hosts: list[str]) -> list[str]:
    if mode == "split":
        ip = address.split("/")[0]
        return ["wireguard.peer-routes", "no", "wireguard.ip4-auto-default-route", "no", *_route_settings(hosts),
                "ipv4.routing-rules", f"priority {RULE_PRIORITY} from {ip} table {TABLE}"]
    return ["wireguard.peer-routes", "yes", "wireguard.ip4-auto-default-route", "default", "ipv4.routes", "",
            "ipv4.routing-rules", ""]


def _hosts_for(summary: dict) -> list[str]:
    hosts = _resolve() or summary["routes"]
    if not hosts:
        raise Net44Error("The AllStarLink servers' addresses could not be looked up, so split routing cannot be set "
                         "up. Check the server's DNS, or use the full tunnel.")
    return hosts


def _set_mode(conn_uuid: str, mode: str, summary: dict) -> None:
    """Mode settings and the route timer. Only for a connection that is not active."""
    hosts = _hosts_for(summary) if mode == "split" else []
    _nmcli_modify(conn_uuid, *_mode_settings(mode, summary["address"], hosts))
    run("systemctl", "enable" if mode == "split" else "disable", "--now", ROUTE_TIMER)


def refresh_routes(root: str = "/") -> str:
    """Split routing: look the AllStarLink servers up again and update the
    host routes (in place, on a running tunnel). For ROUTE_TIMER."""
    conn = _find(root)
    if conn is None:
        return "44Net Connect is not set up."
    summary = _summary(_settings(conn))
    if summary["mode"] != "split":
        return "The tunnel is a full tunnel; there are no routes to update."
    hosts = _resolve()
    if not hosts:
        return "The AllStarLink servers could not be looked up; the routes stay as they are."
    if hosts == summary["routes"]:
        return "The routes are up to date."
    _nmcli_modify(conn, *_route_settings(hosts))
    if _state(conn) == "activated":
        _check("nmcli", "device", "reapply", IFNAME)
    return f"Routes through the tunnel: {', '.join(hosts)}"


# ---- the checkpoint that stops an unconfirmed tunnel ----------------------------------------


def _read_checkpoint(root: str) -> dict | None:
    try:
        with open(_path(root, CHECKPOINT)) as f:
            data = json.load(f)
        return data if isinstance(data, dict) and isinstance(data.get("path"), str) else None
    except (OSError, ValueError):
        return None


def _drop_checkpoint_file(root: str) -> None:
    try:
        os.unlink(_path(root, CHECKPOINT))
    except FileNotFoundError:
        pass


def _checkpoints() -> list[str]:
    code, out, _ = run("busctl", "--json=short", "get-property", NM, NM_PATH, NM, "Checkpoints")
    return json.loads(out)["data"] if code == 0 else []


def _pending(root: str) -> dict | None:
    """{"seconds_left"} while a start waits for confirmation; {"rolled_back"}
    once (then forgotten) after NetworkManager stopped an unconfirmed tunnel."""
    data = _read_checkpoint(root)
    if data is None:
        return None
    if data["path"] in _checkpoints():
        return {"seconds_left": max(0, round(data.get("deadline", 0) - time.time()))}
    _drop_checkpoint_file(root)
    return {"rolled_back": True}


def _start_guarded(root: str, conn: str, rollback: int) -> None:
    cp = _bus(NM_PATH, NM, "CheckpointCreate", "aouu", "0", str(rollback), str(DISCONNECT_NEW_DEVICES))[0]
    path = _path(root, CHECKPOINT)
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    with open(path, "w") as f:
        json.dump({"path": cp, "deadline": time.time() + rollback}, f)
    code, out, err = run("nmcli", "--wait", "45", "connection", "up", conn, timeout=60)
    if code != 0:
        run("busctl", "call", NM, NM_PATH, NM, "CheckpointRollback", "o", cp)
        _drop_checkpoint_file(root)
        raise Net44Error(f"The tunnel did not start: {(err or out).strip()[-300:]}")


# ---- firewalld -----------------------------------------------------------------------------


def _fw_list(*args: str) -> list[str]:
    return _check("firewall-cmd", "--permanent", *args).split()


def _zone() -> dict | None:
    if ZONE not in _fw_list("--get-zones"):
        return None
    return {"services": sorted(_fw_list(f"--zone={ZONE}", "--list-services")),
            "ports": sorted(_fw_list(f"--zone={ZONE}", "--list-ports")),
            "interfaces": _fw_list(f"--zone={ZONE}", "--list-interfaces")}


def _zone_of(interface: str, permanent: bool) -> str | None:
    code, out, _ = run("firewall-cmd", *(["--permanent"] if permanent else []), f"--get-zone-of-interface={interface}")
    return out.strip() if code == 0 and out.strip() else None


def _port(value, what: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 65535:
        raise Net44Error(f"{what} must be a port number.", "invalid")
    return value


def zone_contents(iax_port: int, echolink: bool, rtcm_port: int | None) -> tuple[set[str], set[str]]:
    """(services, ports) the zone opens: a service when it covers the port, else the UDP port."""
    services, ports = set(), set()

    def add(service: str, port: int) -> None:
        low, high = SERVICES[service]
        if low <= port <= high:
            services.add(service)
        else:
            ports.add(f"{port}/udp")

    add("iax2", iax_port)
    if echolink:
        services.add("echolink")
    if rtcm_port is not None:
        add("rtcm", rtcm_port)
    return services, ports


def set_zone(root: str, args: dict) -> dict:
    _require_available(root)
    rtcm = args.get("rtcm_port")
    services, ports = zone_contents(_port(args.get("iax_port"), "iax_port"), args.get("echolink") is True,
                                    None if rtcm is None else _port(rtcm, "rtcm_port"))
    current = _zone()
    if current is None:
        _check("firewall-cmd", "--permanent", f"--new-zone={ZONE}")
        current = {"services": [], "ports": []}
    zone = f"--zone={ZONE}"
    for s in sorted(set(current["services"]) - services):
        _check("firewall-cmd", "--permanent", zone, f"--remove-service={s}")
    for s in sorted(services - set(current["services"])):
        _check("firewall-cmd", "--permanent", zone, f"--add-service={s}")
    for p in sorted(set(current["ports"]) - ports):
        _check("firewall-cmd", "--permanent", zone, f"--remove-port={p}")
    for p in sorted(ports - set(current["ports"])):
        _check("firewall-cmd", "--permanent", zone, f"--add-port={p}")
    _check("firewall-cmd", "--reload")
    return status(root)


# ---- availability and status ---------------------------------------------------------------


def _availability(root: str) -> tuple[str, str] | None:
    """(code, message) when 44Net Connect cannot be used here."""
    if not os.path.isdir(_path(root, APPLIANCE)):
        return "appliance", "44Net Connect needs the AllStarLink appliance (asl3-appliance-pc or asl3-appliance-pi)."
    missing = [s for s in SERVICES if not os.path.exists(_path(root, f"{FIREWALLD_SERVICES}/{s}.xml"))]
    if missing:
        return "appliance", (f"The appliance's firewalld services are missing ({', '.join(missing)}). Reinstall "
                             "the asl3-appliance package.")
    code, out, _ = run("nmcli", "-t", "-f", "RUNNING", "general")
    if code != 0 or out.strip() != "running":
        return "networkmanager", "NetworkManager is not running."
    code, out, _ = run("firewall-cmd", "--state")
    if code != 0 or out.strip() != "running":
        return "firewalld", "firewalld is not running."
    if not os.path.exists(BIN["wg"]):
        return "wireguard", "wireguard-tools is not installed."
    return None


def _require_available(root: str) -> None:
    problem = _availability(root)
    if problem:
        raise Net44Error(problem[1], "unavailable")


def _require_zone() -> None:
    if _zone() is None:
        raise Net44Error(f"Set up the firewall zone {ZONE} first.", "order")


def _legacy(root: str) -> dict | None:
    """A tunnel set up by hand with wg-quick (the documentation's way)."""
    exists = os.path.exists(_path(root, LEGACY_CONF))
    enabled = run("systemctl", "is-enabled", LEGACY_UNIT)[1].strip() == "enabled"
    active = run("systemctl", "is-active", LEGACY_UNIT)[1].strip() == "active"
    zone = _zone_of(LEGACY_IF, permanent=True)
    if not (exists or enabled or active or zone):
        return None
    return {"config": LEGACY_CONF if exists else None, "unit": LEGACY_UNIT, "enabled": enabled, "active": active,
            "interface": LEGACY_IF, "zone": zone}


def _tunnel() -> dict:
    """Live state from the kernel (never "wg show dump": it prints the private key)."""
    def show(what: str) -> list[str]:
        code, out, _ = run("wg", "show", IFNAME, what)
        return out.split("\n")[0].split("\t") if code == 0 and out.strip() else []

    handshake, transfer, endpoint = show("latest-handshakes"), show("transfer"), show("endpoints")
    latest = int(handshake[1]) if len(handshake) > 1 and handshake[1].isdigit() else 0
    return {
        "latest_handshake": latest or None,
        "rx_bytes": int(transfer[1]) if len(transfer) > 2 and transfer[1].isdigit() else None,
        "tx_bytes": int(transfer[2]) if len(transfer) > 2 and transfer[2].isdigit() else None,
        "endpoint": endpoint[1] if len(endpoint) > 1 and endpoint[1] != "(none)" else None,
        "now": int(time.time()),
    }


def status(root: str = "/") -> dict:
    problem = _availability(root)
    if problem:
        return {"available": False, "reason": problem[0], "message": problem[1]}
    zone = _zone()
    legacy = _legacy(root)
    issues = []
    connection = None
    conn = _find(root)
    if conn:
        connection = {**_summary(_settings(conn)), "state": _state(conn), "tunnel": None, "active_zone": None}
        if connection["zone"] != ZONE:
            issues.append(f"The tunnel's firewall zone is {connection['zone'] or 'the default zone'}, not {ZONE}. "
                          "Set up the tunnel again.")
        if connection["state"] == "activated":
            connection["tunnel"] = _tunnel()
            connection["active_zone"] = _zone_of(IFNAME, permanent=False)
            if connection["active_zone"] != ZONE:
                issues.append(f"{IFNAME} is in the firewall zone {connection['active_zone'] or '(none)'}, not {ZONE}. "
                              "Stop the tunnel.")
        if legacy and legacy["active"]:
            issues.append(f"The hand-made tunnel {LEGACY_UNIT} is also running. Stop it, or migrate it.")
    return {"available": True, "zone_name": ZONE, "interface": IFNAME, "zone": zone, "connection": connection,
            "legacy": legacy, "checkpoint": _pending(root), "issues": issues}


# ---- commands ------------------------------------------------------------------------------


def _mode(args: dict, default: str | None = None) -> str:
    mode = args.get("mode") or default
    if mode not in ("full", "split"):
        raise Net44Error("mode must be full or split.", "invalid")
    return mode


def _install(root: str, t: dict, mode: str, existing: str | None) -> None:
    conn_uuid = existing or str(uuidlib.uuid4())
    path = _write_keyfile(root, keyfile_text(t, conn_uuid, _public_key(t["private_key"])))
    _check("nmcli", "connection", "load", path)
    _set_mode(conn_uuid, mode, {"address": t["address"], "routes": []})


def configure(root: str, args: dict) -> dict:
    _require_available(root)
    _require_zone()
    text = args.get("config")
    key = args.get("private_key")
    if not isinstance(text, str) or len(text) > MAX_CONFIG:
        raise Net44Error("Paste the WireGuard configuration from the 44Net portal.", "invalid")
    if key is not None and (not isinstance(key, str) or len(key) > 200):
        raise Net44Error("The private key is not valid.", "invalid")
    t = tunnel_settings(text, key)
    mode = _mode(args, "split" if t["split"] else "full")
    existing = _find(root)
    if existing and _state(existing):
        raise Net44Error("Stop the tunnel before replacing its configuration.", "busy")
    _install(root, t, mode, existing)
    return {"status": status(root), "notes": t["notes"]}


def migrate(root: str, args: dict) -> dict:
    _require_available(root)
    legacy = _legacy(root)
    if not legacy or not legacy["config"]:
        raise Net44Error(f"There is no {LEGACY_CONF} to migrate.", "not_found")
    if _find(root):
        raise Net44Error("44Net Connect is already set up here; remove it first to migrate again.", "conflict")
    _require_zone()
    try:
        with open(_path(root, LEGACY_CONF)) as f:
            text = f.read(MAX_CONFIG + 1)
    except (OSError, UnicodeDecodeError) as exc:
        raise Net44Error(f"{LEGACY_CONF} cannot be read: {exc.__class__.__name__}")
    if len(text) > MAX_CONFIG:
        raise Net44Error(f"{LEGACY_CONF} is too large to be a WireGuard configuration.", "invalid")
    t = tunnel_settings(text)
    mode = "split" if t["split"] else "full"
    if legacy["enabled"] or legacy["active"]:
        _check("systemctl", "disable", "--now", LEGACY_UNIT)
    if legacy["zone"]:
        _check("firewall-cmd", "--permanent", f"--zone={legacy['zone']}", f"--remove-interface={LEGACY_IF}")
        _check("firewall-cmd", "--reload")
    _install(root, t, mode, None)
    notes = t["notes"] + [f"{LEGACY_CONF} is left in place, unused. Delete it once the new tunnel works."]
    return {"status": status(root), "notes": notes}


def set_mode(root: str, args: dict) -> dict:
    """Full tunnel or split routing. A running tunnel restarts (guarded like a start)."""
    _require_available(root)
    mode = _mode(args)
    conn = _find(root)
    if conn is None:
        raise Net44Error("44Net Connect is not set up.", "not_found")
    summary = _summary(_settings(conn))
    if summary["mode"] == mode:
        return status(root)
    if (_pending(root) or {}).get("seconds_left") is not None:
        raise Net44Error("Confirm or stop the tunnel that is starting first.", "busy")
    running = _state(conn) is not None
    rollback = _rollback(args)
    if running:
        _nmcli_modify(conn, "connection.autoconnect", "no")
        _check("nmcli", "connection", "down", conn)
    _set_mode(conn, mode, summary)
    if running:
        _start_guarded(root, conn, rollback)
    return status(root)


def _rollback(args: dict) -> int:
    value = args.get("rollback", ROLLBACK_DEFAULT)
    low, high = ROLLBACK_RANGE
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        raise Net44Error(f"rollback must be {low} to {high} seconds.", "invalid")
    return value


def start(root: str, args: dict) -> dict:
    _require_available(root)
    rollback = _rollback(args)
    conn = _find(root)
    if conn is None:
        raise Net44Error("Set up the tunnel first.", "not_found")
    summary = _summary(_settings(conn))
    _require_zone()
    if summary["zone"] != ZONE:
        raise Net44Error(f"The tunnel is not in the firewall zone {ZONE}; set it up again.", "order")
    legacy = _legacy(root)
    if legacy and legacy["active"]:
        raise Net44Error(f"{LEGACY_UNIT} is running with the same tunnel. Migrate it or stop it first.", "conflict")
    if _state(conn):
        raise Net44Error("The tunnel is already running.", "busy")
    if (_pending(root) or {}).get("seconds_left") is not None:
        raise Net44Error("A start is already waiting for confirmation.", "busy")
    # Unconfirmed, it must not come back by itself after the rollback.
    if summary["autoconnect"]:
        _nmcli_modify(conn, "connection.autoconnect", "no")
    if summary["mode"] == "split":
        hosts = _resolve()
        if hosts and hosts != summary["routes"]:
            _nmcli_modify(conn, *_route_settings(hosts))
    _start_guarded(root, conn, rollback)
    return status(root)


def confirm(root: str, args: dict) -> dict:
    data = _read_checkpoint(root)
    if data is None:
        raise Net44Error("No tunnel start is waiting for confirmation.", "not_found")
    code, _, _ = run("busctl", "call", NM, NM_PATH, NM, "CheckpointDestroy", "o", data["path"])
    _drop_checkpoint_file(root)
    if code != 0:
        raise Net44Error("The time ran out: NetworkManager already stopped the tunnel again.", "expired")
    conn = _find(root)
    if conn:
        _nmcli_modify(conn, "connection.autoconnect", "yes")
    return status(root)


def _stop(root: str, conn: str) -> None:
    data = _read_checkpoint(root)
    if data:
        run("busctl", "call", NM, NM_PATH, NM, "CheckpointDestroy", "o", data["path"])
        _drop_checkpoint_file(root)
    _nmcli_modify(conn, "connection.autoconnect", "no")
    if _state(conn):
        _check("nmcli", "connection", "down", conn)


def stop(root: str, args: dict) -> dict:
    conn = _find(root)
    if conn is None:
        raise Net44Error("44Net Connect is not set up.", "not_found")
    _stop(root, conn)
    return status(root)


def remove(root: str, args: dict) -> dict:
    conn = _find(root)
    if conn:
        _stop(root, conn)
        _check("nmcli", "connection", "delete", conn)
    try:
        os.unlink(_path(root, KEYFILE))
    except FileNotFoundError:
        pass
    run("systemctl", "disable", "--now", ROUTE_TIMER)
    if args.get("delete_zone") is True and _zone() is not None:
        _check("firewall-cmd", "--permanent", f"--delete-zone={ZONE}")
        _check("firewall-cmd", "--reload")
    return status(root)
