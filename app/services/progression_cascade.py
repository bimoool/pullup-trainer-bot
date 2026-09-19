"""app.services.progression_cascade — правка исторической сессии в рамках
STEP-прогрессии (issue #165, продолжение волны 3, раздел 10.6
docs/plan-and-specs.md "Редактирование сессии из плана"): preview/apply
пересчитывают ВСЮ цепочку STEP-сессий заново от
ProgramInclusion.initial_progression_state (неизменяемый снимок на момент
подключения курса, см. докстринг поля в app.db.models_program) — не только
"эту и последующие". Правка более ранней сессии в цепочке меняет РЕЗУЛЬТАТ
пересчёта каждой последующей, поэтому у цепочки нет безопасной "точки
старта" ближе, чем самое начало.

Реализация переиспользует app.services.session_log._apply_step_progression
буквально, ЦИКЛОМ по сессиям цепочки (не второй, параллельный расчёт через
StepProgressionStrategy().apply() с многоэлементным subsequent_workouts) —
это математически ТО ЖЕ САМОЕ: app.domain.progression.recalculate_cascade
делает внутри ровно такой же fold по цепочке (state -> state на каждой
записи по порядку), и вызов _apply_step_progression N раз подряд с
передачей state дальше эквивалентен одному вызову с N-элементным списком.
Через это НЕ заводится вторая копия сборки/распаковки progression_state,
которую _apply_step_progression уже делает для одиночной сессии (issue
#165, критерий "не пиши второй, отдельный путь")."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import ProgramInclusion
from app.db.repositories.training_plans import TrainingPlanRepository
from app.db.repositories.training_sessions import (
    SessionDetail,
    SetLogInput,
    TrainingSessionRepository,
)
from app.domain.progression_strategy import ProgressionStrategyType
from app.services.session_log import (
    _ROLE_BLOCK_A,
    _ROLE_BLOCK_B,
    _apply_step_progression,
    _match_step_blocks,
    _session_block_input_from_detail,
)

_NOT_STEP_STRATEGY = "not_step_strategy"


@dataclass(frozen=True)
class PlanItemDelta:
    plan_item_id: int | None
    exercise: str  # "block_a"/"block_b" — та же конвенция ролей, что _ROLE_BLOCK_A/_ROLE_BLOCK_B
    before: int
    after: int


def _matched_sets_for_session(
    inclusion: ProgramInclusion, session_detail: SessionDetail,
) -> tuple[list[SetLogInput], list[SetLogInput]] | None:
    blocks = [_session_block_input_from_detail(b) for b in session_detail.blocks]
    return _match_step_blocks(inclusion, blocks)


def _block_id_by_role_for_session(
    inclusion: ProgramInclusion, session_detail: SessionDetail,
) -> dict[str, int] | None:
    """role -> SessionBlock.id ДЛЯ ОДНОЙ сессии — нужен только apply(),
    чтобы адресовать конкретный SessionBlock при перезаписи SetLog.
    Вызывается ПОСЛЕ того, как _matched_sets_for_session уже подтвердила
    полное совпадение (ровно 2 блока, обе роли, метрика reps) — здесь не
    повторяется эта проверка, только берутся id блоков по тому же снимку
    ролей."""
    role_by_exercise_id = {item["exercise_id"]: item["role"] for item in inclusion.snapshot.get("exercises", [])}
    result: dict[str, int] = {}
    for block in session_detail.blocks:
        role = role_by_exercise_id.get(block.exercise_id)
        if role is not None:
            result[role] = block.id
    if _ROLE_BLOCK_A not in result or _ROLE_BLOCK_B not in result:
        return None
    return result


def _replay_progression_state(
    inclusion: ProgramInclusion, sessions: list[SessionDetail], *,
    edited_session_id: int | None, edited_block_a_sets: list[SetLogInput] | None,
    edited_block_b_sets: list[SetLogInput] | None,
) -> dict:
    """Реплей ВСЕЙ цепочки от initial_progression_state (см. докстринг
    модуля про эквивалентность recalculate_cascade). edited_session_id=None
    (оба edited_*_sets тоже None) — реплей БЕЗ подстановки, используется
    как "текущее" состояние для сравнения — должно совпасть с живым
    inclusion.progression_state, если цепочка sessions полная и реплей
    корректный (это же свойство доказывают tests/test_web/
    test_v2_progression_cascade.py: preview без правок -> пустой diff)."""
    state = inclusion.initial_progression_state
    for session_detail in sessions:
        matched = _matched_sets_for_session(inclusion, session_detail)
        if matched is None:
            continue
        block_a_sets, block_b_sets = matched
        if session_detail.id == edited_session_id:
            if edited_block_a_sets is not None:
                block_a_sets = edited_block_a_sets
            if edited_block_b_sets is not None:
                block_b_sets = edited_block_b_sets
        state, _progression_result = _apply_step_progression(
            state, performed_at=session_detail.performed_at,
            block_a_sets=block_a_sets, block_b_sets=block_b_sets,
        )
    return state


def _diff_deltas(
    before_state: dict, after_state: dict, plan_item_id_by_role: dict[str, int],
) -> list[PlanItemDelta]:
    deltas = []
    for role in (_ROLE_BLOCK_A, _ROLE_BLOCK_B):
        before_target = before_state[role]["target"]
        after_target = after_state[role]["target"]
        if before_target != after_target:
            deltas.append(
                PlanItemDelta(
                    plan_item_id=plan_item_id_by_role.get(role), exercise=role,
                    before=before_target, after=after_target,
                ),
            )
    return deltas


class ProgressionCascadeService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._sessions = TrainingSessionRepository(session)
        self._plans = TrainingPlanRepository(session)

    async def _resolve_context(
        self, *, inclusion_id: int, user_id: int, edited_session_id: int,
    ) -> tuple[ProgramInclusion, list[SessionDetail]] | str | None:
        """(inclusion, sessions) при успехе; "not_step_strategy" — инклюзия
        существует, но каскад к ней неприменим (роут -> 422); None — любая
        причина "не найдено/не принадлежит" (инклюзия, отредактированная
        сессия, или сессия не входит в цепочку этой инклюзии — роут -> 404,
        см. preview()/apply())."""
        inclusion = await self._plans.get_inclusion_for_user(inclusion_id, user_id)
        if inclusion is None:
            return None
        if inclusion.snapshot.get("progression_strategy_type") != ProgressionStrategyType.STEP.value:
            return _NOT_STEP_STRATEGY

        edited_session = await self._sessions.get_for_user(edited_session_id, user_id)
        if edited_session is None:
            return None

        role_exercise_ids = [item["exercise_id"] for item in inclusion.snapshot.get("exercises", [])]
        sessions = await self._sessions.list_for_user_by_exercise_ids(user_id, role_exercise_ids)
        if not any(s.id == edited_session_id for s in sessions):
            return None
        return inclusion, sessions

    async def _plan_item_id_by_role(self, inclusion: ProgramInclusion) -> dict[str, int]:
        role_by_exercise_id = {item["exercise_id"]: item["role"] for item in inclusion.snapshot.get("exercises", [])}
        plan_items = await self._plans.list_plan_items(
            inclusion.training_plan_id, program_inclusion_id=inclusion.id,
        )
        result: dict[str, int] = {}
        for plan_item in plan_items:
            role = role_by_exercise_id.get(plan_item.exercise_id)
            if role is not None:
                result[role] = plan_item.id
        return result

    async def preview(
        self, *, inclusion_id: int, user_id: int, edited_session_id: int,
        edited_block_a_sets: list[SetLogInput] | None, edited_block_b_sets: list[SetLogInput] | None,
    ) -> tuple[list[PlanItemDelta] | None, bool]:
        """Второй элемент — True, если каскад НЕприменим (не STEP-стратегия,
        роут -> 422); (None, False) — 404; иначе (возможно пустой) список
        дельт, 200. Пустой список — валидный ответ ("Оставить как есть"
        может быть буквальным no-op), не ошибка."""
        context = await self._resolve_context(
            inclusion_id=inclusion_id, user_id=user_id, edited_session_id=edited_session_id,
        )
        if context is None:
            return None, False
        if context == _NOT_STEP_STRATEGY:
            return None, True
        inclusion, sessions = context

        before_state = _replay_progression_state(
            inclusion, sessions, edited_session_id=None, edited_block_a_sets=None, edited_block_b_sets=None,
        )
        after_state = _replay_progression_state(
            inclusion, sessions, edited_session_id=edited_session_id,
            edited_block_a_sets=edited_block_a_sets, edited_block_b_sets=edited_block_b_sets,
        )
        plan_item_id_by_role = await self._plan_item_id_by_role(inclusion)
        return _diff_deltas(before_state, after_state, plan_item_id_by_role), False

    async def apply(
        self, *, inclusion_id: int, user_id: int, edited_session_id: int,
        edited_block_a_sets: list[SetLogInput] | None, edited_block_b_sets: list[SetLogInput] | None,
    ) -> tuple[list[PlanItemDelta] | None, bool]:
        """Тот же расчёт, что preview(), плюс персистенция: переписывает
        SetLog отредактированной сессии новыми значениями и сохраняет
        РЕПЛЕЙНУТОЕ (не "текущее плюс диф") состояние как новый
        progression_state инклюзии — реплей уже учитывает всю цепочку, а
        не только эту одну правку."""
        context = await self._resolve_context(
            inclusion_id=inclusion_id, user_id=user_id, edited_session_id=edited_session_id,
        )
        if context is None:
            return None, False
        if context == _NOT_STEP_STRATEGY:
            return None, True
        inclusion, sessions = context

        before_state = _replay_progression_state(
            inclusion, sessions, edited_session_id=None, edited_block_a_sets=None, edited_block_b_sets=None,
        )
        after_state = _replay_progression_state(
            inclusion, sessions, edited_session_id=edited_session_id,
            edited_block_a_sets=edited_block_a_sets, edited_block_b_sets=edited_block_b_sets,
        )
        plan_item_id_by_role = await self._plan_item_id_by_role(inclusion)
        deltas = _diff_deltas(before_state, after_state, plan_item_id_by_role)

        if edited_block_a_sets is not None or edited_block_b_sets is not None:
            edited_session = next(s for s in sessions if s.id == edited_session_id)
            matched = _matched_sets_for_session(inclusion, edited_session)
            block_id_by_role = _block_id_by_role_for_session(inclusion, edited_session)
            if matched is not None and block_id_by_role is not None:
                current_block_a_sets, current_block_b_sets = matched
                new_block_a_sets = edited_block_a_sets if edited_block_a_sets is not None else current_block_a_sets
                new_block_b_sets = edited_block_b_sets if edited_block_b_sets is not None else current_block_b_sets
                await self._sessions.update_set_logs_for_blocks(
                    session_block_ids_with_sets=[
                        (block_id_by_role[_ROLE_BLOCK_A], new_block_a_sets),
                        (block_id_by_role[_ROLE_BLOCK_B], new_block_b_sets),
                    ],
                )

        await self._plans.update_progression_state(inclusion.id, after_state)
        return deltas, False
