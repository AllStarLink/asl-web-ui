"""A node's ID, courtesy tones, tone definitions and Morse code (nodes.telemetry)."""

import pytest

from asl_web_ui.configengine.edit import Workspace
from asl_web_ui.nodes import telemetry
from asl_web_ui.nodes.planner import Planner, PlanError

RPT = """[node-main](!)
idrecording = |iNOTSET
idtime = 540000
unlinkedct = ct2
remotect = ct3
linkunkeyct = ct8
morse = morse
telemetry = telemetry

[telemetry-main](!)
ct2 = |t(660,880,150,2048)
ct3 = |t(440,0,150,4096)
ct8 = |t(700,1100,150,2048)
patchup = rpt/callproceeding

[telemetry](telemetry-main)

[morse-main](!)
speed = 20
idfrequency = 1065

[morse](morse-main)

[1999](node-main)
rxchannel = Local/pseudo

[2000](node-main)
rxchannel = Local/pseudo
"""


@pytest.fixture
def etc(tmp_path):
    (tmp_path / "rpt.conf").write_text(RPT)
    return tmp_path


def plan(etc, number="1999", **changes):
    ws = Workspace(str(etc))
    planner = Planner(ws)
    planner.set_telemetry(number, **changes)
    return ws, planner


def rpt_text(ws):
    return ws.text("rpt.conf").to_bytes().decode()


def test_status_reads_the_node_and_its_stanzas(etc):
    st = telemetry.status(Workspace(str(etc)), "1999")
    assert st["node"]["unlinkedct"] == {"value": "ct2", "own": False, "fallback": "ct2", "from": "node-main"}
    assert st["node"]["politeid"] == {"value": "30000", "own": False, "fallback": "30000", "from": None}
    assert st["node"]["idtalkover"]["value"] is None
    assert st["telemetry"]["section"] == "telemetry" and st["telemetry"]["users"] == ["1999", "2000"]
    assert st["telemetry"]["in_place"] is False
    tones = {t["name"]: t for t in st["telemetry"]["tones"]}
    assert tones["ct2"]["value"] == "|t(660,880,150,2048)" and tones["ct2"]["from"] == "telemetry-main"
    # Not in the stanza: app_rpt's built-in tone, or nothing.
    assert tones["ct1"]["value"].startswith("|t(350,0,100,3072)") and tones["ct1"]["from"] is None
    assert tones["ct9"]["value"] is None
    assert st["morse"]["settings"]["idfrequency"]["value"] == "1065"
    assert st["morse"]["settings"]["amplitude"] == {"value": "4096", "own": False, "fallback": "4096", "from": None}


def test_changing_a_tone_gives_the_node_its_own_copy(etc):
    (etc / "rpt.conf").write_text(RPT.replace("[telemetry](telemetry-main)\n",
                                              "[telemetry](telemetry-main)\nct4 = |t(550,0,150,2048)\n"))
    ws, planner = plan(etc, tones={"ct2": "|t(500, 0, 100, 2048)", "ct10": "|mOK"})
    text = rpt_text(ws)
    assert ("[telemetry-1999](telemetry-main)\nct4 = |t(550,0,150,2048)\nct2 = |t(500,0,100,2048)\nct10 = |mOK\n\n"
            "[1999](node-main)\nrxchannel = Local/pseudo\ntelemetry = telemetry-1999\n") in text
    assert planner.effects.restart is True
    assert "node 2000 keeps [telemetry]" in planner.effects.notes[0].text
    # Node 2000 keeps the shared stanza; the copy is node 1999's, so the next change goes into it.
    rpt = ws.model("rpt.conf")
    assert rpt.get("2000").value("telemetry") == "telemetry"
    assert telemetry.editable_in_place(rpt, "1999", "telemetry")
    Planner(ws).set_telemetry("1999", tones={"ct2": None})
    assert "[telemetry-1999](telemetry-main)\nct4 = |t(550,0,150,2048)\nct10 = |mOK\n\n" in rpt_text(ws)
    assert ws.model("rpt.conf").value("telemetry-1999", "ct2") == "|t(660,880,150,2048)"


def test_a_stanza_only_this_node_uses_is_changed_in_place(etc):
    (etc / "rpt.conf").write_text(RPT.replace("[1999](node-main)\n", "[tones_1999](telemetry-main)\n\n"
                                              "[1999](node-main)\ntelemetry = tones_1999\n"))
    ws, planner = plan(etc, tones={"ct3": ""})
    assert "[tones_1999](telemetry-main)\nct3 =\n" in rpt_text(ws) and not planner.effects.notes


def test_the_copy_name_must_be_free(etc):
    (etc / "rpt.conf").write_text(RPT + "\n[telemetry-1999](telemetry-main)\n")
    with pytest.raises(PlanError, match=r"\[telemetry-1999\] already exists"):
        plan(etc, tones={"ct2": "|t(1,0,10,10)"})


def test_node_settings(etc):
    ws, planner = plan(etc, settings={"idrecording": "|mW1AW/R", "idtalkover": "|iW1AW", "idtime": "600000",
                                      "unlinkedct": "", "nounkeyct": True, "politeid": None},
                       per_link={"2001": "ct3", "2002": ""})
    text = rpt_text(ws)
    assert ("rxchannel = Local/pseudo\nidrecording = |mW1AW/R\nidtalkover = |iW1AW\nidtime = 600000\nunlinkedct =\n"
            "nounkeyct = 1\nlinkunkeyct_2001 = ct3\nlinkunkeyct_2002 =\n\n[2000]") in text
    assert "[telemetry-1999]" not in text
    st = telemetry.status(ws, "1999")
    assert st["per_link"]["2001"]["value"] == "ct3" and st["node"]["unlinkedct"]["value"] == ""
    # None takes the node's own line away again: the template's value applies.
    Planner(ws).set_telemetry("1999", settings={"unlinkedct": None}, per_link={"2002": None})
    assert telemetry.status(ws, "1999")["node"]["unlinkedct"]["value"] == "ct2"
    assert "2002" not in telemetry.status(ws, "1999")["per_link"]


def test_unchanged_is_not_a_change(etc):
    ws, planner = plan(etc, settings={"unlinkedct": None, "idtalkover": None}, tones={"ct2": None},
                       morse={"speed": None})
    assert ws.changes() == [] and planner.effects.restart is False


def test_morse(etc):
    ws, planner = plan(etc, morse={"speed": "25", "idamplitude": "1024"})
    assert "[morse-1999](morse-main)\nspeed = 25\nidamplitude = 1024\n" in rpt_text(ws)
    assert "morse = morse-1999" in rpt_text(ws)
    with pytest.raises(PlanError, match="from 5 to 35"):
        plan(etc, morse={"speed": "50"})


def test_courtesy_tones_must_exist(etc):
    with pytest.raises(PlanError, match="names the tone ct42") as exc:
        plan(etc, settings={"remotect": "ct42"})
    assert exc.value.field == "remotect"
    # Built in, or defined in the same change.
    plan(etc, settings={"remotect": "ct5"})
    plan(etc, settings={"remotect": "ct42"}, tones={"ct42": "|t(1000,0,50,2048)"})
    # Removing a tone a courtesy tone uses.
    (etc / "rpt.conf").write_text(RPT.replace("[telemetry](telemetry-main)\n",
                                              "[telemetry](telemetry-main)\nbeep = |t(1000,0,50,2048)\n")
                                  .replace("rxchannel = Local/pseudo\n\n[2000]", "rxchannel = Local/pseudo\n"
                                           "linkunkeyct_2001 = beep\n\n[2000]"))
    with pytest.raises(PlanError, match="linkunkeyct_2001 names the tone beep"):
        plan(etc, tones={"beep": None})


def test_no_id_is_a_warning(etc):
    _, planner = plan(etc, settings={"idrecording": ""})
    assert [n.severity for n in planner.effects.notes] == ["warning"]


@pytest.mark.parametrize("value, ok", [
    ("|t(350,440,500,2048)(0,0,100,0)", "|t(350,440,500,2048)(0,0,100,0)"),
    ("|T (350, 440, 500, 2048)", "|T(350,440,500,2048)"),
    ("|mCQ DE W1AW", "|mCQ DE W1AW"),
    ("|i W1AW/R ", "|iW1AW/R"),
    ("rpt/callproceeding", "rpt/callproceeding"),
    ("/var/lib/asterisk/sounds/custom/id", "/var/lib/asterisk/sounds/custom/id"),
    ("", ""),
])
def test_values(value, ok):
    assert telemetry.check_value(value, "x", "x") == ok


@pytest.mark.parametrize("value", ["|t(350,440,500)", "|t(5000,0,100,2048)", "|t(350,0,0,2048)",
                                   "|t(350,0,100,40000)", "|t350,0,100,2048", "|x", "|mW1AW;", "my file.wav",
                                   "|m"])
def test_bad_values(value):
    with pytest.raises(telemetry.TelemetryError):
        telemetry.check_value(value, "x", "x")


def test_other_checks(etc):
    for changes, field in [({"settings": {"idtime": "1000"}}, "idtime"), ({"settings": {"politeid": "x"}}, "politeid"),
                           ({"settings": {"nounkeyct": "yes"}}, "nounkeyct"), ({"settings": {"bogus": "1"}}, "bogus"),
                           ({"tones": {"bad name": "|mX"}}, "tones"), ({"per_link": {"2001": "no such"}}, "per_link")]:
        with pytest.raises(PlanError) as exc:
            plan(etc, **changes)
        assert exc.value.field == field, changes
    plan(etc, settings={"idtime": "0"})  # no timed ID
