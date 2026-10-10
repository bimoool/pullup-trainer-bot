"""Deploy-level репетиция ревизии f4c1a7e9b3d2 + scripts/backfill_training_session_v2.py (issue #307,
MIGRATION_V2 §3, §8). Каждый сценарий — своя временная БД и `alembic` подпроцессом.

Aged-набор на ревизии d8a3c6f1e2b4 (до #307):
  9001 живой старт своей тренировки (v1-снимок, client_session_id), 30 минут;
  9002 «Тренировку из моих» без идентичности — точное совпадение с ОДНОЙ (архивной) тренировкой;
  9003 то же, но списку упражнений соответствуют ДВЕ тренировки — не угадывается;
  9004 внешняя активность 45 минут;
  9005 копия legacy Workout (backfill: блок A системных подтягиваний, completed_at NULL);
  9006 перенесённый факультатив;
  9007 сессия курса с кредитом только по старой M2M (пара A+B);
  9008 сессия плана с одним M2M-звеном (кредит восстановлен #304);
  9009 активная (не завершённая) живая сессия.
"""

from datetime import UTC, date, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.domain.training_session_v2 import effective_duration_seconds
from app.services.training_analytics import TrainingAnalyticsService
from scripts.backfill_training_session_v2 import run
from tests.test_scripts.test_program_plan_migration import _exec
from tests.test_scripts.test_system_content_migration import (
    _alembic,
    _fetch,
    _run,
    _scalar,
    scratch_dsn,  # noqa: F401 — фикстура
)

PRE_REVISION = "d8a3c6f1e2b4"
REVISION = "f4c1a7e9b3d2"

# Колонки, которые ни миграция, ни скрипт не имеют права менять (история, кредит, подписка).
HISTORY = {
    "users": "id, telegram_id, subscription_status, subscription_expires_at",
    "subscriptions": "*",
    "training_sessions": (
        "id, user_id, source, status, performed_at, completed_at, effort, comment, activity_type, "
        "duration_seconds, workout_snapshot, plan_item_id, client_session_id"
    ),
    "session_blocks": "id, session_id, order_index, exercise_id, complex_id, result, started_at",
    "set_targets": "id, session_block_id, set_number, is_max_set, metric_type, value, unit",
    "set_logs": "id, session_block_id, set_target_id, set_number, is_max_set, metric_type, value, unit, is_extra",
    "session_plan_items": "*",
    "plan_items": "*",
    "program_inclusions": "*",
    "complexes": "*",
}


def _fingerprint(dsn: str) -> dict[str, str]:
    return {
        table: _scalar(
            dsn,
            f"SELECT count(*) || ':' || coalesce(md5(string_agg(x::text, '|' ORDER BY x::text)), '-') "
            f"FROM (SELECT {columns} FROM {table}) x",
        )
        for table, columns in HISTORY.items()
    }


AGED = """
INSERT INTO users (id, telegram_id, timezone, subscription_status, subscription_expires_at) VALUES
 (1001, 9001, 'UTC', 'active', '2026-12-31 10:00+00');
INSERT INTO subscriptions (user_id, status, source, started_at, ends_at) VALUES
 (1001, 'active', 'robokassa', '2026-09-01+00', '2026-12-31 10:00+00');
INSERT INTO exercises (id, name, metric_type, category, source_type, owner_user_id) VALUES
 (7001, 'Подтягивания широким', 'reps', 'user', 'user', 1001),
 (7002, 'Отжимания', 'reps', 'user', 'user', 1001),
 (7003, 'Планка', 'time', 'user', 'user', 1001);
INSERT INTO complexes (id, name, source_type, owner_user_id, archived_at) VALUES
 (6001, 'Утро', 'user', 1001, '2026-09-30 10:00+00'),
 (6002, 'Вечер', 'user', 1001, NULL),
 (6003, 'Дубль А', 'user', 1001, NULL),
 (6004, 'Дубль Б', 'user', 1001, NULL);
INSERT INTO complex_items (complex_id, exercise_id, order_index, sets) VALUES
 (6001, 7001, 0, 3), (6001, 7002, 1, 3), (6002, 7002, 0, 2), (6003, 7003, 0, 1), (6004, 7003, 0, 1);
INSERT INTO training_plans (id, user_id, created_at) VALUES (2001, 1001, '2026-09-14 09:00+00');
INSERT INTO plan_items (id, training_plan_id, exercise_id, complex_id, count_per_week, source, workout_definition_id) VALUES
 (5001, 2001, 7002, 6002, 1, 'manual', 6002), (5002, 2001, 7002, 6002, 1, 'manual', 6002),
 (5003, 2001, 7001, NULL, 2, 'manual', NULL);
INSERT INTO training_sessions (id, user_id, source, status, performed_at, completed_at, client_session_id,
  workout_snapshot, activity_type, duration_seconds, plan_item_id) VALUES
 (9001, 1001, 'freeform', 'completed', '2026-09-20 10:00+00', '2026-09-20 10:30+00',
  '11111111-1111-4111-8111-111111111111',
  '{"workout_id": 6002, "title": "Вечер", "items": [{"exercise_id": 7002, "exercise_name": "Отжимания", "order": 0,
    "protocol": {"type": "reps_sets", "sets": [{"target_reps": 10}, {"target_reps": 10}], "rest_seconds": 60}}]}',
  NULL, NULL, NULL),
 (9002, 1001, 'backdated', 'completed', '2026-09-21 12:00+00', '2026-09-21 12:00+00', NULL, NULL, NULL, NULL, NULL),
 (9003, 1001, 'backdated', 'completed', '2026-09-22 12:00+00', '2026-09-22 12:00+00', NULL, NULL, NULL, NULL, NULL),
 (9004, 1001, 'freeform', 'completed', '2026-09-23 12:00+00', '2026-09-23 12:00+00', NULL, NULL, 'running', 2700, NULL),
 (9005, 1001, 'plan', 'completed', '2026-09-10 08:00+00', NULL, NULL, NULL, NULL, NULL, NULL),
 (9006, 1001, 'elective', 'completed', '2026-09-11 08:00+00', NULL, NULL, NULL, NULL, NULL, NULL),
 (9007, 1001, 'plan', 'completed', '2026-09-24 10:00+00', '2026-09-24 10:40+00',
  '22222222-2222-4222-8222-222222222222', NULL, NULL, NULL, NULL),
 (9008, 1001, 'plan', 'completed', '2026-09-25 10:00+00', '2026-09-25 13:00+00',
  '33333333-3333-4333-8333-333333333333', NULL, NULL, NULL, 5001),
 (9009, 1001, 'freeform', 'started', '2026-10-08 10:00+00', NULL,
  '44444444-4444-4444-8444-444444444444', NULL, NULL, NULL, NULL);
INSERT INTO session_blocks (id, session_id, order_index, exercise_id) VALUES
 (9101, 9001, 0, 7002), (9102, 9002, 0, 7001), (9103, 9002, 1, 7002), (9104, 9003, 0, 7003),
 (9107, 9007, 0, 7001), (9108, 9008, 0, 7002), (9109, 9009, 0, 7002);
INSERT INTO session_blocks (id, session_id, order_index, exercise_id)
 SELECT 9105, 9005, 0, id FROM exercises WHERE category = 'pull_ups' AND subcategory = 'block_a' AND owner_user_id IS NULL;
INSERT INTO session_blocks (id, session_id, order_index, exercise_id)
 SELECT 9106, 9006, 0, id FROM exercises WHERE subcategory LIKE 'elective_%' AND owner_user_id IS NULL ORDER BY id LIMIT 1;
INSERT INTO set_targets (id, session_block_id, set_number, is_max_set, metric_type, value, unit) VALUES
 (9201, 9101, 1, false, 'reps', 10, 'reps'), (9202, 9101, 2, false, 'reps', 10, 'reps'),
 (9207, 9107, 1, false, 'reps', 8, 'reps'), (9208, 9107, 2, true, 'reps', 0, 'reps');
INSERT INTO set_logs (session_block_id, set_number, is_max_set, metric_type, value, unit, session_id, set_index) VALUES
 (9101, 1, false, 'reps', 10, 'reps', 9001, 0), (9101, 2, false, 'reps', 7, 'reps', 9001, 1),
 (9102, 1, false, 'reps', 8, 'reps', NULL, NULL), (9103, 1, false, 'reps', 20, 'reps', NULL, NULL),
 (9104, 1, false, 'time', 60, 's', NULL, NULL), (9105, 1, false, 'reps', 12, 'reps', NULL, NULL),
 (9105, 2, true, 'reps', 15, 'reps', NULL, NULL), (9106, 1, false, 'reps', 5, 'reps', NULL, NULL),
 (9107, 1, false, 'reps', 8, 'reps', 9007, 0), (9107, 2, false, 'reps', 11, 'reps', 9007, 1),
 (9108, 1, false, 'reps', 9, 'reps', 9008, 0), (9109, 1, false, 'reps', 3, 'reps', 9009, 0);
INSERT INTO session_plan_items (session_id, plan_item_id) VALUES (9007, 5003), (9007, 5002), (9008, 5001)
"""


def _effective(row) -> int | None:
    return effective_duration_seconds(
        duration_seconds=row.duration_seconds, duration_source=row.duration_source,
        performed_at=row.performed_at, completed_at=row.completed_at,
    )


def _sessions(dsn: str) -> dict[int, object]:
    return {r.id: r for r in _run(_fetch(dsn, "SELECT * FROM training_sessions ORDER BY id"))}


def _old_totals(dsn: str) -> tuple[int, int]:
    """Итоги, которые аналитика показывала ДО #307: число завершённых и секунды — duration_seconds или
    completed_at − performed_at в окне [60 с, 6 ч] (app.domain.training_analytics.session_duration_seconds)."""
    row = _run(_fetch(dsn, """
        SELECT count(*), coalesce(sum(CASE
          WHEN duration_seconds IS NOT NULL THEN duration_seconds
          WHEN completed_at IS NOT NULL AND EXTRACT(EPOCH FROM (completed_at - performed_at)) BETWEEN 60 AND 21600
            THEN FLOOR(EXTRACT(EPOCH FROM (completed_at - performed_at)))::int
          ELSE 0 END), 0)
        FROM training_sessions WHERE status = 'completed'
    """))[0]
    return int(row[0]), int(row[1])


async def _backfill(dsn: str, apply: bool) -> tuple[int, dict]:
    engine = create_async_engine(dsn)
    try:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        return await run(apply=apply, session_factory=factory)
    finally:
        await engine.dispose()


async def _analytics_totals(dsn: str) -> tuple[int, int, int]:
    engine = create_async_engine(dsn)
    try:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            _, metrics, _, _ = await TrainingAnalyticsService(session).build(
                user_id=1001, timezone="UTC", now=datetime(2026, 10, 9, tzinfo=UTC),
                date_from=date(2026, 9, 1), date_to=date(2026, 10, 9),
            )
        return metrics.total_workouts, metrics.total_minutes, metrics.without_duration
    finally:
        await engine.dispose()


def _prepare(dsn: str) -> None:
    _alembic(dsn, "upgrade", PRE_REVISION)
    _run(_exec(dsn, AGED))


def test_aged_upgrade_maps_sources_without_inventing_data(scratch_dsn):  # noqa: F811
    _prepare(scratch_dsn)
    before = _fingerprint(scratch_dsn)
    old_count, old_seconds = _old_totals(scratch_dsn)

    _alembic(scratch_dsn, "upgrade", "head")
    assert _fingerprint(scratch_dsn) == before  # история, кредит, подписка — байт в байт

    rows = _sessions(scratch_dsn)
    assert {i: rows[i].source_v2 for i in rows} == {
        9001: "direct_live", 9002: "manual_custom", 9003: "manual_custom", 9004: "external_activity",
        9005: "planned_live", 9006: "manual_existing_workout", 9007: "planned_live", 9008: "planned_live",
        9009: "direct_live",
    }
    assert {i: rows[i].origin for i in rows} == {
        **{i: "native" for i in rows}, 9005: "legacy_backfill", 9006: "legacy_elective",
    }
    assert rows[9004].kind == "external_activity" and all(rows[i].kind == "strength" for i in rows if i != 9004)
    # длительность: измеренная живая — да; ручная/копия/факультатив — неизвестна (не 0, не выдумка).
    # Колонка duration_seconds истории не переписывается — измеренная = completed_at − performed_at.
    assert (rows[9001].duration_seconds, rows[9001].duration_source) == (None, "measured")
    assert _effective(rows[9001]) == 1800 and _effective(rows[9008]) == 10800
    assert (rows[9004].duration_seconds, rows[9004].duration_source) == (2700, "entered")
    for i in (9002, 9003, 9005, 9006):
        assert (rows[i].duration_seconds, rows[i].duration_source, _effective(rows[i])) == (None, "unknown", None)
    assert rows[9001].started_at == rows[9001].performed_at and rows[9001].ended_at == rows[9001].completed_at
    assert rows[9001].engine_version == 1 and rows[9002].engine_version is None
    assert rows[9001].workout_definition_id == 6002 and rows[9008].workout_definition_id == 6002
    assert rows[9007].plan_item_id is None and rows[9007].workout_definition_id is None  # M2M-пара не угадывается
    assert all(rows[i].workout_definition_version_id is None for i in rows)  # версия истории неизвестна

    # итоги старого пользователя не уменьшились (и не выросли): та же длительность, то же число
    total, minutes, without = _run(_analytics_totals(scratch_dsn))
    assert total == old_count
    assert minutes == old_seconds // 60
    assert without == 4  # 9002, 9003, 9005, 9006 — без длительности


def test_backfill_script_dry_run_apply_and_rerun_is_noop(scratch_dsn):  # noqa: F811
    _prepare(scratch_dsn)
    _alembic(scratch_dsn, "upgrade", "head")
    before = _fingerprint(scratch_dsn)
    columns_before = _sessions(scratch_dsn)

    code, dry = _run(_backfill(scratch_dsn, apply=False))
    assert code == 0 and dry["total_mutations"] > 0, dry
    assert _sessions(scratch_dsn) == columns_before  # dry-run ничего не пишет

    code, applied = _run(_backfill(scratch_dsn, apply=True))
    assert code == 0, applied
    assert applied["totals"] == {"identity_recovered": 1, "prescription_snapshot": 7}, applied
    [user] = applied["users_detail"]
    assert user["unrecovered_identity"] == [{"session_id": 9003, "matches": 2}]

    code, again = _run(_backfill(scratch_dsn, apply=True))
    assert code == 0 and again["total_mutations"] == 0, again
    assert _fingerprint(scratch_dsn) == before

    rows = _sessions(scratch_dsn)
    assert rows[9002].workout_definition_id == 6001  # единственное точное совпадение (архивная тренировка)
    assert (rows[9002].identity_recovered_by, rows[9002].source_v2) == ("exact_match_v1", "manual_existing_workout")
    assert rows[9003].workout_definition_id is None and rows[9003].source_v2 == "manual_custom"
    assert rows[9004].prescription_snapshot is None  # у активности снимка нет
    assert rows[9009].prescription_snapshot is None  # активная — снимок пишет новый код / следующий прогон

    snap = rows[9001].prescription_snapshot
    assert snap["synthesized"] is True and snap["title"] == "Вечер" and "prescription_kind" not in snap
    assert [s["target_reps"] for s in snap["blocks"][0]["sets"]] == [10, 10]
    unprescribed = rows[9002].prescription_snapshot
    assert unprescribed["prescription_kind"] == "unprescribed" and unprescribed["title"] == "Утро"
    assert [b["exercise_id"] for b in unprescribed["blocks"]] == [7001, 7002]
    course = rows[9007].prescription_snapshot
    assert [s["kind"] for s in course["blocks"][0]["sets"]] == ["reps", "max_reps"]  # MAX-цель пережила синтез
    assert rows[9005].prescription_snapshot["blocks"][0]["sets"][1]["role"] == "max"  # факт подхода на максимум

    # J10: старые кредиты остались читаемыми — M2M и явный
    credits = {r.plan_item_id for r in _run(_fetch(scratch_dsn, "SELECT plan_item_id FROM session_plan_items"))}
    assert credits == {5001, 5002, 5003}
    assert rows[9008].plan_item_id == 5001


def test_catch_up_of_rows_written_by_old_code_after_migration(scratch_dsn):  # noqa: F811
    """Окно деплоя: миграция прошла, старый код ещё пишет строки без v2-полей — скрипт их догоняет
    теми же правилами, что миграция."""
    _prepare(scratch_dsn)
    _alembic(scratch_dsn, "upgrade", "head")
    _run(_exec(scratch_dsn, """
INSERT INTO training_sessions (id, user_id, source, status, performed_at, completed_at, activity_type, duration_seconds)
 VALUES (9501, 1001, 'freeform', 'completed', '2026-10-01 10:00+00', '2026-10-01 10:00+00', 'cycling', 1200),
        (9502, 1001, 'backdated', 'completed', '2026-10-02 10:00+00', '2026-10-02 10:00+00', NULL, NULL)
"""))
    code, applied = _run(_backfill(scratch_dsn, apply=True))
    assert code == 0, applied
    rows = _sessions(scratch_dsn)
    assert (rows[9501].kind, rows[9501].source_v2, rows[9501].origin, rows[9501].duration_source) == (
        "external_activity", "external_activity", "native", "entered",
    )
    assert (rows[9502].source_v2, rows[9502].duration_source, _effective(rows[9502])) == (
        "manual_custom", "unknown", None,
    )
    code, again = _run(_backfill(scratch_dsn, apply=True))
    assert again["total_mutations"] == 0, again


def test_rerun_upgrade_and_downgrade_upgrade(scratch_dsn):  # noqa: F811
    _prepare(scratch_dsn)
    before = _fingerprint(scratch_dsn)
    _alembic(scratch_dsn, "upgrade", "head")
    mapped = {i: (r.source_v2, r.origin, r.duration_source) for i, r in _sessions(scratch_dsn).items()}
    _alembic(scratch_dsn, "upgrade", "head")  # повторный деплой — ничего
    assert {i: (r.source_v2, r.origin, r.duration_source) for i, r in _sessions(scratch_dsn).items()} == mapped

    _alembic(scratch_dsn, "downgrade", PRE_REVISION)
    assert _fingerprint(scratch_dsn) == before  # откат схемы не трогает историю и кредит
    columns = {r.column_name for r in _run(_fetch(
        scratch_dsn, "SELECT column_name FROM information_schema.columns WHERE table_name = 'training_sessions'",
    ))}
    assert "source_v2" not in columns and "prescription_snapshot" not in columns
    assert _scalar(scratch_dsn, "SELECT duration_seconds FROM training_sessions WHERE id = 9001") is None

    _alembic(scratch_dsn, "upgrade", REVISION)
    assert {i: (r.source_v2, r.origin, r.duration_source) for i, r in _sessions(scratch_dsn).items()} == mapped
    assert _fingerprint(scratch_dsn) == before


def test_fresh_install_single_head(scratch_dsn):  # noqa: F811
    _alembic(scratch_dsn, "upgrade", "head")
    # Голова цепочки — следующая ревизия (#305 e3b9c5d7a2f1 идёт за этой); эта ревизия применена.
    assert _scalar(scratch_dsn, "SELECT version_num FROM alembic_version") == "e3b9c5d7a2f1"
    assert _scalar(scratch_dsn, "SELECT count(*) FROM training_sessions") == 0
