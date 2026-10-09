"""Deploy-level репетиция ревизии d8a3c6f1e2b4 (issue #304, MIGRATION_V2 §3, §5, §7, §8).

Каждый сценарий — своя временная БД и `alembic` подпроцессом (как deploy/deploy-run.sh):
  A. пустая БД → upgrade head: каталожные «Подтягивания» получают slots/frequency/constraints/assessment,
     OD-2: main = min_days_between_starts 3;
  B. «старая» БД до DOMAIN-v2 Wave 1b (ревизия b7d2e9f4a1c3 + план/инклюзия/агрегатные строки/история) →
     upgrade head: аддитивный бэкфилл (source, workout_definition_id, status, single-link кредит), пары A+B
     не угадываются;
  C. владелецподобный aged-профиль на мигрированной БД → converge (scripts/repair_plan_convergence.py --all)
     → повторный прогон = 0 изменений;
  D. повторный upgrade и повторный бэкфилл (downgrade -1 → upgrade) = тот же результат;
  E. downgrade → upgrade: что теряется (явный кредит/свои планы/разметка), что нет (история, M2M);
  F/G. подписки, доступ (programs.access_level), история сессий — байт в байт до/после.
"""

import asyncio
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from scripts.repair_plan_convergence import run_all
from tests.test_scripts.test_system_content_migration import (
    _alembic,
    _fetch,
    _run,
    _scalar,
    deployed_dsn,  # noqa: F401 — фикстура
    scratch_dsn,  # noqa: F401 — фикстура
)

PRE_REVISION = "b7d2e9f4a1c3"
# Ревизия ЭТОЙ волны (#304), не head: следующая ревизия (#305 e3b9c5d7a2f1) по контракту дописывает
# progression_state.block_b.work_sets — её репетиция в test_course_prescription_migration.py.
REVISION = "d8a3c6f1e2b4"

# Таблицы/колонки, которые ни миграция, ни converge менять не имеют права (MIGRATION_V2 §7 + история).
HISTORY = {
    "users": "id, telegram_id, subscription_status, subscription_expires_at",
    "subscriptions": "*",
    "programs": "id, name, access_level, config",
    "program_items": "*",
    "training_sessions": (
        "id, user_id, source, status, performed_at, completed_at, effort, comment, activity_type, "
        "duration_seconds, workout_snapshot"
    ),
    # Явный список колонок, а не «*»: последующие аддитивные ревизии (#307 добавил block_key/status/kind/…)
    # не меняют значения истории, но меняют текст строки «*».
    "session_blocks": "id, session_id, order_index, exercise_id, complex_id, result, started_at, created_at",
    "set_targets": "id, session_block_id, set_number, is_max_set, metric_type, value, unit, effort, note, created_at",
    "set_logs": (
        "id, session_block_id, set_target_id, set_number, is_max_set, metric_type, value, unit, effort, note, "
        "created_at, session_id, set_index, is_extra"
    ),
    "session_plan_items": "*",
    "plan_weeks": "*",
    "program_inclusions": "id, training_plan_id, program_id, snapshot, progression_state, initial_progression_state, "
    "started_at, expires_at, is_active",
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


async def _exec(dsn: str, sql: str) -> None:
    engine = create_async_engine(dsn)
    try:
        async with engine.begin() as conn:
            for statement in sql.split(";\n"):
                if statement.strip():
                    await conn.exec_driver_sql(statement)
    finally:
        await engine.dispose()


# Владелецподобный пользователь до Wave 1b: курс с 14.09 (недели 1–4 в агрегатной форме A+B × 3),
# история на неделе 2 и 4 (пары A+B по M2M), ручная строка «2 в неделю» с одной сессией (single-link),
# действующая подписка. Каталог «Подтягивания» засеян миграциями (a4c8e1f7b2d9).
AGED = """
INSERT INTO users (id, telegram_id, timezone, subscription_status, subscription_expires_at) VALUES
 (1001, 9001, 'UTC', 'active', '2026-12-31 10:00+00');
INSERT INTO subscriptions (user_id, status, source, started_at, ends_at) VALUES
 (1001, 'active', 'robokassa', '2026-09-01+00', '2026-12-31 10:00+00');
INSERT INTO training_plans (id, user_id, created_at) VALUES (2001, 1001, '2026-09-14 09:00+00');
INSERT INTO program_inclusions (id, training_plan_id, program_id, snapshot, progression_state,
  initial_progression_state, started_at, is_active)
 SELECT 3001, 2001, p.id,
  jsonb_build_object('schema_version', 1, 'program_name', p.name, 'structure_type', 'recurring',
    'progression_strategy_type', 'step', 'config', p.config,
    'exercises', (SELECT jsonb_agg(jsonb_build_object('role', e.subcategory, 'exercise_id', e.id,
        'name', e.name, 'metric_type', 'reps') ORDER BY e.subcategory)
      FROM exercises e WHERE e.category = 'pull_ups' AND e.subcategory IN ('block_a', 'block_b')),
    'program_items', (SELECT jsonb_agg(jsonb_build_object('id', pi.id, 'exercise_id', pi.exercise_id,
        'complex_id', pi.complex_id, 'count_per_week', pi.count_per_week, 'day_of_week', pi.day_of_week,
        'week_phase', 'base') ORDER BY pi.id) FROM program_items pi WHERE pi.program_id = p.id)),
  '{"schema_version": 1, "strategy_type": "step", "block_a": {"target": 12, "work_sets": 3}, "block_b": {"target": 4}}',
  '{"schema_version": 1}', '2026-09-14 09:00+00', true
 FROM programs p WHERE p.name = 'Подтягивания' AND p.category = 'pull_ups';
INSERT INTO plan_weeks (id, training_plan_id, week_number, start_date, phase) VALUES
 (4001, 2001, 1, '2026-09-14', 'base'), (4002, 2001, 2, '2026-09-21', 'base'),
 (4003, 2001, 3, '2026-09-28', 'base'), (4004, 2001, 4, '2026-10-05', 'base');
INSERT INTO plan_items (id, training_plan_id, exercise_id, count_per_week, program_inclusion_id, plan_week_id, week_phase)
 SELECT 5000 + w.n * 10 + r.k, 2001, r.exercise_id, 3, 3001, 4000 + w.n, 'base'
 FROM (VALUES (1), (2), (3), (4)) w(n),
  (SELECT 1 AS k, id AS exercise_id FROM exercises WHERE category = 'pull_ups' AND subcategory = 'block_a'
   UNION ALL SELECT 2, id FROM exercises WHERE category = 'pull_ups' AND subcategory = 'block_b') r;
INSERT INTO plan_items (id, training_plan_id, exercise_id, count_per_week, plan_week_id)
 SELECT 5100, 2001, id, 2, 4004 FROM exercises WHERE name = 'Планка' AND owner_user_id IS NULL;
INSERT INTO training_sessions (id, user_id, source, performed_at, completed_at, status) VALUES
 (8001, 1001, 'plan', '2026-09-22 10:00+00', '2026-09-22 10:40+00', 'completed'),
 (8002, 1001, 'plan', '2026-10-05 10:00+00', '2026-10-05 10:40+00', 'completed'),
 (8003, 1001, 'plan', '2026-10-06 10:00+00', '2026-10-06 10:40+00', 'completed'),
 (8004, 1001, 'plan', '2026-10-06 18:00+00', '2026-10-06 18:20+00', 'completed');
INSERT INTO session_blocks (id, session_id, order_index, exercise_id)
 SELECT 8100 + s.id - 8000, s.id, 0, (SELECT id FROM exercises WHERE category = 'pull_ups' AND subcategory = 'block_a')
 FROM training_sessions s WHERE s.id IN (8001, 8002, 8003);
INSERT INTO session_blocks (id, session_id, order_index, exercise_id)
 SELECT 8104, 8004, 0, id FROM exercises WHERE name = 'Планка' AND owner_user_id IS NULL;
INSERT INTO set_logs (session_block_id, set_number, metric_type, value, unit)
 SELECT id, 1, 'reps', 12, 'reps' FROM session_blocks WHERE id BETWEEN 8101 AND 8104;
INSERT INTO session_plan_items (session_id, plan_item_id) VALUES
 (8001, 5021), (8001, 5022), (8002, 5041), (8002, 5042), (8003, 5041), (8003, 5042), (8004, 5100)
"""


def test_a_fresh_db_seeds_od2_constraint_on_pullups(deployed_dsn):  # noqa: F811
    row = _run(_fetch(
        deployed_dsn,
        "SELECT slots, frequency, constraints, assessment FROM programs WHERE name = 'Подтягивания' "
        "AND category = 'pull_ups'",
    ))[0]
    assert row.constraints == [{"spacing_group": "main", "min_days_between_starts": 3}]
    assert row.frequency == {"sessions_per_week": 3, "per_slot": {}}
    assert [slot["key"] for slot in row.slots] == ["main"] and row.slots[0]["spacing_group"] == "main"
    assert row.assessment["required_before_first_session"] is True
    assert row.assessment["protocol_id"] == _scalar(
        deployed_dsn, "SELECT id FROM assessment_protocols WHERE name = 'Максимум подтягиваний'",
    )
    assert _scalar(deployed_dsn, "SELECT count(*) FROM custom_plans") == 0


def test_b_c_aged_db_upgrade_and_converge_preserve_access_and_history(scratch_dsn):  # noqa: F811
    _alembic(scratch_dsn, "upgrade", PRE_REVISION)
    _run(_exec(scratch_dsn, AGED))
    before = _fingerprint(scratch_dsn)

    _alembic(scratch_dsn, "upgrade", REVISION)
    assert _fingerprint(scratch_dsn) == before  # F/G: подписки, доступ, история — байт в байт

    # Аддитивный бэкфилл: источник строк, статус включения, кредит только для single-link.
    assert _scalar(scratch_dsn, "SELECT count(*) FROM plan_items WHERE source IS NULL") == 0
    assert _scalar(scratch_dsn, "SELECT status FROM program_inclusions WHERE id = 3001") == "active"
    credits = dict(_run(_fetch(scratch_dsn, "SELECT id, plan_item_id FROM training_sessions ORDER BY id")))
    assert credits == {8001: None, 8002: None, 8003: None, 8004: 5100}  # пары A+B не угадываются
    assert _scalar(scratch_dsn, "SELECT count(*) FROM plan_items WHERE occurrence_index IS NOT NULL") == 0

    # C: deploy-time сходимость (тот же runtime converge_user_plan) на мигрированной aged-БД.
    async def converge(apply: bool) -> tuple[int, dict]:
        engine = create_async_engine(scratch_dsn)
        try:
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            return await run_all(apply=apply, today=date(2026, 10, 7), session_factory=factory)
        finally:
            await engine.dispose()

    # Сегодняшний ORM знает колонку следующей ревизии (#305 e3b9c5d7a2f1) — добавить её только для прогона
    # runtime-converge на схеме ЭТОЙ ревизии (как tests/test_scripts/_todays_orm_columns.py).
    _run(_exec(scratch_dsn, "ALTER TABLE program_inclusions ADD COLUMN prescription_provenance jsonb"))
    code, dry = asyncio.run(converge(False))
    assert code == 0 and dry["total_mutations"] > 0, dry
    assert _fingerprint(scratch_dsn) == before  # dry-run ничего не пишет
    code, applied = asyncio.run(converge(True))
    assert code == 0, applied
    code, again = asyncio.run(converge(True))
    assert code == 0 and again["total_mutations"] == 0, again  # E2E «second converge: zero mutations»
    assert _fingerprint(scratch_dsn) == before

    credits = dict(_run(_fetch(scratch_dsn, "SELECT id, plan_item_id FROM training_sessions ORDER BY id")))
    main4 = [r.id for r in _run(_fetch(
        scratch_dsn,
        "SELECT id FROM plan_items WHERE origin_plan_week_id = 4004 AND program_slot_key = 'main' ORDER BY occurrence_index",
    ))]
    assert credits[8002] == main4[0] and credits[8003] == main4[1]  # k сессий → k занятий по performed_at
    assert credits[8001] is None  # прошлое — кредит по старой M2M
    frozen = _run(_fetch(scratch_dsn, "SELECT legacy_aggregate, status FROM plan_items WHERE plan_week_id < 4004 "
                                      "AND occurrence_index IS NULL"))
    assert frozen and all(r.legacy_aggregate and r.status == "open" for r in frozen)
    retired = _run(_fetch(scratch_dsn, "SELECT status FROM plan_items WHERE id IN (5041, 5042)"))
    assert [r.status for r in retired] == ["removed", "removed"]  # не удалены
    assert _scalar(scratch_dsn, "SELECT count(*) FROM program_inclusions") == 1  # no auto-enrol / re-create


def test_d_second_upgrade_and_rerun_backfill_are_noop(scratch_dsn):  # noqa: F811
    _alembic(scratch_dsn, "upgrade", PRE_REVISION)
    _run(_exec(scratch_dsn, AGED))
    _alembic(scratch_dsn, "upgrade", REVISION)
    snapshot = _run(_fetch(scratch_dsn, "SELECT id, source, workout_definition_id, status FROM plan_items ORDER BY id"))
    _alembic(scratch_dsn, "upgrade", REVISION)  # повторный деплой — ничего
    assert _run(_fetch(
        scratch_dsn, "SELECT id, source, workout_definition_id, status FROM plan_items ORDER BY id",
    )) == snapshot


def test_e_downgrade_then_upgrade_keeps_history_and_rebuilds_derivable(scratch_dsn):  # noqa: F811
    _alembic(scratch_dsn, "upgrade", PRE_REVISION)
    _run(_exec(scratch_dsn, AGED))
    before = _fingerprint(scratch_dsn)
    _alembic(scratch_dsn, "upgrade", REVISION)
    _alembic(scratch_dsn, "downgrade", PRE_REVISION)
    assert _fingerprint(scratch_dsn) == before  # история и M2M переживают откат схемы
    columns = {r.column_name for r in _run(_fetch(
        scratch_dsn, "SELECT column_name FROM information_schema.columns WHERE table_name = 'training_sessions'",
    ))}
    assert "plan_item_id" not in columns
    assert _scalar(scratch_dsn, "SELECT to_regclass('custom_plans') IS NULL") is True

    _alembic(scratch_dsn, "upgrade", REVISION)
    assert _fingerprint(scratch_dsn) == before
    assert _scalar(scratch_dsn, "SELECT plan_item_id FROM training_sessions WHERE id = 8004") == 5100  # выводимое
