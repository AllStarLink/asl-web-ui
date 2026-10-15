"""SA818: the same sa818 commands as sa818-menu, from the same sa818.conf.

The system's sa818-menu (asl3 package) runs with --apply under fakeroot
(it insists on root), next to a stand-in sa818 that records its arguments
(sa818-menu prefers the sa818 in its own directory). Nothing touches a
serial port.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from asl_web_ui_priv import sa818

MENU = Path("/usr/bin/sa818-menu")

CASES = {
    "simplex, no tone": {"CURRENT_FREQ_RX": "146.5200", "CURRENT_FREQ_TX": "146.5200"},
    "repeater offset, CTCSS, reverse burst": {
        "CURRENT_BAND": "VHF", "CURRENT_BANDWIDTH": "Narrow", "CURRENT_FREQ_RX": "146.9400",
        "CURRENT_FREQ_TX": "146.3400", "CURRENT_SQUELCH": "3", "CURRENT_VOLUME": "6", "CURRENT_TONE": "CTCSS",
        "CURRENT_CTCSS_RX": "100.0", "CURRENT_CTCSS_TX": "100.0", "CURRENT_TAIL_TONE": "Opened",
        "CURRENT_EMPHASIS": "Enabled", "CURRENT_FILTER_LOW_PASS": "Enabled"},
    "split CTCSS (transmit only)": {"CURRENT_FREQ_RX": "446.0000", "CURRENT_FREQ_TX": "446.0000", "CURRENT_BAND": "UHF",
                                    "CURRENT_TONE": "CTCSS", "CURRENT_CTCSS_TX": "88.5"},
    "CTCSS chosen without tones": {"CURRENT_FREQ_RX": "146.5200", "CURRENT_FREQ_TX": "146.5200", "CURRENT_TONE": "CTCSS"},
    "DCS split, port and speed": {
        "CURRENT_BAND": "UHF", "CURRENT_FREQ_RX": "445.5000", "CURRENT_FREQ_TX": "440.5000", "CURRENT_TONE": "DCS",
        "CURRENT_DCS_RX": "023N", "CURRENT_DCS_TX": "754I", "CURRENT_FILTER_HIGH_PASS": "Enabled",
        "CURRENT_PORT": "/dev/null", "CURRENT_SPEED": "19200"},
}


def _menu_commands(tmp_path: Path, conf_text: str) -> list[list[str]]:
    if not MENU.exists() or shutil.which("fakeroot") is None:
        pytest.skip("needs /usr/bin/sa818-menu (asl3 package) and fakeroot")
    shutil.copy(MENU, tmp_path / "sa818-menu")
    record = tmp_path / "calls"
    fake = tmp_path / "sa818"
    fake.write_text(f'#!/bin/sh\nfor a in "$@"; do printf "%s\\t" "$a"; done >> {record}\necho >> {record}\n')
    fake.chmod(0o755)
    conf = tmp_path / "sa818.conf"
    conf.write_text(conf_text)
    proc = subprocess.run(["fakeroot", str(tmp_path / "sa818-menu"), "--conf", str(conf), "--apply"],
                          capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "TERM": "dumb"})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return [line.rstrip("\t").split("\t") for line in record.read_text().splitlines()]


@pytest.mark.parametrize("case", CASES)
def test_same_sa818_commands(tmp_path, case):
    settings = sa818.check({**sa818.DEFAULTS, **CASES[case]})
    conf_text = sa818.render(settings)
    expected = _menu_commands(tmp_path, conf_text)
    assert sa818.tool_args(settings) == expected


def test_saved_file_reads_back(tmp_path):
    settings = sa818.check({**sa818.DEFAULTS, **CASES["repeater offset, CTCSS, reverse burst"]})
    assert sa818.parse(sa818.render(settings)) == settings
