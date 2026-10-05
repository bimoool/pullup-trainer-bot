"""seed system content (program, exercise library, system workouts)

Revision ID: a4c8e1f7b2d9
Revises: 9e3f1a4b6c80
Create Date: 2026-10-05 12:00:00.000000

"""
import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'a4c8e1f7b2d9'
down_revision: str | None = '9e3f1a4b6c80'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Системный контент «из коробки» (issue #296, FD-01/FD-06/FD-07; docs/SYSTEM_CONTENT_CONTRACT.md).
# Раньше свежая установка (`alembic upgrade head` и ничего больше) не содержала ни программ, ни
# упражнений, ни готовых тренировок: каталог появлялся только после ручных скриптов оператора.
#
# Чисто данные, аддитивно, схема не меняется. Идемпотентно и детерминированно: каждая строка
# ищется по стабильному натуральному ключу и создаётся только если её нет:
#   * Program                      — name (у Program нет владельца; каталог общий);
#   * ProgressionStrategyProfile   — name;
#   * Exercise                     — (name, owner_user_id IS NULL), т.е. системные;
#   * ProgramItem                  — (program_id, exercise_id);
#   * Complex (готовая тренировка) — (name, source_type='system', owner_user_id IS NULL);
#   * CollectionItem               — (collection_id, program_id).
# Поэтому окружения, где `scripts/backfill_multi_program.py` / `seed_exercise_library.py` уже
# создали программу и упражнения, получают НОЛЬ дублей: найденные строки не меняются.
#
# НИКАКИХ пользовательских строк: ни TrainingPlan, ни ProgramInclusion, ни PlanWeek/PlanItem,
# ни сессий, ни истории, ни подписок. В отличие от backfill_multi_program.py, который заодно
# записывает на программу всех онбордившихся пользователей, эта миграция только кладёт каталог.
#
# Конфиг программы — ЗАМОРОЖЕННЫЙ снимок констант app/domain/constants.py на 2026-10-05
# (копия значений, а не импорт «живых» констант): правка констант в будущем не должна задним
# числом менять то, что эта ревизия записывает. Названия/роли/подкатегории тоже литералы.
#
# downgrade — намеренный no-op: на эти строки к моменту отката могут ссылаться планы, включения
# курсов, замороженные снимки сессий и история пользователей (Complex/ComplexItem/Exercise/
# PlanItem не удаляются операциями над сессиями; конституция V — не удалять историю). Откат
# ревизии не должен ломать данные, поэтому каталог остаётся; повторный `upgrade` — тоже no-op.

_STRATEGY_PROFILE_NAME = 'Пошаговая прогрессия подтягиваний'
_PROGRAM_NAME = 'Подтягивания'
_PROGRAM_GOAL = 'Рост числа подтягиваний: объём (блок A) + сила (блок Б)'
_PROGRAM_CATEGORY = 'pull_ups'
_PROGRAM_CONFIG = {
    'block_a': {'base_target': 10, 'work_sets': 3, 'equipment_change_threshold': 20, 'min_viable_reps': 10},
    'block_b': {'base_target': 3, 'work_sets': 4, 'equipment_change_threshold': 7, 'min_viable_reps': 3},
    'step_pct': 0.05,
    'weak_streak_rollback_threshold': 3,
    'set_length': 12,
    'min_rest_days': 2,
}

# Внутренние упражнения (роли STEP-программы и факультативы) — НЕ публичная библиотека
# (GET /exercises их скрывает), но нужны программе, истории и миграциям из старой схемы.
_ROLE_EXERCISES = [
    ('Подтягивания — объём', 'block_a'),
    ('Подтягивания — сила', 'block_b'),
]
_ELECTIVE_EXERCISES = [
    ('Факультатив — подтягивания на максимум', 'elective_max_reps_ladder'),
    ('Факультатив — подтягивания W', 'elective_w_ladder'),
    ('Факультатив — 3 минуты подтягиваний', 'elective_three_minutes'),
    ('Факультатив — подтягивания на объём', 'elective_volume_target'),
]

# Публичная системная библиотека (решение владельца D1): (имя, метрика, категория).
# «Планка» и «Отжимания» — те же, что засевал scripts/seed_exercise_library.py.
_LIBRARY_EXERCISES = [
    ('Подтягивания', 'reps', 'Подтягивания'),
    ('Подтягивания с резиной', 'reps', 'Подтягивания'),
    ('Подтягивания с отягощением', 'reps', 'Подтягивания'),
    ('Австралийские подтягивания', 'reps', 'Подтягивания'),
    ('Лопаточные подтягивания', 'reps', 'Подтягивания'),
    ('Вис на турнике', 'time', 'Хват'),
    ('Планка', 'time', 'Общая физическая подготовка'),
    ('Отжимания', 'reps', 'Общая физическая подготовка'),
]

# Готовые тренировки (решение владельца D2): системные Complex + ComplexItem с protocol
# (definition-форма, docs/adr/WORKOUT_PROTOCOL_V1.md; снимок для живой сессии строится из неё
# при старте, build_workout_snapshot). Это форматы бывших факультативов, представленные
# существующими протоколами: (название, упражнение, protocol).
_SYSTEM_WORKOUTS = [
    (
        # 4 попытки на максимум; в факультативе отдых убывал 180/120/60 — протокол несёт одно
        # значение, берём среднее 120 секунд.
        'Максимум подтягиваний', 'Подтягивания',
        {'type': 'max_effort', 'prescription': {'source': 'static', 'attempts': 4}, 'rest_seconds': 120},
    ),
    (
        # «W» 5-4-3-2-1-2-3-4-5-4-3-2-1-2-3-4-5: 17 подходов, отдых 10 с. Протокол reps_sets задаёт
        # одно число повторений на подход, поэтому цель — среднее по лесенке (53/17 ≈ 3).
        'W-лесенка', 'Подтягивания',
        {'type': 'reps_sets', 'prescription': {'source': 'static', 'sets': 17, 'reps': 3}, 'rest_seconds': 10},
    ),
    (
        # Ровно пример интервального протокола из ADR: 180 с, работа 10 / отдых 20.
        '3 минуты подтягиваний', 'Подтягивания',
        {
            'type': 'interval', 'total_duration_seconds': 180, 'work_seconds': 10,
            'rest_seconds': 20, 'starts_with': 'work',
        },
    ),
    (
        # «На объём» = 5 подходов по 6–10 повторений (середина диапазона — 8), отдых 2 минуты.
        'Объём ×5', 'Подтягивания',
        {'type': 'reps_sets', 'prescription': {'source': 'static', 'sets': 5, 'reps': 8}, 'rest_seconds': 120},
    ),
]

_START_COLLECTION_SLUG = 'start-with-pull-ups'


def _scalar(conn, sql: str, **params):
    return conn.execute(sa.text(sql), params).scalar()


def _ensure_strategy_profile(conn) -> int:
    existing = _scalar(
        conn, "SELECT id FROM progression_strategy_profiles WHERE name = :name ORDER BY id LIMIT 1",
        name=_STRATEGY_PROFILE_NAME,
    )
    if existing is not None:
        return existing
    return _scalar(
        conn,
        "INSERT INTO progression_strategy_profiles (strategy_type, name, config) "
        "VALUES (CAST('step' AS mp_progression_strategy_type), :name, CAST('{}' AS jsonb)) RETURNING id",
        name=_STRATEGY_PROFILE_NAME,
    )


def _ensure_program(conn, strategy_profile_id: int) -> int:
    existing = _scalar(conn, "SELECT id FROM programs WHERE name = :name ORDER BY id LIMIT 1", name=_PROGRAM_NAME)
    if existing is not None:
        return existing
    return _scalar(
        conn,
        "INSERT INTO programs (name, goal, structure_type, category, progression_strategy_id, config) "
        "VALUES (:name, :goal, CAST('recurring' AS mp_program_structure_type), :category, :strategy_id, "
        "CAST(:config AS jsonb)) RETURNING id",
        name=_PROGRAM_NAME, goal=_PROGRAM_GOAL, category=_PROGRAM_CATEGORY, strategy_id=strategy_profile_id,
        config=json.dumps(_PROGRAM_CONFIG),
    )


def _ensure_exercise(conn, *, name: str, metric: str, category: str, subcategory: str | None) -> int:
    existing = _scalar(
        conn, "SELECT id FROM exercises WHERE name = :name AND owner_user_id IS NULL ORDER BY id LIMIT 1",
        name=name,
    )
    if existing is not None:
        return existing
    return _scalar(
        conn,
        "INSERT INTO exercises (name, metric_type, category, subcategory, variants, source_type, owner_user_id) "
        "VALUES (:name, CAST(:metric AS mp_metric_type), :category, :subcategory, CAST('[]' AS jsonb), "
        "'system', NULL) RETURNING id",
        name=name, metric=metric, category=category, subcategory=subcategory,
    )


def _ensure_program_item(conn, *, program_id: int, exercise_id: int) -> None:
    exists = _scalar(
        conn, "SELECT id FROM program_items WHERE program_id = :program_id AND exercise_id = :exercise_id LIMIT 1",
        program_id=program_id, exercise_id=exercise_id,
    )
    if exists is None:
        conn.execute(
            sa.text(
                "INSERT INTO program_items (program_id, week_phase, exercise_id, count_per_week, day_of_week) "
                "VALUES (:program_id, CAST('base' AS mp_week_phase), :exercise_id, 3, NULL)"
            ),
            {'program_id': program_id, 'exercise_id': exercise_id},
        )


def _ensure_system_workout(conn, *, title: str, exercise_id: int, protocol: dict) -> None:
    exists = _scalar(
        conn,
        "SELECT id FROM complexes WHERE name = :name AND source_type = 'system' AND owner_user_id IS NULL LIMIT 1",
        name=title,
    )
    if exists is not None:
        return  # уже есть (в т.ч. отредактированная/архивная владельцем) — не трогаем
    complex_id = _scalar(
        conn,
        "INSERT INTO complexes (name, source_type, owner_user_id) VALUES (:name, 'system', NULL) RETURNING id",
        name=title,
    )
    # sets=0 — тот же placeholder, что у Workout Builder (источник правды — protocol).
    conn.execute(
        sa.text(
            "INSERT INTO complex_items (complex_id, exercise_id, order_index, sets, protocol) "
            "VALUES (:complex_id, :exercise_id, 0, 0, CAST(:protocol AS jsonb))"
        ),
        {'complex_id': complex_id, 'exercise_id': exercise_id, 'protocol': json.dumps(protocol)},
    )


def _ensure_collection_item(conn, *, program_id: int) -> None:
    # Подборка заведена миграцией 9e3f1a4b6c80; если её нет (удалили вручную) — ничего не создаём.
    conn.execute(
        sa.text(
            "INSERT INTO collection_items (collection_id, program_id, position) "
            "SELECT c.id, :program_id, "
            "COALESCE((SELECT MAX(i.position) + 1 FROM collection_items i WHERE i.collection_id = c.id), 0) "
            "FROM collections c WHERE c.slug = :slug "
            "AND NOT EXISTS (SELECT 1 FROM collection_items i WHERE i.collection_id = c.id AND i.program_id = :program_id)"
        ),
        {'program_id': program_id, 'slug': _START_COLLECTION_SLUG},
    )


def seed_system_content(conn) -> None:
    """Идемпотентный сид; вынесен из upgrade() ради теста «двойного прогона» без alembic."""
    profile_id = _ensure_strategy_profile(conn)
    program_id = _ensure_program(conn, profile_id)
    for name, subcategory in _ROLE_EXERCISES:
        exercise_id = _ensure_exercise(
            conn, name=name, metric='reps', category=_PROGRAM_CATEGORY, subcategory=subcategory,
        )
        _ensure_program_item(conn, program_id=program_id, exercise_id=exercise_id)
    for name, subcategory in _ELECTIVE_EXERCISES:
        _ensure_exercise(conn, name=name, metric='reps', category=_PROGRAM_CATEGORY, subcategory=subcategory)

    library_ids = {
        name: _ensure_exercise(conn, name=name, metric=metric, category=category, subcategory=None)
        for name, metric, category in _LIBRARY_EXERCISES
    }
    for title, exercise_name, protocol in _SYSTEM_WORKOUTS:
        _ensure_system_workout(conn, title=title, exercise_id=library_ids[exercise_name], protocol=protocol)

    _ensure_collection_item(conn, program_id=program_id)


def upgrade() -> None:
    seed_system_content(op.get_bind())


def downgrade() -> None:
    # Намеренный no-op, см. комментарий в начале файла.
    pass
