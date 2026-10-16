"""Allmon3 management: the file checks and edits, and the API.

The privileged commands run in-process on a temporary root, as in the
backup tests, with /etc/allmon3 laid out like Allmon3 1.11's package.
"""

import argon2
import pytest

from asl_web_ui import allmon3conf as conf
from test_backups_api import cloud, env  # noqa: F401 (fixtures)

WEB_INI = """\
[web]
; the title
CONFIG_HEADER_TITLE = Allmon3 Monitoring Dashboard
CONFIG_HEADER_LOGO = ""
HOME_BUTTON_URL = index.html

[syscmds]
rpt stats @ = Show Node Status
database put allowlist/@ % &quot;Reason&quot; = Add Allowlist Entry

[node-overrides]

[voter-titles]
"""

RESTRICTIONS = """\
# This file restricts logged-in users
#   user1 | 1999

"""


# ---- checks and edits ------------------------------------------------------------------


def test_stock_files_have_no_findings():
    assert conf.check("web.ini", WEB_INI) == []
    assert conf.check("user-restrictions", RESTRICTIONS) == []
    assert conf.check("allmon3.ini", "; comment\n[1999]\nhost=127.0.0.1\nuser=admin\npass=x\n") == []


def test_node_problems_are_found_by_line():
    text = "[1999]\nhost=h\nuser=admin\npass=a%b\nport=x\n\n[hub]\nhost=h\n[2000]\nhost=h\nhost=i\n"
    found = conf.check("allmon3.ini", text)
    assert found == [conf.finding(11, "host appears twice in [2000]; Allmon3 cannot load the file.")]
    found = conf.check("allmon3.ini", text.replace("host=i\n", "user=u\n"))
    messages = {(f["line"], f["message"].split(";")[0].split(":")[0]) for f in found}
    assert (4, "pass in [1999]") in messages
    assert (5, "port must be a number.") in messages
    assert (7, "[hub] is not a node number") in messages
    assert (9, "Node 2000 has no pass") in messages


def test_web_ini_needs_its_sections():
    found = conf.check("web.ini", "[web]\nHTTP_PORT = abc\n")
    assert sum("is missing" in f["message"] for f in found) == 3
    assert any(f["line"] == 2 and "HTTP_PORT" in f["message"] for f in found)


def test_menu_checks():
    assert conf.check("menu.ini", "[ Hubs ]\ntype = menu\nW8WKY = 43211\n") == []
    assert "Remove menu.ini" in conf.check("menu.ini", "; nothing\n")[0]["message"]
    found = conf.check("menu.ini", '[ A ]\ntype = list\nx = "y"\n[ B ]\ntype = single\n[ C ]\n')
    assert [(f["line"], f["severity"]) for f in found] == [(1, "warning"), (3, "error"), (4, "warning"),
                                                             (6, "error")]


def test_restriction_line_without_bar_stops_allmon3():
    found = conf.check("user-restrictions", "# ok\nalice 1999\n  # indented\nbob | 1999, x\n")
    assert [(f["line"], f["severity"]) for f in found] == [(2, "error"), (3, "error"), (4, "warning")]


def test_set_values_keeps_everything_else():
    text = "; top\n[1999]\nhost = 10.0.0.1\n; keep me\nuser=admin\npass=old\n\n[2000]\nhost=x\n"
    out = conf.set_values(text, "1999", {"host": "127.0.0.1", "pass": None, "port": "5038"})
    assert out == "; top\n[1999]\nhost = 127.0.0.1\n; keep me\nuser=admin\nport=5038\n\n[2000]\nhost=x\n"
    out = conf.set_values("[a]\nx=1", "b", {"y": "2"})
    assert out == "[a]\nx=1\n\n[b]\ny=2\n"
    assert conf.remove_section(text, "1999") == "; top\n[2000]\nhost=x\n"


def test_set_restriction():
    out = conf.set_restriction(RESTRICTIONS, "alice", ["1999", "2000"])
    assert out == RESTRICTIONS + "alice | 1999,2000\n"
    assert conf.set_restriction(out, "alice", ["2001"]) == RESTRICTIONS + "alice | 2001\n"
    assert conf.set_restriction(out, "alice", None) == RESTRICTIONS
    assert conf.restrictions(out) == {"alice": ["1999", "2000"]}


# ---- the API ---------------------------------------------------------------------------


@pytest.fixture
def allmon3(env):  # noqa: F811
    d = env.root / "etc" / "allmon3"
    (d / "web.ini").write_text(WEB_INI)
    (d / "user-restrictions").write_text(RESTRICTIONS)
    (d / "users").write_text("user|pass\r\n")
    (d / "custom.css").write_text("")
    systemctl = env.log.parent / "systemctl"
    systemctl.write_text(f"#!/bin/sh\necho \"$@\" >> {env.log}\n"
                         "[ \"$1\" = show ] && echo ActiveState=active\nexit 0\n")
    env.dir = d
    return env


async def test_overview(allmon3):
    a = await allmon3.make()
    status_, body = await a.call("GET", "allmon3")
    assert status_ == 200 and body["installed"] and body["service"]["active"] == "active"
    assert body["nodes"] == ["1999"]
    menu = next(f for f in body["files"] if f["name"] == "menu.ini")
    assert menu == {**menu, "exists": False, "optional": True}
    status_, body = await a.call("POST", "allmon3/service/restart")
    assert status_ == 200 and body["active"] == "active" and "restart allmon3.service" in allmon3.log.read_text()
    status_, _ = await a.call("POST", "allmon3/service/enable")
    assert status_ == 404


async def test_nodes_list_and_change(allmon3):
    a = await allmon3.make()
    _, body = await a.call("GET", "allmon3/nodes")
    node = body["nodes"][0]
    assert node["node"] == "1999" and node["pass_set"] and node["pass_matches_ami"] and "pass" not in node
    assert body["local"] == [{"number": "1999", "listed": True}] and body["ami_users"] == ["admin"]

    status_, plan = await a.call("POST", "allmon3/nodes/plan", {
        "op": "set", "node": "1999", "host": "127.0.0.1", "user": "admin", "pass_mode": "value",
        "pass": "new%secret", "pollinterval": "0.5"})
    assert status_ == 200, plan
    assert "+pass=••••••••" in plan["diff"] and "new" not in plan["diff"] and "+pollinterval=0.5" in plan["diff"]
    status_, res = await a.call("POST", f"allmon3/plans/{plan['id']}/apply", {})
    assert status_ == 200 and res["warnings"] == []
    text = (allmon3.dir / "allmon3.ini").read_text()
    assert "pass=new%%secret" in text and conf.check("allmon3.ini", text) == []
    assert "restart allmon3.service" in allmon3.log.read_text()
    status_, _ = await a.call("POST", f"allmon3/plans/{plan['id']}/apply", {})
    assert status_ == 404  # a plan is used once

    _, plan = await a.call("POST", "allmon3/nodes/plan", {"op": "set", "node": "2000", "original": "1999",
                                                          "host": "127.0.0.1", "user": "admin", "pass_mode": "ami"})
    assert "-[1999]" in plan["diff"] and "+[2000]" in plan["diff"]
    status_, body = await a.call("POST", "allmon3/nodes/plan", {"op": "set", "node": "2001", "host": "h",
                                                                "user": "admin"})
    assert status_ == 400 and body["field"] == "pass"


async def test_add_local_nodes_and_remove(allmon3):
    (allmon3.dir / "allmon3.ini").write_text("; comments stay\n")
    a = await allmon3.make()
    _, plan = await a.call("POST", "allmon3/nodes/plan", {"op": "add_local"})
    await a.call("POST", f"allmon3/plans/{plan['id']}/apply", {})
    text = (allmon3.dir / "allmon3.ini").read_text()
    assert text == "; comments stay\n\n[1999]\nhost=127.0.0.1\nport=5038\nuser=admin\npass=make4An1ce-secret\n"
    status_, body = await a.call("POST", "allmon3/nodes/plan", {"op": "add_local"})
    assert status_ == 409
    _, plan = await a.call("POST", "allmon3/nodes/plan", {"op": "remove", "node": "1999"})
    status_, body = await a.call("POST", f"allmon3/plans/{plan['id']}/apply", {})
    assert status_ == 200 and (allmon3.dir / "allmon3.ini").read_text() == "; comments stay\n\n"


async def test_files_errors_need_confirmation_and_conflicts_are_refused(allmon3):
    a = await allmon3.make()
    _, f = await a.call("GET", "allmon3/files/web.ini")
    assert f["findings"] == [] and f["content"] == WEB_INI
    _, plan = await a.call("POST", "allmon3/files/web.ini/plan", {"content": "[web]\n", "hash": f["hash"]})
    assert len(plan["findings"]) == 3
    status_, body = await a.call("POST", f"allmon3/plans/{plan['id']}/apply", {})
    assert status_ == 409 and body["error"] == "has_errors"
    (allmon3.dir / "web.ini").write_text(WEB_INI + "\n")
    status_, body = await a.call("POST", f"allmon3/plans/{plan['id']}/apply", {"confirm_errors": True})
    assert status_ == 409 and body["error"] == "conflict"
    status_, _ = await a.call("GET", "allmon3/files/users")
    assert status_ == 404  # hashes never leave the helper


async def test_menu_is_created_and_removed(allmon3):
    a = await allmon3.make()
    _, f = await a.call("GET", "allmon3/files/menu.ini")
    assert not f["exists"] and f["hash"] == "absent"
    _, plan = await a.call("POST", "allmon3/files/menu.ini/plan",
                           {"content": "[ Hubs ]\ntype = menu\nHub = 1999\n", "hash": "absent"})
    assert plan["created"] and plan["findings"] == []
    await a.call("POST", f"allmon3/plans/{plan['id']}/apply", {})
    menu = allmon3.dir / "menu.ini"
    assert menu.read_text().startswith("[ Hubs ]")
    _, f = await a.call("GET", "allmon3/files/menu.ini")
    status_, _ = await a.call("DELETE", "allmon3/files/menu.ini?hash=wrong")
    assert status_ == 409 and menu.exists()
    status_, _ = await a.call("DELETE", f"allmon3/files/menu.ini?hash={f['hash']}")
    assert status_ == 200 and not menu.exists()
    status_, _ = await a.call("DELETE", f"allmon3/files/web.ini?hash={f['hash']}")
    assert status_ == 400


async def test_web_settings(allmon3):
    a = await allmon3.make()
    _, body = await a.call("GET", "allmon3/web")
    assert body["values"]["CONFIG_HEADER_TITLE"] == "Allmon3 Monitoring Dashboard"
    assert body["values"]["CONFIG_HEADER_LOGO"] == ""
    _, plan = await a.call("POST", "allmon3/web/plan", {"values": {"CONFIG_HEADER_TITLE": "N0CALL Hub 50%",
                                                                   "CONFIG_HEADER_LOGO": "",
                                                                   "CONFIG_MENU_SINGLE_TARGET": "_blank"}})
    await a.call("POST", f"allmon3/plans/{plan['id']}/apply", {})
    text = (allmon3.dir / "web.ini").read_text()
    assert "CONFIG_HEADER_TITLE = N0CALL Hub 50%%\n" in text and 'CONFIG_HEADER_LOGO = ""\n' in text
    assert text.index("CONFIG_MENU_SINGLE_TARGET=_blank") < text.index("[syscmds]")
    assert conf.check("web.ini", text) == []
    status_, _ = await a.call("POST", "allmon3/web/plan", {"values": {"EVIL": "x"}})
    assert status_ == 400


async def test_users_and_restrictions(allmon3):
    a = await allmon3.make()
    status_, body = await a.call("POST", "allmon3/users", {"user": "alice", "password": "short"})
    assert status_ == 400 and body["field"] == "password"
    status_, body = await a.call("POST", "allmon3/users", {"user": "user", "password": "long-enough"})
    assert status_ == 400 and body["field"] == "user"
    status_, body = await a.call("POST", "allmon3/users", {"user": "alice", "password": "correct horse"})
    assert status_ == 200 and body["created"]
    users = (allmon3.dir / "users").read_bytes().decode()
    assert users.startswith("user|pass\r\nalice|$argon2id$")
    argon2.PasswordHasher().verify(users.split("|")[2].strip(), "correct horse")

    status_, _ = await a.call("PUT", "allmon3/users/alice/nodes", {"nodes": ["1999"]})
    assert status_ == 200 and (allmon3.dir / "user-restrictions").read_text().endswith("alice | 1999\n")
    _, body = await a.call("GET", "allmon3/users")
    assert body == {"users": [{"name": "alice", "nodes": ["1999"]}], "orphan_restrictions": [], "nodes": ["1999"]}

    status_, body = await (await allmon3.make(recent_auth=0)).call("DELETE", "allmon3/users/alice")
    assert status_ == 403 and body["error"] == "reauth_required"
    status_, _ = await a.call("DELETE", "allmon3/users/alice")
    assert status_ == 200
    assert (allmon3.dir / "users").read_bytes() == b"user|pass\r\n"
    assert (allmon3.dir / "user-restrictions").read_text() == RESTRICTIONS
    status_, _ = await a.call("DELETE", "allmon3/users/alice")
    assert status_ == 404


async def test_other_files_are_read_only_and_listed(allmon3):
    (allmon3.dir / "nginx.conf").write_text("location /allmon3 {}\n")
    a = await allmon3.make()
    status_, f = await a.call("GET", "allmon3/files/nginx.conf")
    assert status_ == 200 and f["content"].startswith("location") and not f["writable"] and f["findings"] == []
    status_, body = await a.call("POST", "allmon3/files/nginx.conf/plan", {"content": "x", "hash": f["hash"]})
    assert status_ == 403 and body["error"] == "read_only"
    status_, _ = await a.call("GET", "allmon3/files/missing.ini")
    assert status_ == 404
    status_, body = await a.call("GET", "config/system-files")
    names = {e["path"]: e for e in body["allmon3"]}
    assert names["/etc/allmon3/web.ini"]["writable"] and not names["/etc/allmon3/nginx.conf"]["writable"]
    assert body["sa818"] is None
