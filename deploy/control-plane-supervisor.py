#!/usr/bin/env python3
"""Stable root trust anchor: complete reviewed bundles, one activation, local recovery.

No command, source URL, filesystem path or environment override is accepted from SSH.
Keep this file independent of the replaceable controller and application imports.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path("/root/bin/control-plane")
LEDGER = Path("/root/backups/cloud-controller")
REPO = Path("/root/pullup-trainer-bot")
LOCKS = (
    Path("/root/backups/.prod-actions.lock"),
    Path("/root/backups/.prod-guarded.lock"),
    Path("/home/deploy/.deploy-staging.lock"),
)
FILES = (
    "prod-guarded-dispatch.sh",
    "server-control.py",
    "deploy-production-guarded-run.sh",
    "rollback-production-guarded.sh",
)
OPTIONAL_FILES = ("drive-backup.py",)
SHA = r"[0-9a-f]{40}"
HASH = r"[0-9a-f]{64}"
OP = r"ops-[1-9][0-9]{0,19}"
ORIGINS = {
    "https://github.com/bimoool/pullup-trainer-bot.git",
    "git@github.com:bimoool/pullup-trainer-bot.git",
}


class Refused(RuntimeError):
    """Only fixed diagnostic codes may leave this process."""


def require(value, code):
    if not value:
        raise Refused(code)


def checkpoint(stage):
    """No production switches; subprocess tests replace this function to SIGKILL."""


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def trusted(path, *, directory=False, private=False):
    info = path.lstat()
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    require(kind(info.st_mode) and info.st_uid == os.geteuid(), "UNTRUSTED_PATH")
    require(not info.st_mode & (0o077 if private else 0o022), "UNTRUSTED_MODE")
    return info


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def read_json(path):
    info = trusted(path, private=True)
    require(0 < info.st_size <= 32768, "RECORD_SIZE")
    value = json.loads(path.read_bytes())
    require(isinstance(value, dict), "RECORD_TYPE")
    return value


def atomic(path, blob, *, exclusive=False, mode=0o600, event="record"):
    """Publish complete bytes. Exclusive claims never expose a partly written JSON."""
    trusted(path.parent, directory=True, private=True)
    if path.exists() or path.is_symlink():
        trusted(path, private=True)
    fd, name = tempfile.mkstemp(prefix=".controller-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as target:
            os.fchmod(target.fileno(), mode)
            target.write(blob)
            target.flush()
            os.fsync(target.fileno())
        checkpoint(event + "-file-synced")
        if exclusive:
            try:
                os.link(name, path, follow_symlinks=False)
            except FileExistsError:
                return False
        else:
            os.replace(name, path)
        checkpoint(event + "-published")
        sync_directory(path.parent)
        checkpoint(event + "-directory-synced")
        return True
    finally:
        if os.path.exists(name):
            os.unlink(name)


def validate_id(value, pattern, code):
    require(isinstance(value, str) and re.fullmatch(pattern, value), code)
    return value


def manifest(sha, tree, blobs):
    validate_id(sha, SHA, "SHA")
    validate_id(tree, SHA, "TREE_SHA")
    require(set(FILES) <= set(blobs) <= {*FILES, *OPTIONAL_FILES}, "SOURCE_FILES")
    return {
        "version": 1,
        "source_sha": sha,
        "tree_sha": tree,
        "files": {name: digest(blob) for name, blob in blobs.items()},
    }


class Store:
    def __init__(self, root):
        self.root = root
        trusted(root, directory=True, private=True)

    def path(self, operation):
        return self.root / (validate_id(operation, OP, "OPERATION") + ".json")

    def get(self, operation):
        path = self.path(operation)
        if not path.exists() and not path.is_symlink():
            return None
        record = read_json(path)
        require(record.get("operation_id") == operation, "RECEIPT_BINDING")
        return record

    def claim(self, record):
        path = self.path(record["operation_id"])
        return atomic(path, encoded(record), exclusive=True, event="claim")

    def write(self, record):
        path = self.path(record["operation_id"])
        trusted(path, private=True)
        atomic(path, encoded(record), event="receipt")


def public(record):
    return {key: value for key, value in record.items() if key not in {"before", "after"}}


def run(args, timeout=30):
    result = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    require(result.returncode == 0, "COMMAND_FAILED")
    return result.stdout


@contextlib.contextmanager
def locks(paths=LOCKS):
    descriptors = []
    try:
        for path in paths:
            info = path.lstat()
            require(stat.S_ISREG(info.st_mode), "LOCK_PATH")
            if path == LOCKS[-1]:
                owner = pwd.getpwnam("deploy")
                parent = path.parent.lstat()
                require(
                    stat.S_ISDIR(parent.st_mode)
                    and parent.st_uid == owner.pw_uid
                    and parent.st_gid == owner.pw_gid
                    and not parent.st_mode & 0o002,
                    "LOCK_PARENT",
                )
                require(info.st_uid == owner.pw_uid and info.st_gid == owner.pw_gid, "LOCK_OWNER")
                require(not info.st_mode & 0o113 and info.st_mode & 0o600 == 0o600, "LOCK_MODE")
            else:
                trusted(path)
            fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
            descriptors.append(fd)
            require(
                (os.fstat(fd).st_dev, os.fstat(fd).st_ino) == (info.st_dev, info.st_ino),
                "LOCK_CHANGED",
            )
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Refused("BUSY") from None
            require(path.lstat().st_ino == info.st_ino, "LOCK_CHANGED")
        yield descriptors
    finally:
        for fd in descriptors:
            os.close(fd)


def not_busy():
    for pattern in (
        "deploy-production-guarded-run[.]sh",
        "rollback-production-guarded[.]sh",
        "deploy-staging(-guarded)?-run[.]sh",
        "deploy-run[.]sh",
        "pg_dump",
        "pg_restore",
    ):
        result = subprocess.run(["pgrep", "-f", pattern], capture_output=True, check=False)
        require(result.returncode == 1, "CONCURRENT_OPERATION")
    require(
        not run(["docker", "ps", "-aq", "--filter", "label=guarded.run"]).strip(),
        "GUARDED_ONEOFF",
    )


def source(sha):
    validate_id(sha, SHA, "SHA")
    require(
        run(["git", "-C", str(REPO), "remote", "get-url", "origin"]).decode().strip() in ORIGINS,
        "ORIGIN",
    )
    run(
        [
            "git",
            "-C",
            str(REPO),
            "fetch",
            "--no-tags",
            "--no-write-fetch-head",
            "origin",
            "main:refs/remotes/origin/main",
        ],
        timeout=60,
    )
    tree = run(["git", "-C", str(REPO), "rev-parse", sha + "^{tree}"]).decode().strip()
    main = (
        run(["git", "-C", str(REPO), "rev-parse", "refs/remotes/origin/main^{tree}"])
        .decode()
        .strip()
    )
    require(tree == main and re.fullmatch(SHA, tree), "TRUSTED_MAIN_TREE")
    blobs = {}
    for name in (*FILES, *OPTIONAL_FILES):
        entry = run(["git", "-C", str(REPO), "ls-tree", sha, "--", "deploy/" + name]).decode()
        if not entry and name in OPTIONAL_FILES:
            continue
        require(
            re.fullmatch(
                r"100(?:644|755) blob " + SHA + r"\tdeploy/" + re.escape(name) + r"\n", entry
            ),
            "SOURCE_MODE",
        )
        blobs[name] = run(["git", "-C", str(REPO), "show", sha + ":deploy/" + name])
    return tree, blobs


class Supervisor:
    def __init__(self, base=BASE, ledger=LEDGER):
        self.base, self.releases = base, base / "releases"
        trusted(base, directory=True, private=True)
        trusted(self.releases, directory=True, private=True)
        self.store = Store(ledger)

    def activation(self):
        value = read_json(self.base / "active.json")
        require(
            set(value) == {"version", "generation", "active", "previous", "operation_id"},
            "ACTIVATION_FIELDS",
        )
        require(
            value["version"] == 1 and type(value["generation"]) is int and value["generation"] > 0,
            "ACTIVATION_VERSION",
        )
        require(
            value["operation_id"] == "bootstrap" or re.fullmatch(OP, value["operation_id"]),
            "ACTIVATION_OPERATION",
        )
        for reference in (value["active"], value["previous"]):
            if reference is None:
                require(reference is value["previous"], "ACTIVE_REQUIRED")
                continue
            require(
                isinstance(reference, dict) and set(reference) == {"sha", "manifest_sha256"},
                "BUNDLE_REFERENCE",
            )
            validate_id(reference["sha"], SHA, "BUNDLE_SHA")
            validate_id(reference["manifest_sha256"], HASH, "MANIFEST_HASH")
        return value

    def bundle(self, reference):
        path = self.releases / reference["sha"]
        trusted(path, directory=True, private=True)
        manifest_path = path / "bundle.json"
        manifest = read_json(manifest_path)
        require(
            digest(manifest_path.read_bytes()) == reference["manifest_sha256"], "MANIFEST_CHANGED"
        )
        require(
            set(manifest) == {"version", "source_sha", "tree_sha", "files"}
            and manifest["version"] == 1,
            "MANIFEST_FIELDS",
        )
        require(manifest["source_sha"] == reference["sha"], "MANIFEST_SOURCE")
        validate_id(manifest["tree_sha"], SHA, "TREE_SHA")
        require(
            isinstance(manifest["files"], dict)
            and set(FILES) <= set(manifest["files"]) <= {*FILES, *OPTIONAL_FILES},
            "MANIFEST_FILES",
        )
        require(
            {item.name for item in path.iterdir()} == {*manifest["files"], "bundle.json"},
            "BUNDLE_FILES",
        )
        for name in manifest["files"]:
            info = trusted(path / name, private=True)
            validate_id(manifest["files"][name], HASH, "FILE_HASH")
            require(
                0 < info.st_size <= 1048576
                and digest((path / name).read_bytes()) == manifest["files"][name],
                "BUNDLE_CHANGED",
            )
        return path

    def stage(self, sha, tree, blobs):
        metadata = manifest(sha, tree, blobs)
        reference = {"sha": sha, "manifest_sha256": digest(encoded(metadata))}
        destination = self.releases / sha
        if destination.exists() or destination.is_symlink():
            self.bundle(reference)
            return reference
        staged = Path(tempfile.mkdtemp(prefix=".staged-", dir=self.releases))
        try:
            for name in blobs:
                blob = blobs[name]
                require(0 < len(blob) <= 1048576, "SOURCE_SIZE")
                if name.endswith(".py"):
                    compile(blob, name, "exec")
                atomic(staged / name, blob, exclusive=True, mode=0o700, event="bundle-file")
                if name.endswith(".sh"):
                    run(["bash", "-n", str(staged / name)])
            atomic(staged / "bundle.json", encoded(metadata), exclusive=True, event="manifest")
            sync_directory(staged)
            checkpoint("bundle-before-rename")
            os.rename(staged, destination)
            checkpoint("bundle-renamed")
            sync_directory(self.releases)
            checkpoint("bundle-directory-synced")
            self.bundle(reference)
            return reference
        finally:
            if staged.exists():
                shutil.rmtree(staged)

    def activate(self, value):
        self.bundle(value["active"])
        atomic(self.base / "active.json", encoded(value), event="activation")

    def status(self, sha, operation):
        record = self.store.get(operation)
        require(record is not None and record.get("candidate") == sha, "RECEIPT_BINDING")
        # Remains readable even when active bundle bytes/dispatcher are broken.
        result = public(record)
        try:
            current = self.activation()
            result["active_sha"] = current["active"]["sha"]
            result["generation"] = current["generation"]
        except (Refused, OSError, ValueError, KeyError, TypeError):
            result["activation_unknown"] = True
        return result

    def operate(self, action, sha, operation, original=None):
        validate_id(sha, SHA, "SHA")
        validate_id(operation, OP, "OPERATION")
        require(action in {"adopt", "recover"}, "ACTION")
        if action == "recover":
            validate_id(original, OP, "ORIGINAL_OPERATION")
            require(original != operation, "RECOVERY_OPERATION")
        existing = self.store.get(operation)
        if existing is not None:
            require(
                (existing.get("candidate"), existing.get("action"), existing.get("original"))
                == (sha, action, original),
                "RECEIPT_BINDING",
            )
            return public(existing)
        record = {
            "operation_id": operation,
            "candidate": sha,
            "action": action,
            "original": original,
            "state": "RUNNING",
            "stage": "claimed",
            "next_step": "controller-status",
        }
        try:
            with locks():
                not_busy()
                current = self.activation()
                record["before"] = current
                if not self.store.claim(record):
                    return self.operate(action, sha, operation, original)
                checkpoint("claimed")
                if action == "adopt":
                    self.bundle(current["active"])
                    if current["operation_id"] != "bootstrap":
                        prior = self.store.get(current["operation_id"])
                        require(
                            prior is not None and prior.get("state") == "VERIFIED",
                            "RECOVERY_REQUIRED",
                        )
                    tree, blobs = source(sha)
                    reference = {
                        "sha": sha,
                        "manifest_sha256": digest(encoded(manifest(sha, tree, blobs))),
                    }
                    after = {
                        "version": 1,
                        "generation": current["generation"] + 1,
                        "active": reference,
                        "previous": current["active"],
                        "operation_id": operation,
                    }
                    record.update(after=after, stage="staging")
                    self.store.write(record)
                    self.stage(sha, tree, blobs)
                else:
                    adoption = self.store.get(original)
                    require(
                        adoption is not None
                        and adoption.get("action") == "adopt"
                        and adoption.get("candidate") == sha,
                        "ADOPTION_BINDING",
                    )
                    before, attempted = adoption.get("before"), adoption.get("after")
                    require(isinstance(before, dict), "RECOVERY_JOURNAL")
                    self.bundle(before["active"])
                    if current == before:
                        after = current  # Never switched, or failed before staging.
                    elif attempted is not None and current == attempted:
                        after = {
                            "version": 1,
                            "generation": current["generation"] + 1,
                            "active": before["active"],
                            "previous": current["active"],
                            "operation_id": operation,
                        }
                    else:
                        prior = self.store.get(current["operation_id"])
                        require(
                            prior is not None
                            and prior.get("action") == "recover"
                            and prior.get("original") == original
                            and prior.get("after") == current
                            and current["active"] == before["active"],
                            "RECOVERY_STATE_CHANGED",
                        )
                        # A previous recovery switched before losing its receipt. Reconcile
                        # metadata only, without executing or switching the bundle again.
                        prior.update(
                            state="VERIFIED", stage="recovered", next_step="controller-status"
                        )
                        self.store.write(prior)
                        after = current
                    record.update(after=after, stage="recovering")
                    self.store.write(record)
                if after != current:
                    require(self.activation() == current, "ACTIVATION_CHANGED")
                    self.activate(after)
                checkpoint("before-final-receipt")
                record.update(
                    state="VERIFIED",
                    stage="adopted" if action == "adopt" else "recovered",
                    next_step="controller-status",
                    active_sha=after["active"]["sha"],
                    generation=after["generation"],
                )
                self.store.write(record)
                return public(record)
        except (
            Refused,
            OSError,
            ValueError,
            KeyError,
            TypeError,
            SyntaxError,
            subprocess.SubprocessError,
        ) as exc:
            error = str(exc) if isinstance(exc, Refused) else "INTERNAL_FAILURE"
            stored = self.store.get(operation)
            if stored is None:
                record.pop("before", None)
                record.update(state="BLOCKED", stage="guard", error=error)
                self.store.claim(record)
                stored = self.store.get(operation)
            else:
                stored.update(state="FAILED", error=error, next_step="controller-recover")
                self.store.write(stored)
            return public(stored)


def allowed_delegate(command):
    patterns = (
        rf"prod-control [a-z][a-z-]{{0,39}} {SHA} {OP}",
        rf"prod-guarded {SHA} preflight [0-9a-f]{{12}} [0-9a-f]{{12}}",
        rf"prod-guarded {SHA} apply [0-9a-f]{{12}} [0-9a-f]{{12}} PRODUCTION-APPLY-[0-9a-f]{{12}}",
        r"prod-rollback R[13] /root/backups/[A-Za-z0-9._-]+\.manifest check",
        r"prod-rollback R[13] /root/backups/[A-Za-z0-9._-]+\.manifest apply ROLLBACK-R[13]-prod-[0-9a-f]{7}-[0-9TZ]+-[0-9]+",
    )
    return ".." not in command and any(re.fullmatch(pattern, command) for pattern in patterns)


def delegate(supervisor, command):
    require(allowed_delegate(command), "COMMAND")
    receipt = re.fullmatch(rf"prod-control receipt {SHA} {OP}", command)
    context = contextlib.nullcontext([]) if receipt else locks(LOCKS[:1])
    with context as descriptors:
        active = supervisor.activation()
        bundle = supervisor.bundle(active["active"])
        environment = {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "HOME": "/root",
            "LANG": "C.UTF-8",
            "SSH_ORIGINAL_COMMAND": command,
        }
        if descriptors:
            os.dup2(descriptors[0], 9, inheritable=True)
            environment["PULLUP_CONTROL_LOCK_FD"] = "9"
        os.execve("/usr/bin/bash", ["bash", str(bundle / "prod-guarded-dispatch.sh")], environment)


def main():
    os.umask(0o077)
    require(os.geteuid() == 0, "ROOT_REQUIRED")
    require(len(sys.argv) == 1, "ARGUMENTS")
    for path in (Path("/"), Path("/root"), Path("/root/bin"), Path("/root/backups")):
        trusted(path, directory=True)
    command = os.environ.get("SSH_ORIGINAL_COMMAND", "")
    require(len(command) <= 512, "COMMAND_SIZE")
    supervisor = Supervisor()
    match = re.fullmatch(rf"prod-controller (adopt|status) ({SHA}) ({OP})", command)
    recovery = re.fullmatch(rf"prod-controller recover ({SHA}) ({OP}) ({OP})", command)
    if match:
        action, sha, operation = match.groups()
        result = (
            supervisor.status(sha, operation)
            if action == "status"
            else supervisor.operate(action, sha, operation)
        )
    elif recovery:
        sha, original, operation = recovery.groups()
        result = supervisor.operate("recover", sha, operation, original)
    else:
        delegate(supervisor, command)
        return
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (Refused, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print('{"state":"REFUSED","error":"SUPERVISOR_GUARD"}')
        raise SystemExit(1) from None
