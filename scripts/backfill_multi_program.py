"""Разовый backfill волны 2 многокурсовой платформы (issue #163):

1. Seed одной Program («Подтягивания») + 2 «программных» Exercise (блок A —
   объём, блок Б — сила) + 4 Exercise под факультативы (issue #94/#160,
   ElectiveType) + ProgressionStrategyProfile (STEP) — статические
   справочные данные, find-or-create по имени (уникального констрейнта на
   Program.name/Exercise.name в схеме волны 1 нет — идемпотентность на
   уровне этого скрипта, не БД).
2. Для каждого онбордившегося пользователя (User.onboarding_completed_at
   IS NOT NULL) — создаёт TrainingPlan (одна строка, UNIQUE user_id) +
   один ProgramInclusion со snapshot конфигурации программы на момент
   backfill и progression_state — ТЕКУЩИМ состоянием прогрессии (то же
   самое, что отдаёт WorkoutRepository.resolve_next_targets, публичный
   вход, которым уже пользуются хендлеры бота, чтобы показать план ДО
   следующей тренировки). Отдельно (issue #172) — для пользователя БЕЗ
   единой тренировки resolve_next_targets отдаёт baseline-агностичную
   заглушку (снаряд BAND, флаг "спроси заново"), а не то, что реально
   показывает экран первой тренировки; _build_progression_state в этом
   случае досчитывает стартовый снаряд/цель блока A по замеру теми же
   suggest_starting_equipment/initial_volume_target, что использует
   _resolve_plan_context (app/web/routes.py) — см. докстринг функции.
3. Переносит ВСЮ историю app.db.models.Workout (issue #160 завела
   SessionSource.PLAN/FREEFORM/BACKDATED ровно под комбинации
   participates_in_cascade/is_free_entry не просто так) в
   TrainingSession/SessionBlock/SetLog, и всю историю
   app.db.models.ElectiveWorkout — в TrainingSession(source=elective) (по
   одной TrainingSession+SessionBlock+SetLog на факультатив, issue #160).
4. НЕ переключает логику — старая схема (app/db/models.py, app/web/routes.py)
   остаётся единственным источником истины для прода, ничего не читает из
   новых таблиц. Разовый скрипт, не migration data-step (по образцу
   scripts/backfill_achievements.py).

Осознанно потеряно при переносе (снимок ТЕКУЩЕГО состояния плюс сама схема
SessionBlock/SetLog не рассчитаны на эти детали — см. обсуждение в issue
#163, подтверждено автором продукта):
  - фиктивный блок Б "➕ Внести свободные подтягивания" (working_reps=[],
    max_reps=0, issue #109/#156) — переносится только блок A;
  - equipment_type/equipment_value/equipment_item_id, is_heavy, is_deload,
    transition_failed отдельных Block — старая схема остаётся источником
    истины для этих деталей, Exercise-каталог намеренно не завязан на
    EquipmentType (см. докстринг Exercise в app/db/models_program.py).
    Для факультативов снаряд всё же сохраняется — в SetLog.note (JSON),
    единственном свободном текстовом поле схемы, куда это можно упаковать
    без потери, компромисс, не «красивое» решение.
  - недельная матрица (ProgramItem/Complex) для подтягиваний НЕ заводится
    в этой волне вообще — у подтягиваний нет понятия "раз в неделю"
    (интервал держит app.domain.constants.MIN_REST_DAYS, не календарная
    неделя) и нет фаз периодизации; ничего её пока не читает.

Идемпотентность — на пользователя: если TrainingPlan для user_id уже
существует, пользователь пропускается целиком. TrainingPlan+ProgramInclusion
создаются ПОСЛЕДНИМ шагом для пользователя, транзакция коммитится сразу
после — при падении скрипта посередине пользователя всё для него
откатится (наличие TrainingPlan — маркер "этот пользователь полностью
смигрирован"), при перезапуске он просто обработается заново без дублей.

Использование (внутри контейнера app, реальный DATABASE_URL):
    python scripts/backfill_multi_program.py --dry-run   # только посчитать
    python scripts/backfill_multi_program.py              # реальный прогон
    python scripts/backfill_multi_program.py --truncate    # ТОЛЬКО для
        повторных тестовых прогонов на копии/синтетике — стирает
        training_plans/training_sessions (и всё, что от них каскадно
        зависит) перед прогоном с нуля. НЕ для единственного реального
        прогона на проде без отдельного подтверждения (см. issue #163).
"""

import argparse
import asyncio
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import async_session_factory
from app.db.models import Block, BlockType, ElectiveWorkout, User, Workout, WorkoutStatus
from app.db.models_program import (
    Exercise,
    Program,
    ProgramInclusion,
    ProgramItem,
    ProgressionStrategyProfile,
    SessionBlock,
    SessionStatus,
    SetLog,
    TrainingPlan,
    TrainingSession,
)
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.programs import ProgramRepository, program_items_snapshot
from app.db.repositories.training_plans import TrainingPlanRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import (
    WorkoutRepository,
    _block_to_log,
    _exclude_deload_entries,
    _exclude_free_entries,
    _exclude_heavy_entries,
    _find_block,
    _stall_streak,
    _weak_streak,
)
from app.domain.constants import (
    MIN_REST_DAYS,
    SET_LENGTH,
    STEP_PCT,
    STRENGTH_BLOCK,
    VOLUME_BLOCK,
    WEAK_STREAK_ROLLBACK_THRESHOLD,
    ExerciseType,
)
from app.domain.electives import ElectiveType
from app.domain.multi_program import MetricType, ProgramStructureType, SessionSource, WeekPhase
from app.domain.progression import initial_volume_target, suggest_starting_equipment
from app.domain.progression_strategy import ProgressionStrategyType
from app.services.plan_week import PlanWeekService

_PROGRAM_NAME = "Подтягивания"
_STRATEGY_PROFILE_NAME = "Пошаговая прогрессия подтягиваний"
_EXERCISE_BLOCK_A_NAME = "Подтягивания — объём"
_EXERCISE_BLOCK_B_NAME = "Подтягивания — сила"
_ELECTIVE_EXERCISE_NAMES: dict[ElectiveType, str] = {
    ElectiveType.MAX_REPS_LADDER: "Факультатив — подтягивания на максимум",
    ElectiveType.W_LADDER: "Факультатив — подтягивания W",
    ElectiveType.THREE_MINUTES: "Факультатив — 3 минуты подтягиваний",
    ElectiveType.VOLUME_TARGET: "Факультатив — подтягивания на объём",
}


# --- Seed справочных данных (п.1) --------------------------------------------------


@dataclass(frozen=True)
class SeedCatalog:
    program_id: int
    exercise_a_id: int
    exercise_b_id: int
    elective_exercise_ids: dict[ElectiveType, int]
    snapshot: dict


def _program_config_snapshot() -> dict:
    """Снимок app/domain/constants.py на момент backfill — копия, не
    live-ссылка (см. докстринг Program.config/ProgramInclusion.snapshot в
    app/db/models_program.py): будущая правка констант не должна тихо
    менять то, что уже записано как исторический снимок."""
    return {
        "block_a": {
            "base_target": VOLUME_BLOCK.base_target,
            "work_sets": VOLUME_BLOCK.work_sets,
            "equipment_change_threshold": VOLUME_BLOCK.equipment_change_threshold,
            "min_viable_reps": VOLUME_BLOCK.min_viable_reps,
        },
        "block_b": {
            "base_target": STRENGTH_BLOCK.base_target,
            "work_sets": STRENGTH_BLOCK.work_sets,
            "equipment_change_threshold": STRENGTH_BLOCK.equipment_change_threshold,
            "min_viable_reps": STRENGTH_BLOCK.min_viable_reps,
        },
        "step_pct": STEP_PCT,
        "weak_streak_rollback_threshold": WEAK_STREAK_ROLLBACK_THRESHOLD,
        "set_length": SET_LENGTH,
        "min_rest_days": MIN_REST_DAYS,
    }


async def _get_or_create_exercise(session: AsyncSession, *, name: str, subcategory: str) -> Exercise:
    result = await session.execute(select(Exercise).where(Exercise.name == name))
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing
    exercise = Exercise(
        name=name, metric_type=MetricType.REPS, category=ExerciseType.PULL_UPS.value, subcategory=subcategory,
    )
    session.add(exercise)
    await session.flush()
    return exercise


async def _get_or_create_strategy_profile(session: AsyncSession) -> ProgressionStrategyProfile:
    result = await session.execute(
        select(ProgressionStrategyProfile).where(ProgressionStrategyProfile.name == _STRATEGY_PROFILE_NAME),
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing
    profile = ProgressionStrategyProfile(
        strategy_type=ProgressionStrategyType.STEP, name=_STRATEGY_PROFILE_NAME, config={},
    )
    session.add(profile)
    await session.flush()
    return profile


async def _get_or_create_program(session: AsyncSession, *, progression_strategy_id: int) -> Program:
    result = await session.execute(select(Program).where(Program.name == _PROGRAM_NAME))
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing
    program = Program(
        name=_PROGRAM_NAME,
        goal="Рост числа подтягиваний: объём (блок A) + сила (блок Б)",
        structure_type=ProgramStructureType.RECURRING,
        category=ExerciseType.PULL_UPS.value,
        progression_strategy_id=progression_strategy_id,
        config=_program_config_snapshot(),
    )
    session.add(program)
    await session.flush()
    return program


async def _get_or_create_program_item(session: AsyncSession, *, program_id: int, exercise_id: int) -> ProgramItem:
    """Checkpoint 1 (issue #188) — read-only-аудит нашёл дословно в этом же
    файле: «семя «Подтягивания» — пустой ProgramItem» (см. докстринг
    bulk_create_plan_items_from_program_items в training_plans.py). Без
    этих строк PlanWeekService.ensure_current_plan_week ничего не
    материализует — уже написанный механизм копирования ProgramItem ->
    PlanItem работал бы на пустом множестве.

    day_of_week=NULL (свободный пул недели, не конкретный день — подход к
    подтягиваниям определяет MIN_REST_DAYS, не календарь, см. докстринг
    backfill_all выше) week_phase=BASE (единственная реально используемая
    фаза для этой программы — периодизации rest/peak в живом алгоритме
    прогрессии подтягиваний нет)."""
    result = await session.execute(
        select(ProgramItem).where(ProgramItem.program_id == program_id, ProgramItem.exercise_id == exercise_id),
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing
    item = ProgramItem(
        program_id=program_id, exercise_id=exercise_id, week_phase=WeekPhase.BASE,
        count_per_week=3, day_of_week=None,
    )
    session.add(item)
    await session.flush()
    return item


async def seed_catalog(session: AsyncSession) -> SeedCatalog:
    """Идемпотентный (find-or-create по имени) seed справочных данных —
    вызывается один раз за прогон, до цикла по пользователям."""
    profile = await _get_or_create_strategy_profile(session)
    program = await _get_or_create_program(session, progression_strategy_id=profile.id)
    exercise_a = await _get_or_create_exercise(session, name=_EXERCISE_BLOCK_A_NAME, subcategory="block_a")
    exercise_b = await _get_or_create_exercise(session, name=_EXERCISE_BLOCK_B_NAME, subcategory="block_b")
    program_item_a = await _get_or_create_program_item(session, program_id=program.id, exercise_id=exercise_a.id)
    program_item_b = await _get_or_create_program_item(session, program_id=program.id, exercise_id=exercise_b.id)
    elective_exercise_ids = {}
    for elective_type, name in _ELECTIVE_EXERCISE_NAMES.items():
        exercise = await _get_or_create_exercise(
            session, name=name, subcategory=f"elective_{elective_type.value}",
        )
        elective_exercise_ids[elective_type] = exercise.id

    snapshot = {
        "schema_version": 1,
        "program_name": program.name,
        "structure_type": program.structure_type.value,
        "progression_strategy_type": ProgressionStrategyType.STEP.value,
        "config": _program_config_snapshot(),
        "exercises": [
            {
                "role": "block_a", "exercise_id": exercise_a.id,
                "name": exercise_a.name, "metric_type": exercise_a.metric_type.value,
            },
            {
                "role": "block_b", "exercise_id": exercise_b.id,
                "name": exercise_b.name, "metric_type": exercise_b.metric_type.value,
            },
        ],
        # Issue #188, checkpoint 1.1 — раньше этого ключа тут не было вообще
        # (контрактный баг: rollover в PlanWeekService читал live ProgramItem
        # вместо snapshot). program_items_snapshot — тот же хелпер, что
        # app.services.program_inclusion._build_snapshot, единственная форма.
        "program_items": program_items_snapshot([program_item_a, program_item_b]),
    }
    return SeedCatalog(
        program_id=program.id,
        exercise_a_id=exercise_a.id,
        exercise_b_id=exercise_b.id,
        elective_exercise_ids=elective_exercise_ids,
        snapshot=snapshot,
    )


# --- Перенос истории Workout -> TrainingSession (п.3) ------------------------------


def _resolve_session_source(workout: Workout) -> SessionSource:
    """Та самая таблица соответствий, ради которой SessionSource в волне 1
    завела FREEFORM/BACKDATED (issue #160) — прямое отражение
    participates_in_cascade/is_free_entry старой схемы."""
    if workout.participates_in_cascade:
        return SessionSource.PLAN
    if workout.is_free_entry:
        return SessionSource.FREEFORM
    return SessionSource.BACKDATED


async def _add_session_block_with_logs(
    session: AsyncSession, *, session_id: int, order_index: int, exercise_id: int, block: Block,
) -> int:
    """Возвращает число созданных SetLog — только для отчётности, поведение
    не меняет."""
    session_block = SessionBlock(session_id=session_id, order_index=order_index, exercise_id=exercise_id)
    session.add(session_block)
    await session.flush()

    log = _block_to_log(block)
    set_number = 1
    created = 0

    if log.reported_volume is not None:
        # Итог за тренировку без раскладки по подходам (issue #88) —
        # working_reps всегда пуст в этом случае, раскладывать нечего.
        session.add(
            SetLog(
                session_block_id=session_block.id, set_number=set_number, is_max_set=False,
                metric_type=MetricType.REPS, value=Decimal(log.reported_volume), unit="reps",
                note="итог без раскладки по подходам",
            ),
        )
        set_number += 1
        created += 1
        if block.max_reps:
            session.add(
                SetLog(
                    session_block_id=session_block.id, set_number=set_number, is_max_set=True,
                    metric_type=MetricType.REPS, value=Decimal(block.max_reps), unit="reps",
                ),
            )
            created += 1
        return created

    for reps in block.working_reps:
        session.add(
            SetLog(
                session_block_id=session_block.id, set_number=set_number, is_max_set=False,
                metric_type=MetricType.REPS, value=Decimal(reps), unit="reps",
            ),
        )
        set_number += 1
        created += 1
    session.add(
        SetLog(
            session_block_id=session_block.id, set_number=set_number, is_max_set=True,
            metric_type=MetricType.REPS, value=Decimal(block.max_reps), unit="reps",
        ),
    )
    created += 1
    return created


async def _create_training_session_for_workout(
    session: AsyncSession, workout: Workout, *, exercise_a_id: int, exercise_b_id: int,
) -> None:
    training_session = TrainingSession(
        user_id=workout.user_id,
        source=_resolve_session_source(workout),
        status=SessionStatus.COMPLETED,
        performed_at=workout.performed_at,
        comment=workout.comment,
    )
    session.add(training_session)
    await session.flush()

    block_a = _find_block(workout, BlockType.A)
    await _add_session_block_with_logs(
        session, session_id=training_session.id, order_index=0, exercise_id=exercise_a_id, block=block_a,
    )

    if not workout.is_free_entry:
        # Фиктивный блок Б свободных подтягиваний (working_reps=[],
        # max_reps=0, issue #109/#156) сознательно не переносится — см.
        # докстринг модуля.
        block_b = _find_block(workout, BlockType.B)
        await _add_session_block_with_logs(
            session, session_id=training_session.id, order_index=1, exercise_id=exercise_b_id, block=block_b,
        )


# --- Перенос ElectiveWorkout -> TrainingSession(source=elective) (п.3) -------------


async def _list_all_electives_for_user(session: AsyncSession, user_id: int) -> list[ElectiveWorkout]:
    """Вся история факультативов пользователя, хронологически — не
    ElectiveWorkoutRepository.list_for_user (та ограничена limit=100 и
    отдаёт по убыванию даты, рассчитана на показ истории в интерфейсе, не
    на полный перенос)."""
    result = await session.execute(
        select(ElectiveWorkout).where(ElectiveWorkout.user_id == user_id).order_by(ElectiveWorkout.performed_at),
    )
    return list(result.scalars().all())


async def _create_training_session_for_elective(
    session: AsyncSession, elective: ElectiveWorkout, *, exercise_id: int,
) -> None:
    training_session = TrainingSession(
        user_id=elective.user_id,
        source=SessionSource.ELECTIVE,
        status=SessionStatus.COMPLETED,
        performed_at=elective.performed_at,
    )
    session.add(training_session)
    await session.flush()

    session_block = SessionBlock(session_id=training_session.id, order_index=0, exercise_id=exercise_id)
    session.add(session_block)
    await session.flush()

    # Снаряд факультатива — единственная деталь блока/сессии, для которой
    # схема SessionBlock/SetLog не заводит структурных полей (см. докстринг
    # модуля) — упаковано в note, единственное свободное текстовое поле.
    note = json.dumps(
        {
            "format": elective.elective_type.value,
            "reps_sequence": elective.reps_sequence,
            "equipment_type": elective.equipment_type.value,
            "equipment_value": str(elective.equipment_value) if elective.equipment_value is not None else None,
            "equipment_item_id": elective.equipment_item_id,
            "equipment_item_name": elective.equipment_item_name,
        },
        ensure_ascii=False,
    )
    session.add(
        SetLog(
            session_block_id=session_block.id, set_number=1, is_max_set=False,
            metric_type=MetricType.REPS, value=Decimal(elective.total_reps), unit="reps", note=note,
        ),
    )


# --- progression_state (п.2) --------------------------------------------------------


def _decimal_str(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


async def _build_progression_state(
    session: AsyncSession, workout_repo: WorkoutRepository, user_id: int, *, now: datetime, history: list[Workout],
) -> dict:
    """Снимок ТЕКУЩЕГО состояния прогрессии — то же самое, что показывает
    хендлеру resolve_next_targets (публичный вход, уже используется ботом
    для отображения плана ДО следующей тренировки), плюс weak/stall-стрики,
    которые в NextBlockState не входят (внутренние для каскада) — считаются
    той же комбинацией приватных хелперов, что использует сам
    WorkoutRepository внутри complete_workout (осознанное разовое
    исключение, не копирование логики: тот же самый код, не его копия).

    Реальный баг (issue #172): для пользователя БЕЗ единой тренировки
    resolve_next_targets намеренно отдаёт заглушку (equipment_type=BAND,
    target=block_config.base_target, needs_new_equipment=True) — сигнал
    "спроси снаряд у пользователя на первой тренировке", а не готовое
    состояние; сама заглушка ничего не знает о замере пользователя. Экран
    "Тренировка" для ПЕРВОЙ тренировки эту заглушку не показывает вовсе —
    _resolve_plan_context (app/web/routes.py) и handle_start_workout бота
    для пустой истории считают стартовый снаряд/цель блока A по замеру
    (suggest_starting_equipment/initial_volume_target), в обход
    resolve_next_targets. Backfill раньше слепо брал заглушку как есть —
    здесь тот же расчёт по замеру, тем же путём, что и реальный экран,
    чтобы progression_state не расходился с тем, что видит пользователь."""
    state_a, state_b = await workout_repo.resolve_next_targets(user_id)

    if not history:
        baseline = await BaselineRepository(session).get_latest_for_user(user_id)
        baseline_reps = baseline.reps if baseline is not None else 0
        equipment_a_type, equipment_b_type = suggest_starting_equipment(baseline_reps)
        state_a = replace(state_a, target=initial_volume_target(baseline_reps), equipment_type=equipment_a_type)
        state_b = replace(state_b, equipment_type=equipment_b_type)

    history_no_free = _exclude_free_entries(history)
    history_a = _exclude_deload_entries(history_no_free)
    history_b = _exclude_heavy_entries(history_no_free)
    weak_streak_a = _weak_streak(history_a, BlockType.A)
    stall_streak_a = _stall_streak(history_a)
    weak_streak_b = _weak_streak(history_b, BlockType.B)

    active_set = await WorkoutSetRepository(session).get_active_for_user(user_id)
    workouts_completed_in_set = active_set.workouts_completed if active_set is not None else 0

    return {
        "schema_version": 1,
        "strategy_type": ProgressionStrategyType.STEP.value,
        "block_a": {
            "target": state_a.target,
            "volume": state_a.volume,
            "work_sets": state_a.work_sets,
            "work_sets_growth_reason": (
                state_a.work_sets_growth_reason.value if state_a.work_sets_growth_reason is not None else None
            ),
            "weak_streak": weak_streak_a,
            "stall_streak": stall_streak_a,
            "equipment_type": state_a.equipment_type.value,
            "equipment_value": _decimal_str(state_a.equipment_value),
            "equipment_item_id": state_a.equipment_item_id,
            "needs_new_equipment": state_a.needs_new_equipment,
        },
        "block_b": {
            "target": state_b.target,
            "volume": state_b.volume,
            "weak_streak": weak_streak_b,
            "equipment_type": state_b.equipment_type.value,
            "equipment_value": _decimal_str(state_b.equipment_value),
            "equipment_item_id": state_b.equipment_item_id,
            "needs_new_equipment": state_b.needs_new_equipment,
            "is_heavy_next": state_b.is_heavy,
            "heavy_equipment_value_next": _decimal_str(state_b.heavy_equipment_value),
        },
        "workouts_completed_in_set": workouts_completed_in_set,
        "backfilled_from": "legacy_v1",
        "backfilled_at": now.isoformat(),
    }


# --- Оркестрация + идемпотентность + отчёт (критерий готовности) -------------------


async def _is_already_migrated(session: AsyncSession, user_id: int) -> bool:
    result = await session.execute(select(TrainingPlan.id).where(TrainingPlan.user_id == user_id))
    return result.scalar_one_or_none() is not None


async def _count(session: AsyncSession, model, *conditions) -> int:
    query = select(func.count()).select_from(model)
    if conditions:
        query = query.where(*conditions)
    result = await session.execute(query)
    return result.scalar_one()


async def _count_onboarded_workouts(session: AsyncSession) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(Workout)
        .join(User, Workout.user_id == User.id)
        .where(Workout.status == WorkoutStatus.COMPLETED, User.onboarding_completed_at.is_not(None)),
    )
    return result.scalar_one()


async def _count_onboarded_electives(session: AsyncSession) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(ElectiveWorkout)
        .join(User, ElectiveWorkout.user_id == User.id)
        .where(User.onboarding_completed_at.is_not(None)),
    )
    return result.scalar_one()


@dataclass
class BackfillReport:
    dry_run: bool
    users_onboarded: int = 0
    users_migrated_this_run: int = 0
    users_already_migrated: int = 0
    training_plans_total: int = 0
    training_sessions_regular_total: int = 0
    training_sessions_elective_total: int = 0
    workouts_completed_expected: int = 0
    electives_expected: int = 0
    legacy_snapshots_normalized: int = 0

    def render(self) -> str:
        lines = [
            "DRY-RUN (ничего не записано)" if self.dry_run else "Прогон завершён",
            f"Онбордившихся пользователей: {self.users_onboarded}",
            "  " + (
                f"будет мигрировано: {self.users_migrated_this_run}" if self.dry_run
                else f"мигрировано в этом прогоне: {self.users_migrated_this_run}"
            ),
            f"  уже было мигрировано (пропущено): {self.users_already_migrated}",
        ]
        if self.dry_run:
            lines.append(f"Будет создано TrainingSession (обычных): {self.training_sessions_regular_total}")
            lines.append(f"Будет создано TrainingSession (elective): {self.training_sessions_elective_total}")
            return "\n".join(lines)

        plans_ok = "OK" if self.training_plans_total == self.users_onboarded else "РАСХОЖДЕНИЕ"
        regular_ok = (
            "OK" if self.training_sessions_regular_total == self.workouts_completed_expected else "РАСХОЖДЕНИЕ"
        )
        elective_ok = "OK" if self.training_sessions_elective_total == self.electives_expected else "РАСХОЖДЕНИЕ"
        lines += [
            f"TrainingPlan всего: {self.training_plans_total} (ожидается {self.users_onboarded}) [{plans_ok}]",
            (
                f"TrainingSession обычные всего: {self.training_sessions_regular_total} "
                f"(ожидается {self.workouts_completed_expected}) [{regular_ok}]"
            ),
            (
                f"TrainingSession elective всего: {self.training_sessions_elective_total} "
                f"(ожидается {self.electives_expected}) [{elective_ok}]"
            ),
            f"Нормализовано legacy-снимков (program_items добавлен): {self.legacy_snapshots_normalized}",
        ]
        return "\n".join(lines)


async def normalize_legacy_snapshots(session: AsyncSession, *, program_id: int, program_items_snap: list[dict]) -> int:
    """Checkpoint 1.1 (issue #188) — контрактный баг: ProgramInclusion,
    созданные до этого чекпоинта, имеют snapshot без ключа "program_items"
    (старый формат seed_catalog). PlanWeekService.ensure_current_plan_week
    читает rollover ИЗ snapshot, не из live Program — без нормализации эти
    пользователи просто не получат материализации на следующей неделе
    (тихий gap, не искажение данных, но и не задуманное поведение).

    Идемпотентно: снимок, у которого "program_items" уже есть, не трогаем
    вообще — ни то же самое значение не перезаписываем, ни оборачиваем.
    Не меняет progression_state/started_at/PlanItem/PlanWeek/историю —
    только один ключ внутри JSON-снимка той же самой ProgramInclusion.
    Возвращает число нормализованных строк (для отчёта)."""
    result = await session.execute(select(ProgramInclusion).where(ProgramInclusion.program_id == program_id))
    normalized = 0
    for inclusion in result.scalars().all():
        snapshot = inclusion.snapshot or {}
        if snapshot.get("program_items"):
            continue
        inclusion.snapshot = {**snapshot, "program_items": program_items_snap}
        normalized += 1
    if normalized:
        await session.flush()
    return normalized


async def backfill_all(session: AsyncSession, *, now: datetime, dry_run: bool = False) -> BackfillReport:
    """Основная логика, отделена от main() ради тестируемости на тестовой БД
    (по образцу scripts/backfill_achievements.py::backfill_all_users).

    На пользователя — атомарный блок: если он уже мигрирован (TrainingPlan
    существует), пропускается целиком без записи; иначе переносится вся его
    история + создаётся TrainingPlan/ProgramInclusion последним шагом, и
    транзакция коммитится сразу — TrainingPlan одновременно и маркер "этот
    пользователь полностью смигрирован", и последний шаг, который его
    создаёт (при падении скрипта посередине пользователя коммита не будет
    вообще, перезапуск просто обработает его заново, без дублей)."""
    users = await UserRepository(session).list_onboarded()
    report = BackfillReport(dry_run=dry_run, users_onboarded=len(users))

    seed = None if dry_run else await seed_catalog(session)
    if seed is not None:
        # Checkpoint 1.1 (issue #188) — нормализация ДО цикла по
        # пользователям: не зависит от того, кто в этом прогоне "новый",
        # трогает существующие ProgramInclusion сразу и один раз.
        report.legacy_snapshots_normalized = await normalize_legacy_snapshots(
            session, program_id=seed.program_id, program_items_snap=seed.snapshot["program_items"],
        )
        await session.commit()
    workout_repo = WorkoutRepository(session)
    program_repo = ProgramRepository(session)
    plans_repo = TrainingPlanRepository(session)

    for user in users:
        if await _is_already_migrated(session, user.id):
            report.users_already_migrated += 1
            if not dry_run:
                # Checkpoint 1 (issue #188): пользователи, смигрированные
                # ДО этого чекпоинта (сегодняшним ручным фиксом, до
                # появления ProgramItem/PlanWeekService), уже имеют
                # PlanItem с plan_week_id=NULL. ensure_current_plan_week
                # находит их веткой "unweeked" (см. app/services/
                # plan_week.py) и просто привязывает — не создаёт дублей,
                # не трогает progression_state/историю. Тот же метод, что
                # использует routes_v2.py для обычных пользователей.
                plan = await plans_repo.get_for_user(user.id)
                if plan is not None:
                    await PlanWeekService(session).ensure_current_plan_week(
                        training_plan_id=plan.id, today=now.date(),
                    )
                    await session.commit()
            continue

        history = await workout_repo.list_for_user(user.id)
        electives = await _list_all_electives_for_user(session, user.id)

        if dry_run:
            report.users_migrated_this_run += 1
            report.training_sessions_regular_total += len(history)
            report.training_sessions_elective_total += len(electives)
            continue

        for workout in history:
            await _create_training_session_for_workout(
                session, workout, exercise_a_id=seed.exercise_a_id, exercise_b_id=seed.exercise_b_id,
            )
        for elective in electives:
            await _create_training_session_for_elective(
                session, elective, exercise_id=seed.elective_exercise_ids[elective.elective_type],
            )

        progression_state = await _build_progression_state(session, workout_repo, user.id, now=now, history=history)
        training_plan = TrainingPlan(user_id=user.id)
        session.add(training_plan)
        await session.flush()
        inclusion = ProgramInclusion(
            training_plan_id=training_plan.id,
            program_id=seed.program_id,
            snapshot=seed.snapshot,
            progression_state=progression_state,
            is_active=True,
        )
        session.add(inclusion)
        await session.flush()
        # Checkpoint 1 (issue #188): раньше здесь была ручная вставка
        # PlanItem в обход ProgramItem (тот самый второй путь, который
        # прямо запрещён Поправкой 7 — "нельзя сохранять два постоянных
        # пути: новые пользователи через inclusion service, старые через
        # специальную логику backfill навсегда"). seed_catalog теперь
        # заполняет ProgramItem для обоих блоков — используем ТОТ ЖЕ
        # репозиторный метод, которым пользуется ProgramInclusionService.
        # create_inclusion для новых (не бэкфилленных) подключений курса.
        program_items = await program_repo.list_program_items(seed.program_id)
        await plans_repo.bulk_create_plan_items_from_program_items(
            training_plan_id=training_plan.id, program_inclusion_id=inclusion.id, program_items=program_items,
        )
        await session.flush()
        # Материализация в текущую PlanWeek — тот же PlanWeekService, что
        # routes_v2.py вызывает на POST /program-inclusions/GET /plan для
        # обычных пользователей (Поправка 7: один канонический путь).
        await PlanWeekService(session).ensure_current_plan_week(training_plan_id=training_plan.id, today=now.date())
        await session.commit()
        report.users_migrated_this_run += 1

    if dry_run:
        # Проекция поверх уже реально существующего в БД (для уже
        # мигрированных прошлым прогоном пользователей) — dry-run ничего не
        # пишет, поэтому "будет создано" считается ПОВЕРХ текущего состояния.
        report.training_plans_total = (
            await _count(session, TrainingPlan) + report.users_migrated_this_run
        )
        report.training_sessions_regular_total += await _count(
            session, TrainingSession, TrainingSession.source != SessionSource.ELECTIVE,
        )
        report.training_sessions_elective_total += await _count(
            session, TrainingSession, TrainingSession.source == SessionSource.ELECTIVE,
        )
    else:
        report.training_plans_total = await _count(session, TrainingPlan)
        report.training_sessions_regular_total = await _count(
            session, TrainingSession, TrainingSession.source != SessionSource.ELECTIVE,
        )
        report.training_sessions_elective_total = await _count(
            session, TrainingSession, TrainingSession.source == SessionSource.ELECTIVE,
        )
    report.workouts_completed_expected = await _count_onboarded_workouts(session)
    report.electives_expected = await _count_onboarded_electives(session)
    return report


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="только посчитать, ничего не писать")
    parser.add_argument(
        "--truncate", action="store_true",
        help=(
            "стереть training_plans/training_sessions (и всё каскадно зависимое) перед прогоном — "
            "ТОЛЬКО для повторных тестовых прогонов на копии/синтетике, не для единственного "
            "реального прогона на проде без отдельного подтверждения"
        ),
    )
    args = parser.parse_args()
    if args.dry_run and args.truncate:
        raise SystemExit("--dry-run и --truncate несовместимы")

    async with async_session_factory() as session:
        if args.truncate:
            await session.execute(text("TRUNCATE TABLE training_plans, training_sessions RESTART IDENTITY CASCADE"))
            await session.commit()
        report = await backfill_all(session, now=datetime.now(UTC), dry_run=args.dry_run)
        print(report.render())


if __name__ == "__main__":
    asyncio.run(main())
