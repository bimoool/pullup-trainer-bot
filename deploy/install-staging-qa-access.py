"""Install two staging QA commands without rotating keys or editing authorized_keys.

Run as root or deploy on the VPS, from a reviewed commit (see the runbook).
No workflow/SSH-key available to the cloud coordinator grants this installation right.
"""

import fcntl
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

HOME = Path("/home/deploy")
REPO = HOME / "pullup-trainer-bot-staging"


def regular(path):
    mode = path.lstat().st_mode
    if not stat.S_ISREG(mode):
        raise RuntimeError("Refusing non-regular server file")


def atomic(path, data, mode=0o755):
    fd, name = tempfile.mkstemp(prefix=".qa-install-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
            os.fchmod(out.fileno(), mode)
            owner = path.parent.stat()
            if os.geteuid() == 0:
                os.fchown(out.fileno(), owner.st_uid, owner.st_gid)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def install(home, helper, dispatcher):
    """Paths are fixed by main; tests use a private synthetic directory."""
    if home.is_symlink() or not home.is_dir():
        raise RuntimeError("Invalid staging home")
    target = home / "deploy-staging-dispatch.sh"
    backup = home / "deploy-staging-dispatch.before-qa.sh"
    qa = home / "qa-staging.sh"
    regular(target)
    current = target.read_bytes()
    for path in (backup, qa):
        if path.exists() or path.is_symlink():
            regular(path)
    # Never overwrite an unknown helper or a later dispatcher modification.
    if qa.exists() and qa.read_bytes() != helper:
        raise RuntimeError("Existing QA helper differs; preserve and review it")
    if backup.exists():
        if current not in (dispatcher, backup.read_bytes()):
            raise RuntimeError("Dispatcher changed since installation; refusing overwrite")
        if backup.read_bytes() == dispatcher:
            raise RuntimeError("Invalid recursive dispatcher backup")
    else:
        if current == dispatcher:
            raise RuntimeError("Installed dispatcher has no recovery copy")
        atomic(backup, current, stat.S_IMODE(target.stat().st_mode))
    atomic(qa, helper)
    atomic(target, dispatcher)


def main():
    if len(sys.argv) != 2 or not re.fullmatch("[0-9a-f]{40}", sys.argv[1]):
        raise RuntimeError("Usage: install-staging-qa-access.py <reviewed 40-hex SHA>")
    if os.geteuid() not in (0, HOME.stat().st_uid):
        raise RuntimeError("Run as root or the staging home owner")
    sha = sys.argv[1]
    payloads = []
    for path in ("deploy/qa-staging.sh", "deploy/staging-qa-access-dispatch.sh"):
        data = subprocess.check_output(["git", "-C", str(REPO), "show", f"{sha}:{path}"])
        subprocess.run(["bash", "-n"], input=data, check=True)
        payloads.append(data)
    lock = HOME / ".deploy-staging.lock"
    # Refuse symlinks; share the same lock used by staging deployment.
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if os.geteuid() == 0:
            owner = HOME.stat()
            os.fchown(fd, owner.st_uid, owner.st_gid)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        install(HOME, *payloads)
    finally:
        os.close(fd)
    print("Staging QA access installed; existing keys and deployment rules preserved.")
    print("No profiles provisioned and no services changed. Verify via the guarded QA workflow.")


if __name__ == "__main__":
    main()
