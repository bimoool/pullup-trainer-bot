#!/usr/bin/env python3
"""Installed root-only, exact allowlist. No candidate code execution or user output."""

from __future__ import annotations

import errno
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
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path("/root/pullup-trainer-bot")
BIN = Path(__file__).resolve().parent
BACKUPS = Path("/root/backups")
LEDGER = BACKUPS / "cloud-operations"
STAGING_LOCK = Path("/home/deploy/.deploy-staging.lock")
ACTIONS = {"readiness", "prepare", "restore", "receipt", "adopt-runner"}
AUTHORIZED_KEYS = Path("/root/.ssh/authorized_keys")
INITIAL_RUNNER_HASH = "7a1d42c1653fc443095b28809b888f110a3110b875eed58ecd5affc4f70d0dde"
SHA_RE = r"[0-9a-f]{40}"
OP_RE = r"ops-[1-9][0-9]{0,19}"
RUNNERS = (
    "deploy-production-guarded-run.sh",
    "rollback-production-guarded.sh",
    "prod-guarded-dispatch.sh",
)
STAGING_ROOT_UID = 0
STAGING_RUNNER_LIMIT = 262144


class Refused(Exception):
    """Only fixed codes are exported. Subprocess output is never exception text."""


def require(value, code):
    if not value:
        raise Refused(code)


def parse_args(args):
    require(len(args) == 3, "ARGUMENTS")
    action, sha, operation = args
    require(action in ACTIONS, "ACTION")
    require(re.fullmatch(SHA_RE, sha) is not None, "SHA")
    require(re.fullmatch(OP_RE, operation) is not None, "OPERATION_ID")
    return action, sha, operation


def now():
    return datetime.now(UTC).isoformat()


def regular(path):
    st = path.lstat()
    require(
        stat.S_ISREG(st.st_mode) and st.st_uid == os.geteuid() and not st.st_mode & 0o022,
        "UNTRUSTED_FILE",
    )
    return st


def trusted_directory(path):
    st = path.lstat()
    require(
        stat.S_ISDIR(st.st_mode) and st.st_uid == os.geteuid() and not st.st_mode & 0o022,
        "UNTRUSTED_DIRECTORY",
    )


class Receipts:
    def __init__(self, root):
        self.root = root
        trusted_directory(root)

    def path(self, operation):
        require(re.fullmatch(OP_RE, operation) is not None, "OPERATION_ID")
        return self.root / (operation + ".json")

    def read(self, operation):
        path = self.path(operation)
        regular(path)
        require(path.stat().st_size <= 32768, "RECEIPT_SIZE")
        return json.loads(path.read_text())

    def claim(self, operation, action, sha):
        path = self.path(operation)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            old = self.read(operation)
            require(old.get("candidate") == sha and old.get("action") == action, "RECEIPT_BINDING")
            return old  # RUNNING/FAILED/UNKNOWN is never automatically replayed.
        with os.fdopen(fd, "w") as target:
            json.dump(
                {
                    "operation_id": operation,
                    "action": action,
                    "candidate": sha,
                    "stage": "claimed",
                    "state": "RUNNING",
                    "observed_at": now(),
                    "next_step": "query-receipt",
                },
                target,
            )
            target.flush()
            os.fsync(target.fileno())
        sync_directory(self.root)
        return None

    def write(self, operation, data):
        path = self.path(operation)
        regular(path)
        fd, name = tempfile.mkstemp(prefix=".receipt-", dir=self.root)
        try:
            with os.fdopen(fd, "w") as target:
                os.fchmod(target.fileno(), 0o600)
                json.dump(data, target, sort_keys=True)
                target.flush()
                os.fsync(target.fileno())
            regular(path)
            os.replace(name, path)
            sync_directory(self.root)
        finally:
            if os.path.exists(name):
                os.unlink(name)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def private_file(path):
    info = regular(path)
    require(not info.st_mode & 0o077, "PRIVATE_FILE_REQUIRED")
    return info


def atomic_private(path, blob, mode=0o600):
    fd, name = tempfile.mkstemp(prefix=".runner-adopt-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as target:
            os.fchmod(target.fileno(), mode)
            target.write(blob)
            target.flush()
            os.fsync(target.fileno())
        os.replace(name, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def adopt_runner(sha, operation):
    # Versioned bundles activate together through the independent stable supervisor.
    require(BIN.parent != Path("/root/bin/control-plane/releases"), "CONTROLLER_BUNDLE_REQUIRED")
    # Called only after the durable operation claim, all three locks and busy checks.
    # Fixed source and destination; no candidate program is executed (bash -n only).
    runner = BIN / "deploy-production-guarded-run.sh"
    protected = [
        BIN / name
        for name in [
            "server-control.py",
            "prod-guarded-dispatch.sh",
            "rollback-production-guarded.sh",
        ]
    ] + [AUTHORIZED_KEYS]
    before = {}
    for path in [runner, *protected]:
        info = private_file(path)
        before[path] = (info.st_dev, info.st_ino, sha256(path))
    state_path = LEDGER / "runner-adopted.json"
    expected = INITIAL_RUNNER_HASH
    if state_path.exists() or state_path.is_symlink():
        private_file(state_path)
        state = json.loads(state_path.read_text())
        require(state.get("state") == "VERIFIED", "ADOPTION_UNCERTAIN")
        expected = state.get("runner_sha256")
        require(
            isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected), "ADOPTION_STATE"
        )
    origin = command(["git", "-C", str(REPO), "remote", "get-url", "origin"]).decode().strip()
    require(
        origin
        in {
            "https://github.com/bimoool/pullup-trainer-bot.git",
            "git@github.com:bimoool/pullup-trainer-bot.git",
        },
        "ORIGIN",
    )
    # Candidate must already exist (execute checks this). Fetch only the fixed trusted
    # main ref, never a caller-controlled object/ref/URL; no checkout or service change.
    command(
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
    candidate_tree = command(["git", "-C", str(REPO), "rev-parse", sha + "^{tree}"]).strip()
    trusted_tree = command(
        ["git", "-C", str(REPO), "rev-parse", "refs/remotes/origin/main^{tree}"]
    ).strip()
    require(
        candidate_tree == trusted_tree and re.fullmatch(rb"[0-9a-f]{40}", candidate_tree),
        "TRUSTED_MAIN_TREE",
    )
    blob = command(
        ["git", "-C", str(REPO), "show", sha + ":deploy/deploy-production-guarded-run.sh"]
    )
    require(0 < len(blob) <= 262144, "RUNNER_SIZE")
    candidate = hashlib.sha256(blob).hexdigest()
    old = runner.read_bytes()
    actual = hashlib.sha256(old).hexdigest()
    require(actual in {expected, candidate}, "UNKNOWN_RUNNER")
    # The temp is root-only and discarded without execution.
    with tempfile.NamedTemporaryFile(prefix=".runner-syntax-", dir=LEDGER) as syntax:
        syntax.write(blob)
        syntax.flush()
        command(["bash", "-n", syntax.name])
    backup = LEDGER / (operation + ".runner-before")
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as target:
        target.write(old)
        target.flush()
        os.fsync(target.fileno())
    sync_directory(LEDGER)
    state = {
        "state": "RUNNING",
        "operation_id": operation,
        "candidate": sha,
        "runner_sha256": candidate,
        "previous_sha256": actual,
    }
    atomic_private(state_path, json.dumps(state, sort_keys=True).encode())
    # Refuse intervening file changes; locks also serialize every supported entry point.
    for path, identity in before.items():
        info = private_file(path)
        require((info.st_dev, info.st_ino, sha256(path)) == identity, "INSTALLATION_CHANGED")
    if actual != candidate:
        atomic_private(runner, blob, 0o700)
    require(sha256(runner) == candidate, "RUNNER_VERIFY")
    private_file(runner)
    for path in protected:
        info = private_file(path)
        require((info.st_dev, info.st_ino, sha256(path)) == before[path], "PROTECTED_FILE_CHANGED")
    state["state"] = "VERIFIED"
    atomic_private(state_path, json.dumps(state, sort_keys=True).encode())
    return {
        "runner_adopted": True,
        "previous_sha256": actual,
        "runner_sha256": candidate,
        "protected_files_unchanged": True,
    }


def restore_budget(available_ram_mib, free_disk_mib, database_mib):
    require(0 < database_mib <= 1024, "DATABASE_BUDGET")
    # tmpfs is capped and charged to the isolated container's memory cgroup.
    data_mib = max(256, database_mib * 4 + 128)
    require(data_mib <= 1024, "RESTORE_DISK_BUDGET")
    required_disk = 3072 + data_mib + max(256, database_mib * 2)
    require(available_ram_mib >= 784, "RAM_RESERVE")
    require(free_disk_mib >= required_disk, "DISK_RESERVE")
    return {
        "required_ram_mib": 784,
        "required_disk_mib": required_disk,
        "pg_memory_mib": 256,
        "data_limit_mib": data_mib,
    }


def restore_container_args(name, image, data_mib):
    require(
        re.fullmatch(r"pullup-restore-ops-[1-9][0-9]{0,19}", name) is not None, "CONTAINER_NAME"
    )
    require(re.fullmatch(r"sha256:[0-9a-f]{64}", image) is not None, "IMAGE_ID")
    require(256 <= data_mib <= 1024, "DATA_LIMIT")
    return [
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "--label",
        "pullup.control.operation=" + name.removeprefix("pullup-restore-"),
        "--network",
        "none",
        "--memory",
        "256m",
        "--memory-swap",
        "256m",
        "--cpus",
        "0.5",
        "--pids-limit",
        "128",
        "--restart",
        "no",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "999:999",
        "--tmpfs",
        f"/var/lib/postgresql/data:rw,nosuid,nodev,noexec,size={data_mib}m,uid=999,gid=999,mode=0700",
        "--tmpfs",
        "/var/run/postgresql:rw,nosuid,nodev,noexec,size=8m,uid=999,gid=999,mode=0700",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,noexec,size=16m,mode=1777",
        "-e",
        "POSTGRES_HOST_AUTH_METHOD=trust",
        "-e",
        "POSTGRES_DB=verify",
        image,
        "postgres",
        "-c",
        "shared_buffers=32MB",
        "-c",
        "max_connections=8",
        "-c",
        "maintenance_work_mem=16MB",
        "-c",
        "work_mem=2MB",
        "-c",
        "max_wal_size=128MB",
        "-c",
        "min_wal_size=32MB",
        "-c",
        "temp_file_limit=65536",
    ]


def command(args, timeout=25):
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise Refused("COMMAND_TIMEOUT") from None
    require(result.returncode == 0, "COMMAND_FAILED")
    return result.stdout


def sha256(path):
    regular(path)
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def resources():
    mem = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    return int(mem["MemAvailable"].split()[0]) // 1024, shutil.disk_usage(REPO).free // 1048576


def acquire_existing(path):
    expected = path.stat()
    require(not path.is_symlink() and stat.S_ISREG(expected.st_mode), "LOCK_PATH")
    # Reuse the dispatcher's inherited open-file description; opening again would self-deadlock.
    for item in Path("/proc/self/fd").iterdir():
        try:
            current = os.fstat(int(item.name))
            if (current.st_dev, current.st_ino) == (expected.st_dev, expected.st_ino):
                fd = os.dup(int(item.name))
                break
        except OSError:
            continue
    else:
        fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    require(
        (os.fstat(fd).st_dev, os.fstat(fd).st_ino) == (expected.st_dev, expected.st_ino),
        "LOCK_CHANGED",
    )
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise Refused("BUSY") from None
    return fd


def no_other_operations():
    for pattern in [
        "deploy-production-guarded-run[.]sh",
        "rollback-production-guarded[.]sh",
        "deploy-staging(-guarded)?-run[.]sh",
        "deploy-run[.]sh",
        "pg_restore",
        "pg_dump",
    ]:
        require(
            subprocess.run(
                ["pgrep", "-f", pattern],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            ).returncode
            == 1,
            "CONCURRENT_OPERATION",
        )
    require(
        not command(["docker", "ps", "-aq", "--filter", "label=guarded.run"]).strip(),
        "GUARDED_ONEOFF",
    )


def object_present(sha):
    return (
        subprocess.run(
            ["git", "-C", str(REPO), "cat-file", "-e", sha + "^{commit}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )


def service(name):
    ids = (
        command(
            [
                "docker",
                "ps",
                "-aq",
                "--filter",
                "label=com.docker.compose.project=pullup-trainer-bot",
                "--filter",
                "label=com.docker.compose.service=" + name,
            ]
        )
        .decode()
        .splitlines()
    )
    require(len(ids) == 1, "SERVICE_COUNT")
    item = json.loads(command(["docker", "inspect", "--format", "{{json .}}", ids[0]]))
    labels = item["Config"]["Labels"]
    require(labels.get("com.docker.compose.project.working_dir") == str(REPO), "PROJECT_PATH")
    require(
        labels.get("com.docker.compose.project.config_files") == str(REPO / "docker-compose.yml"),
        "COMPOSE_PATH",
    )
    require(item["State"]["Running"], "SERVICE_STOPPED")
    return ids[0], item


def query(db, sql):
    # sql is always a literal in installed trusted code, never a client-supplied query.
    return (
        command(
            [
                "docker",
                "exec",
                db,
                "sh",
                "-c",
                'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "$1"',
                "sh",
                sql,
            ]
        )
        .decode()
        .strip()
    )


def staging_installed_hash():
    """Observe only the dispatcher's fixed deploy-owned executable, without following links."""
    fds = []
    try:
        owner = pwd.getpwnam("deploy")
        require(owner.pw_uid > 0 and owner.pw_dir == "/home/deploy", "UNTRUSTED")
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        root = os.open("/", directory_flags)
        fds.append(root)
        chain = []
        for name, uid in [
            (None, STAGING_ROOT_UID),
            ("home", STAGING_ROOT_UID),
            ("deploy", owner.pw_uid),
        ]:
            if name is not None:
                fds.append(os.open(name, directory_flags, dir_fd=fds[-1]))
            info = os.fstat(fds[-1])
            require(
                stat.S_ISDIR(info.st_mode) and info.st_uid == uid and not info.st_mode & 0o7022,
                "UNTRUSTED",
            )
            chain.append((name, info))

        name = "deploy-staging-guarded-run.sh"
        fd = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            dir_fd=fds[-1],
        )
        fds.append(fd)
        before = os.fstat(fd)
        require(
            stat.S_ISREG(before.st_mode)
            and before.st_uid == owner.pw_uid
            and stat.S_IMODE(before.st_mode) == 0o755
            and before.st_nlink == 1
            and 0 < before.st_size <= STAGING_RUNNER_LIMIT,
            "UNTRUSTED",
        )
        # A growing file cannot cause an unbounded read. Metadata/identity checks
        # below discard the digest on in-place writes, renames or path replacement.
        blob = bytearray()
        while len(blob) <= STAGING_RUNNER_LIMIT:
            chunk = os.read(fd, min(65536, STAGING_RUNNER_LIMIT + 1 - len(blob)))
            if not chunk:
                break
            blob.extend(chunk)
        require(len(blob) == before.st_size, "UNKNOWN")

        def identity(info):
            return (
                info.st_dev,
                info.st_ino,
                info.st_mode,
                info.st_uid,
                info.st_gid,
                info.st_nlink,
                info.st_size,
                info.st_mtime_ns,
                info.st_ctime_ns,
            )

        require(identity(os.fstat(fd)) == identity(before), "UNKNOWN")
        require(
            identity(os.stat(name, dir_fd=fds[-2], follow_symlinks=False)) == identity(before),
            "UNKNOWN",
        )
        for index, (entry, info) in enumerate(chain):
            require(identity(os.fstat(fds[index])) == identity(info), "UNKNOWN")
            if entry is not None:
                require(
                    identity(os.stat(entry, dir_fd=fds[index - 1], follow_symlinks=False))
                    == identity(info),
                    "UNKNOWN",
                )
        return "PRESENT", hashlib.sha256(blob).hexdigest()
    except FileNotFoundError:
        return ("UNKNOWN" if len(fds) == 4 else "ABSENT"), None
    except KeyError:
        return "UNKNOWN", None
    except Refused as exc:
        return str(exc), None  # Only the two literal local states above.
    except OSError as exc:
        return ("UNTRUSTED" if exc.errno in {errno.ELOOP, errno.ENOTDIR} else "UNKNOWN"), None
    finally:
        for fd in reversed(fds):
            os.close(fd)


def staging_candidate_hash(sha, found):
    if not found:
        return "ABSENT", None
    expression = sha + ":deploy/deploy-staging-guarded-run.sh"
    try:
        # Check immutable Git object size before materializing its bytes. This
        # reads metadata only; no checkout, fetch or candidate code execution.
        result = subprocess.run(
            ["git", "-C", str(REPO), "cat-file", "--batch-check"],
            input=(expression + "\n").encode(),
            capture_output=True,
            timeout=25,
            check=False,
        )
        require(result.returncode == 0, "UNKNOWN")
        if result.stdout == (expression + " missing\n").encode():
            return "ABSENT", None
        metadata = re.fullmatch(rb"([0-9a-f]{40}) blob ([0-9]+)\n", result.stdout)
        require(metadata is not None, "UNTRUSTED")
        size = int(metadata[2])
        require(0 < size <= STAGING_RUNNER_LIMIT, "UNTRUSTED")
        blob = command(["git", "-C", str(REPO), "cat-file", "blob", metadata[1].decode()])
        require(len(blob) == size, "UNKNOWN")
        return "PRESENT", hashlib.sha256(blob).hexdigest()
    except Refused as exc:
        return ("UNTRUSTED" if str(exc) == "UNTRUSTED" else "UNKNOWN"), None
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN", None


def staging_runner_attestation(sha, found):
    installed_state, installed = staging_installed_hash()
    candidate_state, candidate = staging_candidate_hash(sha, found)
    return {
        "installed_state": installed_state,
        "installed": installed,
        "candidate_state": candidate_state,
        "candidate": candidate,
        "match": installed == candidate
        if installed_state == candidate_state == "PRESENT"
        else None,
    }


def observation(sha):
    available, disk = resources()
    found = object_present(sha)
    result = {
        "production_checkout": command(["git", "-C", str(REPO), "rev-parse", "HEAD"])
        .decode()
        .strip(),
        "candidate_present": found,
        "available_ram_mib": available,
        "free_disk_mib": disk,
        "restore_min_ram_mib": 784,
        "services": {},
        "runner_hashes": {},
    }
    for name in ["app", "web", "db"]:
        db, item = service(name)
        result["services"][name] = {
            "image": item["Image"],
            "health": item["State"].get("Health", {}).get("Status"),
        }
        if name == "db":
            revision = query(db, "select version_num from alembic_version")
            require(re.fullmatch(r"[0-9a-f]{12}", revision) is not None, "ALEMBIC_REVISION")
            result["from_revision"] = revision
    for name in RUNNERS:
        actual = sha256(BIN / name)
        expected = (
            hashlib.sha256(
                command(["git", "-C", str(REPO), "show", sha + ":deploy/" + name])
            ).hexdigest()
            if found
            else None
        )
        result["runner_hashes"][name] = {
            "installed": actual,
            "candidate": expected,
            "match": actual == expected if found else False,
        }
    result["staging_runner_attestation"] = staging_runner_attestation(sha, found)
    return result


def finish(store, operation, action, sha, stage, state, facts=None, error=None):
    result = {
        "operation_id": operation,
        "action": action,
        "candidate": sha,
        "stage": stage,
        "state": state,
        "observed_at": now(),
        "facts": facts or {},
        "next_step": "read-result" if state == "VERIFIED" else "operator-review-no-blind-retry",
    }
    if error:
        result["error"] = error
    store.write(operation, result)
    return result


def prepare(sha):
    before = command(["git", "-C", str(REPO), "rev-parse", "HEAD"])
    origin = command(["git", "-C", str(REPO), "remote", "get-url", "origin"]).decode().strip()
    require(
        origin
        in {
            "https://github.com/bimoool/pullup-trainer-bot.git",
            "https://github.com/bimoool/pullup-trainer-bot",
            "git@github.com:bimoool/pullup-trainer-bot.git",
        },
        "ORIGIN_MISMATCH",
    )
    fetched = False
    if not object_present(sha):
        # Literal existing repository and origin; no refspec/URL from a caller.
        try:
            command(["git", "-C", str(REPO), "fetch", "--no-tags", "origin", sha], timeout=90)
        except Refused:
            # Reconcile object presence even when transport timed out; never fetch again here.
            require(object_present(sha), "FETCH_UNCONFIRMED_QUERY_RECEIPT")
        fetched = True
    require(object_present(sha), "OBJECT_MISSING")
    require(command(["git", "-C", str(REPO), "rev-parse", "HEAD"]) == before, "CHECKOUT_CHANGED")
    return {"candidate_present": True, "fetched_once": fetched, "checkout_unchanged": True}


def restore_worker(sha, operation, store):
    import resource

    name = "pullup-restore-" + operation
    work = LEDGER / operation
    stage = "resources"
    creation_attempted = False
    state, error = "FAILED", None
    facts = {"fresh_backup_created": False, "required_ram_mib": 784}
    try:
        available, disk = resources()
        facts.update(available_ram_mib=available, free_disk_mib=disk)
        db, dbinfo = service("db")
        size = int(query(db, "select pg_database_size(current_database())"))
        budget = restore_budget(available, disk, max(1, (size + 1048575) // 1048576))
        image = dbinfo["Image"]
        env = json.loads(
            command(["docker", "image", "inspect", "--format", "{{json .Config.Env}}", image])
        )
        require("PG_MAJOR=16" in env, "POSTGRES16_REQUIRED")
        require(
            command(["docker", "exec", db, "id", "-u", "postgres"]).strip() == b"999",
            "PG_IMAGE_UID",
        )
        revision = query(db, "select version_num from alembic_version")
        require(re.fullmatch(r"[0-9a-f]{12}", revision), "ALEMBIC_REVISION")
        work.mkdir(mode=0o700)
        dump = work / "consistent.dump"
        stage = "backup"
        with dump.open("xb") as target, (work / "private-backup.log").open("xb") as log:
            os.chmod(dump, 0o600)

            def cap_file():
                resource.setrlimit(resource.RLIMIT_FSIZE, (256 * 1048576, 256 * 1048576))

            p = subprocess.run(
                [
                    "docker",
                    "exec",
                    db,
                    "sh",
                    "-c",
                    'exec pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"',
                ],
                stdout=target,
                stderr=log,
                timeout=180,
                preexec_fn=cap_file,
                check=False,
            )
            require(p.returncode == 0 and dump.stat().st_size > 0, "BACKUP_FAILED")
        digest = sha256(dump)
        facts.update(fresh_backup_created=True, backup_sha256=digest, backup_timestamp=now())
        (work / "consistent.dump.sha256").write_text(digest + "  consistent.dump\n")
        stage = "isolation"
        available, disk = resources()
        restore_budget(available, disk, max(1, (size + 1048575) // 1048576))
        exists = subprocess.run(
            ["docker", "container", "inspect", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        require(exists.returncode != 0, "CONTAINER_EXISTS")
        creation_attempted = True
        command(restore_container_args(name, image, budget["data_limit_mib"]))
        deadline = time.monotonic() + 60
        while subprocess.run(
            ["docker", "exec", name, "pg_isready", "-U", "postgres", "-d", "verify"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode:
            require(time.monotonic() < deadline, "PG_START_TIMEOUT")
            require(resources()[0] >= 400, "LIVE_RAM_RESERVE")
            time.sleep(2)
        stage = "restore"
        with dump.open("rb") as source, (work / "private-restore.log").open("xb") as log:
            p = subprocess.Popen(
                [
                    "docker",
                    "exec",
                    "-i",
                    name,
                    "pg_restore",
                    "-U",
                    "postgres",
                    "-d",
                    "verify",
                    "--no-owner",
                    "--no-acl",
                    "--exit-on-error",
                    "--jobs=1",
                ],
                stdin=source,
                stdout=log,
                stderr=log,
            )
            deadline = time.monotonic() + 600
            try:
                while p.poll() is None:
                    require(time.monotonic() < deadline, "RESTORE_TIMEOUT")
                    require(resources()[0] >= 400, "LIVE_RAM_RESERVE")
                    time.sleep(2)
                require(p.returncode == 0, "RESTORE_FAILED")
            finally:
                if p.poll() is None:
                    p.terminate()
                    p.wait(timeout=10)
        stage = "verify"
        sql = "select version_num from alembic_version; select not exists(select 1 from pg_index where not indisvalid or not indisready); select not exists(select 1 from pg_constraint where not convalidated); select 1;"
        answer = (
            command(
                ["docker", "exec", name, "psql", "-U", "postgres", "-d", "verify", "-Atqc", sql]
            )
            .decode()
            .splitlines()
        )
        require(answer == [revision, "t", "t", "1"], "RESTORE_INVARIANTS")
        facts.update(
            backup_sha256=digest,
            schema_revision=revision,
            constraints_valid=True,
            indexes_valid=True,
            sql_readable=True,
            isolated_network="none",
            pg_memory_mib=256,
            single_restore_worker=True,
            production_reserve_mib=400,
            external_recovery="owner-destination-and-access-required",
        )
        stage, state = "verified", "VERIFIED"
    except Refused as exc:
        state, error = "BLOCKED", str(exc)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        subprocess.SubprocessError,
    ):
        state, error = "FAILED", "INTERNAL_FAILURE_PRIVATE_LOG_ONLY"
    # The durable receipt remains RUNNING until cleanup is positively reconciled.
    # Set this before docker run: a timed-out client may already have created the container.
    try:
        if creation_attempted:
            cleanup_restore_container(name, operation)
        facts["cleanup_verified"] = True
    except (
        Refused,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        subprocess.SubprocessError,
    ):
        stage, state, error = "cleanup", "FAILED", "CLEANUP_UNCONFIRMED_OPERATOR_REVIEW"
        facts["cleanup_verified"] = False
    return finish(store, operation, "restore", sha, stage, state, facts, error=error)


def cleanup_restore_container(name, operation):
    def present():
        # Successful Docker list with an exact name filter proves absence. An inspect
        # failure alone cannot distinguish absence from a disconnected Docker daemon.
        return bool(
            command(
                [
                    "docker",
                    "container",
                    "ls",
                    "--all",
                    "--quiet",
                    "--filter",
                    "name=^/" + name + "$",
                ]
            ).strip()
        )

    if present():
        label = (
            command(
                [
                    "docker",
                    "inspect",
                    "--format",
                    '{{index .Config.Labels "pullup.control.operation"}}',
                    name,
                ]
            )
            .decode()
            .strip()
        )
        require(label == operation, "CLEANUP_OWNERSHIP")
        command(["docker", "rm", "-f", name])
    require(not present(), "CLEANUP_INCOMPLETE")


def execute(action, sha, operation):
    for root in [Path("/"), Path("/root"), BIN, BACKUPS]:
        trusted_directory(root)
    require(os.geteuid() == 0, "ROOT_REQUIRED")
    if not LEDGER.exists():
        LEDGER.mkdir(mode=0o700)
        sync_directory(BACKUPS)
    store = Receipts(LEDGER)
    if action == "receipt":
        result = store.read(operation)
        require(result.get("candidate") == sha, "RECEIPT_BINDING")
        return result
    old = store.claim(operation, action, sha)
    if old is not None:
        return old
    fds = []
    try:
        for lock in [BACKUPS / ".prod-actions.lock", BACKUPS / ".prod-guarded.lock", STAGING_LOCK]:
            fds.append(acquire_existing(lock))
        no_other_operations()
        if action == "readiness":
            return finish(store, operation, action, sha, "observed", "VERIFIED", observation(sha))
        require(object_present(sha) or action == "prepare", "CANDIDATE_MISSING")
        if action == "prepare":
            return finish(store, operation, action, sha, "object-present", "VERIFIED", prepare(sha))
        if action == "adopt-runner":
            return finish(
                store,
                operation,
                action,
                sha,
                "runner-adopted",
                "VERIFIED",
                adopt_runner(sha, operation),
            )
        # A detached, bounded worker survives SSH loss; the durable claim is never replayed.
        private_log = LEDGER / (operation + ".worker.log")
        fd = os.open(private_log, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as log:
            subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "_restore", sha, operation],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                pass_fds=tuple(fds),
                start_new_session=True,
            )
        return store.read(operation)
    except Refused as exc:
        return finish(
            store,
            operation,
            action,
            sha,
            "guard",
            "BLOCKED",
            {"runner_state_unknown": True} if action == "adopt-runner" else None,
            error=str(exc),
        )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        subprocess.SubprocessError,
    ):
        return finish(
            store,
            operation,
            action,
            sha,
            "guard",
            "FAILED",
            facts={"runner_state_unknown": True} if action == "adopt-runner" else None,
            error="INTERNAL_FAILURE_PRIVATE_LOG_ONLY",
        )
    finally:
        for fd in fds:
            os.close(fd)


def main():
    os.umask(0o077)
    try:
        if len(sys.argv) == 4 and sys.argv[1] == "_restore":
            require(os.geteuid() == 0, "ROOT_REQUIRED")
            _, sha, operation = parse_args(["restore", *sys.argv[2:]])
            store = Receipts(LEDGER)
            receipt = store.read(operation)
            require(
                receipt.get("candidate") == sha
                and receipt.get("action") == "restore"
                and receipt.get("state") == "RUNNING",
                "WORKER_CLAIM",
            )
            # Linux watchdog: hard wall-clock cap survives orchestrator/SSH disconnect.
            import signal

            signal.signal(
                signal.SIGALRM, lambda *_: (_ for _ in ()).throw(Refused("WORKER_TIMEOUT"))
            )
            signal.alarm(900)
            restore_worker(sha, operation, store)
            return
        print(json.dumps(execute(*parse_args(sys.argv[1:])), sort_keys=True))
    except (Refused, OSError, ValueError):
        print(
            json.dumps(
                {
                    "state": "REFUSED",
                    "stage": "validation",
                    "next_step": "operator-review-no-blind-retry",
                }
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
