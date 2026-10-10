import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import ProgramInclusion
from app.db.repositories.training_plans import TrainingPlanRepository
from app.db.repositories.training_sessions import (
    SessionBlockDetail,
    SessionBlockInput,
    SessionDetail,
    SetLogInput,
    SetTargetInput,
    TrainingSessionRepository,
)
from app.domain.course_prescription import advance_step_progression
from app.domain.multi_program import MetricType, SessionSource
from app.domain.training_session_v2 import SetStatus

# Роли блока А/Б курса — та же конвенция snapshot
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


def _session_block_input_from_detail(block: SessionBlockDetail) -> SessionBlockInput:
    """Обратное преобразование SessionBlockDetail (то, что вернул
    репозиторий при чтении) -> SessionBlockInput (то, что принимают
    _match_step_blocks/create_session) — общий хелпер для
    app.services.live_session (завершение живой сессии) и
    app.services.progression_cascade (реплей истории при правке), обоим
    нужно скормить УЖЕ ЗАГРУЖЕННУЮ сессию в _match_step_blocks, не только
    свежесобранный запрос."""
    return SessionBlockInput(
        exercise_id=block.exercise_id, complex_id=block.complex_id,
        sets=[
            SetLogInput(
                set_number=log.set_number, metric_type=log.metric_type, value=log.value, unit=log.unit,
                is_max_set=log.is_max_set, effort=log.effort, note=log.note,
            )
            for log in block.set_logs
            # issue #264: подходы сверх плана не участвуют в прогрессии; #305: невыполненный подход
            # (#307 not_performed) — не замер.
            if not log.is_extra and log.status == SetStatus.PERFORMED.value
        ],
    )


def _max_measurement(sets: list[SetLogInput]) -> int | None:
    """Замер цикла — выполненный плановый подход на максимум блока (``is_max_set`` наследуется у цели,
    #305 D3). Нет такого подхода — замера нет (None), роль в этой сессии не двигается. Рабочие подходы
    сюда не попадают ни в каком виде (решение владельца: прогрессию двигает только подход на максимум)."""
    max_set = next((s for s in sets if s.is_max_set), None)
    return int(max_set.value) if max_set is not None else None


def _apply_step_progression(
    progression_state: dict, *, performed_at: datetime, block_a_sets: list[SetLogInput], block_b_sets: list[SetLogInput],
) -> tuple[dict, SessionProgressionResult]:
    """Единственная точка, где путь v2 применяет прогрессию курса (POST /sessions, завершение живой
    сессии, явный каскад /progression/apply). Решение владельца (#305): шаг прогрессии считается
    ТОЛЬКО по явному подходу на максимум этой сессии — ``advance_step_progression``
    (app/domain/course_prescription.py). Значения рабочих подходов, их промахи и объём на состояние не
    влияют (прежний ``weak_streak`` по объёму рабочих подходов снят: теперь это подряд идущие промахи
    замера). Только вперёд: читается текущее состояние и замер этой сессии, история не пересчитывается.
    ``performed_at`` в расчёт не входит (оставлен в сигнатуре для вызывающих)."""
    del performed_at
    new_state, advance_a, advance_b = advance_step_progression(
        progression_state, max_a=_max_measurement(block_a_sets), max_b=_max_measurement(block_b_sets),
    )
    progression_result = SessionProgressionResult(
        block_a=BlockProgressionResult(
            target_before=advance_a.target_before, target_after=advance_a.target_after,
            equipment_changed=advance_a.equipment_changed,
        ),
        block_b=BlockProgressionResult(
            target_before=advance_b.target_before, target_after=advance_b.target_after,
            equipment_changed=advance_b.equipment_changed,
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
    ProgramInclusion.progression_state через advance_step_progression (#305) —
    единственное место волны 3, где новый код касается пересчёта
    прогрессии."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._sessions = TrainingSessionRepository(session)
        self._plans = TrainingPlanRepository(session)

    async def record_session(
        self, *, user_id: int, source: SessionSource, performed_at: datetime,
        effort: Decimal | None, comment: str | None, blocks: list[SessionBlockInput],
        program_inclusion_id: int | None, completed_at: datetime | None = None,
        activity_type: str | None = None, duration_seconds: int | None = None,
        targets_by_block: list[list[SetTargetInput]] | None = None, workout_snapshot: dict | None = None,
        client_session_id: uuid.UUID | None = None,
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
            effort=effort, comment=comment, blocks=blocks, completed_at=completed_at,
            activity_type=activity_type, duration_seconds=duration_seconds, targets_by_block=targets_by_block,
            workout_snapshot=workout_snapshot, client_session_id=client_session_id,
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
