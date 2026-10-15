"""Applying plans: hash checks, snapshots, atomic writes, rollback, audit."""

import json
import os

import pytest

from asl_web_ui.configengine.store import ApplyError, Conflict, FileChange, Store, digest


@pytest.fixture
def setup(tmp_path):
    etc = tmp_path / "etc"
    etc.mkdir()
    (etc / "a.conf").write_bytes(b"[a]\nx = 1\n")
    (etc / "b.conf").write_bytes(b"[b]\ny = 2\n")
    os.chmod(etc / "a.conf", 0o640)
    return Store(str(tmp_path / "state")), etc


def change(path, new):
    data = path.read_bytes() if path.exists() else None
    return FileChange(str(path), digest(data), new)


def test_apply_writes_files_keeps_mode_and_snapshots(setup):
    store, etc = setup
    plan = store.plan("s1", "op", "test", [change(etc / "a.conf", b"[a]\nx = 9\n"), change(etc / "b.conf", b"[b]\ny = 8\n")])
    assert "+x = 9" in plan.changes[0].diff("a.conf")
    snap = store.apply(store.take(plan.id, "s1"))
    assert (etc / "a.conf").read_bytes() == b"[a]\nx = 9\n"
    assert oct(os.stat(etc / "a.conf").st_mode & 0o777) == "0o640"
    manifest = json.loads((store.state / "snapshots" / snap / "manifest.json").read_text())
    assert [f["path"] for f in manifest["files"]] == [str(etc / "a.conf"), str(etc / "b.conf")]
    copy = store.state / "snapshots" / snap / manifest["files"][0]["copy"]
    assert copy.read_bytes() == b"[a]\nx = 1\n"
    audit = [json.loads(l) for l in (store.state / "audit.jsonl").read_text().splitlines()]
    assert audit[-1]["result"] == "applied" and audit[-1]["user"] == "op"


def test_changed_meanwhile_is_a_conflict_and_writes_nothing(setup):
    store, etc = setup
    plan = store.plan("s1", "op", "test", [change(etc / "a.conf", b"new\n")])
    (etc / "a.conf").write_bytes(b"edited by hand\n")
    with pytest.raises(Conflict):
        store.apply(store.take(plan.id, "s1"))
    assert (etc / "a.conf").read_bytes() == b"edited by hand\n"


def test_plans_belong_to_their_session_and_are_single_use(setup):
    store, etc = setup
    plan = store.plan("s1", "op", "test", [change(etc / "a.conf", b"x\n")])
    assert store.take(plan.id, "other-session") is None
    assert store.take(plan.id, "s1") is not None
    assert store.take(plan.id, "s1") is None


def test_failure_part_way_restores_earlier_files(setup, monkeypatch):
    store, etc = setup
    plan = store.plan("s1", "op", "test", [change(etc / "a.conf", b"A\n"), change(etc / "b.conf", b"B\n")])
    real = Store._write
    calls = []

    def flaky(path, data):
        calls.append(path)
        if path.endswith("b.conf") and data == b"B\n":
            raise OSError("disk full")
        real(path, data)

    monkeypatch.setattr(Store, "_write", staticmethod(flaky))
    with pytest.raises(ApplyError):
        store.apply(store.take(plan.id, "s1"))
    assert (etc / "a.conf").read_bytes() == b"[a]\nx = 1\n"  # restored
    assert (etc / "b.conf").read_bytes() == b"[b]\ny = 2\n"


def test_new_file_can_be_created(setup):
    store, etc = setup
    plan = store.plan("s1", "op", "test", [change(etc / "new.conf", b"[n]\n")])
    store.apply(store.take(plan.id, "s1"))
    assert (etc / "new.conf").read_bytes() == b"[n]\n"
