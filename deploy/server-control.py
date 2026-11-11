#!/usr/bin/env python3
"""Installed root-only, exact allowlist. No candidate code execution or user output."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
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
BIN = Path("/root/bin")
BACKUPS = Path("/root/backups")
LEDGER = BACKUPS / "cloud-operations"
STAGING_LOCK = Path("/home/deploy/.deploy-staging.lock")
ACTIONS = {"readiness", "prepare", "restore", "receipt"}
SHA_RE = r"[0-9a-f]{40}"
OP_RE = r"ops-[1-9][0-9]{0,19}"
RUNNERS = (
    "deploy-production-guarded-run.sh",
    "rollback-production-guarded.sh",
    "prod-guarded-dispatch.sh",
)


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
        finally:
            if os.path.exists(name):
                os.unlink(name)


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
    created = False
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
        command(restore_container_args(name, image, budget["data_limit_mib"]))
        created = True
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
        return finish(
            store,
            operation,
            "restore",
            sha,
            "verified",
            "VERIFIED",
            {
                "backup_sha256": digest,
                "backup_timestamp": now(),
                "schema_revision": revision,
                "constraints_valid": True,
                "indexes_valid": True,
                "sql_readable": True,
                "isolated_network": "none",
                "pg_memory_mib": 256,
                "single_restore_worker": True,
                "production_reserve_mib": 400,
                "external_recovery": "owner-destination-and-access-required",
            },
        )
    except Refused as exc:
        return finish(store, operation, "restore", sha, stage, "BLOCKED", facts, error=str(exc))
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
            "restore",
            sha,
            stage,
            "FAILED",
            facts,
            error="INTERNAL_FAILURE_PRIVATE_LOG_ONLY",
        )
    finally:
        try:
            if created:
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
                check = subprocess.run(
                    ["docker", "container", "inspect", name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                require(check.returncode != 0, "CLEANUP_INCOMPLETE")
            result = store.read(operation)
            result.setdefault("facts", {})["cleanup_verified"] = True
            store.write(operation, result)
        except (
            Refused,
            OSError,
            ValueError,
            KeyError,
            TypeError,
            RuntimeError,
            subprocess.SubprocessError,
        ):
            finish(
                store,
                operation,
                "restore",
                sha,
                "cleanup",
                "FAILED",
                facts,
                error="CLEANUP_UNCONFIRMED_OPERATOR_REVIEW",
            )
        # Only this operation's standalone instance is removed. Keep its private backup and receipt.


def execute(action, sha, operation):
    for root in [Path("/"), Path("/root"), BIN, BACKUPS]:
        trusted_directory(root)
    require(os.geteuid() == 0, "ROOT_REQUIRED")
    if not LEDGER.exists():
        LEDGER.mkdir(mode=0o700)
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
        return finish(store, operation, action, sha, "guard", "BLOCKED", error=str(exc))
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
