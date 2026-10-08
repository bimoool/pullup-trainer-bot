"""Deploy-level проверка миграции b7d2e9f4a1c3 (issue #303, MIGRATION_V2 §3, §7, §8).

Каждый сценарий — своя временная БД и `alembic` подпроцессом (как deploy/deploy-run.sh):
  * пустая БД → upgrade head: версии системных тренировок, переписанные W/Максимум/3 минуты;
  * «старая» БД (V1-эпоха, ревизия c3f7a9e2d5b1 + пользовательские строки) → upgrade head:
    версии из V1-головы, неоднозначное помечено и не угадано, подписки/история/доступ — те же;
  * повторный (замороженный) бэкфилл = 0 изменений; рантайм-синхронизация после миграции — тоже;
  * буквальные golden-хеши системного контента на реальной свежей установке;
  * downgrade → upgrade восстанавливает выводимое из V1-голов; история версий сверх этого ТЕРЯЕТСЯ
    (WORKOUT_DOMAIN_V2 §9.13) — тест это фиксирует, а не обещает обратное.
"""

import asyncio

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.migrations._frozen.b7d2e9f4a1c3_backfill import report_lines, run_backfill
from app.db.workout_definition_store import sync_from_v1_head
from app.domain.electives import W_LADDER
from app.domain.workout_definition import content_from_stored, content_hash, describe
from tests.test_scripts.test_frozen_b7d2e9f4a1c3_parity import GOLDEN_CURRENT, GOLDEN_V1
from tests.test_scripts.test_system_content_migration import (
    _alembic,
    _fetch,
    _run,
    _scalar,
    deployed_dsn,  # noqa: F401 — фикстура
    scratch_dsn,  # noqa: F401 — фикстура
)

PRE_V2_REVISION = "c3f7a9e2d5b1"
V2_REVISION = "b7d2e9f4a1c3"
W_SEQUENCE = "5-4-3-2-1-2-3-4-5-4-3-2-1-2-3-4-5"

# Таблицы, которые миграция не имеет права менять (MIGRATION_V2 §7 + история).
PROTECTED = (
    "users", "subscriptions", "programs", "program_items", "training_plans", "plan_weeks", "plan_items",
    "program_inclusions", "training_sessions", "session_blocks", "set_targets", "set_logs", "complex_items",
    "collections", "collection_items",
)


def _fingerprint(dsn: str) -> dict[str, str]:
    result = {
        table: _scalar(dsn, f"SELECT count(*) || ':' || coalesce(md5(string_agg(x::text, '|' ORDER BY x::text)), '-') FROM {table} x")
        for table in PROTECTED
    }
    result["complexes_core"] = _scalar(
        dsn,
        "SELECT md5(string_agg(id || name || source_type || coalesce(owner_user_id::text, '') "
        "|| coalesce(archived_at::text, ''), '|' ORDER BY id)) FROM complexes",
    )
    result["exercises_core"] = _scalar(
        dsn,
        "SELECT md5(string_agg(id || name || category || coalesce(subcategory, '') || metric_type, '|' ORDER BY id)) "
        "FROM exercises",
    )
    return result


def _versions(dsn: str, title: str) -> list:
    return _run(_fetch(
        dsn,
        "SELECT v.id, v.version_no, v.content, v.content_hash, c.current_version_id FROM workout_definition_versions v "
        "JOIN complexes c ON c.id = v.workout_definition_id WHERE c.name = :name ORDER BY v.version_no",
        name=title,
    ))


async def _seed_aged(dsn: str) -> None:
    # exec_driver_sql: в JSON-литералах есть «:», sa.text принял бы их за bind-параметры.
    engine = create_async_engine(dsn)
    try:
        async with engine.begin() as conn:
            for statement in AGED_ROWS.split(";\n"):
                if statement.strip():
                    await conn.exec_driver_sql(statement)
    finally:
        await engine.dispose()


async def _backfill_changes(dsn: str) -> tuple[int, list[str]]:
    engine = create_async_engine(dsn)
    try:
        async with engine.begin() as conn:
            report = await conn.run_sync(run_backfill)
            return report.total_changes, report_lines(report)
    finally:
        await engine.dispose()


AGED_ROWS = """
INSERT INTO users (id, telegram_id, subscription_status, subscription_expires_at) VALUES
 (1001, 9001, 'active', '2026-12-31 10:00+00'), (1002, 9002, 'expired', '2026-09-01 10:00+00');
INSERT INTO subscriptions (user_id, status, source, started_at, ends_at) VALUES
 (1001, 'active', 'robokassa', '2026-09-01+00', '2026-12-31 10:00+00');
INSERT INTO exercises (id, name, metric_type, category, source_type, owner_user_id) VALUES
 (5001, 'Мои подтягивания узким', 'reps', 'user', 'user', 1001),
 (5002, 'Странное', 'reps', 'legacy_misc', 'system', NULL);
INSERT INTO complexes (id, name, source_type, owner_user_id, archived_at) VALUES
 (6001, 'Моя 3×10', 'user', 1001, NULL), (6002, 'Планка + макс', 'user', 1001, NULL),
 (6003, 'Кривой интервал', 'user', 1001, NULL), (6004, 'Пустая', 'user', 1002, NULL),
 (6005, 'Legacy без протокола', 'user', 1002, NULL), (6006, 'Архивная', 'user', 1001, now());
INSERT INTO complex_items (id, complex_id, exercise_id, order_index, sets, protocol) VALUES
 (7001, 6001, 5001, 0, 0, '{"type":"reps_sets","prescription":{"source":"static","sets":3,"reps":10},"rest_seconds":90}'),
 (7002, 6002, (SELECT id FROM exercises WHERE name = 'Планка' AND owner_user_id IS NULL), 0, 0,
  '{"type":"time_sets","prescription":{"source":"static","sets":2,"duration_seconds":30},"rest_seconds":60}'),
 (7003, 6002, 5001, 1, 0, '{"type":"max_effort","prescription":{"source":"static","attempts":2}}'),
 (7004, 6003, 5001, 0, 0, '{"type":"interval","total_duration_seconds":100,"work_seconds":10,"rest_seconds":20,"starts_with":"work"}'),
 (7006, 6006, 5001, 0, 0, '{"type":"reps_sets","prescription":{"source":"static","sets":1,"reps":5},"rest_seconds":0}');
INSERT INTO complex_items (id, complex_id, exercise_id, order_index, sets, target_value, target_unit, rest_seconds) VALUES
 (7005, 6005, 5001, 0, 4, 6, 'reps', 45);
INSERT INTO training_sessions (id, user_id, source, performed_at, completed_at, status, workout_snapshot) VALUES
 (8001, 1001, 'freeform', '2026-09-20 08:00+00', '2026-09-20 08:30+00', 'completed',
  '{"workout_id":6001,"title":"Моя 3×10","items":[]}'),
 (8002, 1002, 'backdated', '2026-09-19 08:00+00', '2026-09-19 08:00+00', 'completed', NULL);
"""


async def _runtime_sync_changes(dsn: str) -> int:
    """Рантайм-путь (Builder) по всем тренировкам сразу после миграции: сколько версий создал бы."""
    engine = create_async_engine(dsn)
    try:
        async with engine.begin() as conn:
            def _sync_all(sync_conn) -> int:
                rows = sync_conn.execute(sa.text("SELECT id, name FROM complexes WHERE source_type = 'user' ORDER BY id")).all()
                return sum(sync_from_v1_head(sync_conn, row.id, row.name)[1] for row in rows)

            created = await conn.run_sync(_sync_all)
            await conn.rollback()
            return created
    finally:
        await engine.dispose()


# --- пустая БД ---------------------------------------------------------------------------------


def test_fresh_db_ships_versions_and_reauthored_system_content(deployed_dsn):  # noqa: F811
    ladder = _versions(deployed_dsn, "W-лесенка")
    assert [v.version_no for v in ladder] == [1, 2]
    v1, v2 = ladder
    assert v2.current_version_id == v2.id
    # v1 — честная V1-голова (17 × 3), v2 — явная лесенка: история не переписана, а дополнена версией.
    assert describe(content_from_stored(v1.content).blocks[0]) == "17 × 3"
    stored = content_from_stored(v2.content, expected_hash=v2.content_hash)
    assert [s.target_reps for s in stored.blocks[0].sets] == list(W_LADDER)
    assert [s.rest_after_seconds for s in stored.blocks[0].sets] == [10] * 16 + [None]
    assert describe(stored.blocks[0]) == W_SEQUENCE
    assert content_hash(stored) == v2.content_hash

    (_, maximum) = _versions(deployed_dsn, "Максимум подтягиваний")
    max_sets = maximum.content["blocks"][0]["sets"]
    assert [s["kind"] for s in max_sets] == ["max_reps"] * 4
    assert [s["target_reps"] for s in max_sets] == [None] * 4
    assert [s["rest_after_seconds"] for s in max_sets] == [180, 120, 60, None]

    (_, three) = _versions(deployed_dsn, "3 минуты подтягиваний")
    assert three.content["blocks"][0]["interval"] == {
        "work_seconds": 10, "rest_seconds": 20, "rounds": 6, "record_reps_per_round": True,
    }
    assert [v.version_no for v in _versions(deployed_dsn, "Объём ×5")] == [1]

    # Идентичность упражнений: подпись есть у всех, служебные указывают на «Подтягивания» (E2).
    assert _scalar(deployed_dsn, "SELECT count(*) FROM exercises WHERE display_name IS NULL OR category_id IS NULL") == 0
    pull_up = _scalar(deployed_dsn, "SELECT id FROM exercises WHERE name = 'Подтягивания' AND owner_user_id IS NULL")
    roles = _run(_fetch(
        deployed_dsn, "SELECT analytics_exercise_id, visibility FROM exercises WHERE subcategory IS NOT NULL",
    ))
    assert len(roles) == 6 and all(r.analytics_exercise_id == pull_up and r.visibility == "internal" for r in roles)
    assert _scalar(
        deployed_dsn, "SELECT count(*) FROM exercise_categories WHERE display_name ~ '^[a-z_]+$'",
    ) == 0


def test_fresh_db_golden_hashes(deployed_dsn):  # noqa: F811
    """Буквальные хеши того, что ревизия b7d2e9f4a1c3 пишет на свежую установку (golden — в
    test_frozen_b7d2e9f4a1c3_parity.py, там же объяснено, почему они не меняются никогда)."""
    for title, golden in GOLDEN_CURRENT.items():
        versions = _versions(deployed_dsn, title)
        current = next(v for v in versions if v.id == v.current_version_id)
        assert current.content_hash == golden, title
        assert versions[0].content_hash == GOLDEN_V1[title], title
        assert current.version_no == max(v.version_no for v in versions)
        assert content_from_stored(current.content, expected_hash=current.content_hash)


def test_fresh_db_second_backfill_is_noop(scratch_dsn):  # noqa: F811
    _alembic(scratch_dsn, "upgrade", "head")
    changes, lines = _run(_backfill_changes(scratch_dsn))
    assert changes == 0, lines


# --- «старая» БД V1-эпохи --------------------------------------------------------------------------


def test_aged_v1_db_upgrade_backfills_without_touching_history(scratch_dsn):  # noqa: F811
    _alembic(scratch_dsn, "upgrade", PRE_V2_REVISION)
    _run(_seed_aged(scratch_dsn))
    before = _fingerprint(scratch_dsn)

    # Ревизия ЭТОЙ волны (#303), не head: следующие ревизии (#304 d8a3c6f1e2b4) добавляют колонки в
    # programs/plan_items/training_sessions — их собственная репетиция в test_program_plan_migration.py.
    _alembic(scratch_dsn, "upgrade", V2_REVISION)
    assert _fingerprint(scratch_dsn) == before  # подписки, история, доступ, V1-головы — байт в байт

    current = {
        r.id: r for r in _run(_fetch(
            scratch_dsn,
            "SELECT c.id, v.version_no, v.content FROM complexes c "
            "LEFT JOIN workout_definition_versions v ON v.id = c.current_version_id WHERE c.id >= 6001 ORDER BY c.id",
        ))
    }
    assert describe(content_from_stored(current[6001].content).blocks[0]) == "3 × 10"
    plank, maximum = content_from_stored(current[6002].content).blocks
    assert describe(plank) == "2 × 0:30" and describe(maximum) == "Максимум × 2"
    assert [s.rest_after_seconds for s in maximum.sets] == [0, None]  # V1 без rest_seconds = 0, как в V1
    assert current[6003].content is None  # интервал 100 с не делится на 30 — не угадываем
    assert current[6004].content is None  # пустая тренировка
    assert describe(content_from_stored(current[6005].content).blocks[0]) == "4 × 6"  # legacy-колонки
    assert describe(content_from_stored(current[6006].content).blocks[0]) == "1 × 5"  # архивная — тоже

    user_ex = _run(_fetch(
        scratch_dsn,
        "SELECT e.display_name, e.visibility, c.display_name AS category FROM exercises e "
        "JOIN exercise_categories c ON c.id = e.category_id WHERE e.id IN (5001, 5002) ORDER BY e.id",
    ))
    assert [(r.display_name, r.visibility, r.category) for r in user_ex] == [
        ("Мои подтягивания узким", "user", "Мои упражнения"),
        ("Странное", "public", "Без категории"),
    ]

    changes, lines = _run(_backfill_changes(scratch_dsn))
    assert changes == 0, lines
    assert any("complex 6003" in line for line in lines)  # неоднозначное — в отчёте, не молча
    assert _fingerprint(scratch_dsn) == before
    # Рантайм (Builder-синхронизация) сегодня видит то же содержимое — новых версий не создаёт.
    assert _run(_runtime_sync_changes(scratch_dsn)) == 0
    keys = _run(_fetch(scratch_dsn, "SELECT content->'blocks'->0->>'key' AS key FROM workout_definition_versions "
                                    "WHERE workout_definition_id = 6001"))
    assert [r.key for r in keys] == ["i7001e5001"]


def test_downgrade_then_upgrade_restores_v1_derived_state(scratch_dsn):  # noqa: F811
    """Без пользовательской истории версий (только то, что выводится из V1-голов и литералов)
    откат → накат воспроизводит то же самое."""
    _alembic(scratch_dsn, "upgrade", PRE_V2_REVISION)
    _run(_seed_aged(scratch_dsn))
    before = _fingerprint(scratch_dsn)
    _alembic(scratch_dsn, "upgrade", "head")
    first = _run(_fetch(scratch_dsn, "SELECT workout_definition_id, version_no, content_hash FROM workout_definition_versions ORDER BY 1, 2"))

    _alembic(scratch_dsn, "downgrade", PRE_V2_REVISION)
    assert _scalar(scratch_dsn, "SELECT to_regclass('workout_definition_versions') IS NULL")
    assert _scalar(
        scratch_dsn,
        "SELECT count(*) FROM information_schema.columns WHERE table_name = 'exercises' AND column_name = 'display_name'",
    ) == 0
    assert _fingerprint(scratch_dsn) == before  # откат не тронул ни истории, ни V1

    _alembic(scratch_dsn, "upgrade", "head")
    again = _run(_fetch(scratch_dsn, "SELECT workout_definition_id, version_no, content_hash FROM workout_definition_versions ORDER BY 1, 2"))
    assert [tuple(r) for r in again] == [tuple(r) for r in first]


def test_downgrade_below_revision_is_lossy_for_user_version_history(scratch_dsn):  # noqa: F811
    """C3: откат схемы ниже b7d2e9f4a1c3 после того, как пользователь накопил историю версий,
    ТЕРЯЕТ её; повторный upgrade строит только то, что выводится из уцелевшей V1-головы."""
    _alembic(scratch_dsn, "upgrade", PRE_V2_REVISION)
    _run(_seed_aged(scratch_dsn))
    _alembic(scratch_dsn, "upgrade", "head")

    async def _edit_head_twice() -> None:
        engine = create_async_engine(scratch_dsn)
        try:
            async with engine.begin() as conn:
                for reps in (5, 7):  # Builder: две правки → v2, v3
                    await conn.exec_driver_sql(
                        "UPDATE complex_items SET protocol = jsonb_set(protocol, '{prescription,reps}', "
                        f"'{reps}') WHERE id = 7001"
                    )
                    await conn.run_sync(lambda c: sync_from_v1_head(c, 6001, "Моя 3×10"))
        finally:
            await engine.dispose()

    _run(_edit_head_twice())
    history = "SELECT version_no, content_hash FROM workout_definition_versions WHERE workout_definition_id = 6001 ORDER BY 1"
    before = [tuple(r) for r in _run(_fetch(scratch_dsn, history))]
    assert [no for no, _ in before] == [1, 2, 3]

    _alembic(scratch_dsn, "downgrade", PRE_V2_REVISION)
    _alembic(scratch_dsn, "upgrade", "head")
    after = [tuple(r) for r in _run(_fetch(scratch_dsn, history))]
    assert after == [(1, before[-1][1])]  # только версия из текущей V1-головы (7 повторений); v1/v2 потеряны


def test_versions_reject_update(deployed_dsn):  # noqa: F811
    async def _attempt():
        engine = create_async_engine(deployed_dsn)
        try:
            async with engine.begin() as conn:
                await conn.execute(sa.text("UPDATE workout_definition_versions SET version_no = version_no"))
        finally:
            await engine.dispose()

    with pytest.raises(Exception, match="immutable"):
        asyncio.run(_attempt())
