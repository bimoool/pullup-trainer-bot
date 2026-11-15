"""Offline backup protocol tests; all bytes and credentials are synthetic."""

import hashlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("drive_backup", ROOT / "deploy/drive-backup.py")
backup = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = backup
spec.loader.exec_module(backup)


class Drive:
    def __init__(self, corrupt=False, fail=False):
        self.uploads = 0
        self.corrupt = corrupt
        self.fail = fail
        self.body = b""

    def allocate(self):
        return "syntheticFile123"

    def upload(self, file_id, folder, operation, path):
        self.uploads += 1
        self.body = path.read_bytes()
        if self.fail:
            raise backup.Refused("TRANSFER_UNKNOWN")

    def metadata(self, file_id):
        return {
            "id": file_id,
            "size": str(len(self.body)),
            "md5Checksum": hashlib.md5(self.body).hexdigest(),
            "parents": ["syntheticFolder123"],
            "trashed": False,
        }

    def download_digest(self, file_id):
        body = b"x" * len(self.body) if self.corrupt else self.body
        return hashlib.sha256(body).hexdigest(), len(body)


@pytest.fixture
def setup(tmp_path):
    tmp_path.chmod(0o700)
    settings = {"folder_id": "syntheticFolder123", "recipient_sha256": "a" * 64}
    calls = []

    def dump(path):
        calls.append("dump")
        path.write_bytes(b"age-encryption.org/v1\nsynthetic ciphertext")
        path.chmod(0o600)

    return tmp_path, settings, calls, dump


def test_verifies_download_and_does_not_repeat(setup):
    root, settings, calls, dump = setup
    drive = Drive()
    first = backup.perform("backup-20261115", root, settings, drive, dump)
    assert first["state"] == "VERIFIED"
    assert first["download_sha256"] == first["sha256"]
    assert drive.uploads == 1 and calls == ["dump"]
    assert not list(root.glob("*.age"))
    assert backup.perform("backup-20261115", root, settings, drive, dump) == first
    assert drive.uploads == 1 and calls == ["dump"]


def test_matching_metadata_cannot_hide_changed_download(setup):
    root, settings, _calls, dump = setup
    result = backup.perform("backup-20261115", root, settings, Drive(corrupt=True), dump)
    assert result["state"] == "FAILED"
    assert result["error"] == "DOWNLOAD_MISMATCH"


def test_ambiguous_upload_is_durable_and_never_replayed(setup):
    root, settings, _calls, dump = setup
    drive = Drive(fail=True)
    first = backup.perform("backup-20261115", root, settings, drive, dump)
    assert first["state"] == "UNKNOWN"
    assert first["file_id"] == "syntheticFile123"
    assert backup.perform("backup-20261115", root, settings, drive, dump) == first
    assert drive.uploads == 1


def test_dump_failure_never_uploads_or_leaks_exception(setup):
    root, settings, _calls, _dump = setup
    drive = Drive()

    def broken(path):
        path.write_bytes(b"partial synthetic")
        raise RuntimeError("SECRET-SYNTHETIC-ONLY")

    result = backup.perform("backup-20261115", root, settings, drive, broken)
    assert result["state"] == "FAILED"
    assert "SECRET" not in json.dumps(result)
    assert drive.uploads == 0
    assert not list(root.glob("*.age"))


def test_interrupted_claim_reports_unknown_without_replay(setup):
    root, settings, calls, dump = setup
    path = root / "backup-20261115.json"
    backup.save(
        path,
        {"operation": "backup-20261115", "state": "RUNNING", "binding": backup.binding(settings)},
    )
    result = backup.perform("backup-20261115", root, settings, Drive(), dump)
    assert result["state"] == "UNKNOWN"
    assert calls == []


def test_private_file_rejects_symlink_and_open_permissions(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path / "secret"
    path.write_text("synthetic")
    path.chmod(0o644)
    with pytest.raises(backup.Refused):
        backup.private_read(path)
    path.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(backup.Refused):
        backup.private_read(link)
    assert backup.private_read(path) == b"synthetic"


def test_lock_is_shared_and_never_replaced(tmp_path):
    path = tmp_path / "lock"
    path.touch(mode=0o600)
    fd = backup.acquire(path)
    try:
        with pytest.raises(backup.Refused, match="BUSY"):
            backup.acquire(path)
        assert os.fstat(fd).st_ino == path.stat().st_ino
    finally:
        os.close(fd)


@pytest.mark.parametrize(
    "field,value",
    [
        ("size", "1"),
        ("md5Checksum", "0" * 32),
        ("parents", ["differentFolder123"]),
        ("trashed", True),
        ("id", "differentFile123"),
    ],
)
def test_bad_metadata_never_verifies(setup, field, value):
    root, settings, _calls, dump = setup
    drive = Drive()
    original = drive.metadata
    drive.metadata = lambda file_id: {**original(file_id), field: value}
    result = backup.perform("backup-20261115", root, settings, drive, dump)
    assert result["state"] == "FAILED"
    assert result["error"] == "METADATA_MISMATCH"


def test_receipt_cannot_be_reused_for_another_recipient(setup):
    root, settings, calls, dump = setup
    drive = Drive()
    backup.perform("backup-20261115", root, settings, drive, dump)
    settings["recipient_sha256"] = "b" * 64
    with pytest.raises(backup.Refused, match="RECEIPT_BINDING"):
        backup.perform("backup-20261115", root, settings, drive, dump)
    assert calls == ["dump"] and drive.uploads == 1


def test_separate_utc_days_cross_month_boundary(setup):
    root, settings, calls, dump = setup
    drive = Drive()
    for operation in ("backup-20261130", "backup-20261201"):
        assert backup.perform(operation, root, settings, drive, dump)["state"] == "VERIFIED"
    assert calls == ["dump", "dump"] and drive.uploads == 2


def test_configuration_rejects_private_keys_and_extra_token_url(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    monkeypatch.setattr(backup, "CONFIG", tmp_path)

    def write(name, content):
        path = tmp_path / name
        path.write_text(content)
        path.chmod(0o600)

    write("config.json", '{"folder_id":"syntheticFolder123"}')
    write("recipient.txt", "-----BEGIN OPENSSH PRIVATE KEY-----")
    with pytest.raises(backup.Refused, match="PUBLIC_RECIPIENT"):
        backup.load_settings()
    write("recipient.txt", "age1" + "a" * 58)
    credentials = {
        "client_id": "synthetic",
        "client_secret": "synthetic",
        "refresh_token": "synthetic",
    }
    write("oauth.json", json.dumps({**credentials, "token_uri": "https://example.invalid"}))
    with pytest.raises(backup.Refused, match="OAUTH_CONFIG"):
        backup.load_settings()
    write("oauth.json", json.dumps(credentials))
    settings, actual = backup.load_settings()
    assert actual == credentials and settings["folder_id"] == "syntheticFolder123"


class Response:
    status = 200

    def __init__(self, body):
        self.body = body

    def read(self, size):
        chunk, self.body = self.body[:size], self.body[size:]
        return chunk


def test_actual_http_download_hashes_bytes_and_uses_fixed_origin(monkeypatch):
    requests = []
    body = b"synthetic encrypted bytes" * 100000

    class Connection:
        def __init__(self, host, timeout):
            assert 0 < timeout <= 30
            self.host = host

        def request(self, method, path, body, headers):
            requests.append((self.host, method, path, headers))

        def getresponse(self):
            return Response(body)

        def close(self):
            pass

    monkeypatch.setattr(backup.http.client, "HTTPSConnection", Connection)
    drive = backup.Drive({})
    drive.token = "synthetic-token"
    assert drive.download_digest("syntheticFile123") == (
        hashlib.sha256(body).hexdigest(),
        len(body),
    )
    assert requests == [
        (
            "www.googleapis.com",
            "GET",
            "/drive/v3/files/syntheticFile123?alt=media",
            {"Authorization": "Bearer synthetic-token"},
        )
    ]


def test_revoked_refresh_token_fails_without_response_content(monkeypatch):
    class Connection:
        def __init__(self, host, timeout):
            assert host == "oauth2.googleapis.com"

        def request(self, method, path, body, headers):
            assert method == "POST" and path == "/token"
            assert "grant_type=refresh_token" in body

        def getresponse(self):
            response = Response(b"SECRET-SYNTHETIC-ONLY")
            response.status = 400
            return response

        def close(self):
            pass

    monkeypatch.setattr(backup.http.client, "HTTPSConnection", Connection)
    with pytest.raises(backup.Refused, match="^AUTH_REQUIRED$"):
        backup.Drive({"refresh_token": "synthetic"}).authenticate()


def test_pipeline_streams_and_checks_both_children(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    monkeypatch.setattr(backup, "REPO", tmp_path)
    monkeypatch.setattr(backup, "ENV", {"PATH": str(tmp_path) + os.pathsep + os.defpath})
    docker = tmp_path / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        + """import sys
if '--version' in sys.argv: print('GNU timeout'); sys.exit(0)
if any(arg.startswith('PGAPPNAME=') for arg in sys.argv):
    sys.stdout.buffer.write(b'PGDMP-synthetic-only')
else: print('0')
"""
    )
    docker.chmod(0o700)
    age = tmp_path / "age"
    age.write_text(
        f"#!{sys.executable}\n"
        + """import sys
sys.stdout.buffer.write(b'age-encryption.org/v1\\n' + sys.stdin.buffer.read())
"""
    )
    age.chmod(0o700)
    output = tmp_path / "output.age"
    backup.encrypted_dump(output, tmp_path / "public-recipient", "backup-20261115")
    assert output.read_bytes() == b"age-encryption.org/v1\nPGDMP-synthetic-only"
    assert output.stat().st_mode & 0o777 == 0o600
    # age can succeed on an incomplete/failed upstream dump; dump exit is still required.
    docker.write_text(
        docker.read_text().replace(
            "sys.stdout.buffer.write(b'PGDMP-synthetic-only')", "sys.exit(2)"
        )
    )
    with pytest.raises(backup.Refused, match="DUMP_FAILED"):
        backup.encrypted_dump(
            tmp_path / "bad.age", tmp_path / "public-recipient", "backup-20261115"
        )


def test_deadline_is_a_failure(monkeypatch):
    monkeypatch.setattr(backup, "DEADLINE", time.monotonic() - 1)
    with pytest.raises(backup.Refused, match="DEADLINE"):
        backup.remaining()


def test_child_exit_race_does_not_skip_any_cleanup(monkeypatch):
    calls = []

    class Child:
        def __init__(self, pid):
            self.pid = pid

        def poll(self):
            return None

        def wait(self, timeout):
            calls.append(("wait", self.pid))

    def kill(pid, signum):
        calls.append(("kill", pid))
        if pid == 123:
            raise ProcessLookupError

    monkeypatch.setattr(backup.os, "killpg", kill)
    assert backup.stop_children((Child(123), Child(456)))
    assert calls == [("kill", 123), ("wait", 123), ("kill", 456), ("wait", 456)]


def test_failed_encrypt_kills_live_dump_and_confirms_database_cleanup(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    monkeypatch.setattr(backup, "REPO", tmp_path)
    monkeypatch.setattr(backup, "ENV", {"PATH": str(tmp_path) + os.pathsep + os.defpath})
    marker = tmp_path / "child.pid"
    cleanup = tmp_path / "cleanup"
    docker = tmp_path / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        + "import os, pathlib, sys, time\n"
        + "if '--version' in sys.argv: print('GNU timeout'); sys.exit(0)\n"
        + "if any(arg.startswith('PGAPPNAME=') for arg in sys.argv):\n"
        + f"    pathlib.Path({str(marker)!r}).write_text(str(os.getpid()))\n"
        + "    time.sleep(30)\n"
        + "else:\n"
        + f"    pathlib.Path({str(cleanup)!r}).open('a').write('checked\\n')\n"
        + "    print('0')\n"
    )
    docker.chmod(0o700)
    age = tmp_path / "age"
    age.write_text(
        f"#!{sys.executable}\n"
        + "import pathlib, time\n"
        + f"while not pathlib.Path({str(marker)!r}).exists(): time.sleep(0.01)\n"
        + "raise SystemExit(2)\n"
    )
    age.chmod(0o700)
    started = time.monotonic()
    with pytest.raises(backup.Refused, match="ENCRYPT_FAILED"):
        backup.encrypted_dump(tmp_path / "output.age", tmp_path / "recipient", "backup-20261115")
    assert time.monotonic() - started < 5
    assert cleanup.read_text().splitlines() == ["checked", "checked"]
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)
