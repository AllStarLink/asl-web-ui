"""Restart pending: configuration changed since Asterisk started.

Computed from the files themselves, so edits made outside the web UI (by
hand, by asl3-menu) count too. Also reports whether rpt.conf currently has
errors, which the restart and reload warnings use.
"""

import os
import time

from .configengine.lint import counts, lint
from .configengine.model import load

# Files under the configuration directory that Asterisk does not read.
NOT_ASTERISK = {"savenode.conf"}


def changed_since(config_dir: str, started: float) -> list[str]:
    changed = []
    for root, _dirs, files in os.walk(config_dir):
        for name in files:
            if not name.endswith(".conf") or name in NOT_ASTERISK:
                continue
            path = os.path.join(root, name)
            try:
                if os.stat(path).st_mtime > started:
                    changed.append(os.path.relpath(path, config_dir))
            except OSError:
                continue
    return sorted(changed)


class RptLintCache:
    """Lint rpt.conf (and what it includes) only when one of them changed."""

    def __init__(self, config_dir: str):
        self.config_dir = config_dir
        self._key: tuple | None = None
        self._result: dict | None = None

    def _signature(self, paths) -> tuple:
        sig = []
        for path in paths:
            try:
                st = os.stat(path)
                sig.append((path, st.st_mtime_ns, st.st_size))
            except OSError:
                sig.append((path, None, None))
        return tuple(sig)

    def get(self) -> dict:
        if self._key is not None and self._signature(p for p, *_ in self._key) == self._key:
            return self._result  # type: ignore[return-value]
        cfg = load("rpt.conf", config_dir=self.config_dir)
        findings = lint(cfg, self.config_dir)
        errors = [f.as_dict() for f in findings if f.severity == "error"]
        self._result = {"errors": counts(findings)["error"], "first_error": errors[0] if errors else None}
        self._key = self._signature(cfg.files)
        return self._result


def asterisk_started(uptime_seconds: int | None) -> float | None:
    return None if uptime_seconds is None else time.time() - uptime_seconds
