#!/usr/bin/env python3
"""Stable local-root scheduler entrypoint; no flags or SSH invocation surface."""

import importlib.util
import os
import stat
import sys
from pathlib import Path

SUPERVISOR = Path("/root/bin/control-plane-supervisor.py")
ENV = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "HOME": "/root",
    "LANG": "C.UTF-8",
}


def admit(arguments, environment, uid):
    if uid != 0 or len(arguments) != 1 or any(key.startswith("SSH_") for key in environment):
        raise RuntimeError("LOCAL_SCHEDULE_ONLY")


def execute(supervisor):
    # Releases are immutable and retained. Pin once, then let the unchanged
    # backup runner acquire all existing locks itself; no inherited self-lock.
    activation = supervisor.activation()
    bundle = supervisor.bundle(activation["active"])
    script = bundle / "drive-backup.py"
    if not script.exists():
        raise RuntimeError("BACKUP_CAPABILITY_UNAVAILABLE")
    os.execve("/usr/bin/python3", ["python3", "-I", str(script)], ENV)


def main():
    admit(sys.argv, os.environ, os.geteuid())
    for path in (Path("/"), Path("/root"), SUPERVISOR.parent):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise RuntimeError("TRUSTED_DIRECTORY_REQUIRED")
    info = SUPERVISOR.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise RuntimeError("TRUSTED_SUPERVISOR_REQUIRED")
    spec = importlib.util.spec_from_file_location("stable_supervisor", SUPERVISOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    execute(module.Supervisor())


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        print("Scheduled backup refused; inspect private controller/backup state.")
        raise SystemExit(1) from None
