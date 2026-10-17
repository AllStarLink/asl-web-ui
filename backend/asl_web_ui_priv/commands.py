"""The privileged commands. Each takes (args, output) and returns JSON data.

Backups follow asl-backup-menu's format, so the two tools share
/var/asl-backups: gzip tar archives named ASL_YYYY-MM-DD_HHMM.tgz holding
the paths in /var/asl-backups/asl-backup-files, stored relative to /.

Restoring is stricter than asl-backup-menu (which untars over /):
- only members under a path in the include list are written;
- absolute names, ".." and anything resolving outside those paths are refused;
- only regular files, directories and symbolic links that stay inside the
  listed paths are extracted (no hard links, devices or FIFOs);
- ownership is never taken from the archive (existing files keep theirs,
  new ones get their directory's), and modes lose set-id bits and group or
  other write access;
- a parent directory that is a symbolic link elsewhere is not followed;
- a backup of the current state is made first.
"""

import csv
import grp
import hashlib
import io
import os
import posixpath
import pwd
import re
import stat
import subprocess
import tarfile
import tempfile
import time
from collections.abc import Callable

from . import dahdi, https, net44, network, sa818

ROOT = "/"
BACKUP_DIR = "/var/asl-backups"
INCLUDE_LIST = "/var/asl-backups/asl-backup-files"
STAGING_DIR = "/var/lib/asl-web-ui/staging"
CONFIG_DIR = "/etc/asterisk"
MARKER = "etc/asterisk/rpt_http_registrations.conf"  # asl-backup-menu's "made on ASL3" check
# Never in a backup, and never restored, whatever the include list says:
# the 44Net Connect keyfile holds the tunnel's private key, which is not
# ours to copy.
NEVER_BACKED_UP = {net44.KEYFILE.lstrip("/")}
# Files outside /etc/asterisk the web UI may replace: the files Allmon3 reads,
# and the SA818 settings (only with content that is safe to source, see
# sa818.lint_text). Every other file directly in /etc/allmon3 can be listed and
# read, but not written: some are web server configuration (allmon3.conf,
# nginx.conf) that root reads. Allmon3's users file is never read here (only
# through the allmon3.* commands, so hashes never leave).
ALLMON3_DIR = "/etc/allmon3"
FILE_ALLOWLIST = {"/etc/allmon3/allmon3.ini", "/etc/allmon3/web.ini", "/etc/allmon3/menu.ini",
                  "/etc/allmon3/custom.css", "/etc/allmon3/user-restrictions", sa818.CONF}
ALLMON3_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.+~-]{0,100}$")
# Of those, the ones that may be created or removed: Allmon3 works without them.
OPTIONAL_FILES = {"/etc/allmon3/menu.ini"}
ALLMON3_USERS = "/etc/allmon3/users"
ALLMON3_USER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,63}$")
ARCHIVE_GROUP = "asterisk"
MAX_FILE = 1 << 20
MAX_ARCHIVE = 64 << 20

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,100}\.tgz$")
STAGED_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

DEFAULT_INCLUDE_LIST = """\
#
# ASL Backup
# ==========
#
# Paths (files or directories) included in backups made by asl-backup-menu
# and asl-web-ui. Lines starting with "#" and blank lines are ignored.
#

# Asterisk and AllStarLink configuration
/etc/asterisk

# The Asterisk database (node access lists)
/var/lib/asterisk/astdb.sqlite3

# This list
/var/asl-backups/asl-backup-files

# SA818 radio modules
/etc/sa818.conf

# Allmon3
/etc/allmon3/allmon3.ini
/etc/allmon3/custom.css
/etc/allmon3/menu.ini
/etc/allmon3/user-restrictions
/etc/allmon3/users
/etc/allmon3/web.ini

#
# Add the configuration files of other packages below. Backups uploaded to
# the AllStarLink servers are limited in size, so list configuration only.
#
"""

Output = Callable[[str], None]


class CommandError(Exception):
    def __init__(self, message: str, code: str = "failed"):
        super().__init__(message)
        self.code = code


def _path(abs_path: str) -> str:
    """Map an absolute path onto ROOT (tests use a temporary root)."""
    return os.path.join(ROOT, abs_path.lstrip("/"))


def _chown(path: str | int, uid: int, gid: int, follow: bool = True) -> None:
    """Set ownership (only possible, and only needed, when running as root)."""
    if os.geteuid() != 0:
        return
    if isinstance(path, int):
        os.fchown(path, uid, gid)
    elif follow:
        os.chown(path, uid, gid)
    else:
        os.lchown(path, uid, gid)


def _str(args: dict, key: str, limit: int = 4096) -> str:
    value = args.get(key)
    if not isinstance(value, str) or len(value) > limit:
        raise CommandError(f"{key} is missing or invalid", "invalid")
    return value


def _digest(data: bytes | None) -> str:
    return "absent" if data is None else hashlib.sha256(data).hexdigest()


def _read(path: str) -> bytes | None:
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None


def _atomic_write(path: str, data: bytes, mode: int, uid: int, gid: int) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".asl-web-ui-", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        _chown(tmp, uid, gid)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


# ---- the include list ------------------------------------------------------------


def include_text() -> str:
    data = _read(_path(INCLUDE_LIST))
    return data.decode("utf-8", "replace") if data is not None else DEFAULT_INCLUDE_LIST


def include_paths(text: str | None = None) -> list[str]:
    """Absolute paths from the include list, without comments and blanks."""
    out = []
    for line in (text if text is not None else include_text()).splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append("/" + posixpath.normpath(line).lstrip("/"))
    return out


def _ensure_include_list() -> None:
    path = _path(INCLUDE_LIST)
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _atomic_write(path, DEFAULT_INCLUDE_LIST.encode(), 0o644, 0, 0)


def read_include_list(args: dict, output: Output) -> dict:
    data = _read(_path(INCLUDE_LIST))
    text = data.decode("utf-8", "replace") if data is not None else DEFAULT_INCLUDE_LIST
    return {"content": text, "hash": _digest(data), "exists": data is not None}


def write_include_list(args: dict, output: Output) -> dict:
    content = _str(args, "content", 64 * 1024)
    expected = _str(args, "expected_hash", 80)
    path = _path(INCLUDE_LIST)
    if _digest(_read(path)) != expected:
        raise CommandError("The include list changed meanwhile. Reload it and try again.", "conflict")
    if "\x00" in content:
        raise CommandError("The include list cannot contain NUL characters.", "invalid")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _atomic_write(path, content.encode("utf-8"), 0o644, 0, 0)
    return {"hash": _digest(content.encode("utf-8"))}


# ---- creating and listing backups -------------------------------------------------


def _archive_owner(path: str) -> None:
    """root:asterisk 0640: the web service (group asterisk) can read archives
    to download or upload them; other users cannot (they hold passwords)."""
    try:
        gid = grp.getgrnam(ARCHIVE_GROUP).gr_gid
    except KeyError:
        gid = 0
    _chown(path, 0, gid)
    os.chmod(path, 0o640)


def _new_name(suffix: str = "") -> str:
    base = time.strftime("ASL_%Y-%m-%d_%H%M") + suffix
    name, n = f"{base}.tgz", 2
    while os.path.exists(os.path.join(_path(BACKUP_DIR), name)):
        name, n = f"{base}-{n}.tgz", n + 1
    return name


def _create(name: str) -> dict:
    os.makedirs(_path(BACKUP_DIR), exist_ok=True)
    _ensure_include_list()
    target = os.path.join(_path(BACKUP_DIR), name)
    fd, tmp = tempfile.mkstemp(prefix=".asl-web-ui-", suffix=".tgz", dir=_path(BACKUP_DIR))
    os.close(fd)
    included = []

    def skip_archives(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        if info.name.endswith(".tgz") or posixpath.normpath(info.name) in NEVER_BACKED_UP:
            return None
        return info

    try:
        with tarfile.open(tmp, "w:gz") as tar:
            for path in include_paths():
                real = os.path.realpath(_path(path))
                if not os.path.lexists(real):
                    continue
                arc = os.path.relpath(real, ROOT)
                tar.add(real, arcname=arc, filter=skip_archives)
                included.append("/" + arc)
        _archive_owner(tmp)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    return {"name": name, "size": os.path.getsize(target), "paths": included}


def backup_create(args: dict, output: Output) -> dict:
    return _create(_new_name())


def _backup_path(name: str) -> str:
    if not NAME_RE.match(name):
        raise CommandError("Invalid backup name.", "invalid")
    path = os.path.join(_path(BACKUP_DIR), name)
    st = os.lstat(path) if os.path.lexists(path) else None
    if st is None or not stat.S_ISREG(st.st_mode):
        raise CommandError(f"There is no backup named {name}.", "not_found")
    return path


def backup_delete(args: dict, output: Output) -> dict:
    os.unlink(_backup_path(_str(args, "name", 120)))
    return {}


def backup_read(args: dict, output: Output) -> dict:
    """List the members of a backup (for review before restoring)."""
    path = _backup_path(_str(args, "name", 120))
    plan = _restore_plan(path)
    return {"files": plan["files"], "skipped": plan["skipped"], "asl3": plan["asl3"]}


def _check_archive(path: str) -> None:
    if os.path.getsize(path) > MAX_ARCHIVE:
        raise CommandError("The archive is too large.", "invalid")
    try:
        with tarfile.open(path, "r:gz") as tar:
            names = tar.getnames()
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise CommandError(f"This is not a backup archive: {exc}", "invalid")
    if MARKER not in names:
        raise CommandError("The archive does not appear to have been made on an ASL3 system.", "invalid")


def backup_import(args: dict, output: Output) -> dict:
    """Move an archive the web service staged (upload or cloud download) into the backups."""
    staged = _str(args, "staged", 80)
    if not STAGED_RE.match(staged):
        raise CommandError("Invalid staged file.", "invalid")
    name = _str(args, "name", 120)
    if not NAME_RE.match(name):
        raise CommandError("Invalid backup name.", "invalid")
    src = os.path.join(_path(STAGING_DIR), staged)
    try:
        fd = os.open(src, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise CommandError("The staged file is missing.", "not_found")
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise CommandError("The staged file is not a regular file.", "invalid")
        data = f.read(MAX_ARCHIVE + 1)
    if len(data) > MAX_ARCHIVE:
        raise CommandError("The archive is too large.", "invalid")
    os.makedirs(_path(BACKUP_DIR), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".asl-web-ui-", suffix=".tgz", dir=_path(BACKUP_DIR))
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    try:
        _check_archive(tmp)
        base = name.removesuffix(".tgz")
        final, n = name, 2
        while os.path.exists(os.path.join(_path(BACKUP_DIR), final)):
            final, n = f"{base}-{n}.tgz", n + 1
        _archive_owner(tmp)
        os.replace(tmp, os.path.join(_path(BACKUP_DIR), final))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    os.unlink(src)
    return {"name": final}


# ---- restoring ---------------------------------------------------------------------------


def _within(rel: str, allowed: list[str]) -> bool:
    return any(rel == a or rel.startswith(a + "/") for a in allowed)


def _restore_plan(path: str) -> dict:
    """Which members would be written, and why others would not."""
    allowed = [p.lstrip("/") for p in include_paths()]
    files, skipped, members = [], [], []
    with tarfile.open(path, "r:gz") as tar:
        for m in tar.getmembers():
            name = m.name
            norm = posixpath.normpath(name)
            reason = None
            if name.startswith("/") or norm.startswith("/"):
                reason = "absolute path"
            elif norm == "." or ".." in norm.split("/"):
                reason = "path leaves the archive"
            elif not _within(norm, allowed):
                reason = "not in the include list"
            elif norm in NEVER_BACKED_UP:
                reason = "never restored (holds a private key)"
            elif m.issym():
                target = posixpath.normpath(posixpath.join(posixpath.dirname(norm), m.linkname)) \
                    if not m.linkname.startswith("/") else posixpath.normpath(m.linkname).lstrip("/")
                if target.startswith("..") or not _within(target, allowed):
                    reason = "link points outside the include list"
            elif not (m.isreg() or m.isdir()):
                reason = "not a regular file or directory"
            if reason:
                skipped.append({"name": name, "reason": reason})
            else:
                members.append((norm, m))
                if not m.isdir():
                    files.append(norm)
    return {"files": files, "skipped": skipped, "members": members, "asl3": MARKER in [n for n, _ in members]}


def _owner_for(dest: str, parent: str) -> tuple[int, int]:
    """Ownership for a restored file: never taken from the archive (a crafted
    archive could hand a configuration file to another local user). An
    existing file keeps its owner; a new one gets its directory's."""
    try:
        st = os.lstat(dest)
    except FileNotFoundError:
        st = os.stat(parent)
    return st.st_uid, st.st_gid


def _safe_mode(mode: int, directory: bool) -> int:
    """No set-id bits, no write access for group or others."""
    mode &= 0o755
    return mode | (0o700 if directory else 0o600)


def _safe_parent(rel: str) -> str | None:
    """Create the member's parent directories; None if one is a link elsewhere."""
    parent = posixpath.dirname(rel)
    expected = os.path.normpath(_path(parent)) if parent else os.path.normpath(ROOT)
    os.makedirs(expected, exist_ok=True)
    if os.path.realpath(expected) != expected:
        return None
    return expected


def backup_restore(args: dict, output: Output) -> dict:
    path = _backup_path(_str(args, "name", 120))
    plan = _restore_plan(path)
    if not plan["asl3"]:
        raise CommandError("The archive does not appear to have been made on an ASL3 system.", "invalid")
    before = _create(_new_name("_before-restore"))
    written, skipped = 0, list(plan["skipped"])
    with tarfile.open(path, "r:gz") as tar:
        for rel, m in plan["members"]:
            parent = _safe_parent(rel)
            if parent is None:
                skipped.append({"name": rel, "reason": "a parent directory is a link"})
                continue
            dest = os.path.join(parent, posixpath.basename(rel))
            uid, gid = _owner_for(dest, parent)
            mode = _safe_mode(m.mode, m.isdir())
            if m.isdir():
                if os.path.lexists(dest) and not os.path.isdir(dest):
                    skipped.append({"name": rel, "reason": "a file is in the way"})
                    continue
                os.makedirs(dest, exist_ok=True)
                os.chmod(dest, mode)
                _chown(dest, uid, gid)
                continue
            if os.path.isdir(dest) and not os.path.islink(dest):
                skipped.append({"name": rel, "reason": "a directory is in the way"})
                continue
            if m.issym():
                tmp = os.path.join(parent, f".asl-web-ui-link-{os.getpid()}")
                if os.path.lexists(tmp):
                    os.unlink(tmp)
                os.symlink(m.linkname, tmp)
                _chown(tmp, uid, gid, follow=False)
                os.replace(tmp, dest)
            else:
                src = tar.extractfile(m)
                if src is None:
                    skipped.append({"name": rel, "reason": "unreadable"})
                    continue
                _atomic_write(dest, src.read(), mode, uid, gid)
            written += 1
    return {"written": written, "skipped": skipped, "before": before["name"]}


# ---- factory restore ------------------------------------------------------------------------


def _admin_secret() -> str | None:
    """The [admin] AMI secret (asl-backup-menu keeps the first secret)."""
    data = _read(os.path.join(_path(CONFIG_DIR), "manager.conf"))
    if data is None:
        return None
    m = re.search(r"^secret\s*=\s*([^;\s]+)", data.decode("utf-8", "replace"), re.M)
    return m.group(1) if m else None


def factory_restore(args: dict, output: Output, run=subprocess.Popen) -> dict:
    """asl-backup-menu's "Restore ASL3 default configuration": reinstall
    asl3-asterisk-config with its own files, keeping the AMI secret."""
    before = _create(_new_name("_before-factory"))
    output(f"Saved the current configuration as {before['name']}.")
    secret = _admin_secret()
    env = dict(os.environ, DEBIAN_FRONTEND="noninteractive", PATH="/usr/sbin:/usr/bin:/sbin:/bin")
    proc = run(["apt-get", "-y", "-o", "Dpkg::Options::=--force-confask,confmiss,confnew", "install",
                "--reinstall", "asl3-asterisk-config"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
               stderr=subprocess.STDOUT, env=env, text=True)
    assert proc.stdout is not None
    for line in proc.stdout:
        output(line.rstrip("\n"))
    if proc.wait() != 0:
        raise CommandError(f"apt-get failed (exit code {proc.returncode}). The saved backup is {before['name']}.")
    for old in os.listdir(_path(CONFIG_DIR)):
        if old.endswith(".dpkg-old"):
            os.unlink(os.path.join(_path(CONFIG_DIR), old))
    new_secret = _admin_secret()
    if secret and new_secret and new_secret != secret:
        path = os.path.join(_path(CONFIG_DIR), "manager.conf")
        st = os.stat(path)
        text = _read(path).decode("utf-8", "replace")
        text = re.sub(rf"^(secret\s*=\s*){re.escape(new_secret)}", lambda m: m.group(1) + secret, text, count=1,
                      flags=re.M)
        _atomic_write(path, text.encode(), stat.S_IMODE(st.st_mode), st.st_uid, st.st_gid)
        output("Kept the AMI secret.")
    return {"before": before["name"]}


# ---- files outside /etc/asterisk -----------------------------------------------------------


def _allowed_file(args: dict, write: bool = False) -> str:
    path = _str(args, "path", 200)
    if path in FILE_ALLOWLIST:
        return _path(path)
    directory, name = posixpath.split(path)
    if not write and directory == ALLMON3_DIR and ALLMON3_NAME_RE.match(name) and path != ALLMON3_USERS:
        return _path(path)
    if write and directory == ALLMON3_DIR:
        raise CommandError(f"Allmon3 does not read {name}, so it cannot be changed here.", "invalid")
    raise CommandError("That file cannot be accessed.", "invalid")


def file_list(args: dict, output: Output) -> dict:
    """The files directly in /etc/allmon3, and /etc/sa818.conf."""
    def entry(path: str, st: os.stat_result) -> dict:
        try:
            owner = pwd.getpwuid(st.st_uid).pw_name
        except KeyError:
            owner = str(st.st_uid)
        return {"path": path, "size": st.st_size, "modified": int(st.st_mtime), "owner": owner,
                "writable": path in FILE_ALLOWLIST, "readable": path != ALLMON3_USERS}

    allmon3 = None
    directory = _path(ALLMON3_DIR)
    if os.path.isdir(directory) and not os.path.islink(directory):
        allmon3 = []
        for name in sorted(os.listdir(directory)):
            st = os.lstat(os.path.join(directory, name))
            if stat.S_ISREG(st.st_mode) and ALLMON3_NAME_RE.match(name):
                allmon3.append(entry(f"{ALLMON3_DIR}/{name}", st))
    conf = _path(sa818.CONF)
    st = os.lstat(conf) if os.path.lexists(conf) else None
    return {"allmon3": allmon3, "sa818": entry(sa818.CONF, st) if st and stat.S_ISREG(st.st_mode) else None}


def file_read(args: dict, output: Output) -> dict:
    path = _allowed_file(args)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return {"exists": False, "content": "", "hash": "absent"}
    except OSError as exc:
        raise CommandError(f"Cannot read {args['path']}: {exc}")
    with os.fdopen(fd, "rb") as f:
        data = f.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise CommandError("The file is too large.")
    return {"exists": True, "content": data.decode("utf-8", "replace"), "hash": _digest(data)}


def _existing(path: str, name: str, optional: bool) -> os.stat_result | None:
    st = os.lstat(path) if os.path.lexists(path) else None
    if st is None and optional:
        return None
    if st is None or not stat.S_ISREG(st.st_mode):
        raise CommandError(f"{name} does not exist or is not a regular file.", "not_found")
    return st


def file_write(args: dict, output: Output) -> dict:
    path = _allowed_file(args, write=True)
    content = _str(args, "content", MAX_FILE)
    expected = _str(args, "expected_hash", 80)
    if args["path"] == sa818.CONF:
        unsafe = [f for f in sa818.lint_text(content) if f["severity"] == "error"]
        if unsafe:
            line = unsafe[0]["line"]
            raise CommandError(f"{sa818.CONF} line {line}: {unsafe[0]['message']} Nothing was written.", "invalid")
    st = _existing(path, args["path"], args["path"] in OPTIONAL_FILES)
    current = _read(path) if st is not None else None
    if (_digest(current) if current is not None else "absent") != expected:
        raise CommandError(f"{args['path']} changed meanwhile. Nothing was written.", "conflict")
    if st is None:
        # A new optional file is configuration like web.ini: root's, readable by Allmon3.
        mode, uid, gid = 0o644, 0, 0
    else:
        mode, uid, gid = stat.S_IMODE(st.st_mode), st.st_uid, st.st_gid
    _atomic_write(path, content.encode("utf-8"), mode, uid, gid)
    return {"hash": _digest(content.encode("utf-8"))}


def file_delete(args: dict, output: Output) -> dict:
    path = _allowed_file(args)
    if args["path"] not in OPTIONAL_FILES:
        raise CommandError("That file cannot be removed.", "invalid")
    expected = _str(args, "expected_hash", 80)
    if _existing(path, args["path"], True) is None:
        return {"removed": False}
    if _digest(_read(path)) != expected:
        raise CommandError(f"{args['path']} changed meanwhile. Nothing was removed.", "conflict")
    os.unlink(path)
    return {"removed": True}


# ---- Allmon3 users ---------------------------------------------------------------
# /etc/allmon3/users is "user|pass" lines with argon2id hashes, read by
# Allmon3 with a csv.DictReader (so the header line is required). Written
# the way allmon3-passwd writes it.


def _users() -> tuple[str, os.stat_result, list[list[str]]]:
    path = _path(ALLMON3_USERS)
    st = _existing(path, ALLMON3_USERS, False)
    rows, first = [], True
    for row in csv.reader(io.StringIO((_read(path) or b"").decode("utf-8", "replace"), newline=""), delimiter="|"):
        if len(row) < 2:
            continue
        if first:
            first = False
            if [f.strip() for f in row[:2]] == ["user", "pass"]:
                continue
        rows.append([row[0], row[1]])
    return path, st, rows


def _write_users(path: str, st: os.stat_result, rows: list[list[str]]) -> None:
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, delimiter="|", lineterminator="\r\n")
    writer.writerow(["user", "pass"])
    writer.writerows(rows)
    _atomic_write(path, buf.getvalue().encode("utf-8"), stat.S_IMODE(st.st_mode), st.st_uid, st.st_gid)


def _allmon3_user(args: dict) -> str:
    user = _str(args, "user", 64)
    if not ALLMON3_USER_RE.match(user) or user == "user":
        raise CommandError("A user name may contain letters, numbers, _ . @ and - (and cannot be \"user\").",
                           "invalid")
    return user


def allmon3_users(args: dict, output: Output) -> dict:
    _, _, rows = _users()
    return {"users": [r[0] for r in rows]}


def allmon3_set_password(args: dict, output: Output) -> dict:
    user = _allmon3_user(args)
    password = _str(args, "password", 256)
    if len(password) < 8:
        raise CommandError("The password must have at least 8 characters.", "invalid")
    try:
        import argon2
    except ImportError:
        raise CommandError("python3-argon2 is not installed (it comes with Allmon3).", "unavailable")
    hashed = argon2.PasswordHasher(type=argon2.Type.ID).hash(password)
    path, st, rows = _users()
    existed = any(r[0] == user for r in rows)
    rows = [[r[0], hashed] if r[0] == user else r for r in rows] if existed else rows + [[user, hashed]]
    _write_users(path, st, rows)
    return {"created": not existed}


def allmon3_delete_user(args: dict, output: Output) -> dict:
    user = _allmon3_user(args)
    path, st, rows = _users()
    if not any(r[0] == user for r in rows):
        raise CommandError(f"Allmon3 has no user {user}.", "not_found")
    _write_users(path, st, [r for r in rows if r[0] != user])
    return {}


def fix_ownership(args: dict, output: Output) -> dict:
    """Give a file under /etc/asterisk back to the owner of /etc/asterisk."""
    name = _str(args, "path", 300)
    config = os.path.realpath(_path(CONFIG_DIR))
    path = os.path.normpath(os.path.join(config, name))
    if not path.startswith(config + os.sep) or os.path.realpath(path) != path:
        raise CommandError("Only files inside /etc/asterisk can be fixed.", "invalid")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise CommandError("No such file.", "not_found")
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise CommandError("Only regular files can be fixed.", "invalid")
        owner = os.stat(config)
        _chown(fd, owner.st_uid, owner.st_gid)
        mode = stat.S_IMODE(os.fstat(fd).st_mode)
        if not mode & stat.S_IWUSR:
            os.fchmod(fd, mode | stat.S_IWUSR | stat.S_IRUSR)
    finally:
        os.close(fd)
    return {"path": name}


# ---- SA818 RF modules (as sa818-menu) --------------------------------------------------

SA818_TOOL = sa818.TOOL


def _sa818_saved() -> tuple[bool, dict[str, str]]:
    data = _read(_path(sa818.CONF))
    return data is not None, sa818.parse(data.decode("utf-8", "replace") if data else "")


def sa818_read(args: dict, output: Output) -> dict:
    exists, settings = _sa818_saved()
    return {"saved": exists, "settings": settings, "ports": sa818.ports(ROOT),
            "tool": os.path.exists(SA818_TOOL)}


def _sa818_program(settings: dict[str, str], output: Output) -> tuple[bool, list[str]]:
    log = []
    for args in sa818.tool_args(settings):
        log.append("# sa818 " + " ".join(args))
        output(log[-1])
        ok, lines = sa818.run(SA818_TOOL, args)
        log += lines
        for line in lines:
            output(line)
        if not ok:
            return False, log
    return True, log


def sa818_apply(args: dict, output: Output) -> dict:
    """Save the settings to /etc/sa818.conf (as sa818-menu does) and program the module."""
    wanted = args.get("settings")
    if not isinstance(wanted, dict):
        raise CommandError("settings are required.", "invalid")
    try:
        settings = sa818.check(wanted, ports_exist=lambda p: os.path.exists(_path(p)))
    except sa818.Invalid as exc:
        raise CommandError(f"{exc.field}: {exc.message}", "invalid")
    exists, saved = _sa818_saved()
    changed = not exists or saved != settings
    if changed:
        path = _path(sa818.CONF)
        st = os.lstat(path) if os.path.lexists(path) else None
        if st is not None and not stat.S_ISREG(st.st_mode):
            raise CommandError(f"{sa818.CONF} is not a regular file.", "invalid")
        _atomic_write(path, sa818.render(settings).encode(), stat.S_IMODE(st.st_mode) if st else 0o644,
                      st.st_uid if st else 0, st.st_gid if st else 0)
    ok, log = _sa818_program(settings, output)
    return {"saved": changed, "programmed": ok, "log": log, "settings": settings}


def sa818_version(args: dict, output: Output) -> dict:
    """Ask the module for its firmware version: shows the connection works."""
    _, saved = _sa818_saved()
    base = []
    if saved["CURRENT_PORT"]:
        base += ["--port", saved["CURRENT_PORT"]]
    if saved["CURRENT_SPEED"]:
        base += ["--speed", saved["CURRENT_SPEED"]]
    ok, lines = sa818.run(SA818_TOOL, base + ["version"])
    firmware = next((m.group(1).strip() for line in lines if (m := re.search(r"Firmware (.*)$", line))), None)
    return {"ok": ok and firmware is not None, "firmware": firmware, "log": lines}


# ---- HTTPS and Let's Encrypt (Apache) ------------------------------------------------------


def _https(fn, *args):
    try:
        return fn(*args)
    except https.HttpsError as exc:
        message = f"{exc.field}: {exc.message}" if exc.field else exc.message
        raise CommandError(message, exc.code)


def https_status(args: dict, output: Output) -> dict:
    return _https(https.status, ROOT)


def https_install(args: dict, output: Output) -> dict:
    return _https(https.install_packages, output)


def https_enable_listener(args: dict, output: Output) -> dict:
    return _https(https.enable_listener, ROOT, output)


def https_obtain(args: dict, output: Output) -> dict:
    return _https(https.obtain, ROOT, args, output)


def https_redirect(args: dict, output: Output) -> dict:
    return _https(https.set_redirect, ROOT, args.get("redirect") is True, output)


def https_renew_test(args: dict, output: Output) -> dict:
    return _https(https.renew_test, ROOT, output)


def https_remove(args: dict, output: Output) -> dict:
    return _https(https.remove, ROOT, args.get("delete_certificate") is True, output)


# ---- Network interfaces and the appliance's fallback AP --------------------------------------


def _network(fn, *args):
    try:
        return fn(*args)
    except network.NetworkError as exc:
        raise CommandError(exc.message, exc.code)


def network_status(args: dict, output: Output) -> dict:
    return _network(network.status, ROOT)


def network_fallback_ap(args: dict, output: Output) -> dict:
    if not isinstance(args.get("enable"), bool):
        raise CommandError("enable must be true or false", "invalid")
    return _network(network.set_fallback_ap, ROOT, args["enable"])


# ---- 44Net Connect (WireGuard through NetworkManager, firewalld) ------------------------------


def _net44(fn, *args):
    try:
        return fn(*args)
    except net44.Net44Error as exc:
        raise CommandError(exc.message, exc.code)


def net44_status(args: dict, output: Output) -> dict:
    return _net44(net44.status, ROOT)


def net44_zone(args: dict, output: Output) -> dict:
    return _net44(net44.set_zone, ROOT, args)


def net44_configure(args: dict, output: Output) -> dict:
    return _net44(net44.configure, ROOT, args)


def net44_migrate(args: dict, output: Output) -> dict:
    return _net44(net44.migrate, ROOT, args)


def net44_mode(args: dict, output: Output) -> dict:
    return _net44(net44.set_mode, ROOT, args)


def net44_start(args: dict, output: Output) -> dict:
    return _net44(net44.start, ROOT, args)


def net44_confirm(args: dict, output: Output) -> dict:
    return _net44(net44.confirm, ROOT, args)


def net44_stop(args: dict, output: Output) -> dict:
    return _net44(net44.stop, ROOT, args)


def net44_remove(args: dict, output: Output) -> dict:
    return _net44(net44.remove, ROOT, args)


# ---- DAHDI ---------------------------------------------------------------------------------


def dahdi_remove(args: dict, output: Output) -> dict:
    """Uninstall dahdi-dkms once app_rpt no longer needs it (dahdi.py has the checks)."""
    try:
        return dahdi.remove(ROOT, output)
    except dahdi.DahdiError as exc:
        raise CommandError(exc.message, exc.code)


# ---- package lists -----------------------------------------------------------------------


def apt_update(args: dict, output: Output) -> dict:
    """Refresh apt's package lists (apt-get update), so the service can see pending updates."""
    try:
        code, text = dahdi.run([dahdi.APT_GET, "update"], output)
    except dahdi.DahdiError as exc:
        raise CommandError(exc.message, exc.code)
    if code != 0:
        raise CommandError(f"apt-get update failed (exit code {code}): {text[-400:]}")
    return {"updated": True}


COMMANDS = {
    "backup.create": backup_create,
    "backup.delete": backup_delete,
    "backup.read": backup_read,
    "backup.restore": backup_restore,
    "backup.import": backup_import,
    "backup.read_include_list": read_include_list,
    "backup.write_include_list": write_include_list,
    "factory.restore": factory_restore,
    "file.list": file_list,
    "file.read": file_read,
    "file.write": file_write,
    "file.delete": file_delete,
    "allmon3.users": allmon3_users,
    "allmon3.set_password": allmon3_set_password,
    "allmon3.delete_user": allmon3_delete_user,
    "asterisk.fix_ownership": fix_ownership,
    "sa818.read": sa818_read,
    "sa818.apply": sa818_apply,
    "sa818.version": sa818_version,
    "https.status": https_status,
    "https.install": https_install,
    "https.enable_listener": https_enable_listener,
    "https.obtain": https_obtain,
    "https.redirect": https_redirect,
    "https.renew_test": https_renew_test,
    "https.remove": https_remove,
    "network.status": network_status,
    "network.fallback_ap": network_fallback_ap,
    "net44.status": net44_status,
    "net44.zone": net44_zone,
    "net44.configure": net44_configure,
    "net44.migrate": net44_migrate,
    "net44.mode": net44_mode,
    "net44.start": net44_start,
    "net44.confirm": net44_confirm,
    "net44.stop": net44_stop,
    "net44.remove": net44_remove,
    "dahdi.remove": dahdi_remove,
    "apt.update": apt_update,
}
