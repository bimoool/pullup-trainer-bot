#!/usr/bin/env python3
"""One reviewed administrative conversion; never edits keys or starts services."""

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("/root/bin")
LEDGER = Path("/root/backups/cloud-controller")
REPO = Path("/root/pullup-trainer-bot")
CURRENT = {
    "prod-guarded-dispatch.sh": "daaa8e739e8a57518723193789c5911288e176ccbd2f7cf4ccfd62078b0db429",
    "server-control.py": "3c6061c60a452bb682f80aead0efc98c4cbdf1159c4b94ab623f616a657af5da",
    "deploy-production-guarded-run.sh": "c97a36be89bbce6782ca181a641327be69b3c27e1d91d1810da7a90b57fe4b35",
    "rollback-production-guarded.sh": "6286544abbe156e4d9725a005f37ecd9fb7e69ac34945a9fd1085e8a55a60bbd",
}


def load_supervisor(blob):
    # Only exact reviewed Git object bytes; never a path or upload supplied by SSH.
    with tempfile.TemporaryDirectory(prefix="reviewed-controller-") as directory:
        path = Path(directory) / "supervisor.py"
        path.write_bytes(blob)
        spec = importlib.util.spec_from_file_location("reviewed_supervisor", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def install(
    c, root, ledger, sha, tree, blobs, supervisor_blob, launcher_blob, *, apply=False, expected=None
):
    expected = CURRENT if expected is None else expected
    c.trusted(root, directory=True, private=True)
    c.trusted(ledger.parent, directory=True)
    c.validate_id(sha, c.SHA, "SHA")
    c.validate_id(tree, c.SHA, "TREE")
    c.require(set(blobs) == set(c.FILES) and set(expected) == set(c.FILES), "FILES")
    for name, value in {**blobs, "control-plane-entrypoint.sh": launcher_blob}.items():
        c.require(0 < len(value) <= 1048576, "SOURCE_SIZE")
        if name.endswith(".py"):
            compile(value, name, "exec")
        else:
            syntax = subprocess.run(["bash", "-n"], input=value, capture_output=True, check=False)
            c.require(syntax.returncode == 0, "SOURCE_SYNTAX")
    base = root / "control-plane"
    backup = root / "control-plane.bootstrap-before"
    supervisor = root / "control-plane-supervisor.py"
    launcher = root / "prod-guarded-dispatch.sh"
    for directory in (base, base / "releases", ledger):
        if directory.exists() or directory.is_symlink():
            c.trusted(directory, directory=True, private=True)
    for name in c.FILES:
        c.trusted(root / name, private=True)
    already = launcher.read_bytes() == launcher_blob
    for name, known in expected.items():
        original = backup / name if already and name == "prod-guarded-dispatch.sh" else root / name
        c.trusted(original, private=True)
        c.require(c.digest(original.read_bytes()) == known, "UNKNOWN_INSTALLED_FILE")
        if backup.exists() or backup.is_symlink():
            c.trusted(backup, directory=True, private=True)
            if (backup / name).exists() or (backup / name).is_symlink():
                c.trusted(backup / name, private=True)
                c.require(c.digest((backup / name).read_bytes()) == known, "UNKNOWN_BACKUP")
    for name in ("deploy-production-guarded-run.sh", "rollback-production-guarded.sh"):
        c.require(blobs[name] == (root / name).read_bytes(), "BOOTSTRAP_RUNNER_CHANGED")
    if supervisor.exists() or supervisor.is_symlink():
        c.trusted(supervisor, private=True)
        c.require(supervisor.read_bytes() == supervisor_blob, "UNKNOWN_SUPERVISOR")
    identities = {
        name: ((root / name).stat().st_ino, c.digest((root / name).read_bytes()))
        for name in c.FILES
        if name != "prod-guarded-dispatch.sh"
    }
    result = {
        "source_sha": sha,
        "installed": already,
        "changed": False,
        "keys_unchanged": True,
        "legacy_helpers_unchanged": True,
    }
    if not apply:
        return result
    for directory in (backup, base, base / "releases", ledger):
        if not directory.exists() and not directory.is_symlink():
            directory.mkdir(mode=0o700)
            c.sync_directory(directory.parent)
        c.trusted(directory, directory=True, private=True)
    for name in c.FILES:
        saved = backup / name
        if not saved.exists():
            c.atomic(
                saved,
                (root / name).read_bytes(),
                exclusive=True,
                mode=0o700,
                event="bootstrap-backup",
            )
    if not supervisor.exists():
        c.atomic(
            supervisor, supervisor_blob, exclusive=True, mode=0o700, event="bootstrap-supervisor"
        )
    control = c.Supervisor(base, ledger)
    reference = control.stage(sha, tree, blobs)
    initial = {
        "version": 1,
        "generation": 1,
        "active": reference,
        "previous": None,
        "operation_id": "bootstrap",
    }
    if (base / "active.json").exists() or (base / "active.json").is_symlink():
        c.require(control.activation() == initial, "UNKNOWN_ACTIVATION")
    else:
        control.activate(initial)
    control.bundle(reference)
    c.checkpoint("bootstrap-ready")
    if not already:
        c.require(
            c.digest(launcher.read_bytes()) == expected["prod-guarded-dispatch.sh"],
            "DISPATCHER_CHANGED",
        )
        c.atomic(launcher, launcher_blob, mode=0o700, event="bootstrap-launcher")
    for name, identity in identities.items():
        c.require(
            ((root / name).stat().st_ino, c.digest((root / name).read_bytes())) == identity,
            "PROTECTED_FILE_CHANGED",
        )
    c.require(
        launcher.read_bytes() == launcher_blob and supervisor.read_bytes() == supervisor_blob,
        "BOOTSTRAP_VERIFY",
    )
    return dict(result, installed=True, changed=not already)


def main():
    os.umask(0o077)
    if (
        os.geteuid() != 0
        or len(sys.argv) != 3
        or not re.fullmatch(r"[0-9a-f]{40}", sys.argv[1])
        or sys.argv[2] not in {"--check", "--install"}
    ):
        raise RuntimeError("ARGUMENTS")
    sha = sys.argv[1]

    def blob(name):
        return subprocess.check_output(
            ["git", "-C", str(REPO), "show", sha + ":deploy/" + name], stderr=subprocess.DEVNULL
        )

    supervisor_blob, launcher_blob = (
        blob("control-plane-supervisor.py"),
        blob("control-plane-entrypoint.sh"),
    )
    c = load_supervisor(supervisor_blob)
    for directory in (Path("/"), Path("/root"), ROOT, LEDGER.parent):
        c.trusted(directory, directory=True)
    c.require(
        c.run(["git", "-C", str(REPO), "remote", "get-url", "origin"]).decode().strip()
        in c.ORIGINS,
        "ORIGIN",
    )
    tree = c.run(["git", "-C", str(REPO), "rev-parse", sha + "^{tree}"]).decode().strip()
    main_tree = (
        c.run(["git", "-C", str(REPO), "rev-parse", "refs/remotes/origin/main^{tree}"])
        .decode()
        .strip()
    )
    c.require(tree == main_tree, "TRUSTED_MAIN_TREE")
    keys = Path("/root/.ssh/authorized_keys")
    c.trusted(keys, private=True)
    before = (keys.stat().st_ino, c.digest(keys.read_bytes()))
    with c.locks():
        c.not_busy()
        result = install(
            c,
            ROOT,
            LEDGER,
            sha,
            tree,
            {name: blob(name) for name in c.FILES},
            supervisor_blob,
            launcher_blob,
            apply=sys.argv[2] == "--install",
        )
        c.require((keys.stat().st_ino, c.digest(keys.read_bytes())) == before, "KEYS_CHANGED")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        SyntaxError,
        subprocess.SubprocessError,
    ):
        print("Controller bootstrap refused; inspect fixed preconditions privately.")
        raise SystemExit(1) from None
