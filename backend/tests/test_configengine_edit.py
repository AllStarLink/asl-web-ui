import difflib

from hypothesis import given, settings, strategies as st

from asl_web_ui.configengine.edit import (
    Section, Workspace, append_section, find_headers, module_state, remove_section, set_module,
)

RPT = """[general]

[node-main](!)
duplex = 2                          ; full duplex
hangtime = 2000

#tryinclude "custom/rpt.conf"

[1999](node-main)
rxchannel = SimpleUSB/1999      ; SimpleUSB
;startup_macro = *8132000

; Settings for another node
[2000](node-main)
duplex=1
"""


def ws_with(tmp_path, files: dict[str, str]) -> Workspace:
    for name, content in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return Workspace(str(tmp_path))


def changed_lines(before: str, after: str) -> list[str]:
    return [l for l in difflib.ndiff(before.splitlines(), after.splitlines()) if l[:1] in "+-"]


def new_text(ws: Workspace, name: str) -> str:
    return ws.text(name).to_text()


def test_override_goes_into_the_section_when_value_comes_from_a_template(tmp_path):
    ws = ws_with(tmp_path, {"rpt.conf": RPT})
    Section(ws, "rpt.conf", "1999").set("duplex", "1")
    out = new_text(ws, "rpt.conf")
    assert changed_lines(RPT, out) == ["+ duplex = 1"]
    assert out.index("duplex = 1") > out.index("rxchannel = SimpleUSB/1999")
    assert ws.model("rpt.conf").value("1999", "duplex") == "1"


def test_existing_line_is_changed_in_place_keeping_spacing_and_comment(tmp_path):
    ws = ws_with(tmp_path, {"rpt.conf": RPT})
    Section(ws, "rpt.conf", "1999").set("rxchannel", "Radio/1999")
    assert changed_lines(RPT, new_text(ws, "rpt.conf")) == [
        "- rxchannel = SimpleUSB/1999      ; SimpleUSB",
        "+ rxchannel = Radio/1999      ; SimpleUSB",
    ]


def test_new_lines_copy_the_neighbours_spacing(tmp_path):
    ws = ws_with(tmp_path, {"rpt.conf": RPT})
    Section(ws, "rpt.conf", "2000").set("hangtime", "100")
    assert "duplex=1\nhangtime=100\n" in new_text(ws, "rpt.conf")


def test_templates_are_never_edited(tmp_path):
    ws = ws_with(tmp_path, {"rpt.conf": RPT})
    Section(ws, "rpt.conf", "1999").set("hangtime", "100")
    out = new_text(ws, "rpt.conf")
    assert "hangtime = 2000" in out
    assert ws.model("rpt.conf").value("1999", "hangtime") == "100"


def test_last_line_in_effect_is_the_one_changed(tmp_path):
    rpt = RPT.replace("duplex=1\n", "duplex=1\nhangtime=5\nduplex=3\n")
    ws = ws_with(tmp_path, {"rpt.conf": rpt})
    sec = Section(ws, "rpt.conf", "2000")
    assert len(sec.redundant("duplex")) == 1
    sec.set("duplex", "4")
    assert changed_lines(rpt, new_text(ws, "rpt.conf")) == ["- duplex=3", "+ duplex=4"]


def test_value_set_in_an_included_file_is_changed_there(tmp_path):
    ws = ws_with(tmp_path, {
        "rpt.conf": "[1999]\n#include \"node.conf\"\n",
        "node.conf": "duplex = 2\n",
    })
    Section(ws, "rpt.conf", "1999").set("duplex", "0")
    assert new_text(ws, "rpt.conf") == "[1999]\n#include \"node.conf\"\n"
    assert new_text(ws, "node.conf") == "duplex = 0\n"


def test_plus_equals_gets_a_plain_override_after_it(tmp_path):
    ws = ws_with(tmp_path, {"rpt.conf": "[a]\nx = 1\nx += 2\n"})
    Section(ws, "rpt.conf", "a").set("x", "9")
    assert new_text(ws, "rpt.conf") == "[a]\nx = 1\nx += 2\nx = 9\n"
    assert ws.model("rpt.conf").value("a", "x") == "9"


def test_semicolons_in_values_are_escaped(tmp_path):
    ws = ws_with(tmp_path, {"rpt.conf": "[a]\n"})
    Section(ws, "rpt.conf", "a").set("idrecording", "a;b")
    assert "idrecording = a\\;b" in new_text(ws, "rpt.conf")
    assert ws.model("rpt.conf").value("a", "idrecording") == "a;b"


def test_unset_removes_own_lines_only(tmp_path):
    ws = ws_with(tmp_path, {"rpt.conf": RPT.replace("duplex=1\n", "duplex=1\nhangtime=5\n")})
    Section(ws, "rpt.conf", "2000").unset("hangtime")
    assert ws.model("rpt.conf").value("2000", "hangtime") == "2000"


def test_set_templates_and_rename_keep_comments(tmp_path):
    ws = ws_with(tmp_path, {"rpt.conf": "[t](!)\n[1999](t)   ; my node\nx = 1\n"})
    sec = Section(ws, "rpt.conf", "1999")
    sec.set_templates(["t", "u"])
    assert "[1999](t,u)   ; my node\n" in new_text(ws, "rpt.conf")
    sec.rename("2001")
    assert "[2001](t,u)   ; my node\n" in new_text(ws, "rpt.conf")


def test_append_section_at_end_with_blank_line(tmp_path):
    ws = ws_with(tmp_path, {"rpt.conf": "[a]\nx = 1"})
    text = ws.text("rpt.conf")
    append_section(text, "2001", ["node-main"], ["rxchannel = Local/pseudo"])
    assert text.to_text() == "[a]\nx = 1\n\n[2001](node-main)\nrxchannel = Local/pseudo\n"


def test_append_section_before_another(tmp_path):
    ws = ws_with(tmp_path, {"rpt.conf": "[a]\n\n[1999](n)\n"})
    text = ws.text("rpt.conf")
    append_section(text, "events-1999", ["events-main"], before=find_headers(text, "1999")[0])
    assert text.to_text() == "[a]\n\n[events-1999](events-main)\n\n[1999](n)\n"


def test_remove_section_keeps_the_next_sections_comments(tmp_path):
    ws = ws_with(tmp_path, {"rpt.conf": RPT})
    text = ws.text("rpt.conf")
    remove_section(text, find_headers(text, "1999")[0], keep_comment=lambda c: "1999" not in c)
    out = text.to_text()
    assert "[1999]" not in out and "rxchannel" not in out
    assert ";startup_macro = *8132000\n" in out
    assert "; Settings for another node\n[2000](node-main)" in out
    assert "\n\n\n" not in out


def test_remove_section_drops_comments_naming_the_node(tmp_path):
    ws = ws_with(tmp_path, {"rpt.conf": "[a]\n\n; node 1999 is the hotspot\n[1999]\nx = 1\n; 1999 notes\n\n[b]\n"})
    text = ws.text("rpt.conf")
    remove_section(text, find_headers(text, "1999")[0], keep_comment=lambda c: "1999" not in c)
    assert text.to_text() == "[a]\n\n[b]\n"


MODULES = """[modules]
autoload = no
load    = chan_simpleusb.so              ; SimpleUSB
noload  = chan_usbradio.so               ; USB Console
"""


def test_set_module_keeps_columns(tmp_path):
    ws = ws_with(tmp_path, {"modules.conf": MODULES})
    set_module(ws, "chan_simpleusb", False)
    set_module(ws, "chan_usbradio.so", True)
    out = new_text(ws, "modules.conf")
    assert "noload  = chan_simpleusb.so              ; SimpleUSB\n" in out
    assert "load    = chan_usbradio.so               ; USB Console\n" in out
    assert module_state(ws, "chan_usbradio") is True
    assert module_state(ws, "chan_simpleusb") is False


def test_set_module_adds_a_line_when_unlisted(tmp_path):
    ws = ws_with(tmp_path, {"modules.conf": MODULES})
    assert module_state(ws, "chan_voter") is None
    set_module(ws, "chan_voter", True)
    assert module_state(ws, "chan_voter") is True
    set_module(ws, "chan_usrp", False)  # nothing to do: not listed, not loaded
    assert "usrp" not in new_text(ws, "modules.conf")


def test_workspace_changes_only_lists_modified_files(tmp_path):
    ws = ws_with(tmp_path, {"rpt.conf": RPT, "iax.conf": "[general]\n"})
    ws.text("iax.conf")
    Section(ws, "rpt.conf", "1999").set("duplex", "1")
    changes = ws.changes()
    assert [c.path for c in changes] == [str(tmp_path / "rpt.conf")]
    assert changes[0].old == RPT.encode()


values = st.text(alphabet=st.characters(blacklist_categories=("Cs", "Cc")), max_size=30).map(str.strip)


@settings(max_examples=200)
@given(key=st.sampled_from(["duplex", "hangtime", "idrecording", "newkey"]), value=values)
def test_set_changes_one_line_and_asterisk_reads_the_value(tmp_path_factory, key, value):
    tmp = tmp_path_factory.mktemp("ws")
    ws = ws_with(tmp, {"rpt.conf": RPT})
    Section(ws, "rpt.conf", "1999").set(key, value)
    out = new_text(ws, "rpt.conf")
    diff = changed_lines(RPT, out)
    assert len([l for l in diff if l.startswith("+")]) <= 1
    assert len([l for l in diff if l.startswith("-")]) <= 1
    assert ws.model("rpt.conf").value("1999", key) == value
