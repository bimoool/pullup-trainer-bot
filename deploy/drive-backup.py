#!/usr/bin/env python3
"""Root-only VPS -> owner Drive encrypted backup. Stdlib; no app/CI credentials."""

from __future__ import annotations

import fcntl
import hashlib
import http.client
import json
import os
import re
import signal
import stat
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

CONFIG = Path("/etc/pullup-drive-backup")
STATE = Path("/root/backups/drive-operations")
REPO = Path("/root/pullup-trainer-bot")
LOCKS = (
    Path("/root/backups/.prod-actions.lock"),
    Path("/root/backups/.prod-guarded.lock"),
    Path("/home/deploy/.deploy-staging.lock"),
)
ID = r"[A-Za-z0-9_-]{10,200}"
OP = r"backup-[0-9]{8}"
DEADLINE = 0.0
ENV = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "HOME": "/root",
    "LANG": "C.UTF-8",
}


class Refused(Exception):
    """Only literal nonsecret error codes are exported."""


def require(condition, code):
    if not condition:
        raise Refused(code)


def directory(path, private=False):
    st = path.lstat()
    require(
        stat.S_ISDIR(st.st_mode)
        and st.st_uid == os.geteuid()
        and not st.st_mode & (0o077 if private else 0o022),
        "DIRECTORY_PERMISSIONS",
    )


def private_read(path):
    directory(path.parent, private=True)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        raise Refused("PRIVATE_FILE_UNAVAILABLE") from None
    with os.fdopen(fd, "rb") as source:
        st = os.fstat(source.fileno())
        require(
            stat.S_ISREG(st.st_mode)
            and st.st_uid == os.geteuid()
            and stat.S_IMODE(st.st_mode) == 0o600
            and st.st_size <= 32768,
            "FILE_PERMISSIONS",
        )
        return source.read(32769)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def save(path, value):
    temporary = path.with_suffix(".pending")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w") as target:
            json.dump(value, target, sort_keys=True)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def acquire(path):
    # Existing inode only: never create/replace a deployment lock.
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        after = path.lstat()
        require(
            stat.S_ISREG(before.st_mode)
            and (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino),
            "LOCK_CHANGED",
        )
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Refused("BUSY") from None
        return fd
    except BaseException:
        os.close(fd)
        raise


def remaining(maximum=30):
    value = min(maximum, DEADLINE - time.monotonic()) if DEADLINE else maximum
    require(value > 0, "DEADLINE")
    return value


def hashes(path):
    sha, md5, size = hashlib.sha256(), hashlib.md5(), 0
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            remaining()
            sha.update(chunk)
            md5.update(chunk)
            size += len(chunk)
    return {"sha256": sha.hexdigest(), "md5": md5.hexdigest(), "size": size}


class Drive:
    """Fixed Google origins; no proxy, redirects, arbitrary URL or shell callbacks."""

    def __init__(self, credentials):
        self.token = None
        self.credentials = credentials

    def request(self, host, method, path, body=None, headers=None, download=False):
        conn = http.client.HTTPSConnection(host, timeout=remaining())
        headers = dict(headers or {})
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        try:
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            if host == "oauth2.googleapis.com":
                require(response.status == 200, "AUTH_REQUIRED")
            require(response.status not in (401, 403), "AUTH_REQUIRED")
            require(200 <= response.status < 300, "DRIVE_HTTP_FAILED")
            if download:
                sha, size = hashlib.sha256(), 0
                while chunk := response.read(1024 * 1024):
                    remaining()
                    sha.update(chunk)
                    size += len(chunk)
                return sha.hexdigest(), size
            data = response.read(1024 * 1024 + 1)
            require(len(data) <= 1024 * 1024, "RESPONSE_SIZE")
            return json.loads(data)
        finally:
            conn.close()

    def authenticate(self):
        result = self.request(
            "oauth2.googleapis.com",
            "POST",
            "/token",
            urlencode({**self.credentials, "grant_type": "refresh_token"}),
            {"Content-Type": "application/x-www-form-urlencoded"},
        )
        token = result.get("access_token")
        require(isinstance(token, str) and 1 <= len(token) <= 16384, "AUTH_REQUIRED")
        self.token = token

    def folder(self, folder_id):
        result = self.request(
            "www.googleapis.com",
            "GET",
            "/drive/v3/files/"
            + folder_id
            + "?fields=id,mimeType,trashed,capabilities(canAddChildren)",
        )
        require(
            result.get("id") == folder_id
            and not result.get("trashed")
            and result.get("mimeType") == "application/vnd.google-apps.folder"
            and result.get("capabilities", {}).get("canAddChildren") is True,
            "FOLDER_UNAVAILABLE",
        )

    def allocate(self):
        result = self.request(
            "www.googleapis.com",
            "GET",
            "/drive/v3/files/generateIds?count=1&space=drive&type=files",
        )
        value = result["ids"][0]
        require(re.fullmatch(ID, value), "FILE_ID")
        return value

    def upload(self, file_id, folder, operation, path):
        boundary = "pullup-" + uuid.uuid4().hex
        metadata = {
            "id": file_id,
            "name": operation + ".dump.age",
            "parents": [folder],
            "mimeType": "application/octet-stream",
            "appProperties": {"pullupBackupOperation": operation},
        }
        prefix = (
            "--"
            + boundary
            + "\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
            + json.dumps(metadata)
            + "\r\n--"
            + boundary
            + "\r\nContent-Type: application/octet-stream\r\n\r\n"
        ).encode()
        suffix = ("\r\n--" + boundary + "--\r\n").encode()
        conn = http.client.HTTPSConnection("www.googleapis.com", timeout=remaining())
        try:
            conn.putrequest("POST", "/upload/drive/v3/files?uploadType=multipart&fields=id")
            conn.putheader("Authorization", "Bearer " + self.token)
            conn.putheader("Content-Type", "multipart/related; boundary=" + boundary)
            conn.putheader("Content-Length", str(len(prefix) + path.stat().st_size + len(suffix)))
            conn.endheaders()
            conn.send(prefix)
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    remaining()
                    conn.send(chunk)
            conn.send(suffix)
            result = conn.getresponse()
            require(200 <= result.status < 300, "TRANSFER_UNKNOWN")
            require(json.loads(result.read(32768)).get("id") == file_id, "TRANSFER_UNKNOWN")
        finally:
            conn.close()

    def metadata(self, file_id):
        return self.request(
            "www.googleapis.com",
            "GET",
            "/drive/v3/files/" + file_id + "?fields=id,size,md5Checksum,parents,trashed",
        )

    def download_digest(self, file_id):
        return self.request(
            "www.googleapis.com", "GET", "/drive/v3/files/" + file_id + "?alt=media", download=True
        )


def binding(settings):
    return hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()


def perform(operation, root, settings, drive, dump):
    require(re.fullmatch(OP, operation), "OPERATION_ID")
    directory(root, private=True)
    receipt = root / (operation + ".json")
    ciphertext = root / (operation + ".dump.age")
    if receipt.exists() or receipt.is_symlink():
        previous = json.loads(private_read(receipt))
        require(previous.get("binding") == binding(settings), "RECEIPT_BINDING")
        if previous.get("state") == "RUNNING":
            return {**previous, "state": "UNKNOWN", "error": "INTERRUPTED_NO_REPLAY"}
        return previous
    result = {
        "operation": operation,
        "binding": binding(settings),
        "state": "RUNNING",
        "stage": "claim",
        "started_at": datetime.now(UTC).isoformat(),
        "retention": "REPORT_ONLY_NO_REMOTE_DELETION",
    }
    save(receipt, result)
    try:
        result["stage"] = "dump-encrypt"
        save(receipt, result)
        dump(ciphertext)
        result.update(hashes(ciphertext))
        require(result["size"] > 0, "EMPTY_CIPHERTEXT")
        result["stage"] = "allocate"
        save(receipt, result)
        result["file_id"] = drive.allocate()
        require(re.fullmatch(ID, result["file_id"]), "FILE_ID")
        result["stage"] = "upload"
        save(receipt, result)  # allocated ID is durable BEFORE remote mutation
        drive.upload(result["file_id"], settings["folder_id"], operation, ciphertext)
        result["stage"] = "verify"
        save(receipt, result)
        meta = drive.metadata(result["file_id"])
        require(
            meta.get("id") == result["file_id"]
            and not meta.get("trashed")
            and settings["folder_id"] in meta.get("parents", [])
            and meta.get("size") == str(result["size"])
            and meta.get("md5Checksum") == result["md5"],
            "METADATA_MISMATCH",
        )
        digest, size = drive.download_digest(result["file_id"])
        require(digest == result["sha256"] and size == result["size"], "DOWNLOAD_MISMATCH")
        result.update(state="VERIFIED", download_sha256=digest, download_size=size)
    except (
        Refused,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        subprocess.SubprocessError,
        http.client.HTTPException,
        KeyboardInterrupt,
    ) as exc:
        result["state"] = "UNKNOWN" if result["stage"] == "upload" else "FAILED"
        result["error"] = str(exc) if isinstance(exc, Refused) else "OPERATION_FAILED"
    finally:
        ciphertext.unlink(missing_ok=True)
    result["finished_at"] = datetime.now(UTC).isoformat()
    save(receipt, result)
    return result


def command(args, timeout=30):
    result = subprocess.run(
        args,
        cwd=REPO,
        env=ENV,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=remaining(timeout),
        check=False,
    )
    require(result.returncode == 0, "COMMAND_FAILED")
    return result.stdout


def stop_children(children):
    stopped = True
    for child in children:
        if child is None:
            continue
        try:
            if child.poll() is None:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass  # It exited after poll; still reap it and clean every other child.
            child.wait(timeout=5)
        except (OSError, subprocess.SubprocessError):
            stopped = False
    return stopped


def wait_dump_horizon(deadline):
    # /proc/uptime and CLOCK_BOOTTIME share the host boot clock in this Docker setup.
    # Even a delayed server exec cannot start pg_dump after the absolute deadline.
    while (left := deadline + 10 - time.clock_gettime(time.CLOCK_BOOTTIME)) > 0:
        try:
            time.sleep(min(1, left))
        except Refused as exc:
            require(str(exc) == "INTERRUPTED", "CLEANUP_WAIT_FAILED")
            # Repeated TERM must not shorten the failed-dump lock holding period.


def encrypted_dump(path, recipient, operation):
    appname = "pullup-drive-" + operation + "-" + uuid.uuid4().hex
    base = ["docker", "compose", "exec", "-T", "db"]
    # GNU timeout runs INSIDE db, so killing the docker client cannot orphan an unbounded dump.
    command(base + ["timeout", "--version"])
    deadline = int(time.clock_gettime(time.CLOCK_BOOTTIME)) + 600
    dump = encrypt = None
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            dump = subprocess.Popen(
                [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "-e",
                    "PGAPPNAME=" + appname,
                    "db",
                    "sh",
                    "-c",
                    (
                        "read -r uptime rest < /proc/uptime; "
                        'left=$(($1 - ${uptime%.*})); [ "$left" -gt 0 ] || exit 124; '
                        'exec timeout --signal=KILL "${left}s" pg_dump -U "$POSTGRES_USER" '
                        '-Fc --lock-wait-timeout=30000 "$POSTGRES_DB"'
                    ),
                    "sh",
                    str(deadline),
                ],
                cwd=REPO,
                env=ENV,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            encrypt = subprocess.Popen(
                ["age", "--encrypt", "--recipients-file", str(recipient)],
                env=ENV,
                stdin=dump.stdout,
                stdout=output,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            dump.stdout.close()
            require(encrypt.wait(timeout=remaining(630)) == 0, "ENCRYPT_FAILED")
            require(dump.wait(timeout=remaining(30)) == 0, "DUMP_FAILED")
            output.flush()
            os.fsync(output.fileno())
    finally:
        failed = any(child is not None and child.poll() != 0 for child in (dump, encrypt))
        stopped = stop_children((dump, encrypt))
        if failed and dump is not None:
            cleanup_confirmed = stopped
            # Only this invocation's random PGAPPNAME. No database-wide cancellation.
            query = (
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE application_name='" + appname + "'"
            )
            try:
                command(
                    base
                    + [
                        "sh",
                        "-c",
                        (
                            'exec psql -U "$POSTGRES_USER" '
                            '-d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -At -c "$1"'
                        ),
                        "sh",
                        query,
                    ]
                )
                query = (
                    "SELECT count(*) FROM pg_stat_activity WHERE application_name='" + appname + "'"
                )
                require(
                    command(
                        base
                        + [
                            "sh",
                            "-c",
                            ('exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c "$1"'),
                            "sh",
                            query,
                        ]
                    ).strip()
                    == b"0",
                    "DUMP_CLEANUP",
                )
                require(stopped, "LOCAL_CLEANUP")
            except (Refused, OSError, subprocess.SubprocessError):
                cleanup_confirmed = False
            finally:
                # Backend absence cannot exclude an exec that has not connected yet.
                # Always retain deployment locks through the absolute remote deadline.
                wait_dump_horizon(deadline)
            if not cleanup_confirmed:
                raise Refused("DUMP_CLEANUP_UNCONFIRMED") from None


def load_settings():
    settings = json.loads(private_read(CONFIG / "config.json"))
    require(set(settings) == {"folder_id"} and re.fullmatch(ID, settings["folder_id"]), "CONFIG")
    recipient = private_read(CONFIG / "recipient.txt").decode().strip()
    require(
        re.fullmatch(
            r"age1[0-9a-z]{58}|ssh-ed25519 [A-Za-z0-9+/=]+(?: [^\r\n]+)?|"
            r"ssh-rsa [A-Za-z0-9+/=]+(?: [^\r\n]+)?",
            recipient,
        ),
        "PUBLIC_RECIPIENT",
    )
    settings["recipient_sha256"] = hashlib.sha256(recipient.encode()).hexdigest()
    credentials = json.loads(private_read(CONFIG / "oauth.json"))
    require(
        set(credentials) == {"client_id", "client_secret", "refresh_token"}
        and all(
            isinstance(value, str) and 0 < len(value) <= 16384 for value in credentials.values()
        ),
        "OAUTH_CONFIG",
    )
    return settings, credentials


def main(args):
    global DEADLINE
    os.umask(0o077)
    require(os.geteuid() == 0, "ROOT_REQUIRED")
    require(len(args) <= 1, "ARGUMENTS")
    operation = args[0] if args else "backup-" + datetime.now(UTC).strftime("%Y%m%d")
    require(re.fullmatch(OP, operation), "OPERATION_ID")
    for path in (Path("/"), Path("/root"), Path("/root/backups"), Path("/etc"), CONFIG):
        directory(path)
    if not STATE.exists():
        STATE.mkdir(mode=0o700)
        sync_directory(STATE.parent)
    directory(STATE, private=True)
    DEADLINE = time.monotonic() + 1100

    def interrupted(signum, frame):
        raise Refused("INTERRUPTED")

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    locks = []
    try:
        for lock in LOCKS:
            locks.append(acquire(lock))
        settings, credentials = load_settings()
        drive = Drive(credentials)

        # Authentication/folder checks precede dumping, but never replay an existing claim.
        def dump(path):
            drive.authenticate()
            drive.folder(settings["folder_id"])
            encrypted_dump(path, CONFIG / "recipient.txt", operation)

        result = perform(operation, STATE, settings, drive, dump)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["state"] == "VERIFIED" else 1
    finally:
        for fd in reversed(locks):
            os.close(fd)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (
        Refused,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        subprocess.SubprocessError,
        http.client.HTTPException,
        KeyboardInterrupt,
    ) as exc:
        print(
            json.dumps(
                {
                    "state": "BLOCKED",
                    "error": str(exc) if isinstance(exc, Refused) else "PREFLIGHT_FAILED",
                }
            )
        )
        sys.exit(1)
