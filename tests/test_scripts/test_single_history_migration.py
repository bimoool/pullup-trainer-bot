"""Deploy-level репетиция ревизии a7e2c5b9d1f4 + `scripts/backfill_multi_program.py --converge-history`
(issue #308, MIGRATION_V2 §4, §8). Реальный Postgres, каждый сценарий — своя временная БД, `alembic` и скрипт
подпроцессами (ровно как `deploy/deploy-run.sh`).

Aged-набор на ревизии f4c1a7e9b3d2 (до #308), одним пользователем:
  workouts 8001, 8002 — их копии backfill-а (origin legacy_backfill) без ключа legacy_id, содержимое совпадает;
  workout 8003 — отредактирован в legacy ПОСЛЕ backfill (копия 9003 хранит прежний максимум);
  копия 9004 — legacy-запись удалена (сирота);
  elective 7001 с копией 9005; elective 7002 записан ПОСЛЕ миграции пользователя (копии нет);
  elective 7003 записан ДО миграции и копии нет (удалён/правлен в Журнале) — НЕ воскрешается."""

import subprocess
import sys

from tests.test_scripts.test_program_plan_migration import _exec
from tests.test_scripts.test_system_content_migration import (
    REPO_ROOT,
    _alembic,
    _fetch,
    _run,
    _scalar,
    scratch_dsn,  # noqa: F401 — фикстура
)

PRE_REVISION = "f4c1a7e9b3d2"
HEAD = "a7e2c5b9d1f4"

# Содержимое legacy-таблиц и подписок не имеет права измениться ни миграцией, ни сведением.
LEGACY_GUARD = {
    "users": "id, telegram_id, subscription_status, subscription_expires_at",
    "subscriptions": "*",
    "workouts": "id, user_id, performed_at, status, comment, participates_in_cascade, is_free_entry",
    "blocks": "id, workout_id, block_type, working_reps, max_reps, reported_volume",
    "elective_workouts": "id, user_id, elective_type, performed_at, reps_sequence, total_reps",
    "workout_sets": "id, user_id, workouts_completed",
}


def _fingerprint(dsn: str, tables: dict[str, str]) -> dict[str, str]:
    return {
        table: _scalar(
            dsn,
            f"SELECT count(*) || ':' || coalesce(md5(string_agg(x::text, '|' ORDER BY x::text)), '-') "
            f"FROM (SELECT {columns} FROM {table}) x",
        )
        for table, columns in tables.items()
    }


def _script(dsn: str, *args: str) -> str:
    import os

    env = {**os.environ, "DATABASE_URL": dsn}
    env.setdefault("BOT_TOKEN", "ci-test-token")
    result = subprocess.run(
        [sys.executable, "scripts/backfill_multi_program.py", *args], cwd=REPO_ROOT, env=env,
        capture_output=True, text=True, timeout=300, check=False,
    )
    assert result.returncode == 0, f"{args}\n{result.stdout}\n{result.stderr}"
    return result.stdout


def _copy_sql(copy_id: int, workout_id: int, at: str, source: str, source_v2: str, max_a: int, max_b: int) -> str:
    """Копия legacy Workout ровно так, как её писал backfill #163: блок A (3 подхода + максимум) и блок Б (4 + максимум)."""
    exercise_a = "(SELECT id FROM exercises WHERE name = 'Подтягивания — объём' ORDER BY id LIMIT 1)"
    exercise_b = "(SELECT id FROM exercises WHERE name = 'Подтягивания — сила' ORDER BY id LIMIT 1)"
    block_a, block_b = copy_id * 10 + 1, copy_id * 10 + 2
    logs_a = ", ".join(f"({block_a}, {n}, false, 'reps', 10, 'reps')" for n in (1, 2, 3))
    logs_b = ", ".join(f"({block_b}, {n}, false, 'reps', 3, 'reps')" for n in (1, 2, 3, 4))
    return f"""
INSERT INTO training_sessions (id, user_id, source, status, performed_at, kind, origin, source_v2, duration_source)
 VALUES ({copy_id}, 1001, '{source}', 'completed', '{at}', 'strength', 'legacy_backfill', '{source_v2}', 'unknown');
INSERT INTO session_blocks (id, session_id, order_index, exercise_id) VALUES
 ({block_a}, {copy_id}, 0, {exercise_a}), ({block_b}, {copy_id}, 1, {exercise_b});
INSERT INTO set_logs (session_block_id, set_number, is_max_set, metric_type, value, unit) VALUES
 {logs_a}, ({block_a}, 4, true, 'reps', {max_a}, 'reps'), {logs_b}, ({block_b}, 5, true, 'reps', {max_b}, 'reps');
"""


def _workout_sql(workout_id: int, at: str, *, cascade: bool, sequence: int | None, max_a: int) -> str:
    return f"""
INSERT INTO workouts (id, user_id, workout_set_id, sequence_number, performed_at, status, participates_in_cascade)
 VALUES ({workout_id}, 1001, 4001, {sequence if sequence is not None else 'NULL'}, '{at}', 'completed', {str(cascade).lower()});
INSERT INTO blocks (workout_id, block_type, working_reps, max_reps, target_before, target_after, equipment_type) VALUES
 ({workout_id}, 'a', '[10, 10, 10]', {max_a}, 10, 10, 'bodyweight'), ({workout_id}, 'b', '[3, 3, 3, 3]', 3, 3, 3, 'bodyweight');
"""


def _aged(dsn: str) -> None:
    sql = """
INSERT INTO users (id, telegram_id, timezone, subscription_status, subscription_expires_at) VALUES
 (1001, 9101, 'UTC', 'active', '2026-12-31 10:00+00');
INSERT INTO subscriptions (user_id, status, source, started_at, ends_at) VALUES
 (1001, 'active', 'robokassa', '2026-09-01+00', '2026-12-31 10:00+00');
INSERT INTO baselines (id, user_id, performed_at, reps) VALUES (3001, 1001, '2026-09-01 09:00+00', 10);
INSERT INTO workout_sets (id, user_id, started_from_baseline_id, set_number) VALUES (4001, 1001, 3001, 1);
INSERT INTO training_plans (id, user_id, created_at) VALUES (2001, 1001, '2026-09-14 09:00+00');
""" + _workout_sql(8001, "2026-09-20 09:00+00", cascade=True, sequence=1, max_a=11) \
        + _workout_sql(8002, "2026-09-21 09:00+00", cascade=False, sequence=None, max_a=12) \
        + _workout_sql(8003, "2026-09-22 09:00+00", cascade=True, sequence=2, max_a=14) \
        + _copy_sql(9001, 8001, "2026-09-20 09:00+00", "plan", "planned_live", 11, 3) \
        + _copy_sql(9002, 8002, "2026-09-21 09:00+00", "backdated", "manual_custom", 12, 3) \
        + _copy_sql(9003, 8003, "2026-09-22 09:00+00", "plan", "planned_live", 12, 3) \
        + _copy_sql(9004, 8099, "2026-09-18 09:00+00", "plan", "planned_live", 9, 3) + """
INSERT INTO elective_workouts (id, user_id, elective_type, performed_at, reps_sequence, total_reps, equipment_type, created_at) VALUES
 (7001, 1001, 'three_minutes', '2026-09-10 09:00+00', '[4, 3, 2]', 9, 'bodyweight', '2026-09-10 09:00+00'),
 (7002, 1001, 'volume_target', '2026-09-25 09:00+00', NULL, 40, 'bodyweight', '2026-09-25 09:00+00'),
 (7003, 1001, 'w_ladder', '2026-09-12 09:00+00', '[5, 4, 3]', 12, 'bodyweight', '2026-09-12 09:00+00');
INSERT INTO training_sessions (id, user_id, source, status, performed_at, kind, origin, source_v2, duration_source)
 VALUES (9005, 1001, 'elective', 'completed', '2026-09-10 09:00+00', 'strength', 'legacy_elective', 'manual_existing_workout', 'unknown');
INSERT INTO session_blocks (id, session_id, order_index, exercise_id) VALUES
 (90051, 9005, 0, (SELECT id FROM exercises WHERE name = 'Факультатив — 3 минуты подтягиваний' ORDER BY id LIMIT 1));
INSERT INTO set_logs (session_block_id, set_number, is_max_set, metric_type, value, unit, note) VALUES
 (90051, 1, false, 'reps', 9, 'reps', '{"format": "three_minutes", "reps_sequence": [4, 3, 2], "equipment_type": "bodyweight", "equipment_value": null, "equipment_item_id": null, "equipment_item_name": null}');
"""
    _run(_exec(dsn, sql))


def _canonical(dsn: str) -> int:
    return _scalar(dsn, "SELECT count(*) FROM training_sessions WHERE status = 'completed' AND superseded_at IS NULL")


def _summary(dsn: str) -> dict:
    rows = _run(_fetch(dsn, """
        SELECT id, origin, legacy_id, superseded_reason, revision FROM training_sessions ORDER BY id"""))
    return {r.id: (r.origin, r.legacy_id, r.superseded_reason, r.revision) for r in rows}


def test_fresh_install_has_a_single_head_and_the_unique_copy_key(scratch_dsn):  # noqa: F811
    _alembic(scratch_dsn, "upgrade", "head")
    assert _scalar(scratch_dsn, "SELECT version_num FROM alembic_version") == HEAD
    heads = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"], cwd=REPO_ROOT, capture_output=True, text=True, check=True,
        env={**__import__("os").environ, "DATABASE_URL": scratch_dsn, "BOT_TOKEN": "x"},
    ).stdout.strip().splitlines()
    assert len(heads) == 1 and heads[0].startswith(HEAD)
    columns = {r[0] for r in _run(_fetch(scratch_dsn, """
        SELECT column_name FROM information_schema.columns WHERE table_name = 'training_sessions'"""))}
    assert {"legacy_id", "superseded_at", "superseded_reason", "superseded_by_id"} <= columns
    assert _scalar(scratch_dsn, "SELECT count(*) FROM pg_indexes WHERE indexname = 'uq_training_sessions_origin_legacy_id'") == 1
    assert _scalar(scratch_dsn, "SELECT count(*) FROM training_sessions") == 0


def test_aged_database_converges_idempotently_without_touching_legacy_history(scratch_dsn):  # noqa: F811
    _alembic(scratch_dsn, "upgrade", PRE_REVISION)
    _aged(scratch_dsn)
    legacy_before = _fingerprint(scratch_dsn, LEGACY_GUARD)
    _alembic(scratch_dsn, "upgrade", "head")
    assert _fingerprint(scratch_dsn, LEGACY_GUARD) == legacy_before  # миграция схемы — ничего не переписала
    assert _canonical(scratch_dsn) == 5  # как на проде сразу после выкладки: копии 9001–9005

    summary_before = _summary(scratch_dsn)
    dry = _script(scratch_dsn, "--converge-history")
    assert "DRY-RUN" in dry and "привязано" in dry
    assert _summary(scratch_dsn) == summary_before  # dry-run по-настоящему сухой

    applied = _script(scratch_dsn, "--converge-history", "--apply")
    assert "Прогон завершён" in applied
    after = _summary(scratch_dsn)
    assert after[9001][:2] == ("legacy_backfill", 8001) and after[9002][:2] == ("legacy_backfill", 8002)
    assert after[9005][:2] == ("legacy_elective", 7001)
    assert after[9003][2] == "legacy_replaced" and after[9004][2] == "legacy_replaced"  # устаревшая копия и сирота
    new_ids = set(after) - set(summary_before)
    assert len(new_ids) == 2  # копия 8003 и факультатив 7002; 7003 не воскрешён
    assert _scalar(scratch_dsn, "SELECT count(*) FROM training_sessions WHERE legacy_id = 7003 AND origin = 'legacy_elective'") == 0
    # 3 живые legacy-записи + 2 факультатива с копией = 5 канонических; на каждую живую строку ровно одна копия
    assert _canonical(scratch_dsn) == 5
    assert _scalar(scratch_dsn, """
        SELECT count(*) FROM (SELECT legacy_id FROM training_sessions WHERE origin = 'legacy_backfill'
          AND legacy_id IS NOT NULL AND superseded_at IS NULL GROUP BY legacy_id HAVING count(*) > 1) d""") == 0
    assert _fingerprint(scratch_dsn, LEGACY_GUARD) == legacy_before  # оригинальные legacy-данные не тронуты
    assert _scalar(scratch_dsn, "SELECT count(*) FROM workouts") == 3  # архив/удаление не выполнялись скриптом

    again = _script(scratch_dsn, "--converge-history", "--apply")
    assert _summary(scratch_dsn) == after  # apply-again = 0 изменений (ни строк, ни ревизий)
    assert "создано" not in again and "обновлено" not in again and "замещено" not in again
    assert _fingerprint(scratch_dsn, LEGACY_GUARD) == legacy_before


def test_downgrade_then_upgrade_keeps_sessions_and_reconverges_deterministically(scratch_dsn):  # noqa: F811
    _alembic(scratch_dsn, "upgrade", PRE_REVISION)
    _aged(scratch_dsn)
    _alembic(scratch_dsn, "upgrade", "head")
    _script(scratch_dsn, "--converge-history", "--apply")
    converged = _summary(scratch_dsn)
    sessions = _scalar(scratch_dsn, "SELECT count(*) FROM training_sessions")

    _alembic(scratch_dsn, "downgrade", PRE_REVISION)
    assert _scalar(scratch_dsn, "SELECT version_num FROM alembic_version") == PRE_REVISION
    assert _scalar(scratch_dsn, "SELECT count(*) FROM training_sessions") == sessions  # сессии не потеряны
    assert _scalar(scratch_dsn, """
        SELECT count(*) FROM information_schema.columns
        WHERE table_name = 'training_sessions' AND column_name IN ('legacy_id', 'superseded_at', 'superseded_reason')""") == 0

    _alembic(scratch_dsn, "upgrade", "head")
    _script(scratch_dsn, "--converge-history", "--apply")
    again = _summary(scratch_dsn)
    # после повторного upgrade ключи и замещения восстановлены тем же сведением; новых строк нет. Причина замещения
    # — справочная метка (после downgrade «заменена» читается как «удалена»), поэтому сравниваем сам факт замещения.
    def shape(summary):
        return {k: (v[0], v[1], v[2] is not None) for k, v in summary.items()}

    assert shape(again) == shape(converged)
    assert _canonical(scratch_dsn) == 5
