"""Run node-setup's own operations next to the planner's, on the same files.

The stock configuration (asl3-asterisk-config) and node-setup with its
customization files (asl3-menu) are taken from the packages the system's
apt sources offer, in the installed versions, so the tests follow each ASL
release. They are downloaded once into ~/.cache/asl-web-ui-tests.

node-setup is a whiptail program; its functions are loaded without the menu
loop, the dialogs are replaced by functions that fail the test if called,
and the Asterisk CLI is replaced so the system's AstDB is never touched.
"""

import os
import shutil
import subprocess
from pathlib import Path

from asl_web_ui.configengine.edit import Workspace, module_state
from asl_web_ui.configengine.lint import REPEATABLE
from asl_web_ui.configengine.model import load
from asl_web_ui.nodes import savenode

CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "asl-web-ui-tests"
PACKAGES = ("asl3-asterisk-config", "asl3-menu")
# What node-setup and the planner touch.
# modules.conf is compared as the channel drivers' load state ("modules").
FILES = ["rpt.conf", "rpt_http_registrations.conf", "iax.conf", "extensions.conf", "manager.conf", "simpleusb.conf", "usbradio.conf", "voter.conf"]
CHANNEL_MODULES = ["chan_simpleusb", "chan_usbradio", "chan_usrp", "chan_voter", "chan_pi"]


class Unavailable(Exception):
    pass


def _version(package: str) -> str:
    out = subprocess.run(["dpkg-query", "-W", "-f=${Version}", package], capture_output=True, text=True)
    if out.returncode != 0 or not out.stdout:
        raise Unavailable(f"{package} is not installed")
    return out.stdout


def packages() -> Path:
    """Directory with both packages extracted (cached per version)."""
    key = "_".join(f"{p}-{_version(p)}" for p in PACKAGES).replace(":", "_")
    root = CACHE / key
    if (root / ".done").exists():
        return root
    shutil.rmtree(root, ignore_errors=True)
    debs = root / "debs"
    debs.mkdir(parents=True)
    for p in PACKAGES:
        got = subprocess.run(["apt-get", "download", f"{p}={_version(p)}"], cwd=debs, capture_output=True, text=True)
        if got.returncode != 0:
            raise Unavailable(f"apt-get download {p} failed: {got.stderr.strip()}")
    tree = root / "tree"
    for deb in debs.iterdir():
        subprocess.run(["dpkg-deb", "-x", str(deb), str(tree)], check=True)
    (root / ".done").touch()
    return root


def stock(dest: Path) -> Path:
    """A fresh copy of the stock /etc/asterisk, custom/ files included."""
    src = packages() / "tree" / "etc" / "asterisk"
    shutil.copytree(src, dest, symlinks=True)
    return dest


def node_setup_script() -> Path:
    return packages() / "tree" / "usr" / "bin" / "node-setup"


PRELUDE = r"""
set -u +e
source <(sed -e '/^while \[\[ \$# -gt 0 \]\]; do/,$d' "$NODE_SETUP")
# Dialogs take their answers from the "answers" array, in order: text is
# returned as the dialog's output, __no__ makes it return 1 (No/Cancel).
# Dialogs run in $(...) subshells, so the position is kept in a file.
answers=()
whiptail() {
    local n; n=$(cat "$ANSWER_POS" 2>/dev/null || echo 0)
    if [[ $n -ge ${#answers[@]} ]]; then echo "unexpected dialog: $*" >&2; exit 99; fi
    echo $((n + 1)) > "$ANSWER_POS"
    local a="${answers[$n]}"
    case "$a" in
        __no__) return 1 ;;
        __yes__) return 0 ;;
        *) echo "$a" >&2; return 0 ;;
    esac
}
dialog() { whiptail "$@"; }
calc_wt_size() { WT_HEIGHT=40; WT_WIDTH=100; WT_MENU_HEIGHT=32; }
clear() { :; }
ASTERISK=true
logfile=/dev/null
"""


def run_node_setup(config_dir: Path, script: str) -> str:
    env = dict(os.environ, CONFIG_DIR=str(config_dir), DESTDIR=str(config_dir.parent / "destdir"),
               NODE_SETUP=str(node_setup_script()), TERM="dumb",
               ANSWER_POS=str(config_dir.parent / "answer-position"))
    (config_dir.parent / "answer-position").unlink(missing_ok=True)
    proc = subprocess.run(["bash", "-c", PRELUDE + "\nset +u\n" + script], env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                          timeout=60)
    if proc.returncode != 0:
        raise AssertionError(f"node-setup script failed ({proc.returncode}):\n{proc.stderr}\n{proc.stdout}")
    return proc.stdout


def effective(config_dir: Path) -> dict:
    """What Asterisk would load: per file, each section's templates and values."""
    out: dict = {}
    for name in FILES:
        if not (config_dir / name).exists():
            continue
        cfg = load(name, config_dir=str(config_dir))
        assert not cfg.errors, f"{name}: {cfg.errors}"
        sections = {}
        for cat in cfg.categories:
            if cat.template:
                continue
            # The value Asterisk uses (the last one), or every value for keys
            # that are meant to repeat.
            values: dict[str, object] = {}
            for v in cat.vars:
                if v.key.lower() in REPEATABLE:
                    values.setdefault(v.key, []).append(v.value)  # type: ignore[union-attr]
                else:
                    values[v.key] = v.value
            sections[cat.name] = {"templates": cat.templates, "values": values}
        out[name] = sections
    ws = Workspace(str(config_dir))
    out["modules"] = {m: module_state(ws, m) for m in CHANNEL_MODULES}
    out["savenode"] = savenode.read(ws)
    return out


def diff(a: dict, b: dict) -> list[str]:
    """Readable differences between two effective views."""
    lines = []
    for name in sorted(set(a) | set(b)):
        x, y = a.get(name, {}), b.get(name, {})
        if x == y:
            continue
        for key in sorted(set(x) | set(y), key=str):
            sx, sy = x.get(key), y.get(key)
            if sx == sy:
                continue
            if isinstance(sx, dict) and isinstance(sy, dict) and "values" in sx and "values" in sy:
                if sx["templates"] != sy["templates"]:
                    lines.append(f"{name} [{key}] templates: node-setup={sx['templates']} planner={sy['templates']}")
                vx, vy = sx["values"], sy["values"]
                for k in sorted(set(vx) | set(vy)):
                    if vx.get(k) != vy.get(k):
                        lines.append(f"{name} [{key}] {k}: node-setup={vx.get(k)!r} planner={vy.get(k)!r}")
            else:
                lines.append(f"{name} [{key}]: node-setup={sx!r} planner={sy!r}")
    return lines
