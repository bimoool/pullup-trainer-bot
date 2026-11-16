"""Actual R3 psql/stdin SQL against owned, disposable PostgreSQL 16 databases.

CI uses its explicit TEST_DATABASE_URL and local psql. For the existing synthetic
cloud instance, set R3_TEST_PSQL_CONTAINER to its Docker container name. No app
fixtures, production manifest/dump, installed runner or server commands are used.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import unquote, urlsplit

import asyncpg
import pytest

ROLLBACK = Path(__file__).resolve().parents[2] / "deploy/rollback-production-guarded.sh"


class SwapDatabases:
    def __init__(self, dsn: str):
        self.dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")
        self.admin_dsn = self.dsn.rsplit("/", 1)[0] + "/postgres"
        self.prefix = "r3_swap_" + uuid.uuid4().hex
        self.live = self.prefix + "_live"
        self.restored = self.prefix + "_rb"
        self.failed = self.prefix + "_failed"
        self.sentinel = self.prefix + "_sentinel"
        self.owned = (self.live, self.restored, self.failed, self.sentinel)
        self.created_oids: set[int] = set()

    async def query(self, sql: str, *args):
        conn = await asyncpg.connect(self.admin_dsn)
        try:
            return await conn.fetch(sql, *args)
        finally:
            await conn.close()

    async def create(self):
        version = (await self.query("SHOW server_version_num"))[0][0]
        assert 160000 <= int(version) < 170000, "this regression requires PostgreSQL 16"
        for name, marker in (
            (self.live, "failed-live-state"),
            (self.restored, "verified-predeploy-copy"),
            (self.sentinel, "unrelated-database"),
        ):
            await self.query(f"CREATE DATABASE {name} CONNECTION LIMIT 7")
            self.created_oids.add(
                (await self.query("SELECT oid FROM pg_database WHERE datname=$1", name))[0][0]
            )
            await self.query(f"COMMENT ON DATABASE {name} IS '{marker}'")
            conn = await asyncpg.connect(self.dsn.rsplit("/", 1)[0] + "/" + name)
            try:
                await conn.execute("CREATE SCHEMA protected_history")
                await conn.execute(
                    "CREATE TABLE protected_history.workouts "
                    "(id integer PRIMARY KEY, payload jsonb NOT NULL)"
                )
                await conn.execute(
                    "INSERT INTO protected_history.workouts VALUES "
                    "(1, jsonb_build_object('marker', $1::text, 'sets', 12))",
                    marker,
                )
                await conn.execute(
                    "CREATE TABLE protected_history.workouts_archive_v1 "
                    "AS SELECT * FROM protected_history.workouts"
                )
                await conn.execute(
                    "COMMENT ON TABLE protected_history.workouts IS 'synthetic protected history'"
                )
            finally:
                await conn.close()

    async def snapshot(self):
        metadata = await self.query(
            "SELECT datname, oid, datdba, encoding, datcollate, datctype, datistemplate, "
            "datallowconn, datconnlimit, datacl::text, shobj_description(oid, 'pg_database') "
            "FROM pg_database WHERE datname = ANY($1::text[]) ORDER BY datname",
            list(self.owned),
        )
        result = {}
        for row in metadata:
            name = row[0]
            conn = await asyncpg.connect(self.dsn.rsplit("/", 1)[0] + "/" + name)
            try:
                contents = await conn.fetch(
                    "SELECT 'workouts', id, payload::text FROM protected_history.workouts "
                    "UNION ALL SELECT 'archive', id, payload::text "
                    "FROM protected_history.workouts_archive_v1 ORDER BY 1, 2"
                )
                schema = await conn.fetch(
                    "SELECT table_name, column_name, data_type, is_nullable "
                    "FROM information_schema.columns WHERE table_schema='protected_history' "
                    "ORDER BY table_name, ordinal_position"
                )
                comment = await conn.fetchval(
                    "SELECT obj_description('protected_history.workouts'::regclass)"
                )
                result[name] = (
                    tuple(row[1:]),
                    list(map(tuple, contents)),
                    list(map(tuple, schema)),
                    comment,
                )
            finally:
                await conn.close()
        return result

    async def cleanup(self):
        # Renames can leave either name arrangement. Only names belonging to this
        # fixture may be removed; never scan for or terminate unrelated sessions.
        if not self.created_oids:
            return
        rows = await self.query(
            "SELECT datname FROM pg_database WHERE datname = ANY($1::text[]) "
            "AND oid = ANY($2::oid[])",
            list(self.owned),
            list(self.created_oids),
        )
        for row in rows:
            await self.query(f"DROP DATABASE {row[0]}")

    def start(self, *, first_failure=False, pause=False):
        source = ROLLBACK.read_text()
        helper = next(line for line in source.splitlines() if line.startswith("adminq()"))
        swap = next(
            line.strip()
            for line in source.splitlines()
            if line.strip().startswith('adminq "') and "ALTER DATABASE" in line
        )
        if pause:
            # Inject a barrier between the actual two statements, without adding
            # a transaction absent from the production command.
            swap = swap.replace("; ALTER DATABASE $RB", "; SELECT pg_sleep(60); ALTER DATABASE $RB")
        parsed = urlsplit(self.admin_dsn)
        env = {
            **os.environ,
            "PGHOST": parsed.hostname or "localhost",
            "PGPORT": str(parsed.port or 5432),
            "PGPASSWORD": unquote(parsed.password or ""),
            "POSTGRES_USER": unquote(parsed.username or ""),
            "PGAPPNAME": self.prefix,
            "DB_NAME": self.live,
            "RB": self.restored,
            "FAILED": self.sentinel if first_failure else self.failed,
        }
        # Exercise the unchanged production helper and its psql arguments. Only
        # adapt docker's transport to CI's local psql or the synthetic container.
        transport = 'shift 3; "$@"'
        if os.environ.get("R3_TEST_PSQL_CONTAINER"):
            transport = (
                'command docker exec -i -e PGAPPNAME="$PGAPPNAME" '
                '"$R3_TEST_PSQL_CONTAINER" "${@:4}"'
            )
        script = (
            "set -euo pipefail\nDBC=r3-test-dbc\n"
            "docker() {\n"
            '  [[ $# = 6 && "$1" = exec && "$2" = -i && "$3" = r3-test-dbc ]] || return 2\n'
            f"  {transport}\n}}\n"
            'die() { echo "$*" >&2; exit 1; }\n'
            f"{helper}\n{swap}\n"
        )
        return subprocess.Popen(
            ["bash", "-c", script],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    async def interrupt_between_renames(self):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            rows = await self.query(
                "SELECT pid FROM pg_stat_activity WHERE application_name=$1 "
                "AND state='active' AND query LIKE 'SELECT pg_sleep%'",
                self.prefix,
            )
            if rows:
                # Interrupt this fixture's PostgreSQL backend process only. This
                # disconnects the real psql client before the second rename/COMMIT.
                assert (await self.query("SELECT pg_terminate_backend($1)", rows[0][0]))[0][0]
                return
            await asyncio.sleep(0.05)
        pytest.fail("psql did not reach the between-renames interruption barrier")


@pytest.fixture
def databases():
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("requires explicit synthetic TEST_DATABASE_URL")
    if not os.environ.get("R3_TEST_PSQL_CONTAINER"):
        assert shutil.which("psql"), "install the PostgreSQL client for this real SQL regression"
    fixture = SwapDatabases(dsn)
    try:
        asyncio.run(fixture.create())
        yield fixture
    finally:
        asyncio.run(fixture.cleanup())


@pytest.mark.parametrize("failure", ["first-rename", "second-rename", "backend-interruption"])
def test_r3_swap_failure_preserves_both_names_data_and_metadata(databases, failure):
    before = asyncio.run(databases.snapshot())
    # A late connection can race the runner's zero-connections check. It makes
    # PostgreSQL reject rename two, after rename one has succeeded.
    holder = None
    loop = asyncio.new_event_loop()
    proc = None
    try:
        if failure == "second-rename":
            holder = loop.run_until_complete(
                asyncpg.connect(databases.dsn.rsplit("/", 1)[0] + "/" + databases.restored)
            )
        proc = databases.start(
            first_failure=failure == "first-rename", pause=failure == "backend-interruption"
        )
        if failure == "backend-interruption":
            asyncio.run(databases.interrupt_between_renames())
        out, err = proc.communicate(timeout=20)
        assert proc.returncode != 0, out + err
        assert "database swap failed" in err
    finally:
        if proc and proc.poll() is None:
            # Stop only this fixture's backend, including failed barrier tests.
            asyncio.run(
                databases.query(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE application_name=$1",
                    databases.prefix,
                )
            )
            proc.communicate(timeout=10)
        if holder:
            loop.run_until_complete(holder.close())
        loop.close()
    after = asyncio.run(databases.snapshot())
    assert after == before, (
        f"{failure}: expected all original database names, OIDs, metadata and protected data; "
        f"before={list(before)}, after={list(after)}"
    )
    assert "nothing renamed" not in err


def test_r3_swap_commits_both_names_and_retains_failed_history(databases):
    before = asyncio.run(databases.snapshot())
    proc = databases.start()
    out, err = proc.communicate(timeout=20)
    assert proc.returncode == 0, out + err
    assert asyncio.run(databases.snapshot()) == {
        databases.live: before[databases.restored],
        databases.failed: before[databases.live],
        databases.sentinel: before[databases.sentinel],
    }
