"""RTCM/voter nodes: voter.conf's clients and settings, as chan_voter reads them."""

from asl_web_ui.nodes import voter
from test_nodes_api import api  # noqa: F401 (fixture)

VOTER_CONF = """\
[general]
port = 1667                     ; UDP port
buflen = 480
password = secret_password      ; host password
utos = y

[1999]
Main = secret,transmit,master   ; the master timing source
plfilter = y
thresholds = 255,110=5

[1998]
NORTH = password_1,transmit
"""


def test_client_parsing_follows_chan_voter():
    c = voter.Client.parse("Main", "secret, transmit,MASTER,gpsid=garmin,prio=2,adpcm")
    assert (c.password, c.transmit, c.master, c.gpsid, c.prio, c.other) == ("secret", True, True, "garmin", 2,
                                                                            ["adpcm"])
    assert c.value() == "secret,transmit,master,gpsid=garmin,prio=2,adpcm"
    assert not voter.is_client("Transmitter") and not voter.is_client("plfilter")
    assert voter.is_client("Linger")  # chan_voter compares instance keys case-sensitively


async def _voter_node(a, api):  # noqa: F811
    (api.etc / "voter.conf").write_text(VOTER_CONF)
    plan, status_, _ = await a.change({"op": "interface", "node": "1999", "interface": "Voter"})
    assert status_ == 200, plan


async def test_status_hides_passwords(api):  # noqa: F811
    a = await api.make()
    await _voter_node(a, api)
    _, node = await a.get("nodes/1999")
    v = node["voter"]
    assert v["clients"] == [{"name": "Main", "transmit": True, "master": True, "nodeemp": False, "noplfilter": False,
                             "gpsid": None, "prio": None, "other": []}]
    assert v["settings"] == {"plfilter": "y", "thresholds": "255,110=5"}
    assert v["general"] == {"port": "1667", "utos": "y", "buflen": "480"} and v["host_password_set"]
    assert "secret" not in str(v)


async def test_clients_change_with_a_reload_not_a_restart(api):  # noqa: F811
    a = await api.make()
    await _voter_node(a, api)
    plan, status_, res = await a.change({"op": "voter", "node": "1999", "clients": [
        {"original": "Main", "name": "Main", "password": None, "transmit": True, "master": True},
        {"original": None, "name": "Hilltop", "password": "hill-1", "transmit": False, "prio": 1},
    ], "settings": {"plfilter": "", "linger": "8"}, "general": {}})
    assert status_ == 200 and res["restart"] is False, (plan, res)
    text = (api.etc / "voter.conf").read_text()
    assert "Main = secret,transmit,master   ; the master timing source\n" in text  # untouched
    assert "Hilltop = hill-1,prio=1\n" in text and "linger = 8\n" in text and "plfilter = y" not in text
    assert "module reload chan_voter.so" in api.cli.commands

    # Renaming keeps the password; removing drops the line.
    await a.change({"op": "voter", "node": "1999", "clients": [
        {"original": "Hilltop", "name": "Ridge", "transmit": True}], "settings": {}, "general": {}})
    text = (api.etc / "voter.conf").read_text()
    assert "Ridge = hill-1,transmit\n" in text and "Main" not in text and "Hilltop" not in text


async def test_port_change_needs_restart(api):  # noqa: F811
    a = await api.make()
    await _voter_node(a, api)
    plan, _, res = await a.change({"op": "voter", "node": "1999", "clients": [{"original": "Main", "name": "Main",
                                   "transmit": True, "master": True}], "settings": {}, "general": {"port": "1668"}})
    assert res["restart"] is True and any("port is read when Asterisk starts" in n["text"] for n in plan["notes"])


async def test_voter_rules(api):  # noqa: F811
    a = await api.make()
    await _voter_node(a, api)

    async def refused(clients, **extra):
        status_, body = await a.post("nodes/plan", {"op": "voter", "node": "1999", "clients": clients,
                                                    "settings": {}, "general": {}, **extra})
        assert status_ in (400, 409), body
        return body["message"]

    main = {"original": "Main", "name": "Main", "transmit": True, "master": True}
    assert "same password" in await refused([main, {"name": "B", "password": "password_1"}])
    assert "master timing source" in await refused([main, {"name": "B", "password": "x1", "master": True}])
    assert "as a setting" in await refused([{"name": "Master2", "password": "x2"}])
    assert "two clients named" in await refused([main, {"name": "main", "password": "x3"}])
    assert "password" in await refused([{"name": "New"}])
    status_, body = await a.post("nodes/plan", {"op": "voter", "node": "1999", "clients": [main],
                                                "settings": {"txtoctype": "loud"}, "general": {}})
    assert status_ == 400 and body["field"] == "txtoctype"


async def test_only_voter_nodes(api):  # noqa: F811
    a = await api.make()
    status_, body = await a.post("nodes/plan", {"op": "voter", "node": "1999", "clients": [], "settings": {},
                                                "general": {}})
    assert status_ == 409 and "RTCM" in body["message"]
