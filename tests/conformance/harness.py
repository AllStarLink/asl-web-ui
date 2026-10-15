"""Ask a real (private, unprivileged) Asterisk how it reads a config file.

Uses AST_CONFIG(file,section,key,-1) in a generated dialplan, run through a
Local channel, and reads the answers from the instance's log. Needs the ASL
packages installed (asterisk, app_rpt) but no root.
"""

import itertools
import re
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
INSTANCE = HERE.parent / "asterisk" / "instance.sh"
_counter = itertools.count()

# Messages config.c logs when it rejects a file.
REJECT_PATTERNS = [
    r"parse error",
    r"Inheritance requested, but category",
    r"Category addition requested, but category",
    r"listed as a #include but it does not exist",
    r"No category context",
    r"Invalid escape in line",
]


class PrivateAsterisk:
    def __init__(self, directory: Path):
        self.dir = Path(directory)

    def start(self) -> None:
        subprocess.run([str(INSTANCE), "start", str(self.dir)], check=True, capture_output=True)

    def stop(self) -> None:
        subprocess.run([str(INSTANCE), "stop", str(self.dir)], check=False, capture_output=True)

    def cli(self, command: str) -> str:
        out = subprocess.run([str(INSTANCE), "cli", str(self.dir), command], capture_output=True, text=True)
        return out.stdout

    @property
    def log(self) -> Path:
        return self.dir / "log" / "messages.log"

    def query(self, files: dict[str, str], main: str, pairs: list[tuple[str, str]]) -> tuple[dict, bool, str]:
        """Write ``files`` (names relative to etc/), then read ``pairs`` from
        ``main``. Returns ({(section, key): value}, rejected, log text)."""
        tag = f"t{next(_counter)}x{int(time.time() * 1000) % 100000}"
        names = {}
        for name, text in files.items():
            unique = name.replace(".conf", f"-{tag}.conf") if name == main else name
            names[name] = unique
            path = self.dir / "etc" / unique
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        target = names[main]
        lines = ["[dump]", "exten => s,1,NoOp()"]
        for i, (section, key) in enumerate(pairs):
            lines.append(f"same => n,Verbose(0,ASLCHK {tag} {i} <${{AST_CONFIG({target},{section},{key},-1)}}>)")
        lines.append(f"same => n,Verbose(0,ASLCHK {tag} done)")
        lines.append("same => n,Hangup()")
        (self.dir / "etc" / "extensions.conf").write_text("\n".join(lines) + "\n")
        start = self.log.stat().st_size if self.log.exists() else 0
        self.cli("dialplan reload")
        self.cli("channel originate Local/s@dump application Wait 1")
        deadline = time.time() + 10
        text = ""
        while time.time() < deadline:
            with open(self.log, "rb") as f:
                f.seek(start)
                text = f.read().decode(errors="replace")
            if f"ASLCHK {tag} done" in text:
                break
            time.sleep(0.1)
        values = {}
        for m in re.finditer(rf"ASLCHK {tag} (\d+) <(.*)>", text):
            values[pairs[int(m.group(1))]] = m.group(2) or None
        # Each query uses a fresh file name, so any rejection logged in this
        # window comes from this file or one it includes.
        rejected = any(re.search(p, text) for p in REJECT_PATTERNS)
        return values, rejected, text
