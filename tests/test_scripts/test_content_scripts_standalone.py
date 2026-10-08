"""Контент-скрипты запускаются ровно так, как их документирует оператор: `python scripts/<x>.py`
в чистом интерпретаторе (issue #296, FD-06).

Раньше `scripts/seed_exercise_library.py` падал на `NoReferencedTableError: ... exercises.owner_user_id
-> users` (импортировал только models_program), а тесты этого не видели: они сами импортировали
`app.db.models` до скрипта. Здесь — subprocess, где ничего заранее не импортировано. Падение
случалось на INSERT (flush), поэтому проверка на БД ДО ревизии контента (строк ещё нет и скрипт
реально вставляет); на БД с поставленным контентом скрипты — идемпотентный no-op.
Продакшен от этих скриптов не зависит (каталог ставит миграция); скрипты остаются безопасными
ручными инструментами."""

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from tests.test_scripts import _todays_orm_columns as todays_orm_columns

REPO_ROOT = Path(__file__).resolve().parents[2]


def _admin(dsn: str, statement: str) -> None:
    async def run() -> None:
        engine = create_async_engine(dsn.rsplit("/", 1)[0] + "/pullup", isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as conn:
                await conn.execute(sa.text(statement))
        finally:
            await engine.dispose()

    asyncio.run(run())


def _admin_on(dsn: str, statement: str) -> None:
    """DDL в самой scratch-БД (не в служебной pullup)."""
    async def run() -> None:
        engine = create_async_engine(dsn, isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as conn:
                await conn.execute(sa.text(statement))
        finally:
            await engine.dispose()

    asyncio.run(run())


def _count(dsn: str, sql: str) -> int:
    async def run() -> int:
        engine = create_async_engine(dsn)
        try:
            async with engine.connect() as conn:
                return (await conn.execute(sa.text(sql))).scalar_one()
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _python(dsn: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": dsn}
    env.setdefault("BOT_TOKEN", "ci-test-token")
    return subprocess.run(
        [sys.executable, *args], cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=300, check=False,
    )


def _scratch_db(test_dsn: str, revision: str) -> Iterator[str]:
    name = f"pullup_scripts_{uuid.uuid4().hex[:10]}"
    _admin(test_dsn, f'CREATE DATABASE "{name}" OWNER pullup')
    dsn = test_dsn.rsplit("/", 1)[0] + f"/{name}"
    try:
        result = _python(dsn, "-m", "alembic", "upgrade", revision)
        assert result.returncode == 0, result.stderr
        yield dsn
    finally:
        _admin(test_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture(scope="module")
def migrated_dsn(test_dsn: str) -> Iterator[str]:
    """БД после `alembic upgrade head`: системный контент уже поставлен миграцией."""
    yield from _scratch_db(test_dsn, "head")


@pytest.fixture
def pre_content_dsn(test_dsn: str) -> Iterator[str]:
    """БД до ревизии контента: каталога/упражнений нет, скрипты вставляют строки по-настоящему."""
    yield from _scratch_db(test_dsn, "9e3f1a4b6c80")


SCRIPTS = [
    ["scripts/seed_exercise_library.py"],
    ["scripts/seed_collections.py", "--dry-run"],
    ["scripts/seed_collections.py"],
]


@pytest.mark.parametrize("argv", SCRIPTS, ids=[" ".join(a) for a in SCRIPTS])
def test_content_script_runs_in_clean_interpreter_and_is_idempotent(migrated_dsn: str, argv: list[str]):
    before = {
        "exercises": _count(migrated_dsn, "SELECT count(*) FROM exercises"),
        "collection_items": _count(migrated_dsn, "SELECT count(*) FROM collection_items"),
    }
    for _ in range(2):  # повторный запуск тоже exit 0 и без дублей
        result = _python(migrated_dsn, *argv)
        assert result.returncode == 0, f"{' '.join(argv)} упал:\n{result.stdout}\n{result.stderr}"
    assert _count(migrated_dsn, "SELECT count(*) FROM exercises") == before["exercises"]
    assert _count(migrated_dsn, "SELECT count(*) FROM collection_items") == before["collection_items"]


def test_seed_exercise_library_ids_match_shipped_rows(migrated_dsn: str):
    """Скрипт находит поставленные миграцией строки по тому же ключу (имя + без владельца), а не создаёт копии."""
    result = _python(migrated_dsn, "scripts/seed_exercise_library.py")
    assert result.returncode == 0, result.stderr
    assert "Планка" in result.stdout and "Отжимания" in result.stdout
    assert _count(migrated_dsn, "SELECT count(*) FROM exercises WHERE name IN ('Планка', 'Отжимания')") == 2


def test_seed_exercise_library_inserts_in_clean_interpreter_on_empty_db(pre_content_dsn: str):
    """Регрессия FD-06: на пустой библиотеке `python scripts/seed_exercise_library.py` вставляет строки и
    выходит 0 (раньше — NoReferencedTableError на flush)."""
    assert _count(pre_content_dsn, "SELECT count(*) FROM exercises") == 0
    # Сегодняшний ORM на старой схеме — его поздние колонки на время скрипта (_todays_orm_columns.py).
    for statement in todays_orm_columns.ADD:
        _admin_on(pre_content_dsn, statement)
    for _ in range(2):
        result = _python(pre_content_dsn, "scripts/seed_exercise_library.py")
        assert result.returncode == 0, f"упал:\n{result.stdout}\n{result.stderr}"
    assert _count(pre_content_dsn, "SELECT count(*) FROM exercises") == 2


def test_seed_collections_runs_in_clean_interpreter_on_empty_db(pre_content_dsn: str):
    for argv in (["--dry-run"], [], []):
        result = _python(pre_content_dsn, "scripts/seed_collections.py", *argv)
        assert result.returncode == 0, f"{argv} упал:\n{result.stdout}\n{result.stderr}"
    assert _count(pre_content_dsn, "SELECT count(*) FROM collection_items") == 0  # программ ещё нет
