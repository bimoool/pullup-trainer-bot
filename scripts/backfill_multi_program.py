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
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import async_session_factory
from app.db.models import BlockType, ElectiveWorkout, User, Workout, WorkoutStatus
from app.db.models_program import (
    Exercise,
    Program,
    ProgramInclusion,
    ProgramItem,
    ProgressionStrategyProfile,
    SessionStatus,
    TrainingPlan,
    TrainingSession,
)
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.legacy_convergence import (
    ELECTIVE_EXERCISE_NAMES,
    EXERCISE_BLOCK_A_NAME,
    EXERCISE_BLOCK_B_NAME,
    ConvergenceOutcome,
    LegacyConvergenceRepository,
)
from app.db.repositories.programs import ProgramRepository, program_items_snapshot
from app.db.repositories.training_plans import TrainingPlanRepository
from app.db.repositories.training_sessions import TrainingSessionRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import (
    WorkoutRepository,
    _exclude_deload_entries,
    _exclude_free_entries,
    _exclude_heavy_entries,
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
from app.domain.multi_program import (
    MetricType,
    ProgramStructureType,
    WeekPhase,
    snapshot_program_items_gap,
)
from app.domain.program_access import ProgramAccessLevel
from app.domain.progression import initial_volume_target, suggest_starting_equipment
from app.domain.progression_strategy import ProgressionStrategyType
from app.domain.training_session_v2 import SessionOrigin
from app.services.legacy_history_convergence import MUTATING_KEYS, LegacyHistoryConvergenceService
from app.services.plan_week import PlanWeekService

_PROGRAM_NAME = "Подтягивания"
_STRATEGY_PROFILE_NAME = "Пошаговая прогрессия подтягиваний"
_EXERCISE_BLOCK_A_NAME = EXERCISE_BLOCK_A_NAME
_EXERCISE_BLOCK_B_NAME = EXERCISE_BLOCK_B_NAME
_ELECTIVE_EXERCISE_NAMES = ELECTIVE_EXERCISE_NAMES


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
        # Бесплатна навсегда (решение владельца 2026-10-07) — как миграция c3f7a9e2d5b1 для уже созданной строки.
        access_level=ProgramAccessLevel.FREE.value,
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


async def _create_training_session_for_workout(
    session: AsyncSession, workout: Workout, *, exercise_a_id: int, exercise_b_id: int,
) -> ConvergenceOutcome:
    """Нативная копия legacy Workout (MIGRATION_V2 §3/§4). С #308 — ТА ЖЕ функция, что dual-write писателей
    старой схемы (LegacyConvergenceRepository.sync_workout): ключ (origin, legacy_id) уникален, повторный
    вызов копию не дублирует и не меняет (UNCHANGED)."""
    return await LegacyConvergenceRepository(session).sync_workout(
        workout, exercise_a_id=exercise_a_id, exercise_b_id=exercise_b_id,
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
) -> ConvergenceOutcome:
    """Копия факультатива (origin legacy_elective, ключ legacy_id). Создаётся один раз; существующую
    (в т.ч. отредактированную в Журнале) повторный вызов не трогает."""
    return await LegacyConvergenceRepository(session).sync_elective(elective, exercise_id=exercise_id)


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
            # issue #305: каноническая форма — work_sets у обеих ролей (у блока Б он постоянный).
            "work_sets": STRENGTH_BLOCK.work_sets,
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


def _onboarded_completed_workout_ids():
    return (
        select(Workout.id)
        .join(User, Workout.user_id == User.id)
        .where(Workout.status == WorkoutStatus.COMPLETED, User.onboarding_completed_at.is_not(None))
    )


def _onboarded_elective_ids():
    return (
        select(ElectiveWorkout.id)
        .join(User, ElectiveWorkout.user_id == User.id)
        .where(User.onboarding_completed_at.is_not(None))
    )


async def _count_legacy_copies(session: AsyncSession, origin: SessionOrigin, legacy_ids) -> int:
    """Копии legacy-строк, которые сверяются с ожидаемым числом: origin копии и legacy_id из того же множества,
    что считает ожидаемое (_count_onboarded_workouts / _count_onboarded_electives). (origin, legacy_id) уникальна
    в БД, поэтому одна legacy-строка даёт не больше одной копии."""
    return await _count(
        session, TrainingSession, TrainingSession.origin == origin.value, TrainingSession.legacy_id.in_(legacy_ids),
    )


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
    # Сессии, которые не являются копиями сверяемых legacy-строк: самостоятельные сессии Mini App (origin native или
    # NULL до #307), копии строк не онбордившихся пользователей или незавершённых тренировок. Показываются, не сверяются.
    training_sessions_not_reconciled: int = 0
    legacy_snapshots_normalized: int = 0
    # #308: сведение legacy-истории уже мигрированных пользователей (HistoryConvergenceReport)
    history: Counter = field(default_factory=Counter)

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
            lines.append(self._not_reconciled_line())
            lines += _render_history(self.history, dry_run=True)
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
            self._not_reconciled_line(),
            f"Нормализовано legacy-снимков (program_items добавлен): {self.legacy_snapshots_normalized}",
            *_render_history(self.history, dry_run=False),
        ]
        return "\n".join(lines)

    def _not_reconciled_line(self) -> str:
        return (
            "TrainingSession вне сверки (сессии Mini App и строки без пары в сверяемой legacy-истории), "
            f"не сверяются: {self.training_sessions_not_reconciled}"
        )


_HISTORY_LABELS = (
    ("classified", "origin проставлен копиям без origin"),
    ("bound", "копий привязано к legacy-строке (legacy_id)"),
    ("created", "копий создано"),
    ("elective_created", "копий факультативов создано"),
    ("elective_first_import_without_plan", "  из них у пользователей без плана (по инварианту «нет плана — backfill не проходил»)"),
    ("updated", "копий обновлено"),
    ("superseded", "копий замещено (legacy-строка удалена/заменена)"),
    ("unchanged", "копий без изменений"),
    ("ambiguous_elective_without_copy", "факультативов без копии, НЕ воскрешены (неоднозначно)"),
    ("elective_unkeyed_copies_kept", "копий факультативов без пары оставлено как есть"),
    ("superseded_but_alive", "замещённых копий с живой legacy-строкой (оставлены замещёнными)"),
)


def _render_history(counts: Counter, *, dry_run: bool) -> list[str]:
    if not counts:
        return []
    prefix = "[будет] " if dry_run else ""
    return ["Сведение legacy-истории (#308, MIGRATION_V2 §4):"] + [
        f"  {prefix}{label}: {counts[key]}" for key, label in _HISTORY_LABELS if counts[key]
    ]


_UNRESOLVED_REASONS = {
    "backfilled_copy_edited_or_deleted": "старый backfill его уже перенёс (записан не позже плана, есть копия из транзакции плана), "
                                         "точной копии нет — правлена или удалена в Журнале",
    "pre_migration_without_copy": "записан не позже TrainingPlan, копии нет — удалена в Журнале либо план создан "
                                  "до импорта (уцелевшей копии транзакции плана нет — перенос не доказуем)",
    "nonstandard_copy_history": "история копий пользователя не объяснима штатными писателями (след в evidence: копия "
                                "вне транзакции плана / копия без плана) — не создаётся и не привязывается ничего",
    "exact_copy_predates_elective": "есть копия того же содержимого, но она старше факультатива — не привязана, "
                                    "вторая не создана",
}


def _history_result_line(counts: Counter, unresolved: list[dict], *, apply: bool, user_ids: list[int] | None) -> str:
    """`RESULT-JSON {...}` — счётчики, число изменений (MUTATING_KEYS, в т. ч. classified) и неразрешённые случаи."""
    return "RESULT-JSON " + json.dumps({
        "mode": "apply" if apply else "dry-run", "user_ids": user_ids, "users": counts["users"],
        "mutations": sum(counts[key] for key in MUTATING_KEYS),
        "counts": {key: value for key, value in sorted(counts.items()) if key != "users"},
        "unresolved": sorted(
            ({"user_id": item["user_id"], "elective_id": item["elective_id"], "reason": item["reason"]} for item in unresolved),
            key=lambda item: (item["user_id"], item["elective_id"]),
        ),
    }, ensure_ascii=False, sort_keys=True)


def _render_unresolved(items: list[dict]) -> list[str]:
    """Неразрешённые факультативы: копия НЕ создана (не воскрешаем удалённое и не дублируем правленое), ничего не
    привязано. candidates — непривязанные копии того же формата для ручной проверки."""
    if not items:
        return []
    lines = [f"Не разрешено (копия НЕ создана, ничего не привязано): {len(items)}"]
    for item in items:
        lines.append(
            f"  user_id={item['user_id']} elective_id={item['elective_id']} {item.get('elective_type', '?')} "
            f"{item.get('performed_at', '?')} reps={item.get('total_reps', '?')}: "
            f"{_UNRESOLVED_REASONS.get(item['reason'], item['reason'])}; "
            f"кандидаты (копии без ключа): {item.get('candidate_copy_ids') or 'нет'}"
            + (f"; evidence: {item['evidence']}" if item.get("evidence") else ""),
        )
    return lines


async def _count_missing_copies(session: AsyncSession, origin: SessionOrigin, legacy_ids: list[int]) -> int:
    if not legacy_ids:
        return 0
    have = await session.scalar(
        select(func.count()).select_from(TrainingSession).where(
            TrainingSession.origin == origin.value, TrainingSession.legacy_id.in_(legacy_ids),
        ),
    )
    return len(legacy_ids) - int(have or 0)


async def converge_history_all(
    session: AsyncSession, *, apply: bool, user_ids: list[int] | None = None, unresolved: list[dict] | None = None,
) -> Counter:
    """MIGRATION_V2 §4: у каждой живой строки workouts/elective_workouts — ровно одна нативная копия
    (origin, legacy_id). Идёт по ВСЕМ пользователям с legacy-историей или копиями (не только онбордившимся и не
    только «ещё не смигрированным»), по одному в транзакции; dry-run (apply=False) только читает.
    Повторный apply возвращает counts без изменяющих ключей (mutations = 0). unresolved — если передан,
    дополняется неразрешёнными случаями (факультатив без копии, происхождение которой не доказать) с user_id."""
    total: Counter = Counter()
    if apply and not user_ids:
        # Защита на уровне функции, не только CLI: запись сведения всегда по явному списку подтверждённых пользователей.
        raise ValueError("converge_history_all(apply=True) requires an explicit non-empty user_ids list")
    if user_ids is None:
        ids: set[int] = set()
        for column in (Workout.user_id, ElectiveWorkout.user_id):
            ids |= set((await session.execute(select(column).distinct())).scalars().all())
        ids |= set((await session.execute(
            select(TrainingSession.user_id).where(
                TrainingSession.origin.in_((SessionOrigin.LEGACY_BACKFILL.value, SessionOrigin.LEGACY_ELECTIVE.value)),
            ).distinct(),
        )).scalars().all())
        ids |= set((await session.execute(
            select(TrainingSession.user_id).where(
                TrainingSession.origin.is_(None), TrainingSession.status == SessionStatus.COMPLETED,
                TrainingSessionRepository.legacy_copy_fingerprint_for_recovery(),
            ).distinct(),
        )).scalars().all())
        user_ids = sorted(ids)
    service = LegacyHistoryConvergenceService(session)
    for user_id in user_ids:
        report = await service.converge_user(user_id, apply=apply)
        total.update(report.counts)
        total["users"] += 1
        if unresolved is not None:
            unresolved.extend({"user_id": user_id, **item} for item in report.ambiguous)
        if apply:
            await session.commit()
        else:
            await session.rollback()
    return total


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
        if snapshot_program_items_gap(snapshot) is None:
            continue  # тот же предикат, что у рантайма (PlanWeekService.converge_inclusion_snapshot, #301)
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
    # Только id, собранные заранее: dry-run делает session.rollback() после каждого уже смигрированного
    # пользователя — это expire всех загруженных User, и следующее `user.id` из ORM-объекта в async-сессии падало
    # MissingGreenlet (репетиция прод-миграции 2026-10-16: контрольный dry-run после apply, exit 1).
    user_ids = [user.id for user in users]

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

    for user_id in user_ids:
        if await _is_already_migrated(session, user_id):
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
                plan = await plans_repo.get_for_user(user_id)
                if plan is not None:
                    await PlanWeekService(session).ensure_current_plan_week(
                        training_plan_id=plan.id, today=now.date(),
                    )
                    await session.commit()
            # #308: legacy-история уже мигрированного пользователя сводится в нативные копии
            # (привязка, недостающие, обновлённые, замещённые); dry-run только считает.
            history_report = await LegacyHistoryConvergenceService(session).converge_user(
                user_id, apply=not dry_run,
            )
            report.history.update(history_report.counts)
            if dry_run:
                await session.rollback()
            else:
                await session.commit()
            continue

        history = await workout_repo.list_for_user(user_id)
        electives = await _list_all_electives_for_user(session, user_id)

        if dry_run:
            report.users_migrated_this_run += 1
            # Копии, которые dual-write (#308) уже создал, заново не создаются — считаем только недостающие.
            report.training_sessions_regular_total += await _count_missing_copies(
                session, SessionOrigin.LEGACY_BACKFILL, [w.id for w in history],
            )
            report.training_sessions_elective_total += await _count_missing_copies(
                session, SessionOrigin.LEGACY_ELECTIVE, [e.id for e in electives],
            )
            continue

        for workout in history:
            await _create_training_session_for_workout(
                session, workout, exercise_a_id=seed.exercise_a_id, exercise_b_id=seed.exercise_b_id,
            )
        for elective in electives:
            await _create_training_session_for_elective(
                session, elective, exercise_id=seed.elective_exercise_ids[elective.elective_type],
            )

        progression_state = await _build_progression_state(session, workout_repo, user_id, now=now, history=history)
        training_plan = TrainingPlan(user_id=user_id)
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

    # Сверяются только копии legacy-строк (origin + legacy_id) с теми же legacy-строками, что считает ожидаемое
    # число. Раньше «фактическое» брало ВСЕ сессии source != elective: самостоятельная сессия Mini App давала
    # ложное РАСХОЖДЕНИЕ (прод-выкат 2026-10-17, фаза 8: «74 (ожидается 73)»), а при потерянной копии — ложное OK.
    regular_copies = await _count_legacy_copies(session, SessionOrigin.LEGACY_BACKFILL, _onboarded_completed_workout_ids())
    elective_copies = await _count_legacy_copies(session, SessionOrigin.LEGACY_ELECTIVE, _onboarded_elective_ids())
    report.training_sessions_not_reconciled = await _count(session, TrainingSession) - regular_copies - elective_copies
    if dry_run:
        # Проекция поверх уже реально существующего в БД (для уже
        # мигрированных прошлым прогоном пользователей) — dry-run ничего не
        # пишет, поэтому "будет создано" считается ПОВЕРХ текущего состояния.
        report.training_plans_total = (
            await _count(session, TrainingPlan) + report.users_migrated_this_run
        )
        report.training_sessions_regular_total += regular_copies
        report.training_sessions_elective_total += elective_copies
    else:
        report.training_plans_total = await _count(session, TrainingPlan)
        report.training_sessions_regular_total = regular_copies
        report.training_sessions_elective_total = elective_copies
    report.workouts_completed_expected = await _count_onboarded_workouts(session)
    report.electives_expected = await _count_onboarded_electives(session)
    return report


async def verify_migrated_database(session: AsyncSession) -> dict:
    """Verify existing migration coverage without calendar materialization or any writes.

    Requires a fresh session: the server-enforced repeatable-read/read-only transaction
    protects this mode even if a future dry-run implementation accidentally writes.
    """
    if session.in_transaction():
        raise ValueError("verify-only requires a fresh session")
    await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
    errors: list[str] = []
    onboarded = int(await session.scalar(text(
        "SELECT count(*) FROM users WHERE onboarding_completed_at IS NOT NULL"
    )))
    checks = {
        "onboarded_without_plan": """SELECT count(*) FROM users u
            WHERE u.onboarding_completed_at IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM training_plans p WHERE p.user_id=u.id)""",
        "plans_without_onboarded_user": """SELECT count(*) FROM training_plans p
            JOIN users u ON u.id=p.user_id WHERE u.onboarding_completed_at IS NULL""",
        "plans_without_one_active_inclusion": """SELECT count(*) FROM training_plans p
            WHERE (SELECT count(*) FROM program_inclusions i
                   WHERE i.training_plan_id=p.id AND i.is_active) <> 1""",
        "duplicate_legacy_copies": """SELECT count(*) FROM (SELECT 1 FROM training_sessions
            WHERE legacy_id IS NOT NULL GROUP BY origin,legacy_id HAVING count(*)>1) d""",
        "workouts_without_copy": """SELECT count(*) FROM workouts w WHERE w.status='completed'
            AND NOT EXISTS (SELECT 1 FROM training_sessions s WHERE s.origin='legacy_backfill'
                AND s.legacy_id=w.id AND s.user_id=w.user_id AND s.status='completed')""",
        "electives_without_copy": """SELECT count(*) FROM elective_workouts e
            WHERE NOT EXISTS (SELECT 1 FROM training_sessions s WHERE s.origin='legacy_elective'
                AND s.legacy_id=e.id AND s.user_id=e.user_id AND s.status='completed')""",
    }
    for name, sql in checks.items():
        count = int(await session.scalar(text(sql)))
        if count:
            errors.append(f"{name}={count}")
    # Use the SAME historical reconciliation semantics as migration, without row locks.
    # Calendar convergence is deliberately excluded: legitimate next-week work belongs
    # to runtime, not to this no-schema release's preservation check.
    user_ids = list((await session.execute(select(User.id).order_by(User.id))).scalars().all())
    required_names = {EXERCISE_BLOCK_A_NAME, EXERCISE_BLOCK_B_NAME, *ELECTIVE_EXERCISE_NAMES.values()}
    names = set((await session.execute(select(Exercise.name).where(Exercise.name.in_(required_names)))).scalars().all())
    missing_names = sorted(required_names - names)
    if missing_names:
        errors.append("missing_legacy_catalog:" + ",".join(missing_names))
    service = LegacyHistoryConvergenceService(session, read_only=True)
    mutations = 0
    unresolved = 0
    for user_id in user_ids if not missing_names else []:
        report = await service.converge_user(user_id, apply=False)
        mutations += report.mutations
        unresolved += len(report.ambiguous)
        if report.counts["superseded_but_alive"]:
            errors.append(f"superseded_live_copy:user_id={user_id}")
    if mutations:
        errors.append(f"history_mutations={mutations}")
    if unresolved:
        errors.append(f"unresolved_history={unresolved}")
    result = {
        "mode": "verify-only", "verified": not errors, "users_onboarded": onboarded,
        "history_mutations": mutations, "unresolved": unresolved, "errors": errors,
    }
    await session.rollback()
    return result


def _parse_user_ids(value: str) -> list[int]:
    try:
        ids = sorted({int(part) for part in value.split(",")})
    except ValueError:
        raise argparse.ArgumentTypeError("ожидается список целых users.id через запятую") from None
    if not ids or ids[0] <= 0:
        raise argparse.ArgumentTypeError("users.id должны быть положительными")
    return ids


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verify-only", action="store_true", help="verify fully migrated DB in a read-only transaction")
    parser.add_argument("--dry-run", action="store_true", help="только посчитать, ничего не писать")
    parser.add_argument(
        "--truncate", action="store_true",
        help=(
            "стереть training_plans/training_sessions (и всё каскадно зависимое) перед прогоном — "
            "ТОЛЬКО для повторных тестовых прогонов на копии/синтетике, не для единственного "
            "реального прогона на проде без отдельного подтверждения"
        ),
    )
    parser.add_argument(
        "--converge-history", action="store_true",
        help=(
            "ТОЛЬКО сведение legacy-истории в нативные копии (#308) для всех пользователей, без миграции плана; "
            "по умолчанию dry-run, запись — с --apply"
        ),
    )
    parser.add_argument("--apply", action="store_true", help="с --converge-history: записать изменения")
    parser.add_argument(
        "--user-ids", type=_parse_user_ids, default=None,
        help=(
            "с --converge-history: внутренние users.id через запятую (подтверждённые владельцем). Без списка dry-run "
            "читает ВСЕХ пользователей (ничего не пишет); --apply без списка запрещён"
        ),
    )
    args = parser.parse_args()
    if args.verify_only:
        if args.dry_run or args.truncate or args.converge_history or args.apply or args.user_ids is not None:
            raise SystemExit("--verify-only cannot be combined with other modes")
        async with async_session_factory() as session:
            result = await verify_migrated_database(session)
            print("RESULT-JSON " + json.dumps(result, sort_keys=True))
            if not result["verified"]:
                raise SystemExit(1)
        return
    if args.dry_run and args.truncate:
        raise SystemExit("--dry-run и --truncate несовместимы")
    if args.converge_history and (args.truncate or args.dry_run):
        raise SystemExit("--converge-history несовместим с --truncate/--dry-run (dry-run — без --apply)")
    if args.apply and not args.converge_history:
        raise SystemExit("--apply допустим только с --converge-history")
    if args.user_ids is not None and not args.converge_history:
        raise SystemExit("--user-ids допустим только с --converge-history")
    if args.converge_history and args.apply and not args.user_ids:
        raise SystemExit("--converge-history --apply требует --user-ids: сведение истории не применяется ко всем пользователям")

    if args.converge_history:
        async with async_session_factory() as session:
            unresolved: list[dict] = []
            if args.user_ids is not None:
                known = set((await session.execute(select(User.id).where(User.id.in_(args.user_ids)))).scalars().all())
                if missing := sorted(set(args.user_ids) - known):
                    raise SystemExit(f"--user-ids: пользователей нет в БД: {missing}")
            counts = await converge_history_all(
                session, apply=args.apply, user_ids=args.user_ids, unresolved=unresolved,
            )
            scope = f"пользователи {args.user_ids}" if args.user_ids is not None else "ВСЕ пользователи (только чтение)"
            print("\n".join(["Прогон завершён" if args.apply else "DRY-RUN (ничего не записано)",
                              f"Область: {scope}", f"Пользователей: {counts['users']}", *_render_history(counts, dry_run=not args.apply),
                              *_render_unresolved(unresolved)]))
            # Машинный результат для автоматических проверок (guarded deploy): одна последняя строка JSON.
            print(_history_result_line(counts, unresolved, apply=args.apply, user_ids=args.user_ids))
        return

    async with async_session_factory() as session:
        if args.truncate:
            await session.execute(text("TRUNCATE TABLE training_plans, training_sessions RESTART IDENTITY CASCADE"))
            await session.commit()
        report = await backfill_all(session, now=datetime.now(UTC), dry_run=args.dry_run)
        print(report.render())


if __name__ == "__main__":
    asyncio.run(main())
