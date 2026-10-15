"""Tuning: parsing the drivers' menu-support replies and live displays.

The settings replies are real transcripts (asl3-asterisk 3.10.5, drivers
loaded without a USB device); the display text follows the drivers' format
strings (tune_rxdisplay, tune_rxtx_status in chan_simpleusb.c).
"""

import pytest

from asl_web_ui import tuning

SIMPLEUSB_CSV = "500,500,0,0,0,0,1,0,4,2,0,0,500,0,0,0\n"
USBRADIO_CSV = "1,1,0,1,0,1,3,0,0,1,1,2,3,0,500,0.500000,500,500,500,200,0,0,0,12000\n"


def test_simpleusb_settings():
    v = tuning.parse_settings(tuning.SIMPLEUSB, SIMPLEUSB_CSV)
    assert v["rxmixerset"] == 500 and v["rxcdtype"] == 4 and v["rxsdtype"] == 2 and v["plfilter"] == 1
    shown = {s["name"]: s for s in tuning.present(tuning.SIMPLEUSB, v)}
    assert shown["plfilter"]["value"] is True
    assert shown["rxcdtype"]["value"] == 4 and {"value": 4, "label": "USB input, inverted"} in shown["rxcdtype"]["options"]


def test_usbradio_settings_derive_voice_levels():
    v = tuning.parse_settings(tuning.USBRADIO, USBRADIO_CSV)
    assert v["rxvoiceadj"] == 0.5 and v["rxdemod"] == 2
    assert v["rxvoice"] == 100  # flat audio: rxvoiceadj * 200
    assert v["txvoice"] == 500  # txmixa = composite carries the voice
    assert v["txslimsp"] == 12000


def test_settings_reply_must_be_complete():
    with pytest.raises(ValueError):
        tuning.parse_settings(tuning.SIMPLEUSB, "No such command 'susb tune menu-support 0+4'\n")
    with pytest.raises(ValueError):
        tuning.parse_settings(tuning.SIMPLEUSB, "500,500,0\n")


@pytest.mark.parametrize("name,value,arg", [
    ("rxmixerset", 650, "c650"), ("txmixaset", 0, "f0"), ("rxboost", True, "m1"), ("plfilter", False, "p0"),
    ("rxcdtype", 3, "r3"), ("rxondelay", 100, "t5"),
])
def test_commands(name, value, arg):
    assert tuning.command_for(tuning.SIMPLEUSB, name, value) == arg


@pytest.mark.parametrize("name,value", [
    ("rxmixerset", 1000), ("rxmixerset", "5"), ("rxboost", 1), ("rxcdtype", 1), ("nope", 1), ("rxondelay", 70000),
])
def test_invalid_commands(name, value):
    with pytest.raises(ValueError):
        tuning.command_for(tuning.SIMPLEUSB, name, value)


def test_device_list():
    assert tuning.device_list("1999,2701\n") == ["1999", "2701"]
    assert tuning.device_list("\n") == []


def meter_line(level):
    bar = "".join("=" if j < level else ">" if j == level else " " for j in range(75))
    return f"|{bar}|\r"


def test_meter_display():
    p = tuning.DisplayParser("meter")
    header = " " + " " * 75 + " \rRX VOICE DISPLAY:\n                                 v -- 3KHz        v -- 5KHz\n"
    readings = p.feed(header + "\r\r" + meter_line(30)[:40])
    assert readings == [{"keyed": False, "level": 0, "columns": 75}, {"keyed": False, "level": 0, "columns": 75}]
    readings = p.feed(meter_line(30)[40:] + meter_line(52))
    assert [r["level"] for r in readings] == [30, 52] and all(r["keyed"] for r in readings)


def test_status_display():
    p = tuning.DisplayParser("status")
    text = ("Receiver/Transmitter Status Display:\n  COS   | CTCSS  | COS   | PTT\n Input  | Input  | Out   | Out\n"
            " Keyed  | Clear  | Keyed | Clear\r Off    | Off    | Clear | Keyed\r")
    assert p.feed(text) == [
        {"cos": "keyed", "ctcss": "clear", "rx_keyed": True, "ptt": False},
        {"cos": "off", "ctcss": "off", "rx_keyed": False, "ptt": True},
    ]


def test_display_without_device():
    p = tuning.DisplayParser("meter")
    out = p.feed("Device 1999 is selected, the associated USB device string  was not found\n")
    assert out[0]["error"] == "no_device"


def test_driver_saves_do_not_ask_for_a_restart(tmp_path):
    import os
    import time
    from asl_web_ui import restart
    etc, state = tmp_path / "etc", tmp_path / "state"
    etc.mkdir()
    started = time.time() - 10
    (etc / "simpleusb.conf").write_text("saved by the driver\n")
    (etc / "rpt.conf").write_text("edited\n")
    restart.record_driver_save(str(state), str(etc / "simpleusb.conf"))
    assert restart.changed_since(str(etc), started, str(state)) == ["rpt.conf"]
    time.sleep(0.01)
    (etc / "simpleusb.conf").write_text("edited by hand afterwards\n")
    os.utime(etc / "simpleusb.conf")
    assert sorted(restart.changed_since(str(etc), started, str(state))) == ["rpt.conf", "simpleusb.conf"]
