"""deploy/prod-guarded-dispatch.sh — forced command ключа GitHub Actions для guarded-выката production.

Проверяется без сервера: копия диспетчера с путями /root/bin и /root/backups, заменёнными на временный каталог, и
заглушки guarded-скриптов, которые печатают полученные аргументы и окружение. Цель — доказать, что через SSH проходит
ровно четыре шаблона, аргументы попадают в guarded-скрипты только из разобранного regex, окружение вызывающего не
пропускается, а второй параллельный запуск отклоняется."""

import os
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DISPATCH = REPO / "deploy" / "prod-guarded-dispatch.sh"
SHA = "0123456789abcdef0123456789abcdef01234567"
REV = "b5d8e1f3a6c9"
MANIFEST = "/root/backups/prod-pre-0123456-20261017T120000Z.manifest"
RUN_ID = "prod-0123456-20261017T120000Z-4242"

STUB = """#!/usr/bin/env bash
echo "SCRIPT=$(basename "$0")"
echo "ARGS=$*"
echo "FROM=${PROD_EXPECTED_FROM_REV:-unset} TO=${PROD_EXPECTED_TO_REV:-unset} DIR=${PROD_DIR:-unset} LEAK=${LEAK:-unset}"
"""


@pytest.fixture
def dispatcher(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    lock_dir = tmp_path / "backups"
    bin_dir.mkdir()
    for name in ("deploy-production-guarded-run.sh", "rollback-production-guarded.sh"):
        stub = bin_dir / name
        stub.write_text(STUB)
        stub.chmod(0o755)
    text = DISPATCH.read_text()
    assert "BIN=/root/bin\n" in text and "LOCK_DIR=/root/backups\n" in text
    text = text.replace("BIN=/root/bin\n", f"BIN={bin_dir}\n").replace("LOCK_DIR=/root/backups\n", f"LOCK_DIR={lock_dir}\n")
    script = tmp_path / "dispatch.sh"
    script.write_text(text)
    script.chmod(0o755)
    return script


def _run(script: Path, command: str) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ["PATH"], "SSH_ORIGINAL_COMMAND": command, "LEAK": "x", "PROD_DIR": "/tmp/evil"}
    return subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=30, check=False)


def test_preflight_passes_parsed_args_and_revisions_only(dispatcher):
    r = _run(dispatcher, f"prod-guarded {SHA} preflight {REV} {REV}")
    assert r.returncode == 0, r.stderr
    assert "SCRIPT=deploy-production-guarded-run.sh" in r.stdout
    assert f"ARGS={SHA} preflight\n" in r.stdout
    # Окружение вызывающего (PROD_DIR, LEAK) не проходит, ревизии — только из regex.
    assert f"FROM={REV} TO={REV} DIR=unset LEAK=unset" in r.stdout


def test_apply_requires_and_forwards_token(dispatcher):
    token = f"PRODUCTION-APPLY-{SHA[:12]}"
    r = _run(dispatcher, f"prod-guarded {SHA} apply e7c2a4f9d1b3 {REV} {token}")
    assert r.returncode == 0, r.stderr
    assert f"ARGS={SHA} apply {token}" in r.stdout
    assert f"FROM=e7c2a4f9d1b3 TO={REV}" in r.stdout

    r = _run(dispatcher, f"prod-guarded {SHA} apply {REV} {REV}")
    assert r.returncode != 0 and "SCRIPT=" not in r.stdout


def test_rollback_check_and_apply(dispatcher):
    r = _run(dispatcher, f"prod-rollback R1 {MANIFEST} check")
    assert r.returncode == 0, r.stderr
    assert "SCRIPT=rollback-production-guarded.sh" in r.stdout
    assert f"ARGS=R1 {MANIFEST} check\n" in r.stdout

    r = _run(dispatcher, f"prod-rollback R3 {MANIFEST} apply ROLLBACK-R3-{RUN_ID}")
    assert r.returncode == 0, r.stderr
    assert f"ARGS=R3 {MANIFEST} apply ROLLBACK-R3-{RUN_ID}" in r.stdout


@pytest.mark.parametrize(
    "command",
    [
        "",
        "./deploy.sh " + SHA,
        "bash",
        f"prod-guarded {SHA} preflight {REV} {REV}; id",
        f"prod-guarded {SHA} preflight {REV} {REV} PRODUCTION-APPLY-{SHA[:12]}",
        f"prod-guarded {SHA} rehearse-check {REV} {REV}",
        f"prod-guarded {SHA[:12]} preflight {REV} {REV}",
        f"prod-guarded {SHA.upper()} preflight {REV} {REV}",
        f"prod-guarded {SHA} apply {REV} {REV} PRODUCTION-APPLY-$(id)",
        f"prod-guarded  {SHA} preflight {REV} {REV}",
        f"prod-rollback R2 {MANIFEST} check",
        "prod-rollback R1 /etc/passwd.manifest check",
        "prod-rollback R1 /root/backups/../etc/x.manifest check",
        f"prod-rollback R1 {MANIFEST} check ROLLBACK-R1-{RUN_ID}",
        f"prod-rollback R1 {MANIFEST} apply",
    ],
)
def test_everything_else_is_rejected(dispatcher, command):
    r = _run(dispatcher, command)
    assert r.returncode != 0
    assert "SCRIPT=" not in r.stdout


def test_parallel_run_is_refused(dispatcher, tmp_path):
    lock_dir = tmp_path / "backups"
    lock_dir.mkdir()
    holder = subprocess.Popen(["flock", str(lock_dir / ".prod-actions.lock"), "sleep", "5"])
    try:
        for _ in range(50):
            probe = subprocess.run(["flock", "-n", str(lock_dir / ".prod-actions.lock"), "true"], check=False)
            if probe.returncode != 0:
                break
            time.sleep(0.1)
        r = _run(dispatcher, f"prod-guarded {SHA} preflight {REV} {REV}")
        assert r.returncode != 0
        assert "SCRIPT=" not in r.stdout
        assert "in progress" in r.stderr
    finally:
        holder.kill()
        holder.wait()
