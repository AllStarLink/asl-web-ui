"""The planner must leave Asterisk with the same configuration node-setup does.

Each test runs one node-setup operation (its own shell functions, on a copy
of the stock files) and the matching planner operation (on another copy),
then compares what Asterisk would load. Intended differences are asserted
explicitly and named after the design decisions (docs/design-notes.md).

    python3 -m pytest tests/parity
"""

import shutil

import pytest

from asl_web_ui.configengine.edit import Workspace
from asl_web_ui.nodes.planner import Planner
from parity_harness import Unavailable, diff, effective, run_node_setup, stock

try:
    from parity_harness import packages
    packages()
except Unavailable as exc:  # pragma: no cover
    pytest.skip(str(exc), allow_module_level=True)


class Pair:
    """Two identical configuration directories: one for node-setup, one for the planner."""

    def __init__(self, tmp_path, prepare: str | None = None):
        self.ns = stock(tmp_path / "ns" / "etc")
        if prepare:
            run_node_setup(self.ns, prepare)
        self.pl = tmp_path / "pl" / "etc"
        shutil.copytree(self.ns, self.pl, symlinks=True)

    def node_setup(self, script: str) -> None:
        run_node_setup(self.ns, script)

    def planner(self, fn) -> Planner:
        ws = Workspace(str(self.pl))
        planner = Planner(ws)
        fn(planner)
        for change in ws.changes():
            with open(change.path, "wb") as f:
                f.write(change.new)
        return planner

    def differences(self) -> list[str]:
        return diff(effective(self.ns), effective(self.pl))


# A public node set up the way node-setup's first run leaves it.
PUBLIC = """
CURRENT_NODE=1999; get_node_settings; NEW_NODE=2701; do_node_rename
CURRENT_NODE=2701; get_node_settings; NEW_PASSWORD=secret1; do_node_set_password
CURRENT_NODE=2701; get_node_settings; NEW_CALLSIGN=W1AW; do_node_set_callsign
"""


def node(n, call):
    return f"CURRENT_NODE={n}; get_node_settings; {call}"


def test_callsign(tmp_path):
    p = Pair(tmp_path)
    p.node_setup(node(1999, "NEW_CALLSIGN=W1AW; do_node_set_callsign"))
    p.planner(lambda pl: pl.set_callsign("1999", "w1aw"))
    assert p.differences() == []


@pytest.mark.parametrize("start", [None, 0, 1, 3])
@pytest.mark.parametrize("new,l2l", [(0, "no"), (0, "yes"), (1, None), (2, None), (3, None), (4, None)])
def test_duplex(tmp_path, start, new, l2l):
    prepare = None
    if start is not None:
        prepare = node(1999, f"NEW_DUPLEX={start}; NEW_LINKTOLINK=no; do_node_set_duplex")
    p = Pair(tmp_path, prepare)
    p.node_setup(node(1999, f"NEW_DUPLEX={new}; NEW_LINKTOLINK={l2l or '$CURRENT_LINKTOLINK'}; do_node_set_duplex"))
    p.planner(lambda pl: pl.set_duplex("1999", new, l2l))
    if start == 1 and new == 0:
        # D8: node-setup deletes the "hangtime = 100" it has just added.
        assert p.differences() == ["rpt.conf [1999] hangtime: node-setup='2000' planner='100'"]
    else:
        assert p.differences() == []


@pytest.mark.parametrize("enabled", [True, False])
def test_statpost(tmp_path, enabled):
    p = Pair(tmp_path, PUBLIC + node(2701, "NEW_STATPOST=Yes; do_node_set_statpost"))
    p.node_setup(node(2701, f"NEW_STATPOST={'Yes' if enabled else 'No'}; do_node_set_statpost"))
    p.planner(lambda pl: pl.set_statpost("2701", enabled))
    assert p.differences() == []


def test_password_change(tmp_path):
    p = Pair(tmp_path, PUBLIC)
    p.node_setup(node(2701, "NEW_PASSWORD=other22; do_node_set_password"))
    p.planner(lambda pl: pl.set_password("2701", "other22"))
    assert p.differences() == []


def test_password_on_private_node_removes_registration(tmp_path):
    p = Pair(tmp_path)
    p.node_setup(node(1999, "NEW_PASSWORD=whatever; do_node_set_password"))
    p.planner(lambda pl: pl.set_password("1999", "whatever"))
    assert p.differences() == []


@pytest.mark.parametrize("fn,iface", [("simpleusb", "SimpleUSB"), ("usbradio", "USBRadio"), ("voter", "Voter"),
                                      ("pseudo", "Pseudo"), ("usrp", "USRP")])
def test_interface(tmp_path, fn, iface):
    # Start from USBRadio so that switching to SimpleUSB is a change too.
    p = Pair(tmp_path, node(1999, "do_node_set_usbradio") if iface == "SimpleUSB" else None)
    p.node_setup(node(1999, f"do_node_set_{fn}"))
    p.planner(lambda pl: pl.set_interface("1999", iface))
    differences = p.differences()
    # D7: node-setup's noload pattern ("load =>") does not match the stock
    # modules.conf ("load    ="), so it never unloads a driver.
    differences = [d for d in differences if not d.startswith("modules [")]
    assert differences == []
    planned = effective(p.pl)["modules"]
    loaded = {m for m, state in planned.items() if state}
    expected = {"SimpleUSB": {"chan_simpleusb"}, "USBRadio": {"chan_usbradio"}, "Voter": {"chan_voter"},
                "Pseudo": set(), "USRP": {"chan_usrp"}}[iface]
    assert loaded == expected


@pytest.mark.parametrize("new", ["2702", "1001"])
def test_rename(tmp_path, new):
    p = Pair(tmp_path, PUBLIC)
    p.node_setup(node(2701, f"NEW_NODE={new}; do_node_rename"))
    p.planner(lambda pl: pl.rename("2701", new))
    assert p.differences() == []


def test_rename_stock_template_node(tmp_path):
    p = Pair(tmp_path)
    p.node_setup(node(1999, "NEW_NODE=2701; do_node_rename"))
    p.planner(lambda pl: pl.rename("1999", "2701"))
    assert p.differences() == []


ADD = """
CURRENT_DUPLEX=2; CURRENT_HANGTIME=2000; CURRENT_LINKTOLINK=no
answers=({answers})
do_node_add
"""


@pytest.mark.parametrize("number,password,preset,iface,duplex,statpost", [
    ("2702", "secret2", "  Half-duplex node (Hotspot) with telemetry tones", "SimpleUSB", 1, True),
    ("2703", "secret3", "  Full-duplex node (Repeater or Hotspot)", "USBRadio", 2, True),
    ("2704", "secret4", "  HUB node w/no radio interface", "Pseudo", 2, True),
    ("1002", None, "  Half-duplex node (Hotspot) with no telemetry tones", "SimpleUSB", 0, False),
])
def test_add(tmp_path, number, password, preset, iface, duplex, statpost):
    p = Pair(tmp_path, PUBLIC)
    answers = [number] + ([password] if password else []) + [preset]
    if iface != "Pseudo":
        answers.append({"SimpleUSB": "1", "USBRadio": "2"}[iface])
    answers += ["k1abc", "__no__", "__no__"]  # call sign; customize? no; tune now? no
    if duplex == 0:
        answers.insert(-2, "__no__")  # full or half duplex: half
    script = ADD.format(answers=" ".join(f"'{a}'" for a in answers))
    p.node_setup(script)
    p.planner(lambda pl: pl.add(number, password=password, interface=iface, duplex=duplex,
                                linktolink="no" if duplex == 0 else None, callsign="k1abc", statpost=statpost))
    differences = [d for d in p.differences() if not d.startswith("modules [")]  # D7
    assert differences == []


def test_remove(tmp_path):
    p = Pair(tmp_path, PUBLIC + ADD.format(answers="2702 secret2 '  Full-duplex node (Repeater or Hotspot)' 1 k1abc __no__ __no__"))
    p.node_setup('nodes=( $(grep "^\\[[0-9][0-9]*]" $CONFIG_DIR/rpt.conf | sed -e "s/^\\[//" -e "s/].*//") ); '
                 'answers=(2701); do_node_remove')
    p.planner(lambda pl: pl.remove("2701"))
    differences = [d for d in p.differences() if not d.startswith("modules [")]  # D7
    assert differences == []


def test_iax_port(tmp_path):
    p = Pair(tmp_path, PUBLIC)
    p.node_setup("answers=(4570); do_update_iax_bindport")
    p.planner(lambda pl: pl.set_iax_port(4570))
    assert p.differences() == []


def test_ami_secret(tmp_path):
    p = Pair(tmp_path)
    p.node_setup("answers=(NewSecret-12345); do_update_ami_secret")
    p.planner(lambda pl: pl.set_ami_secret("NewSecret-12345"))
    assert p.differences() == []


# ---- customizations -----------------------------------------------------------------

def _checklist_answer(p: Pair, names: list[str]) -> str:
    from asl_web_ui.nodes.customize import options
    opts = options(str(p.ns), "simpleusb")
    tags = [str(i) for i, o in enumerate(opts) if o.name in names]
    return "\n".join(tags)


def test_customization_device(tmp_path):
    p = Pair(tmp_path)
    p.node_setup(node(1999, "check_customization; do_update_customizations update shari-pixx"))
    p.planner(lambda pl: pl.customize("1999", ["shari-pixx"]))
    assert p.differences() == []
    view = effective(p.pl)
    assert view["rpt.conf"]["events-1999"]["templates"] == ["events-main", "events-shari-pixx"]
    assert view["rpt.conf"]["1999"]["values"]["events"] == "events-1999"
    assert view["simpleusb.conf"]["1999"]["templates"] == ["node-main", "shari-pixx"]
    # The stock 500s are commented out, so the device's values apply.
    assert view["simpleusb.conf"]["1999"]["values"]["rxmixerset"] == "650"


@pytest.mark.parametrize("names", [
    ["audio-archiving", "keyed-gpio4", "hd", "clip-led-gpio1"],
    ["hotspotradio-pihat", "keyed-gpio8"],
    ["allscan-uci"],
])
def test_customization_checklist(tmp_path, names):
    p = Pair(tmp_path)
    answer = _checklist_answer(p, names)
    p.node_setup(node(1999, f"check_customization; answers=($'{answer}'); do_update_customizations update"))
    p.planner(lambda pl: pl.customize("1999", names))
    assert p.differences() == []


def test_customization_removed_again(tmp_path):
    p = Pair(tmp_path, node(1999, "check_customization; do_update_customizations update shari-pixx")
             + "\n" + node(1999, "check_customization; answers=($'" + "11" + "'); do_update_customizations update"))
    p.node_setup(node(1999, "check_customization; answers=(''); do_update_customizations update"))
    p.planner(lambda pl: pl.customize("1999", []))
    assert p.differences() == []


def test_add_with_device_preset(tmp_path):
    p = Pair(tmp_path, PUBLIC)
    answers = ["2702", "secret2", "  *Kits4Hams* SHARI PiXX", "k1abc", "__no__", "__no__"]
    p.node_setup(ADD.format(answers=" ".join(f"'{a}'" for a in answers)))

    def plan(pl):
        pl.add("2702", password="secret2", interface="SimpleUSB", duplex=1, callsign="k1abc", statpost=True)
        pl.customize("2702", ["shari-pixx"])
    p.planner(plan)
    differences = [d for d in p.differences() if not d.startswith("modules [")]  # D7
    assert differences == []


@pytest.mark.parametrize("number,password", [("2701", "secret1"), ("1999", None), ("1005", None)])
def test_first_run(tmp_path, number, password):
    p = Pair(tmp_path)
    answers = [number] + ([password] if password else []) + ["  Half-duplex node (Hotspot) with telemetry tones",
                                                             "1", "w1aw", "__no__", "__no__"]
    p.node_setup("answers=(" + " ".join(f"'{a}'" for a in answers) + "); do_allstar_node_select_menu")
    p.planner(lambda pl: pl.first_run(number, password=password, interface="SimpleUSB", duplex=1, callsign="w1aw"))
    differences = [d for d in p.differences() if not d.startswith("modules [")]  # D7
    assert differences == []
    view = effective(p.pl)
    regs = view["rpt_http_registrations.conf"]["registrations"]["values"].get("register", [])
    mine = [r for r in regs if r.startswith(f"{number}:")]
    assert mine == ([f"{number}:{password}@register.allstarlink.org"] if password else [])
    assert view["rpt.conf"][number]["values"]["idrecording"] == "|iW1AW"


def test_first_run_loads_the_channel_driver(tmp_path):
    """The stock node already uses SimpleUSB; setting it up must still make
    sure chan_simpleusb is loaded (node-setup forces the interface step)."""
    p = Pair(tmp_path)
    for d in (p.ns, p.pl):
        text = (d / "modules.conf").read_text()
        (d / "modules.conf").write_text(text.replace("load    = chan_simpleusb.so", "noload  = chan_simpleusb.so"))
    answers = ["2701", "secret1", "  Half-duplex node (Hotspot) with telemetry tones", "1", "w1aw", "__no__", "__no__"]
    p.node_setup("answers=(" + " ".join(f"'{a}'" for a in answers) + "); do_allstar_node_select_menu")
    p.planner(lambda pl: pl.first_run("2701", password="secret1", interface="SimpleUSB", duplex=1, callsign="w1aw"))
    assert effective(p.ns)["modules"]["chan_simpleusb"] is True
    assert effective(p.pl)["modules"]["chan_simpleusb"] is True
