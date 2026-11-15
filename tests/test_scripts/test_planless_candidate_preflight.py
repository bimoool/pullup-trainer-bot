"""The literal installed guard and candidate CLI consume byte-identical classification."""

import hashlib
import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path

import asyncpg
import pytest

from tests.test_scripts import test_deploy_production_guarded as guard_tests
from tests.test_scripts.test_deploy_production_guarded import NEW_HEAD, SHA, TOKEN

ROOT = Path(__file__).resolve().parents[2]
QUERY = ROOT / "scripts/sql/planless_classification.sql"
GUARD = ROOT / "deploy/deploy-production-guarded-run.sh"


@pytest.fixture
def sandbox(tmp_path):
    return guard_tests.sandbox.__wrapped__(tmp_path)


@lru_cache
def candidate_host_sql():
    source = GUARD.read_text()
    function = source[
        source.index("require_candidate_planless_zero() {") : source.index("\nsummary() {")
    ]
    stub = r"""
exec 7>/dev/null
exec 8>&1
SHA=cccccccccccccccccccccccccccccccccccccccc
git() {
  case "$1" in
    ls-tree) printf '100644 blob aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\tscripts/sql/planless_classification.sql\n' ;;
    cat-file) wc -c < "$CANDIDATE_SQL_FILE" ;;
    show) cat "$CANDIDATE_SQL_FILE" ;;
    *) return 1 ;;
  esac
}
dbq() { printf '%s\n' "$1" >&8; printf '1|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0\n'; }
"""
    proc = subprocess.run(
        ["bash", "-c", stub + function + "\nrequire_candidate_planless_zero"],
        env={**os.environ, "CANDIDATE_SQL_FILE": str(QUERY)},
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert QUERY.read_text().strip() in proc.stdout
    return proc.stdout


async def candidate_counts(test_dsn):
    """Execute the exact host wrapper on the same explicitly synthetic database."""
    statements = [part.strip() for part in candidate_host_sql().split(";") if part.strip()]
    assert len(statements) == 6
    conn = await asyncpg.connect(test_dsn.replace("postgresql+asyncpg://", "postgresql://"))
    try:
        for statement in statements[:-2]:
            await conn.execute(statement)
        assert await conn.fetchval("SHOW transaction_read_only") == "on"
        assert await conn.fetchval("SHOW transaction_isolation") == "repeatable read"
        assert await conn.fetchval("SHOW statement_timeout") == "5s"
        assert await conn.fetchval("SHOW lock_timeout") == "1s"
        row = await conn.fetchval(statements[-2])
        with pytest.raises(asyncpg.ReadOnlySQLTransactionError):
            await conn.execute("UPDATE users SET username='must-not-write'")
        return list(map(int, row.split("|")))[1:]
    finally:
        await conn.close()


def test_guard_pin_and_query_are_exact_and_rehearsal_pin_matches():
    source = GUARD.read_text()
    assert hashlib.sha256(QUERY.read_bytes()).hexdigest() in source
    assert (
        hashlib.sha256(GUARD.read_bytes()).hexdigest()
        in (ROOT / "deploy/rehearse-rest01-release.sh").read_text()
    )
    sql = candidate_host_sql()
    assert sql.startswith("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;")
    assert sql.rstrip().endswith("ROLLBACK;")
    assert not re.search(
        r"\b(UPDATE|DELETE|INSERT|CREATE|ALTER|DROP|FOR UPDATE)\b", sql, re.IGNORECASE
    )
    assert (
        "ast"
        not in source[
            source.index("require_candidate_planless_zero() {") : source.index("\nsummary() {")
        ]
    )


@pytest.mark.parametrize("mode", ["preflight", "apply"])
@pytest.mark.parametrize(
    "bad",
    [
        {
            "CANDIDATE_QUERY_ENTRY": "120000 blob "
            + "a" * 40
            + "\tscripts/sql/planless_classification.sql"
        },
        {"CANDIDATE_QUERY_SIZE": "32769"},
        {"CANDIDATE_QUERY_BAD_HASH": "1"},
        {"FAIL_CANDIDATE_DIAGNOSTIC": "1"},
        {"CANDIDATE_DIAGNOSTIC_ROW": "private-row"},
        {"CANDIDATE_DIAGNOSTIC_ROW": "1|1|0|0|0|0|0|1|0|1|" + "|".join(["0"] * 14)},
    ],
)
def test_same_schema_candidate_preflight_fails_closed_before_build_or_stop(sandbox, mode, bad):
    sandbox.preset(rev=NEW_HEAD)
    proc, log, state = sandbox(
        SHA,
        mode,
        *([TOKEN] if mode == "apply" else []),
        PROD_EXPECTED_FROM_REV=NEW_HEAD,
        **bad,
    )
    assert proc.returncode == 1, proc.stderr
    assert "candidate planless compatibility is blocked or unavailable" in proc.stderr
    assert "private-row" not in proc.stdout + proc.stderr
    assert "PRIVATE-CANDIDATE-ERROR" not in proc.stdout + proc.stderr
    assert not any(re.search(r"compose -p \S+ (build|stop|run)\b|docker tag", line) for line in log)
    assert state["running"] == {"app": True, "web": True}
    assert not (sandbox.root / "backups").exists()


def test_same_schema_planless_zero_is_read_only_and_only_necessary(sandbox):
    sandbox.preset(rev=NEW_HEAD)
    proc, log, _ = sandbox(SHA, "preflight", PROD_EXPECTED_FROM_REV=NEW_HEAD)
    assert proc.returncode == 0, proc.stderr
    assert '"status":"PLANLESS_CANDIDATE_ZERO"' in proc.stderr
    assert '"PLANLESS_BLOCKED":0' in proc.stderr
    assert log.count("planless-candidate-host") == 1
    assert not (sandbox.root / "backups").exists()


