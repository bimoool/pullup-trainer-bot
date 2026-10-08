"""Deploy-level проверка системного контента (issue #296, FD-01/FD-06/FD-07).

Пустая БД → `alembic upgrade head` ПОДПРОЦЕССОМ (ровно как `deploy/deploy-run.sh`:
`docker compose run --rm app alembic upgrade head`) → ничего, кроме миграций: каталог,
библиотека и готовые тренировки уже на месте, а пользовательских строк нет.

Каждый сценарий — своя временная БД (создаётся/удаляется тут же): conftest чистит
programs/exercises/complexes между обычными тестами, поэтому контент миграции в обычных
тестах не виден. Админский DSN — база `pullup` (как в tests/conftest.py)."""

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from scripts.backfill_multi_program import (
    _ELECTIVE_EXERCISE_NAMES,
    _EXERCISE_BLOCK_A_NAME,
    _EXERCISE_BLOCK_B_NAME,
    _PROGRAM_NAME,
    _STRATEGY_PROFILE_NAME,
    _program_config_snapshot,
    seed_catalog,
)
from scripts.seed_collections import seed_collections
from scripts.seed_exercise_library import seed_exercise_library
from tests.test_scripts import _todays_orm_columns as todays_orm_columns

REPO_ROOT = Path(__file__).resolve().parents[2]
PRE_CONTENT_REVISION = "9e3f1a4b6c80"  # head до ревизии системного контента

LIBRARY = [
    ("Подтягивания", "reps"), ("Подтягивания с резиной", "reps"), ("Подтягивания с отягощением", "reps"),
    ("Австралийские подтягивания", "reps"), ("Лопаточные подтягивания", "reps"), ("Вис на турнике", "time"),
    ("Планка", "time"), ("Отжимания", "reps"),
]
WORKOUTS = ["3 минуты подтягиваний", "W-лесенка", "Максимум подтягиваний", "Объём ×5"]

# Всё, что принадлежит конкретному пользователю: миграция каталога не имеет права создать ни одной строки.
USER_SPECIFIC_TABLES = (
    "users", "training_plans", "plan_weeks", "plan_items", "program_inclusions", "training_sessions",
    "session_blocks", "set_logs", "subscriptions", "baselines", "workouts", "elective_workouts",
    "assessment_results", "user_favorites", "events", "workout_drafts",
)


def _admin_dsn(dsn: str) -> str:
    return dsn.rsplit("/", 1)[0] + "/pullup"


def _run(coro):
    return asyncio.run(coro)


async def _admin(dsn: str, statement: str) -> None:
    engine = create_async_engine(_admin_dsn(dsn), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(sa.text(statement))
    finally:
        await engine.dispose()


async def _fetch(dsn: str, sql: str, **params) -> list[sa.Row]:
    engine = create_async_engine(dsn)
    try:
        async with engine.connect() as conn:
            return list((await conn.execute(sa.text(sql), params)).all())
    finally:
        await engine.dispose()


async def _execute(dsn: str, sql: str) -> None:
    engine = create_async_engine(dsn)
    try:
        async with engine.begin() as conn:
            await conn.execute(sa.text(sql))
    finally:
        await engine.dispose()


def _scalar(dsn: str, sql: str, **params):
    return _run(_fetch(dsn, sql, **params))[0][0]


def _alembic(dsn: str, *args: str) -> None:
    env = {**os.environ, "DATABASE_URL": dsn}
    env.setdefault("BOT_TOKEN", "ci-test-token")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=300, check=False,
    )
    assert result.returncode == 0, f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}"


@pytest.fixture
def scratch_dsn(test_dsn: str) -> Iterator[str]:
    name = f"pullup_deploy_{uuid.uuid4().hex[:10]}"
    _run(_admin(test_dsn, f'CREATE DATABASE "{name}" OWNER pullup'))
    try:
        yield test_dsn.rsplit("/", 1)[0] + f"/{name}"
    finally:
        _run(_admin(test_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture(scope="module")
def deployed_dsn(test_dsn: str) -> Iterator[str]:
    """Одна БД «как после деплоя на пустую установку» на весь модуль — для read-only проверок."""
    name = f"pullup_deploy_{uuid.uuid4().hex[:10]}"
    _run(_admin(test_dsn, f'CREATE DATABASE "{name}" OWNER pullup'))
    dsn = test_dsn.rsplit("/", 1)[0] + f"/{name}"
    try:
        _alembic(dsn, "upgrade", "head")
        yield dsn
    finally:
        _run(_admin(test_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def _content_counts(dsn: str) -> dict[str, int]:
    tables = (
        "programs", "program_items", "progression_strategy_profiles", "exercises", "complexes", "complex_items",
        "collections", "collection_items", "assessment_protocols",
    )
    return {table: _scalar(dsn, f"SELECT count(*) FROM {table}") for table in tables}


def _user_rows(dsn: str) -> dict[str, int]:
    return {table: _scalar(dsn, f"SELECT count(*) FROM {table}") for table in USER_SPECIFIC_TABLES}


# --- пустая БД → alembic upgrade head -----------------------------------------------------------


def test_empty_db_upgrade_head_ships_program_library_and_workouts(deployed_dsn: str):
    programs = _run(_fetch(deployed_dsn, "SELECT id, name, category, structure_type::text, config FROM programs"))
    assert [(p.name, p.category, p.structure_type) for p in programs] == [("Подтягивания", "pull_ups", "recurring")]
    # Решение владельца 2026-10-07: «Подтягивания» бесплатна навсегда (c3f7a9e2d5b1), остальное — premium по умолчанию.
    assert _scalar(deployed_dsn, "SELECT access_level FROM programs WHERE name = 'Подтягивания'") == "free"

    # Публичная библиотека (D1): ровно согласованный набор, системные, без владельца, не служебные.
    library = _run(_fetch(
        deployed_dsn,
        "SELECT name, metric_type::text FROM exercises WHERE owner_user_id IS NULL AND source_type = 'system' "
        "AND subcategory IS NULL ORDER BY name",
    ))
    assert sorted((r.name, r.metric_type) for r in library) == sorted(LIBRARY)

    # Готовые тренировки (D2): системные Complex с ComplexItem и protocol.
    workouts = _run(_fetch(
        deployed_dsn,
        "SELECT c.name, c.source_type, c.owner_user_id, c.archived_at, count(i.id) AS items, "
        "min(i.protocol->>'type') AS protocol_type "
        "FROM complexes c LEFT JOIN complex_items i ON i.complex_id = c.id GROUP BY c.id ORDER BY c.name",
    ))
    assert [w.name for w in workouts] == WORKOUTS
    assert all(w.source_type == "system" and w.owner_user_id is None and w.archived_at is None for w in workouts)
    assert all(w.items == 1 for w in workouts)
    assert {w.name: w.protocol_type for w in workouts} == {
        "Максимум подтягиваний": "max_effort", "W-лесенка": "reps_sets",
        "3 минуты подтягиваний": "interval", "Объём ×5": "reps_sets",
    }

    # Подборка «Начни с подтягиваний» непуста: на Главной она видна.
    in_collection = _scalar(
        deployed_dsn,
        "SELECT count(*) FROM collection_items i JOIN collections c ON c.id = i.collection_id "
        "JOIN programs p ON p.id = i.program_id WHERE c.slug = 'start-with-pull-ups' AND p.name = 'Подтягивания'",
    )
    assert in_collection == 1


def test_internal_exercises_ship_but_are_not_library(deployed_dsn: str):
    internal = _run(_fetch(
        deployed_dsn, "SELECT name, subcategory FROM exercises WHERE subcategory IS NOT NULL ORDER BY name",
    ))
    assert {r.subcategory for r in internal} == {
        "block_a", "block_b", "elective_max_reps_ladder", "elective_w_ladder", "elective_three_minutes",
        "elective_volume_target",
    }
    assert len(internal) == 6


def test_shipped_program_matches_seed_catalog_definition(deployed_dsn: str):
    """Та же программа, что делает seed_catalog: имя, профиль прогрессии, ProgramItems, роли, электив-упражнения
    и замороженный конфиг (копия значений — сейчас равна «живым» константам; если константы осознанно
    поменяются, ДАННЫЕ миграции остаются прежними, а этот тест надо обновить намеренно)."""
    program = _run(_fetch(deployed_dsn, "SELECT id, name, goal, config, progression_strategy_id FROM programs"))[0]
    assert program.name == _PROGRAM_NAME
    assert program.config == _program_config_snapshot()

    profile = _run(_fetch(
        deployed_dsn, "SELECT name, strategy_type::text, config FROM progression_strategy_profiles WHERE id = :id",
        id=program.progression_strategy_id,
    ))[0]
    assert (profile.name, profile.strategy_type, profile.config) == (_STRATEGY_PROFILE_NAME, "step", {})

    roles = {
        r.subcategory: r.name for r in _run(_fetch(
            deployed_dsn,
            "SELECT e.name, e.subcategory FROM program_items pi JOIN exercises e ON e.id = pi.exercise_id "
            "WHERE pi.program_id = :pid", pid=program.id,
        ))
    }
    assert roles == {"block_a": _EXERCISE_BLOCK_A_NAME, "block_b": _EXERCISE_BLOCK_B_NAME}
    items = _run(_fetch(
        deployed_dsn, "SELECT week_phase::text, count_per_week, day_of_week FROM program_items WHERE program_id = :pid",
        pid=program.id,
    ))
    assert [(i.week_phase, i.count_per_week, i.day_of_week) for i in items] == [("base", 3, None)] * 2

    electives = {
        r.subcategory: r.name for r in _run(_fetch(
            deployed_dsn, "SELECT name, subcategory FROM exercises WHERE subcategory LIKE 'elective\\_%'",
        ))
    }
    assert electives == {f"elective_{t.value}": name for t, name in _ELECTIVE_EXERCISE_NAMES.items()}


def test_migration_creates_no_user_specific_rows(deployed_dsn: str):
    assert _user_rows(deployed_dsn) == dict.fromkeys(USER_SPECIFIC_TABLES, 0)


def test_no_duplicate_system_rows_by_natural_key(deployed_dsn: str):
    assert _run(_fetch(
        deployed_dsn,
        "SELECT name FROM exercises WHERE owner_user_id IS NULL GROUP BY name HAVING count(*) > 1",
    )) == []
    assert _run(_fetch(deployed_dsn, "SELECT name FROM programs GROUP BY name HAVING count(*) > 1")) == []
    assert _run(_fetch(
        deployed_dsn, "SELECT name FROM complexes WHERE owner_user_id IS NULL GROUP BY name HAVING count(*) > 1",
    )) == []


# --- повторные прогоны --------------------------------------------------------------------------


def test_repeated_upgrade_and_downgrade_upgrade_create_no_duplicates(scratch_dsn: str):
    _alembic(scratch_dsn, "upgrade", "head")
    first = _content_counts(scratch_dsn)

    _alembic(scratch_dsn, "upgrade", "head")  # повторный деплой
    assert _content_counts(scratch_dsn) == first

    # откат ревизии контента (и всех над ней) — no-op для каталога, каталог остаётся
    _alembic(scratch_dsn, "downgrade", PRE_CONTENT_REVISION)
    assert _scalar(scratch_dsn, "SELECT version_num FROM alembic_version") == PRE_CONTENT_REVISION
    assert _content_counts(scratch_dsn) == first
    _alembic(scratch_dsn, "upgrade", "head")
    assert _content_counts(scratch_dsn) == first
    assert _user_rows(scratch_dsn) == dict.fromkeys(USER_SPECIFIC_TABLES, 0)


def test_seed_function_run_twice_is_a_noop(scratch_dsn: str):
    import importlib.util

    _alembic(scratch_dsn, "upgrade", "head")
    before = _content_counts(scratch_dsn)
    path = REPO_ROOT / "app/db/migrations/versions/a4c8e1f7b2d9_system_content_seed.py"
    spec = importlib.util.spec_from_file_location("system_content_migration_twice", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    async def _twice() -> None:
        engine = create_async_engine(scratch_dsn)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(module.seed_system_content)
                await conn.run_sync(module.seed_system_content)
        finally:
            await engine.dispose()

    _run(_twice())
    assert _content_counts(scratch_dsn) == before


# --- окружение, где каталог уже создан вручную скриптами -----------------------------------------


async def _run_catalog_scripts(dsn: str, *, with_collections: bool) -> dict[str, int]:
    engine = create_async_engine(dsn)
    try:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            catalog = await seed_catalog(session)
            library = await seed_exercise_library(session)
            if with_collections:
                await seed_collections(session)
            await session.commit()
        return {
            "program": catalog.program_id, "block_a": catalog.exercise_a_id, "block_b": catalog.exercise_b_id,
            "plank": library["Планка"], "pushups": library["Отжимания"],
        }
    finally:
        await engine.dispose()


@pytest.mark.parametrize("with_collections", [False, True])
def test_migration_does_not_duplicate_what_seed_scripts_already_created(scratch_dsn: str, with_collections: bool):
    _alembic(scratch_dsn, "upgrade", PRE_CONTENT_REVISION)
    assert _scalar(scratch_dsn, "SELECT count(*) FROM programs") == 0  # до ревизии каталога нет
    # Скрипты — сегодняшний ORM, он знает колонки поздних ревизий (programs.access_level, идентичность
    # упражнений #303). Колонки добавляются только на время скриптов и снимаются, чтобы БД была ровно
    # «старая схема + строки скриптов» (tests/test_scripts/_todays_orm_columns.py).
    for statement in todays_orm_columns.ADD:
        _run(_execute(scratch_dsn, statement))
    ids = _run(_run_catalog_scripts(scratch_dsn, with_collections=with_collections))
    for statement in todays_orm_columns.DROP:
        _run(_execute(scratch_dsn, statement))

    _alembic(scratch_dsn, "upgrade", "head")

    # Всё, что уже было, — те же строки (найдены, не пересозданы и не продублированы).
    assert _scalar(scratch_dsn, "SELECT count(*) FROM programs") == 1
    assert _scalar(scratch_dsn, "SELECT id FROM programs") == ids["program"]
    # Бесплатна навсегда (решение 2026-10-07) и на окружениях, где программу создал скрипт.
    assert _scalar(scratch_dsn, "SELECT access_level FROM programs") == "free"
    assert _scalar(scratch_dsn, "SELECT count(*) FROM progression_strategy_profiles") == 1
    assert _scalar(scratch_dsn, "SELECT count(*) FROM program_items") == 2
    for key, name in (
        ("block_a", _EXERCISE_BLOCK_A_NAME), ("block_b", _EXERCISE_BLOCK_B_NAME), ("plank", "Планка"),
        ("pushups", "Отжимания"),
    ):
        rows = _run(_fetch(scratch_dsn, "SELECT id FROM exercises WHERE name = :n AND owner_user_id IS NULL", n=name))
        assert [r.id for r in rows] == [ids[key]], name
    assert _run(_fetch(
        scratch_dsn, "SELECT name FROM exercises WHERE owner_user_id IS NULL GROUP BY name HAVING count(*) > 1",
    )) == []
    # Остальное недостающее миграция добавила: библиотека D1 целиком, 6 служебных, 4 тренировки.
    assert _scalar(scratch_dsn, "SELECT count(*) FROM exercises WHERE subcategory IS NULL") == len(LIBRARY)
    assert _scalar(scratch_dsn, "SELECT count(*) FROM exercises") == len(LIBRARY) + 6
    assert _scalar(scratch_dsn, "SELECT count(*) FROM complexes") == len(WORKOUTS)
    # Подборка: программа ровно один раз, независимо от того, кто её положил.
    assert _scalar(scratch_dsn, "SELECT count(*) FROM collection_items WHERE program_id IS NOT NULL") == 1
    # И ни одного пользователя/плана/включения.
    assert _user_rows(scratch_dsn) == dict.fromkeys(USER_SPECIFIC_TABLES, 0)
