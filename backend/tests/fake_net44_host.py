"""Stand-ins for nmcli, firewall-cmd, busctl, wg and systemctl for the 44Net
Connect tests: just enough of each, with the output formats seen on an ASL3
appliance (NetworkManager 1.52, firewalld 2.3). State lives in a JSON file.

    fake_net44_host.py <program> <state.json> <args...>
"""

import base64
import configparser
import hashlib
import json
import os
import sys

IFNAME = "wg44net"


def load(path):
    with open(path) as f:
        return json.load(f)


def save(path, state):
    with open(path, "w") as f:
        json.dump(state, f, indent=1)


def fail(text, code=1):
    print(text, file=sys.stderr)
    sys.exit(code)


def boolean(value):
    return {"yes": True, "true": True, "no": False, "false": False}[value]


# ---- nmcli -------------------------------------------------------------------------------


def keyfile_settings(path):
    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str
    cp.read(path)
    con = cp["connection"]
    s = {"connection": {"id": con["id"], "uuid": con["uuid"], "type": con["type"],
                        "interface-name": con.get("interface-name"),
                        "autoconnect": boolean(con.get("autoconnect", "true"))},
         "wireguard": {"peers": []}, "ipv4": {"method": cp["ipv4"]["method"]}, "ipv6": {"method": cp["ipv6"]["method"]}}
    if "zone" in con:
        s["connection"]["zone"] = con["zone"]
    wg = cp["wireguard"]
    if "mtu" in wg:
        s["wireguard"]["mtu"] = int(wg["mtu"])
    for name in cp.sections():
        if name.startswith("wireguard-peer."):
            p = cp[name]
            peer = {"public-key": name.split(".", 1)[1], "endpoint": p["endpoint"],
                    "allowed-ips": [a for a in p["allowed-ips"].split(";") if a]}
            if "persistent-keepalive" in p:
                peer["persistent-keepalive"] = int(p["persistent-keepalive"])
            s["wireguard"]["peers"].append(peer)
    addr, prefix = cp["ipv4"]["address1"].split("/")
    s["ipv4"]["address-data"] = [{"address": addr, "prefix": int(prefix)}]
    if "user" in cp:
        s["user"] = {"data": dict(cp["user"])}
    return s, wg["private-key"]


def modify(s, key, value):
    section, prop = key.split(".", 1)
    target = s.setdefault(section, {})
    if key in ("connection.autoconnect", "wireguard.peer-routes"):
        target[prop] = boolean(value)
    elif key == "wireguard.ip4-auto-default-route":
        target[prop] = {"no": 0, "yes": 1, "default": -1}[value]
    elif key == "ipv4.routes":
        routes = []
        for item in filter(None, (r.strip() for r in value.split(","))):
            dest, *attrs = item.split()
            ip, prefix = dest.split("/")
            route = {"dest": ip, "prefix": int(prefix)}
            for a in attrs:
                k, v = a.split("=")
                route[k] = int(v)
            routes.append(route)
        target["route-data"] = routes
    elif key == "ipv4.routing-rules":
        rules = []
        if value:
            words = value.split()
            rule = {"family": 2}
            for k, v in zip(words[::2], words[1::2]):
                if k == "from":
                    rule["from"], rule["from-len"] = v, 32
                else:
                    rule[k] = int(v)
            rules.append(rule)
        target["routing-rules"] = rules
    else:
        fail(f"Error: invalid property '{key}'.", 2)


def nmcli(state, args):
    if args[:2] == ["--wait", "45"]:
        args = args[2:]
    conns = state["connections"]
    if args == ["-t", "-f", "RUNNING", "general"]:
        print("running" if state["nm_running"] else "stopped")
    elif args == ["-t", "-f", "UUID,FILENAME", "connection", "show"]:
        print(f"{state['wifi_uuid']}:/etc/NetworkManager/system-connections/Home.nmconnection")
        for u, c in conns.items():
            print(f"{u}:{c['filename']}")
    elif args == ["-t", "-f", "UUID,STATE", "connection", "show", "--active"]:
        print(f"{state['wifi_uuid']}:activated")
        for u in state["active"]:
            print(f"{u}:activated")
    elif args[:2] == ["connection", "load"]:
        settings, key = keyfile_settings(args[2])
        u = settings["connection"]["uuid"]
        conns[u] = {"filename": args[2], "settings": settings, "private_key": key}
    elif args[:2] == ["connection", "modify"]:
        c = conns.get(args[2]) or fail(f"Error: unknown connection '{args[2]}'.", 10)
        rest = args[3:]
        for key, value in zip(rest[::2], rest[1::2]):
            modify(c["settings"], key, value)
    elif args[:2] == ["connection", "up"]:
        if state.get("fail_up"):
            fail("Error: Connection activation failed: The base network connection was interrupted.", 4)
        c = conns.get(args[2]) or fail("Error: unknown connection.", 10)
        state["active"].append(args[2])
        state["runtime_zone"] = c["settings"]["connection"].get("zone") or state["default_zone"]
    elif args[:2] == ["connection", "down"]:
        if args[2] not in state["active"]:
            fail(f"Error: '{args[2]}' is not an active connection.", 10)
        state["active"].remove(args[2])
    elif args[:2] == ["connection", "delete"]:
        c = conns.pop(args[2])
        os.unlink(c["filename"])
    elif args == ["device", "reapply", IFNAME]:
        if not state["active"]:
            fail(f"Error: Device '{IFNAME}' is not active.", 10)
        state["reapplied"] += 1
    else:
        fail(f"fake nmcli: unexpected {args}", 99)


# ---- firewall-cmd ----------------------------------------------------------------------------


def firewall_cmd(state, args):
    zones = state["zones"]
    permanent = args[:1] == ["--permanent"]
    if permanent:
        args = args[1:]
    if args == ["--state"]:
        print("running")
        return
    if args == ["--get-zones"]:
        print(" ".join(sorted(zones)))
        return
    if args == ["--reload"]:
        state["reloads"] += 1
        print("success")
        return
    if args[0].startswith("--get-zone-of-interface="):
        iface = args[0].split("=", 1)[1]
        if not permanent and iface == IFNAME and state["active"]:
            print(state["runtime_zone"])
            return
        for name, z in zones.items():
            if iface in z["interfaces"]:
                print(name)
                return
        fail("no zone", 2)
    if args[0].startswith("--new-zone="):
        zones[args[0].split("=", 1)[1]] = {"services": [], "ports": [], "interfaces": []}
        print("success")
        return
    if args[0].startswith("--delete-zone="):
        del zones[args[0].split("=", 1)[1]]
        print("success")
        return
    zone = zones.get(args[0].split("=", 1)[1]) if args[0].startswith("--zone=") else None
    if zone is None:
        fail(f"Error: INVALID_ZONE: {args[0]}", 112)
    op = args[1]
    lists = {"service": "services", "port": "ports", "interface": "interfaces"}
    if op.startswith("--list-"):
        print(" ".join(zone[op[len("--list-"):]]))
        return
    verb, _, rest = op[2:].partition("-")
    kind, _, value = rest.partition("=")
    items = zone[lists[kind]]
    if verb == "add" and value not in items:
        items.append(value)
    elif verb == "remove" and value in items:
        items.remove(value)
    print("success")


# ---- busctl ----------------------------------------------------------------------------------


def variant(value):
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return {"type": "aa{sv}", "data": [{k: {"type": "?", "data": v} for k, v in d.items()} for d in value]}
    return {"type": "?", "data": value}


def busctl(state, args):
    if args[0] == "--json=short":
        args = args[1:]
    verb, _service, obj, *rest = args
    if verb == "get-property":
        print(json.dumps({"type": "ao", "data": sorted(state["checkpoints"])}))
        return
    iface, method, *params = rest
    if method == "GetConnectionByUuid":
        if params[1] not in state["connections"]:
            fail("Call failed: No connection with the UUID was found.")
        print(json.dumps({"type": "o", "data": [f"/org/freedesktop/NetworkManager/Settings/{params[1]}"]}))
    elif method == "GetSettings":
        c = state["connections"][obj.rsplit("/", 1)[1]]
        out = {}
        for section, keys in c["settings"].items():
            if section == "user":
                out[section] = {"data": {"type": "a{ss}", "data": keys["data"]}}
            else:
                out[section] = {k: variant(v) for k, v in keys.items()}
        print(json.dumps({"type": "a{sa{sv}}", "data": [out]}))
    elif method == "CheckpointCreate":
        path = f"/org/freedesktop/NetworkManager/Checkpoint/{len(state['checkpoint_log']) + 1}"
        state["checkpoints"].append(path)
        state["checkpoint_log"].append({"path": path, "rollback": int(params[2]), "flags": int(params[3])})
        print(json.dumps({"type": "o", "data": [path]}))
    elif method in ("CheckpointDestroy", "CheckpointRollback"):
        if params[1] not in state["checkpoints"]:
            fail(f"Call failed: checkpoint {params[1]} does not exist")
        state["checkpoints"].remove(params[1])
        if method == "CheckpointRollback":
            state["active"] = []
    else:
        fail(f"fake busctl: unexpected {args}", 99)


# ---- wg, systemctl ---------------------------------------------------------------------------


def wg(state, args):
    if args == ["pubkey"]:
        private = sys.stdin.read().strip()
        print(base64.b64encode(hashlib.sha256(private.encode()).digest()).decode())
        return
    if args[:2] == ["show", IFNAME] and state["active"]:
        peer = "UGVlcktleUZvclRlc3RzT25seTAxMjM0NTY3ODkwYWI="
        print({"latest-handshakes": f"{peer}\t1792267000", "transfer": f"{peer}\t1024\t2048",
               "endpoints": f"{peer}\t44.32.0.1:44000"}[args[2]])
        return
    fail("Unable to access interface: No such device", 1)


def systemctl(state, args):
    units = state["units"]
    verb = args[0]
    if verb in ("is-enabled", "is-active"):
        u = units.get(args[1], {})
        key = "enabled" if verb == "is-enabled" else "active"
        value = u.get(key, False)
        print(("enabled" if value else "disabled") if verb == "is-enabled" else ("active" if value else "inactive"))
        sys.exit(0 if value else 1)
    if verb in ("enable", "disable"):
        name = args[-1]
        on = verb == "enable"
        units[name] = {"enabled": on, "active": on if "--now" in args else units.get(name, {}).get("active", False)}
        return
    fail(f"fake systemctl: unexpected {args}", 99)


def main():
    program, state_path, *args = sys.argv[1:]
    state = load(state_path)
    state["calls"].append([program, *args])
    try:
        {"nmcli": nmcli, "firewall-cmd": firewall_cmd, "busctl": busctl, "wg": wg, "systemctl": systemctl}[program](
            state, args)
    finally:
        save(state_path, state)


if __name__ == "__main__":
    main()
