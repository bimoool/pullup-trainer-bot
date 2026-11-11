#!/usr/bin/env python3
"""One-time reviewed bootstrap; extends the existing key's forced dispatcher, never rotates keys."""

import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

BASE_DISPATCH = "9313be214b5dc1ad7756171d80f649b3394e1d50a92140a3980933be156706e5"
ROOT = Path("/root/bin")
BACKUPS = Path("/root/backups")
REPO = Path("/root/pullup-trainer-bot")


def ensure(condition, code="INSTALL_PRECONDITION"):
    if not condition:
        raise RuntimeError(code)


def check(path, directory=False):
    info = path.lstat()
    ensure(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
    ensure(info.st_uid == os.geteuid() and not info.st_mode & 0o022)


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def write_new(path, blob, mode=0o700):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "wb") as target:
        target.write(blob)
        os.fchmod(target.fileno(), mode)
        target.flush()
        os.fsync(target.fileno())


def atomic(path, blob):
    fd, temp = tempfile.mkstemp(prefix=".control-install-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as target:
            target.write(blob)
            os.fchmod(target.fileno(), 0o700)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def install(root, blobs, *, baseline_hash=BASE_DISPATCH, apply=False):
    check(root, directory=True)
    dispatcher = root / "prod-guarded-dispatch.sh"
    check(dispatcher)
    old = dispatcher.read_bytes()
    expected = blobs["prod-guarded-dispatch.sh"]
    backup = root / "prod-guarded-dispatch.before-cloud-control.sh"
    helper = root / "server-control.py"
    compile(blobs["server-control.py"], "server-control.py", "exec")
    if digest(old) == digest(expected):
        check(helper)
        ensure(helper.read_bytes() == blobs["server-control.py"])
        check(backup)
        ensure(digest(backup.read_bytes()) == baseline_hash)
        return {
            "installed": True,
            "changed": False,
            "dispatcher_sha256": digest(old),
            "helper_sha256": digest(helper.read_bytes()),
        }
    ensure(digest(old) == baseline_hash, "UNKNOWN_DISPATCHER")
    if helper.exists() or helper.is_symlink():
        check(helper)
        ensure(helper.read_bytes() == blobs["server-control.py"], "UNKNOWN_HELPER")
    if backup.exists() or backup.is_symlink():
        check(backup)
        ensure(backup.read_bytes() == old, "UNKNOWN_BACKUP")
    if not apply:
        return {
            "installed": False,
            "changed": False,
            "old_dispatcher_sha256": digest(old),
            "new_dispatcher_sha256": digest(expected),
            "helper_sha256": digest(blobs["server-control.py"]),
        }
    # Enable new routes only after the trusted helper is in place. Keep old policy bytes untouched.
    if not backup.exists():
        write_new(backup, old)
    if not helper.exists():
        write_new(helper, blobs["server-control.py"])
    ensure(helper.read_bytes() == blobs["server-control.py"])
    ensure(dispatcher.read_bytes() == old)
    atomic(dispatcher, expected)
    try:
        check(dispatcher)
        ensure(dispatcher.read_bytes() == expected)
        ensure(backup.read_bytes() == old)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError):
        atomic(dispatcher, old)
        raise
    return {
        "installed": True,
        "changed": True,
        "dispatcher_sha256": digest(expected),
        "helper_sha256": digest(blobs["server-control.py"]),
        "backup_sha256": digest(old),
    }


def main():
    os.umask(0o077)
    ensure(os.geteuid() == 0)
    ensure(len(sys.argv) == 3 and sys.argv[2] in {"--check", "--install"})
    sha = sys.argv[1]
    ensure(re.fullmatch("[0-9a-f]{40}", sha))
    for directory in [Path("/"), Path("/root"), ROOT, BACKUPS]:
        check(directory, directory=True)
    # Only already fetched/reviewed object bytes, never checkout, keys or candidate app execution.
    blobs = {
        name: subprocess.check_output(["git", "-C", str(REPO), "show", sha + ":deploy/" + name])
        for name in ["server-control.py", "prod-guarded-dispatch.sh"]
    }
    with tempfile.NamedTemporaryFile(dir=ROOT, prefix=".dispatcher-syntax-") as temp:
        temp.write(blobs["prod-guarded-dispatch.sh"])
        temp.flush()
        subprocess.run(
            ["bash", "-n", temp.name],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    descriptors = []
    for path in [
        BACKUPS / ".prod-actions.lock",
        BACKUPS / ".prod-guarded.lock",
        Path("/home/deploy/.deploy-staging.lock"),
    ]:
        # Staging lock belongs to deploy; preserve its existing inode and ownership.
        info = path.lstat()
        ensure(stat.S_ISREG(info.st_mode) and not info.st_mode & 0o022)
        if path.parent == BACKUPS:
            check(path)
        fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        descriptors.append(fd)
    for pattern in [
        "deploy-production-guarded-run[.]sh",
        "rollback-production-guarded[.]sh",
        "deploy-staging(-guarded)?-run[.]sh",
        "pg_dump",
        "pg_restore",
    ]:
        ensure(
            subprocess.run(
                ["pgrep", "-f", pattern], stdout=subprocess.DEVNULL, check=False
            ).returncode
            == 1
        )
    keys = Path("/root/.ssh/authorized_keys")
    check(keys)
    key_hash = digest(keys.read_bytes())
    runners = {
        name: digest((ROOT / name).read_bytes())
        for name in ["deploy-production-guarded-run.sh", "rollback-production-guarded.sh"]
    }
    result = install(ROOT, blobs, apply=sys.argv[2] == "--install")
    ensure(digest(keys.read_bytes()) == key_hash)
    ensure(all(digest((ROOT / name).read_bytes()) == value for name, value in runners.items()))
    print(json.dumps(dict(result, keys_unchanged=True, runners_unchanged=True, source_sha=sha)))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError):
        print(
            "Server-control installation refused; no keys rotated. Inspect the fixed preconditions."
        )
        raise SystemExit(1) from None
