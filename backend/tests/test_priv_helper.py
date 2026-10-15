"""The privileged helper: protocol, polkit check, and each command, on a
temporary root directory (never the real system)."""

import io
import json
import os
import stat
import tarfile
import time

import pytest

from asl_web_ui_priv import commands, helper


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(commands, "ROOT", str(tmp_path))
    etc = tmp_path / "etc" / "asterisk"
    etc.mkdir(parents=True)
    (etc / "rpt.conf").write_text("[1999]\n")
    (etc / "rpt_http_registrations.conf").write_text("[registrations]\n")
    (etc / "manager.conf").write_text("[admin]\nsecret = old-secret-1234\n")
    (etc / "old.tgz").write_text("not included")
    (tmp_path / "etc" / "allmon3").mkdir()
    (tmp_path / "etc" / "allmon3" / "allmon3.ini").write_text("[1999]\npass=old-secret-1234\n")
    (tmp_path / "var" / "lib" / "asl-web-ui" / "staging").mkdir(parents=True)
    return tmp_path


def run(command, args=None, table=None, allow=True, caller=(1234, 999, 999)):
    out = io.BytesIO()
    request = json.dumps({"op": command, "args": args or {}, "user": "dev"}).encode() + b"\n"
    channel = helper.Channel(io.BytesIO(request), out)
    try:
        helper.handle(channel, caller, is_authorized=lambda c, pid, uid: allow, table=table)
    except helper.RequestError as exc:
        return [{"op": "result", "ok": False, "error": str(exc), "code": exc.code}]
    return [json.loads(line) for line in out.getvalue().splitlines()]


def result(command, args=None, **kw):
    return run(command, args, **kw)[-1]


# ---- protocol and authorization -------------------------------------------------------


def test_unknown_command_and_denied_caller(root):
    assert result("shell.exec")["code"] == "invalid"
    assert result("backup.create", allow=False)["code"] == "denied"
    assert result("backup.create", caller=None)["code"] == "denied"


def test_pkcheck_is_asked_about_the_callers_process(tmp_path):
    log = tmp_path / "args"
    fake = tmp_path / "pkcheck"
    fake.write_text(f'#!/bin/sh\necho "$@" > {log}\nexit 0\n')
    fake.chmod(0o755)
    assert helper.authorized("backup.restore", os.getpid(), os.getuid(), pkcheck=str(fake))
    args = log.read_text().split()
    assert args[:2] == ["--action-id", "org.allstarlink.asl-web-ui.backup-restore"]
    pid, start, uid = args[3].split(",")
    assert pid == str(os.getpid()) and uid == str(os.getuid()) and start.isdigit()
    fake.write_text("#!/bin/sh\nexit 1\n")
    assert not helper.authorized("backup.restore", os.getpid(), os.getuid(), pkcheck=str(fake))


def test_start_time_handles_odd_command_names(tmp_path, monkeypatch):
    stat_line = "42 (a) b (c)) S 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 777 20\n"
    real_open = open
    monkeypatch.setattr("builtins.open", lambda p, *a, **k: io.StringIO(stat_line) if p == "/proc/42/stat"
                        else real_open(p, *a, **k))
    assert helper.start_time(42) == "777"


# ---- backups --------------------------------------------------------------------------------


def test_create_backup(root):
    res = result("backup.create")
    assert res["ok"]
    name = res["data"]["name"]
    assert name.startswith("ASL_") and name.endswith(".tgz")
    archive = root / "var" / "asl-backups" / name
    assert stat.S_IMODE(archive.stat().st_mode) == 0o640
    with tarfile.open(archive) as tar:
        names = tar.getnames()
    assert "etc/asterisk/rpt.conf" in names and "etc/allmon3/allmon3.ini" in names
    assert "etc/asterisk/old.tgz" not in names  # archives are never nested
    assert (root / "var" / "asl-backups" / "asl-backup-files").exists()
    second = result("backup.create")["data"]["name"]
    assert second != name


def _archive(root, name, members):
    """members: list of (TarInfo, bytes | None)."""
    path = root / "var" / "asl-backups" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as tar:
        for info, data in members:
            tar.addfile(info, io.BytesIO(data) if data is not None else None)
    return path


def _file(name, data=b"x", mode=0o644):
    info = tarfile.TarInfo(name)
    info.size, info.mode, info.mtime = len(data), mode, int(time.time())
    return info, data


def _special(name, kind, link=""):
    info = tarfile.TarInfo(name)
    info.type, info.linkname = kind, link
    return info, None


def test_restore_writes_only_safe_listed_paths(root):
    outside = root / "etc" / "passwd"
    outside.write_text("untouched")
    _archive(root, "ASL_evil.tgz", [
        _file("etc/asterisk/rpt_http_registrations.conf", b"[registrations]\nregister => 2701:pw@x\n"),
        _file("etc/asterisk/rpt.conf", b"[2701]\n", mode=0o4777),
        _file("/etc/passwd", b"root::0:0"),
        _file("etc/asterisk/../passwd", b"root::0:0"),
        _file("etc/passwd", b"root::0:0"),
        _special("etc/asterisk/evil-link", tarfile.SYMTYPE, "/etc/passwd"),
        _special("etc/asterisk/ok-link", tarfile.SYMTYPE, "rpt.conf"),
        _special("etc/asterisk/hard", tarfile.LNKTYPE, "etc/passwd"),
        _special("etc/asterisk/fifo", tarfile.FIFOTYPE),
    ])
    res = result("backup.restore", {"name": "ASL_evil.tgz"})
    assert res["ok"], res
    assert outside.read_text() == "untouched"
    assert (root / "etc" / "asterisk" / "rpt.conf").read_text() == "[2701]\n"
    # set-uid and group/other write dropped
    assert stat.S_IMODE((root / "etc" / "asterisk" / "rpt.conf").stat().st_mode) == 0o755
    assert os.readlink(root / "etc" / "asterisk" / "ok-link") == "rpt.conf"
    for name in ("evil-link", "hard", "fifo"):
        assert not os.path.lexists(root / "etc" / "asterisk" / name)
    reasons = {s["name"]: s["reason"] for s in res["data"]["skipped"]}
    assert reasons["/etc/passwd"] == "absolute path"
    assert reasons["etc/passwd"] == "not in the include list"
    assert reasons["etc/asterisk/evil-link"] == "link points outside the include list"
    assert res["data"]["before"].endswith("_before-restore.tgz")
    assert (root / "var" / "asl-backups" / res["data"]["before"]).exists()


def test_restore_does_not_follow_a_linked_parent(root):
    elsewhere = root / "elsewhere"
    elsewhere.mkdir()
    (root / "etc" / "asterisk" / "custom").symlink_to(elsewhere)
    _archive(root, "ASL_link.tgz", [
        _file("etc/asterisk/rpt_http_registrations.conf"),
        _file("etc/asterisk/custom/x.conf", b"evil"),
    ])
    res = result("backup.restore", {"name": "ASL_link.tgz"})
    assert not (elsewhere / "x.conf").exists()
    assert {"name": "etc/asterisk/custom/x.conf", "reason": "a parent directory is a link"} in res["data"]["skipped"]


def test_restore_refuses_non_asl3_archives_and_bad_names(root):
    _archive(root, "ASL_other.tgz", [_file("etc/asterisk/rpt.conf")])
    assert result("backup.restore", {"name": "ASL_other.tgz"})["code"] == "invalid"
    assert result("backup.restore", {"name": "../../etc/passwd"})["code"] == "invalid"
    assert result("backup.restore", {"name": "missing.tgz"})["code"] == "not_found"


def test_read_lists_what_would_be_restored(root):
    _archive(root, "ASL_r.tgz", [_file("etc/asterisk/rpt_http_registrations.conf"), _file("etc/shadow")])
    data = result("backup.read", {"name": "ASL_r.tgz"})["data"]
    assert data["files"] == ["etc/asterisk/rpt_http_registrations.conf"] and data["asl3"]
    assert data["skipped"] == [{"name": "etc/shadow", "reason": "not in the include list"}]


def test_delete(root):
    _archive(root, "ASL_d.tgz", [_file("etc/asterisk/rpt_http_registrations.conf")])
    assert result("backup.delete", {"name": "ASL_d.tgz"})["ok"]
    assert not (root / "var" / "asl-backups" / "ASL_d.tgz").exists()
    assert result("backup.delete", {"name": "asl-backup-files"})["code"] == "invalid"


def test_import_from_staging(root):
    staged = root / "var" / "lib" / "asl-web-ui" / "staging" / "abcdefgh12"
    with tarfile.open(staged, "w:gz") as tar:
        info, data = _file("etc/asterisk/rpt_http_registrations.conf")
        tar.addfile(info, io.BytesIO(data))
    res = result("backup.import", {"staged": "abcdefgh12", "name": "ASL_2026-10-01_1200.tgz"})
    assert res["ok"] and res["data"]["name"] == "ASL_2026-10-01_1200.tgz"
    assert not staged.exists()
    bad = root / "var" / "lib" / "asl-web-ui" / "staging" / "zzzzzzzz99"
    bad.write_bytes(b"not a tar")
    assert result("backup.import", {"staged": "zzzzzzzz99", "name": "ASL_x.tgz"})["code"] == "invalid"
    assert result("backup.import", {"staged": "../../etc", "name": "ASL_x.tgz"})["code"] == "invalid"


def test_include_list_round_trip(root):
    first = result("backup.read_include_list")["data"]
    assert first["exists"] is False and "/etc/asterisk" in first["content"]
    res = result("backup.write_include_list", {"content": "/etc/asterisk\n", "expected_hash": first["hash"]})
    assert res["ok"]
    assert result("backup.write_include_list", {"content": "/", "expected_hash": first["hash"]})["code"] == "conflict"


# ---- files and ownership ---------------------------------------------------------------------


def test_allmon3_file_read_and_write(root):
    read = result("file.read", {"path": "/etc/allmon3/allmon3.ini"})["data"]
    assert "pass=old-secret-1234" in read["content"]
    res = result("file.write", {"path": "/etc/allmon3/allmon3.ini", "content": "[1999]\npass=new\n",
                                "expected_hash": read["hash"]})
    assert res["ok"]
    assert result("file.write", {"path": "/etc/allmon3/allmon3.ini", "content": "x",
                                 "expected_hash": read["hash"]})["code"] == "conflict"
    assert result("file.read", {"path": "/etc/shadow"})["code"] == "invalid"


def test_fix_ownership_stays_in_etc_asterisk(root):
    assert result("asterisk.fix_ownership", {"path": "rpt.conf"})["ok"]
    assert result("asterisk.fix_ownership", {"path": "../allmon3/allmon3.ini"})["code"] == "invalid"
    (root / "etc" / "asterisk" / "link.conf").symlink_to(root / "etc" / "allmon3" / "allmon3.ini")
    assert result("asterisk.fix_ownership", {"path": "link.conf"})["code"] == "invalid"
    assert result("asterisk.fix_ownership", {"path": "nope.conf"})["code"] == "not_found"


def test_factory_restore_keeps_the_ami_secret(root):
    class FakeApt:
        def __init__(self, argv, **kw):
            assert argv[:2] == ["apt-get", "-y"] and "asl3-asterisk-config" in argv
            (root / "etc" / "asterisk" / "manager.conf").write_text("[admin]\nsecret = make4An1ce-secret\n")
            (root / "etc" / "asterisk" / "rpt.conf.dpkg-old").write_text("old")
            self.stdout = io.StringIO("Reinstalling\n")
            self.returncode = 0

        def wait(self):
            return 0

    lines = []
    res = commands.factory_restore({}, lines.append, run=FakeApt)
    assert "secret = old-secret-1234" in (root / "etc" / "asterisk" / "manager.conf").read_text()
    assert not (root / "etc" / "asterisk" / "rpt.conf.dpkg-old").exists()
    assert "Reinstalling" in lines and res["before"].endswith("_before-factory.tgz")
