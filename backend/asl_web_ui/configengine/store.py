"""Applying planned file changes safely.

A plan holds, for each file, the new content and the hash of the content it
was planned against. Applying it:

1. takes an exclusive lock (one writer at a time, across all requests);
2. checks every file still has the planned-against hash, so edits made
   meanwhile (by hand, asl3-menu or another browser) are never overwritten;
3. snapshots the current files under the state directory, with a manifest;
4. writes each file to a temporary file in the same directory, syncs it and
   renames it into place, keeping the original permissions;
5. if a later file fails, restores the files already replaced from the
   snapshot.

Every attempt is recorded in the audit log (audit.jsonl).
"""

import contextlib
import difflib
import fcntl
import hashlib
import json
import os
import secrets
import shutil
import stat
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

PLAN_LIFETIME = 300  # seconds
KEEP_SNAPSHOTS = 50


def digest(data: bytes | None) -> str:
    return "absent" if data is None else hashlib.sha256(data).hexdigest()


class Conflict(Exception):
    """A file changed after the plan was made."""


class ApplyError(Exception):
    pass


@dataclass
class FileChange:
    path: str
    base_hash: str
    new: bytes
    old: bytes | None = None

    def diff(self, label: str) -> str:
        old = (self.old or b"").decode("utf-8", "replace").splitlines(keepends=True)
        new = self.new.decode("utf-8", "replace").splitlines(keepends=True)
        return "".join(difflib.unified_diff(old, new, f"a/{label}", f"b/{label}", n=3))


@dataclass
class Plan:
    id: str
    owner: str  # session that may apply it
    user: str
    action: str
    changes: list[FileChange]
    errors: int = 0  # lint errors in the new content; applying needs confirmation
    created: float = field(default_factory=time.monotonic)

    @property
    def expired(self) -> bool:
        return time.monotonic() - self.created > PLAN_LIFETIME


class Store:
    def __init__(self, state_dir: str = "/var/lib/asl-web-ui"):
        self.state = Path(state_dir)
        self.plans: dict[str, Plan] = {}

    # ---- reading ---------------------------------------------------------

    @staticmethod
    def read(path: str) -> bytes | None:
        try:
            with open(path, "rb") as f:
                return f.read()
        except FileNotFoundError:
            return None

    # ---- plans -----------------------------------------------------------

    def plan(self, owner: str, user: str, action: str, changes: list[FileChange]) -> Plan:
        for plan_id in [k for k, p in self.plans.items() if p.expired]:
            del self.plans[plan_id]
        for change in changes:
            if change.old is None:
                change.old = self.read(change.path)
        plan = Plan(secrets.token_urlsafe(16), owner, user, action, changes)
        self.plans[plan.id] = plan
        return plan

    def peek(self, plan_id: str, owner: str) -> Plan | None:
        plan = self.plans.get(plan_id)
        if plan is None or plan.owner != owner or plan.expired:
            return None
        return plan

    def take(self, plan_id: str, owner: str) -> Plan | None:
        plan = self.plans.get(plan_id)
        if plan is None or plan.owner != owner or plan.expired:
            return None
        del self.plans[plan_id]
        return plan

    # ---- applying --------------------------------------------------------

    @contextlib.contextmanager
    def _lock(self):
        self.state.mkdir(parents=True, exist_ok=True)
        with open(self.state / "config.lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def apply(self, plan: Plan) -> str:
        """Apply a plan; returns the snapshot ID. Raises Conflict or ApplyError."""
        with self._lock():
            current = {c.path: self.read(c.path) for c in plan.changes}
            stale = [c.path for c in plan.changes if digest(current[c.path]) != c.base_hash]
            if stale:
                self._audit(plan, "conflict", None, stale)
                raise Conflict(stale)
            snapshot = self._snapshot(plan, current)
            done: list[FileChange] = []
            try:
                for change in plan.changes:
                    self._write(change.path, change.new)
                    done.append(change)
            except OSError as exc:
                self._restore(done, current)
                self._audit(plan, "failed", snapshot, [str(exc)])
                raise ApplyError(str(exc)) from exc
            self._audit(plan, "applied", snapshot, [c.path for c in plan.changes])
            self._prune()
            return snapshot

    def _snapshot(self, plan: Plan, current: dict[str, bytes | None]) -> str:
        snap_id = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
        root = self.state / "snapshots" / snap_id
        root.mkdir(parents=True)
        manifest = {"id": snap_id, "time": time.time(), "user": plan.user, "action": plan.action, "files": []}
        for i, (path, data) in enumerate(current.items()):
            entry = {"path": path, "existed": data is not None}
            if data is not None:
                name = f"{i:03d}-{os.path.basename(path)}"
                (root / name).write_bytes(data)
                entry["copy"] = name
            manifest["files"].append(entry)
        (root / "manifest.json").write_text(json.dumps(manifest, indent=2))
        return snap_id

    @staticmethod
    def _write(path: str, data: bytes) -> None:
        directory = os.path.dirname(path) or "."
        try:
            mode = stat.S_IMODE(os.stat(path).st_mode)
        except FileNotFoundError:
            mode = 0o644
        fd, tmp = tempfile.mkstemp(prefix=".asl-web-ui-", dir=directory)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, mode)
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp)
            raise

    def _restore(self, done: list[FileChange], current: dict[str, bytes | None]) -> None:
        for change in reversed(done):
            original = current[change.path]
            with contextlib.suppress(OSError):
                if original is None:
                    os.unlink(change.path)
                else:
                    self._write(change.path, original)

    def _audit(self, plan: Plan, result: str, snapshot: str | None, detail: list[str]) -> None:
        entry = {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "user": plan.user, "action": plan.action,
                 "files": [c.path for c in plan.changes], "snapshot": snapshot, "result": result, "detail": detail}
        self.state.mkdir(parents=True, exist_ok=True)
        with open(self.state / "audit.jsonl", "a") as f:
            f.write(json.dumps(entry) + "\n")

    def _prune(self) -> None:
        snaps = sorted((self.state / "snapshots").iterdir()) if (self.state / "snapshots").exists() else []
        for old in snaps[:-KEEP_SNAPSHOTS]:
            shutil.rmtree(old, ignore_errors=True)
