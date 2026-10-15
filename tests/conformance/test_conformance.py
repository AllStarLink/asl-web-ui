"""The config engine must read files exactly as ASL's Asterisk does.

Runs only where the ASL packages are installed (skipped otherwise):
    python3 -m pytest tests/conformance
"""

import os
import shutil
from pathlib import Path

import pytest

from asl_web_ui.configengine.model import load
from harness import PrivateAsterisk

pytestmark = pytest.mark.skipif(not os.path.exists("/usr/sbin/asterisk"), reason="Asterisk is not installed")


@pytest.fixture(scope="module")
def asterisk(tmp_path_factory):
    ast = PrivateAsterisk(tmp_path_factory.mktemp("asterisk"))
    ast.start()
    yield ast
    ast.stop()


def compare(asterisk, files, main="test.conf"):
    etc = asterisk.dir / "etc"
    model = load(main, config_dir=str(etc), reader=lambda p: (files[os.path.relpath(p, etc)]).encode()
                 if os.path.relpath(p, etc) in files else (_ for _ in ()).throw(FileNotFoundError(p)),
                 glob=lambda pat: sorted(str(etc / k) for k in files if Path(etc / k).match(pat)))
    pairs = sorted({(c.name, v.key) for c in model.categories for v in c.vars if model.get(c.name) is c})
    got, rejected, log = asterisk.query(files, main, pairs)
    assert model.rejected == rejected, f"model rejected={model.rejected} errors={model.errors}\n{log[-2000:]}"
    if not rejected:
        # Asterisk prints an empty value and a missing one the same way.
        expected = {(s, k): model.value(s, k) or None for s, k in pairs}
        assert got == expected
    return model


CASES = {
    "template override and duplicate keys (last wins)":
        "[t](!)\nrx = A\nduplex = 1\n[1999](t)\nrx = B\nduplex = 2\nduplex = 3\n",
    "template copied when the header is read":
        "[t](!)\na = 1\n[n](t)\n[t](+)\nb = 2\n",
    "multiple templates":
        "[a](!)\nx = 1\ny = 1\n[b](!)\ny = 2\nz = 2\n[n](a,b)\nz = 3\n",
    "append operator":
        "[s]\nallow = ulaw\nallow += gsm\n",
    "comments, escapes and block comments":
        "[s]\na = 1 ; note\nb = x\\;y\nc = 1 ;-- start\nd = 2\nend --; e = 5\nf = 6\n",
    "object operator and spacing":
        "[s]\nregister=>1999:pw@host\n   key   =   spaced value   \n",
    "line without equals is ignored":
        "[s]\nno equals here\na = 1\n",
    "unknown directive is ignored":
        "[s]\n#bogus thing\na = 1\n",
    "stray block end hides the rest of the file":
        "[s]\na = 1\nb = 2 --;\nc = 3\n[t]\nd = 4\n",
    "duplicate sections: first one is used":
        "[s]\na = 1\n[s]\na = 2\nb = 3\n",
    "undefined template rejects the file":
        "[n](missing)\na = 1\n",
    "template defined later rejects the file":
        "[n](later)\na = 1\n[later](!)\nb = 2\n",
    "missing closing bracket rejects the file":
        "[s]\na = 1\n[broken\nb = 2\n",
    "variable before any section rejects the file":
        "a = 1\n[s]\nb = 2\n",
    "addition to a missing section rejects the file":
        "[s]\na = 1\n[nope](+)\nb = 2\n",
}


@pytest.mark.parametrize("name", list(CASES))
def test_single_file_cases(asterisk, name):
    compare(asterisk, {"test.conf": CASES[name]})


def test_includes_and_current_section(asterisk):
    model = compare(asterisk, {
        "test.conf": "[general]\n#include conformance-more.conf\nafter = yes\n#tryinclude conformance-custom/*.conf\n",
        "conformance-more.conf": "starts_in_includer = 1\n[fromfile]\nz = 9\n",
        "conformance-custom/a.conf": "[ca](!)\nx = 1\n",
    })
    assert model.value("general", "after") == "yes"


def test_missing_include_rejects(asterisk):
    compare(asterisk, {"test.conf": "[s]\na = 1\n#include conformance-nope.conf\n"})


def test_missing_tryinclude_is_fine(asterisk):
    compare(asterisk, {"test.conf": "[s]\na = 1\n#tryinclude conformance-nope/*.conf\n"})


STOCK = Path("/etc/asterisk")


@pytest.mark.parametrize("name", ["rpt.conf", "simpleusb.conf", "usbradio.conf", "iax.conf", "modules.conf", "voter.conf"])
def test_stock_files_from_the_installed_package(asterisk, name):
    path = STOCK / name
    if not path.exists():
        pytest.skip(f"{path} not present")
    files = {"test.conf": path.read_text(errors="surrogateescape")}
    # Bring along what the file includes, so both sides see the same tree.
    for inc in STOCK.glob("custom/**/*.conf"):
        files[str(inc.relative_to(STOCK))] = inc.read_text(errors="surrogateescape")
    compare(asterisk, files)
