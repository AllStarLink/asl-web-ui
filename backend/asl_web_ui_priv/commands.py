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

import grp
import hashlib
import os
import posixpath
import re
import stat
import subprocess
import tarfile
import tempfile
import time
from collections.abc import Callable

ROOT = "/"
BACKUP_DIR = "/var/asl-backups"
INCLUDE_LIST = "/var/asl-backups/asl-backup-files"
STAGING_DIR = "/var/lib/asl-web-ui/staging"
CONFIG_DIR = "/etc/asterisk"
MARKER = "etc/asterisk/rpt_http_registrations.conf"  # asl-backup-menu's "made on ASL3" check
# Files outside /etc/asterisk the web UI may read and replace.
FILE_ALLOWLIST = {"/etc/allmon3/allmon3.ini"}
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
        return None if info.name.endswith(".tgz") else info

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


def _allowed_file(args: dict) -> str:
    path = _str(args, "path", 200)
    if path not in FILE_ALLOWLIST:
        raise CommandError("That file cannot be accessed.", "invalid")
    return _path(path)


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


def file_write(args: dict, output: Output) -> dict:
    path = _allowed_file(args)
    content = _str(args, "content", MAX_FILE)
    expected = _str(args, "expected_hash", 80)
    st = os.lstat(path) if os.path.lexists(path) else None
    if st is None or not stat.S_ISREG(st.st_mode):
        raise CommandError(f"{args['path']} does not exist or is not a regular file.", "not_found")
    if _digest(_read(path)) != expected:
        raise CommandError(f"{args['path']} changed meanwhile. Nothing was written.", "conflict")
    _atomic_write(path, content.encode("utf-8"), stat.S_IMODE(st.st_mode), st.st_uid, st.st_gid)
    return {"hash": _digest(content.encode("utf-8"))}


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


COMMANDS = {
    "backup.create": backup_create,
    "backup.delete": backup_delete,
    "backup.read": backup_read,
    "backup.restore": backup_restore,
    "backup.import": backup_import,
    "backup.read_include_list": read_include_list,
    "backup.write_include_list": write_include_list,
    "factory.restore": factory_restore,
    "file.read": file_read,
    "file.write": file_write,
    "asterisk.fix_ownership": fix_ownership,
}
