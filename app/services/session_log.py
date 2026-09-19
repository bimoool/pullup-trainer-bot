from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import ProgramInclusion
from app.db.repositories.training_plans import TrainingPlanRepository
from app.db.repositories.training_sessions import (
    SessionBlockInput,
    SessionDetail,
    SetLogInput,
    TrainingSessionRepository,
)
from app.domain.constants import EquipmentType
from app.domain.multi_program import MetricType, SessionSource
from app.domain.progression_strategy import ProgressionContext, StepProgressionStrategy
from app.domain.session import BlockAssignment, BlockLog, WorkoutRecord

# Роли блока А/Б для StepProgressionStrategy — та же конвенция snapshot
# ["exercises"], которую строит ProgramInclusionService/
# scripts/backfill_multi_program.py (issue #165, подтверждено Кириллом).
_ROLE_BLOCK_A = "block_a"
_ROLE_BLOCK_B = "block_b"


@dataclass(frozen=True)
class BlockProgressionResult:
    target_before: int
    target_after: int
    equipment_changed: bool


@dataclass(frozen=True)
class SessionProgressionResult:
    block_a: BlockProgressionResult
    block_b: BlockProgressionResult


@dataclass(frozen=True)
class RecordSessionResult:
    session: SessionDetail
    progression_result: SessionProgressionResult | None
    progression_skipped_reason: str | None


def _equipment_type_from_state(block_state: dict) -> EquipmentType:
    return EquipmentType(block_state["equipment_type"])


def _equipment_value_from_state(block_state: dict) -> Decimal | None:
    value = block_state.get("equipment_value")
    return Decimal(value) if value is not None else None


def _block_log_from_sets(sets: list[SetLogInput]) -> BlockLog:
    working_reps = tuple(
        int(s.value) for s in sorted(sets, key=lambda s: s.set_number) if not s.is_max_set
    )
    max_set = next((s for s in sets if s.is_max_set), None)
    return BlockLog(working_reps=working_reps, max_reps=int(max_set.value) if max_set is not None else 0)


def _block_assignment(log: BlockLog, block_state: dict) -> BlockAssignment:
    return BlockAssignment(
        log=log,
        target_before=block_state["target"],
        target_after=block_state["target"],
        equipment_changed=False,
        equipment_type=_equipment_type_from_state(block_state),
        equipment_value=_equipment_value_from_state(block_state),
        equipment_item_id=block_state.get("equipment_item_id"),
    )


def _apply_step_progression(
    progression_state: dict, *, performed_at: datetime, block_a_sets: list[SetLogInput], block_b_sets: list[SetLogInput],
) -> tuple[dict, SessionProgressionResult]:
    """Единственное место, где новый код волны 3 касается пересчёта
    прогрессии — целиком через StepProgressionStrategy.apply() (волна 0,
    issue #158), не второй путь расчёта (issue #165, план п. "используй
    ProgressionStrategy... не пиши второй, отдельный путь").

    weak_streak/stall_streak в progression_state — бегущие счётчики
    (та же форма, что уже использует scripts/backfill_multi_program.py::
    _build_progression_state), не пересчитываемые из полной истории при
    каждом вызове: у TrainingSession/SessionBlock (в отличие от старой
    Block) нет персистентных target_before/after на запись, поэтому
    app.db.repositories.workouts._weak_streak/_stall_streak (сканирование
    истории) здесь неприменимо — состояние обязано жить в
    ProgramInclusion.progression_state между вызовами. Формулы обновления
    ниже — те же условия, что recalculate_cascade уже использует ВНУТРИ
    своего цикла (см. app/domain/progression.py) для этих же счётчиков,
    просто применённые к единственной новой записи, а не заново
    выведенные — тот же приём, каким _weak_streak/_stall_streak сами
    устроены СНАРУЖИ recalculate_cascade для старой схемы."""
    block_a_state, block_b_state = progression_state["block_a"], progression_state["block_b"]
    block_a_log = _block_log_from_sets(block_a_sets)
    block_b_log = _block_log_from_sets(block_b_sets)

    record = WorkoutRecord(
        performed_at=performed_at,
        block_a=_block_assignment(block_a_log, block_a_state),
        block_b=_block_assignment(block_b_log, block_b_state),
    )
    context = ProgressionContext(
        starting_target_a=block_a_state["target"], starting_target_b=block_b_state["target"],
        starting_volume_a=block_a_state["volume"], starting_volume_b=block_b_state["volume"],
        subsequent_workouts=[record],
        starting_weak_streak_a=block_a_state["weak_streak"], starting_weak_streak_b=block_b_state["weak_streak"],
        starting_work_sets_a=block_a_state["work_sets"], starting_stall_streak_a=block_a_state["stall_streak"],
    )
    [result] = StepProgressionStrategy().apply(context)

    grew_a = (
        result.block_a.target_after > result.block_a.target_before
        or result.block_a.work_sets_after > block_a_state["work_sets"]
    )
    new_weak_streak_a = block_a_state["weak_streak"] + 1 if result.block_a.log.volume < block_a_state["volume"] else 0
    new_stall_streak_a = 0 if grew_a else block_a_state["stall_streak"] + 1
    new_weak_streak_b = block_b_state["weak_streak"] + 1 if result.block_b.log.volume < block_b_state["volume"] else 0

    new_state = {
        "schema_version": progression_state.get("schema_version", 1),
        "strategy_type": progression_state["strategy_type"],
        "block_a": {
            **block_a_state,
            "target": result.block_a.target_after,
            "volume": result.block_a.log.volume,
            "work_sets": result.block_a.work_sets_after,
            "work_sets_growth_reason": (
                result.block_a.work_sets_growth_reason.value
                if result.block_a.work_sets_growth_reason is not None else None
            ),
            "weak_streak": new_weak_streak_a,
            "stall_streak": new_stall_streak_a,
            # Смена снаряда (equipment_changed=True) только СИГНАЛИЗИРУЕТСЯ —
            # выбор конкретного следующего снаряда (какой вес/резина) в этой
            # волне не автоматизирован (нет UI, нет эндпоинта выбора), тот же
            # принцип "явный пробел, не молчаливое поведение", что и у
            # equipment_setup_required в старой схеме (см. CLAUDE.md).
            "needs_new_equipment": result.block_a.equipment_changed,
        },
        "block_b": {
            **block_b_state,
            "target": result.block_b.target_after,
            "volume": result.block_b.log.volume,
            "weak_streak": new_weak_streak_b,
            "needs_new_equipment": result.block_b.equipment_changed,
        },
        "workouts_completed_in_set": progression_state.get("workouts_completed_in_set", 0) + 1,
    }
    progression_result = SessionProgressionResult(
        block_a=BlockProgressionResult(
            target_before=result.block_a.target_before, target_after=result.block_a.target_after,
            equipment_changed=result.block_a.equipment_changed,
        ),
        block_b=BlockProgressionResult(
            target_before=result.block_b.target_before, target_after=result.block_b.target_after,
            equipment_changed=result.block_b.equipment_changed,
        ),
    )
    return new_state, progression_result


def _match_step_blocks(
    inclusion: ProgramInclusion, blocks: list[SessionBlockInput],
) -> tuple[list[SetLogInput], list[SetLogInput]] | None:
    """Сопоставляет присланные блоки сессии с ролями block_a/block_b из
    snapshot["exercises"] (issue #165, открытый вопрос плана — подтверждено
    Кириллом: та же конвенция category/subcategory, что backfill-скрипт).
    None, если сопоставление не однозначно (не ровно 2 блока, или их
    exercise_id не покрывают обе роли) — вызывающий код тогда пишет только
    факт, без пересчёта."""
    exercises = inclusion.snapshot.get("exercises", [])
    role_by_exercise_id = {item["exercise_id"]: item["role"] for item in exercises}
    if len(blocks) != 2:
        return None
    by_role: dict[str, SessionBlockInput] = {}
    for block in blocks:
        role = role_by_exercise_id.get(block.exercise_id)
        if role is None or role in by_role:
            return None
        by_role[role] = block
    if _ROLE_BLOCK_A not in by_role or _ROLE_BLOCK_B not in by_role:
        return None
    block_a, block_b = by_role[_ROLE_BLOCK_A], by_role[_ROLE_BLOCK_B]
    if any(s.metric_type != MetricType.REPS for s in (*block_a.sets, *block_b.sets)):
        return None
    return block_a.sets, block_b.sets


class TrainingSessionLogService:
    """Оркестрация POST /api/v2/sessions (issue #165, волна 3): всегда
    пишет факт через TrainingSessionRepository; УСЛОВНО (см.
    _match_step_blocks/_apply_step_progression) пересчитывает
    ProgramInclusion.progression_state через StepProgressionStrategy —
    единственное место волны 3, где новый код касается пересчёта
    прогрессии."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._sessions = TrainingSessionRepository(session)
        self._plans = TrainingPlanRepository(session)

    async def record_session(
        self, *, user_id: int, source: SessionSource, performed_at: datetime,
        effort: Decimal | None, comment: str | None, blocks: list[SessionBlockInput],
        program_inclusion_id: int | None,
    ) -> tuple[RecordSessionResult | None, bool]:
        """Второй элемент кортежа — True, если program_inclusion_id передан,
        но не найден/не принадлежит пользователю (вызывающий код превращает
        это в 404 на РОУТЕ, не здесь — сервис не знает про HTTPException,
        тот же принцип разделения слоёв, что и в остальном проекте)."""
        inclusion = None
        if program_inclusion_id is not None:
            inclusion = await self._plans.get_inclusion_for_user(program_inclusion_id, user_id)
            if inclusion is None:
                return None, True

        training_session = await self._sessions.create_session(
            user_id=user_id, source=source, performed_at=performed_at,
            effort=effort, comment=comment, blocks=blocks,
        )
        session_detail = await self._sessions.get_for_user(training_session.id, user_id)

        progression_result: SessionProgressionResult | None = None
        skipped_reason: str | None = None
        if inclusion is None:
            skipped_reason = "no_program_inclusion"
        elif inclusion.snapshot.get("progression_strategy_type") != "step":
            skipped_reason = "not_step_strategy"
        else:
            matched = _match_step_blocks(inclusion, blocks)
            if matched is None:
                skipped_reason = "blocks_do_not_match_step_roles"
            else:
                block_a_sets, block_b_sets = matched
                new_state, progression_result = _apply_step_progression(
                    inclusion.progression_state, performed_at=performed_at,
                    block_a_sets=block_a_sets, block_b_sets=block_b_sets,
                )
                await self._plans.update_progression_state(inclusion.id, new_state)

        return RecordSessionResult(
            session=session_detail, progression_result=progression_result, progression_skipped_reason=skipped_reason,
        ), False
