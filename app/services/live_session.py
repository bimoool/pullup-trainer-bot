"""Оркестрация server-driven живой сессии (issue #165, продолжение волны 3
— "сессия — live", разделы 10.7-10.9/11/12 docs/plan-and-specs.md):
POST /sessions/live (старт) + /phase/next (переход фазы) + /sets:batch
(офлайн-батч подходов) + /complete (завершение + опциональная прогрессия)
+ GET /sessions/live/active (баннер незавершённой сессии).

Правила из офлайн-контракта (раздел 12), выдержанные буквально:
- старт идемпотентен по client_session_id — повторный POST /sessions/live
  с уже виденным UUID возвращает СУЩЕСТВУЮЩУЮ сессию, не создаёт вторую;
- переход фазы НИКОГДА не ошибка по рассинхрону индекса — сервер либо
  переходит (совпадение), либо молча возвращает текущее состояние (клиент
  отстал или прислал будущий индекс), всегда 200;
- батч подходов идемпотентен по (session_id, set_index) — см.
  TrainingSessionRepository.upsert_set_logs_batch.

Резолв блоков/целей при старте — три пути (комплекс / STEP-роль / общий
случай без источника целей) реализованы буквально по плану задачи, включая
намеренно НЕзакрытый последний путь (см. _resolve_plain_exercise_block)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import PlanItem, ProgramInclusion, SessionPhase, SessionStatus
from app.db.repositories.programs import ProgramRepository
from app.db.repositories.training_plans import TrainingPlanRepository
from app.db.repositories.training_sessions import (
    BatchSetLogInput,
    SessionBlockInput,
    SessionDetail,
    SetTargetInput,
    TrainingSessionRepository,
)
from app.domain.live_session import (
    DEFAULT_UNIT_BY_METRIC_TYPE,
    BlockPlan,
    PhaseState,
    SessionPhaseName,
    initial_phase,
    next_phase,
)
from app.domain.multi_program import MetricType, SessionSource
from app.domain.progression_strategy import ProgressionStrategyType
from app.services.session_log import (
    SessionProgressionResult,
    _apply_step_progression,
    _match_step_blocks,
    _session_block_input_from_detail,
)


@dataclass(frozen=True)
class LiveSessionResult:
    session: SessionDetail


@dataclass(frozen=True)
class CompleteResult:
    session: SessionDetail
    progression_result: SessionProgressionResult | None
    progression_skipped_reason: str | None


def _db_phase(name: SessionPhaseName) -> SessionPhase:
    """Явная конвертация domain SessionPhaseName -> db SessionPhase (те же
    4 значения, но домен не импортирует app.db, см. докстринг
    app.domain.live_session) — единственное место сервисного слоя, где эти
    два enum'а встречаются друг с другом."""
    return SessionPhase(name.value)


def _domain_phase(name: SessionPhase) -> SessionPhaseName:
    return SessionPhaseName(name.value)


def _phase_ends_at_from_offset(offset_seconds: int | None) -> datetime | None:
    if offset_seconds is None:
        return None
    return datetime.now(UTC) + timedelta(seconds=offset_seconds)


class LiveSessionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._sessions = TrainingSessionRepository(session)
        self._plans = TrainingPlanRepository(session)
        self._programs = ProgramRepository(session)

    # --- Старт -----------------------------------------------------------

    async def start_session(
        self, *, user_id: int, client_session_id: uuid.UUID, plan_item_ids: list[int],
    ) -> LiveSessionResult | None:
        existing = await self._sessions.get_by_client_session_id(user_id, client_session_id)
        if existing is not None:
            return await self._build_result(existing.id, user_id)

        plan = await self._plans.get_for_user(user_id)
        if plan is None:
            return None

        resolved_blocks: list[SessionBlockInput] = []
        resolved_targets: list[list[SetTargetInput]] = []
        for plan_item_id in plan_item_ids:
            plan_item = await self._plans.get_plan_item_for_user(plan_item_id, user_id)
            if plan_item is None or plan_item.training_plan_id != plan.id:
                return None
            blocks, targets = await self._resolve_blocks_for_plan_item(plan_item)
            resolved_blocks.extend(blocks)
            resolved_targets.extend(targets)

        block_plans = [BlockPlan(sets_count=len(targets)) for targets in resolved_targets]
        phase_state = initial_phase(block_plans)
        phase_ends_at = _phase_ends_at_from_offset(phase_state.ends_at_offset_seconds)

        training_session = await self._sessions.create_live_session(
            user_id=user_id, client_session_id=client_session_id, source=SessionSource.PLAN,
            performed_at=datetime.now(UTC), plan_item_ids=plan_item_ids,
            blocks=resolved_blocks, targets_by_block=resolved_targets, phase_ends_at=phase_ends_at,
        )
        return await self._build_result(training_session.id, user_id)

    async def _resolve_blocks_for_plan_item(
        self, plan_item: PlanItem,
    ) -> tuple[list[SessionBlockInput], list[list[SetTargetInput]]]:
        if plan_item.complex_id is not None:
            return await self._resolve_complex_blocks(plan_item.complex_id)
        return await self._resolve_exercise_block(plan_item)

    async def _resolve_complex_blocks(
        self, complex_id: int,
    ) -> tuple[list[SessionBlockInput], list[list[SetTargetInput]]]:
        """Один SessionBlock на каждый ComplexItem, по order_index —
        target_value/target_unit NULL у ComplexItem (оба поля опциональны
        в схеме) падают на тот же fallback, что и в
        _resolve_plain_exercise_block ниже (значение 0 / дефолтная единица
        по metric_type), не на отдельную вторую заглушку."""
        items = await self._programs.list_complex_items(complex_id)
        blocks: list[SessionBlockInput] = []
        targets_by_block: list[list[SetTargetInput]] = []
        for item in items:
            exercise = await self._programs.get_exercise(item.exercise_id)
            metric_type = exercise.metric_type
            value = item.target_value if item.target_value is not None else Decimal(0)
            unit = item.target_unit if item.target_unit is not None else DEFAULT_UNIT_BY_METRIC_TYPE[metric_type]
            blocks.append(SessionBlockInput(exercise_id=item.exercise_id, sets=[]))
            targets_by_block.append([
                SetTargetInput(set_number=i + 1, metric_type=metric_type, value=value, unit=unit)
                for i in range(item.sets)
            ])
        return blocks, targets_by_block

    async def _resolve_exercise_block(
        self, plan_item: PlanItem,
    ) -> tuple[list[SessionBlockInput], list[list[SetTargetInput]]]:
        step_match = await self._find_step_role_for_exercise(plan_item.training_plan_id, plan_item.exercise_id)
        if step_match is not None:
            return self._resolve_step_role_block(plan_item.exercise_id, *step_match)
        return await self._resolve_plain_exercise_block(plan_item.exercise_id)

    async def _find_step_role_for_exercise(
        self, training_plan_id: int, exercise_id: int,
    ) -> tuple[ProgramInclusion, str] | None:
        """Та же конвенция, что app.services.session_log::_match_step_blocks
        — роль ищется в СНИМКЕ инклюзии (snapshot["exercises"]), не через
        повторный ProgramRepository.find_step_role_exercises(category=...):
        snapshot уже несёт role/exercise_id ровно в том виде, в котором его
        построил ProgramInclusionService при создании инклюзии — второй,
        параллельный способ узнать роль дал бы два источника истины вместо
        одного (см. CLAUDE.md про "не пиши второй, отдельный путь")."""
        inclusions = await self._plans.list_inclusions(training_plan_id)
        for inclusion in inclusions:
            if not inclusion.is_active:
                continue
            role_by_exercise_id = {
                item["exercise_id"]: item["role"] for item in inclusion.snapshot.get("exercises", [])
            }
            role = role_by_exercise_id.get(exercise_id)
            if role is not None:
                return inclusion, role
        return None

    def _resolve_step_role_block(
        self, exercise_id: int, inclusion: ProgramInclusion, role: str,
    ) -> tuple[list[SessionBlockInput], list[list[SetTargetInput]]]:
        """sets_count — progression_state[role]["work_sets"], если есть
        (блок A — объёмный, растущее число рабочих подходов, см.
        app.services.session_log._apply_step_progression), иначе 1 (блок Б
        — силовой, число подходов у него в этой волне не выведено в
        progression_state отдельным полем, см. план задачи: "default 1 if
        role is block_b" — намеренное упрощение, не забытое поле)."""
        role_state = inclusion.progression_state[role]
        sets_count = role_state.get("work_sets", 1)
        target = Decimal(role_state["target"])
        block = SessionBlockInput(exercise_id=exercise_id, sets=[])
        targets = [
            SetTargetInput(set_number=i + 1, metric_type=MetricType.REPS, value=target, unit="reps")
            for i in range(sets_count)
        ]
        return [block], [targets]

    async def _resolve_plain_exercise_block(
        self, exercise_id: int,
    ) -> tuple[list[SessionBlockInput], list[list[SetTargetInput]]]:
        """Известный, осознанно не закрытый пробел схемы (план задачи,
        раздел резолва целей): обычное упражнение — не комплекс, не
        step-роль — не имеет в текущей схеме источника числа подходов/цели
        сессии (ни ComplexItem, ни progression_state). 3 подхода со
        значением 0 — заглушка, задокументированная явно, а не тихая
        придумка; не используется E2E-фикстурами этой волны (только
        комплекс/step-роль путь), НЕ дорабатывается здесь дальше запроса
        задачи ("over-engineering now is out of scope")."""
        exercise = await self._programs.get_exercise(exercise_id)
        metric_type = exercise.metric_type
        unit = DEFAULT_UNIT_BY_METRIC_TYPE[metric_type]
        block = SessionBlockInput(exercise_id=exercise_id, sets=[])
        targets = [
            SetTargetInput(set_number=i + 1, metric_type=metric_type, value=Decimal(0), unit=unit)
            for i in range(3)
        ]
        return [block], [targets]

    # --- Переход фазы ------------------------------------------------------

    async def advance_phase(
        self, *, session_id: int, user_id: int, expected_phase_index: int,
    ) -> LiveSessionResult | None:
        detail = await self._sessions.get_for_user(session_id, user_id)
        if detail is None or detail.status != SessionStatus.STARTED:
            return None

        if expected_phase_index == detail.phase_index:
            blocks = [BlockPlan(sets_count=len(block.set_targets)) for block in detail.blocks]
            current = PhaseState(
                phase_name=_domain_phase(detail.phase_name), block_index=detail.current_block_index,
                set_number=detail.current_set_number, ends_at_offset_seconds=None,
            )
            new_state = next_phase(current, blocks)
            await self._sessions.advance_phase(
                session_id, phase_name=_db_phase(new_state.phase_name),
                phase_ends_at=_phase_ends_at_from_offset(new_state.ends_at_offset_seconds),
                current_block_index=new_state.block_index, current_set_number=new_state.set_number,
                phase_index=detail.phase_index + 1,
            )
        # expected_phase_index != detail.phase_index (клиент отстал или
        # прислал индекс из будущего) — НЕ переход, просто отдаём текущее
        # состояние как есть (офлайн-контракт: никогда не 409, никогда откат).
        return await self._build_result(session_id, user_id)

    # --- Батч подходов -------------------------------------------------------

    async def batch_sets(
        self, *, session_id: int, user_id: int, entries: list[BatchSetLogInput],
    ) -> LiveSessionResult | None:
        detail = await self._sessions.get_for_user(session_id, user_id)
        if detail is None:
            return None
        # upsert_set_logs_batch может поднять ValueError (exercise_id не
        # найден среди блоков сессии) — намеренно не ловим здесь, роут
        # превращает её в 404 (см. докстринг репозитория/план задачи).
        await self._sessions.upsert_set_logs_batch(session_id, entries)
        return await self._build_result(session_id, user_id)

    # --- Активная сессия ------------------------------------------------------

    async def get_active(self, *, user_id: int) -> LiveSessionResult | None:
        training_session = await self._sessions.get_active_for_user(user_id)
        if training_session is None:
            return None
        return await self._build_result(training_session.id, user_id)

    # --- Завершение -------------------------------------------------------

    async def complete_session(
        self, *, session_id: int, user_id: int, abandoned: bool,
    ) -> tuple[CompleteResult | None, bool]:
        """Второй элемент — True, если сессия не найдена/не принадлежит
        пользователю (роут превращает в 404) — тот же (result, not_found)
        приём, что TrainingSessionLogService.record_session уже использует
        для program_inclusion_id (app.services.session_log)."""
        detail = await self._sessions.get_for_user(session_id, user_id)
        if detail is None:
            return None, True

        await self._sessions.mark_completed(session_id)

        progression_result: SessionProgressionResult | None = None
        skipped_reason: str | None = None
        if abandoned:
            skipped_reason = "abandoned"
        else:
            inclusion = await self._find_step_inclusion_for_session(detail, user_id)
            if inclusion is None:
                skipped_reason = "no_program_inclusion"
            else:
                matched = _match_step_blocks(inclusion, [_session_block_input_from_detail(b) for b in detail.blocks])
                if matched is None:
                    skipped_reason = "blocks_do_not_match_step_roles"
                else:
                    block_a_sets, block_b_sets = matched
                    new_state, progression_result = _apply_step_progression(
                        inclusion.progression_state, performed_at=detail.performed_at,
                        block_a_sets=block_a_sets, block_b_sets=block_b_sets,
                    )
                    await self._plans.update_progression_state(inclusion.id, new_state)

        final_detail = await self._sessions.get_for_user(session_id, user_id)
        return (
            CompleteResult(
                session=final_detail, progression_result=progression_result,
                progression_skipped_reason=skipped_reason,
            ),
            False,
        )

    async def _find_step_inclusion_for_session(
        self, detail: SessionDetail, user_id: int,
    ) -> ProgramInclusion | None:
        plan = await self._plans.get_for_user(user_id)
        if plan is None:
            return None
        inclusions = await self._plans.list_inclusions(plan.id)
        session_blocks = [_session_block_input_from_detail(b) for b in detail.blocks]
        for inclusion in inclusions:
            if not inclusion.is_active:
                continue
            if inclusion.snapshot.get("progression_strategy_type") != ProgressionStrategyType.STEP.value:
                continue
            if _match_step_blocks(inclusion, session_blocks) is not None:
                return inclusion
        return None

    # --- Общий сбор результата ---------------------------------------------

    async def _build_result(self, session_id: int, user_id: int) -> LiveSessionResult | None:
        detail = await self._sessions.get_for_user(session_id, user_id)
        if detail is None:
            return None
        return LiveSessionResult(session=detail)
