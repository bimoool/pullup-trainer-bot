"""Opt-in real tools drill, strictly on the pre-existing local synthetic PG service.

Run with PULLUP_BACKUP_INTEGRATION=1 and AGE_TEST_BIN_DIR pointing at unpacked
age/age-keygen test binaries. No provider traffic; generated identity is disposable.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("PULLUP_BACKUP_INTEGRATION") != "1", reason="opt-in synthetic Docker/age drill"
)


def test_real_postgres_age_roundtrip(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "drive_backup_real", root / "deploy/drive-backup.py"
    )
    backup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(backup)
    docker = shutil.which("docker")
    tools = Path(os.environ["AGE_TEST_BIN_DIR"])
    container = "pullup-cloud-postgres"
    env = {"PATH": os.defpath}

    def run(args, data=None):
        return subprocess.run(
            args, input=data, capture_output=True, env=env, timeout=60, check=True
        ).stdout

    # Force the local Unix socket: DOCKER_HOST/context and caller credentials are not inherited.
    inspected = json.loads(run([docker, "inspect", container]))[0]
    assert inspected["NetworkSettings"]["Ports"]["5432/tcp"] == [
        {"HostIp": "127.0.0.1", "HostPort": "55432"}
    ]
    database = "pullup_backup_test_" + uuid.uuid4().hex[:12]
    restored = database + "_restored"

    def sql(db, query):
        return run(
            [
                docker,
                "exec",
                container,
                "psql",
                "-U",
                "pullup",
                "-d",
                db,
                "-v",
                "ON_ERROR_STOP=1",
                "-At",
                "-c",
                query,
            ]
        )

    created = []
    try:
        for db in (database, restored):
            sql("postgres", "CREATE DATABASE " + db + " TEMPLATE template0")
            created.append(db)
        sql(
            database,
            "CREATE TABLE backup_probe(id integer primary key, note text); "
            "INSERT INTO backup_probe VALUES (1, 'synthetic-only-α'), (2, 'boundary-2026-12-01')",
        )
        tmp_path.chmod(0o700)
        identity = tmp_path / "test-identity"
        run([str(tools / "age-keygen"), "-o", str(identity)])
        recipient = tmp_path / "recipient.txt"
        recipient.write_bytes(run([str(tools / "age-keygen"), "-y", str(identity)]))
        recipient.chmod(0o600)
        adapter = tmp_path / "docker"
        # Adapt fixed Compose db calls ONLY to the explicit local synthetic container/database.
        adapter.write_text(
            f"#!{sys.executable}\n"
            + "import os, sys\n"
            + "args=sys.argv[1:]\n"
            + "assert args[:3] == ['compose','exec','-T']\n"
            + "args=args[3:]; extra=[]\n"
            + "if args[0]=='-e': extra=args[:2]; args=args[2:]\n"
            + "assert args[0]=='db'\n"
            + f"os.execv({docker!r}, [{docker!r}, 'exec', '-i', '-e', "
            + f"'POSTGRES_DB={database}', *extra, {container!r}, *args[1:]])\n"
        )
        adapter.chmod(0o700)
        monkeypatch.setattr(
            backup,
            "ENV",
            {"PATH": str(tmp_path) + os.pathsep + str(tools) + os.pathsep + os.defpath},
        )
        monkeypatch.setattr(backup, "REPO", tmp_path)
        encrypted = tmp_path / "test.dump.age"
        backup.encrypted_dump(encrypted, recipient, "backup-20261115")
        assert encrypted.read_bytes().startswith(b"age-encryption.org/v1\n")
        assert b"synthetic-only" not in encrypted.read_bytes()
        # Only this disposable synthetic test is decrypted; production never enters this drill.
        archive = run([str(tools / "age"), "-d", "-i", str(identity), str(encrypted)])
        assert archive.startswith(b"PGDMP")
        listing = run([docker, "exec", "-i", container, "pg_restore", "--list"], archive)
        assert b"TABLE public backup_probe" in listing
        run(
            [
                docker,
                "exec",
                "-i",
                container,
                "pg_restore",
                "-U",
                "pullup",
                "-d",
                restored,
                "--exit-on-error",
                "--no-owner",
            ],
            archive,
        )
        assert sql(restored, "SELECT id,note FROM backup_probe ORDER BY id").decode() == (
            "1|synthetic-only-α\n2|boundary-2026-12-01\n"
        )
    finally:
        for db in reversed(created):
            sql("postgres", "DROP DATABASE " + db)
        for name in ("test-identity", "recipient.txt", "test.dump.age"):
            (tmp_path / name).unlink(missing_ok=True)
