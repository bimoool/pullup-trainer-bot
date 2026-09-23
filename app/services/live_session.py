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

from pydantic import TypeAdapter
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
from app.domain.interval_timing import (
    IntervalPhase,
    calculate_completed_cycles,
    compute_interval_timing,
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
from app.domain.workout_protocol import DefinitionProtocol, ProtocolType, ResolvedInterval
from app.domain.workout_snapshot import WorkoutSnapshot, build_workout_snapshot
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
        workout_snapshot: dict | None = None
        for plan_item_id in plan_item_ids:
            plan_item = await self._plans.get_plan_item_for_user(plan_item_id, user_id)
            if plan_item is None or plan_item.training_plan_id != plan.id:
                return None
            blocks, targets, snapshot = await self._resolve_blocks_for_plan_item(plan_item)
            resolved_blocks.extend(blocks)
            resolved_targets.extend(targets)
            # Phase B1 (issue #215): workout_snapshot только для interval workouts
            # (один на всю сессию, не несколько), не для standard STEP/manual path.
            if snapshot is not None:
                workout_snapshot = snapshot

        block_plans = [BlockPlan(sets_count=len(targets)) for targets in resolved_targets]
        phase_state = initial_phase(block_plans)
        phase_ends_at = _phase_ends_at_from_offset(phase_state.ends_at_offset_seconds)

        training_session = await self._sessions.create_live_session(
            user_id=user_id, client_session_id=client_session_id, source=SessionSource.PLAN,
            performed_at=datetime.now(UTC), plan_item_ids=plan_item_ids,
            blocks=resolved_blocks, targets_by_block=resolved_targets, phase_ends_at=phase_ends_at,
            workout_snapshot=workout_snapshot,
        )
        return await self._build_result(training_session.id, user_id)

    async def _resolve_blocks_for_plan_item(
        self, plan_item: PlanItem,
    ) -> tuple[list[SessionBlockInput], list[list[SetTargetInput]], dict | None]:
        """Резолвит блоки/targets/snapshot для одного PlanItem. Третий элемент
        (workout_snapshot) — только для interval workouts (Phase B1), None для
        standard STEP/manual path."""
        if plan_item.complex_id is not None:
            return await self._resolve_complex_blocks(plan_item.complex_id)
        blocks, targets = await self._resolve_exercise_block(plan_item)
        return blocks, targets, None  # exercise path никогда не interval

    async def _resolve_complex_blocks(
        self, complex_id: int,
    ) -> tuple[list[SessionBlockInput], list[list[SetTargetInput]], dict | None]:
        """Один SessionBlock на каждый ComplexItem, по order_index —
        target_value/target_unit NULL у ComplexItem (оба поля опциональны
        в схеме) падают на тот же fallback, что и в
        _resolve_plain_exercise_block ниже (значение 0 / дефолтная единица
        по metric_type), не на отдельную вторую заглушку.

        Phase B1 (issue #215): если хотя бы один ComplexItem.protocol.type ==
        "interval", создаёт workout_snapshot (build_workout_snapshot) и для
        interval-блоков возвращает НОЛЬ SetTarget (interval execution path —
        server-authoritative timing, не targets). Standard path (STEP/manual,
        без protocol) — старое поведение, snapshot=None."""
        items = await self._programs.list_complex_items(complex_id)

        # Проверка: есть ли хотя бы один interval protocol
        has_interval = False
        protocols: dict[int, DefinitionProtocol] = {}
        for item in items:
            if item.protocol is not None:
                protocol = TypeAdapter(DefinitionProtocol).validate_python(item.protocol)
                protocols[item.id] = protocol
                if protocol.type == ProtocolType.INTERVAL:
                    has_interval = True

        blocks: list[SessionBlockInput] = []
        targets_by_block: list[list[SetTargetInput]] = []

        for item in items:
            exercise = await self._programs.get_exercise(item.exercise_id)
            protocol = protocols.get(item.id)

            # Interval block — ноль targets (timing-driven execution)
            if protocol is not None and protocol.type == ProtocolType.INTERVAL:
                blocks.append(SessionBlockInput(exercise_id=item.exercise_id, sets=[]))
                targets_by_block.append([])  # пустой список targets
            else:
                # Standard path — старая логика
                metric_type = exercise.metric_type
                value = item.target_value if item.target_value is not None else Decimal(0)
                unit = item.target_unit if item.target_unit is not None else DEFAULT_UNIT_BY_METRIC_TYPE[metric_type]
                blocks.append(SessionBlockInput(exercise_id=item.exercise_id, sets=[]))
                targets_by_block.append([
                    SetTargetInput(set_number=i + 1, metric_type=metric_type, value=value, unit=unit)
                    for i in range(item.sets)
                ])

        # Создание snapshot только если есть interval
        snapshot_dict: dict | None = None
        if has_interval:
            complex = await self._programs.get_complex(complex_id)
            exercises = {item.exercise_id: await self._programs.get_exercise(item.exercise_id) for item in items}
            snapshot = build_workout_snapshot(
                workout=complex, items=items, exercises=exercises, protocols=protocols,
                progression_resolver=None,  # interval не использует progression
            )
            snapshot_dict = snapshot.model_dump()

        return blocks, targets_by_block, snapshot_dict

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
        # Phase B1 (issue #215, раздел 5) — lazy finalization для expired
        # interval сессий. Если финализация только что завершила её
        # (status стал COMPLETED), эндпоинт НЕ должен отдавать её как
        # "активную" — /sessions/live/active семантически означает "есть,
        # что продолжить", не "существует какая-то сессия". Перечитываем
        # статус после финализации и возвращаем None, если сессия больше
        # не STARTED — фронт идёт в Summary/Journal обычным путём, не
        # получает ложное "resume" состояние.
        await self.finalize_expired_interval_if_needed(training_session.id, user_id)
        result = await self._build_result(training_session.id, user_id)
        if result is not None and result.session.status != SessionStatus.STARTED:
            return None
        return result

    def _interval_result_dict(
        self, protocol: ResolvedInterval, execution_started_at: datetime, total_end_at: datetime, now: datetime,
        *, is_deadline_completion: bool,
    ) -> dict:
        """Общий helper (issue #215, gate fix). Два разных случая, разная
        семантика completed_at/actual_duration_seconds — НЕ угадывается из
        `now` относительно `total_end_at` (это и было корнем бага: min(now,
        total_end_at) зависел от того, успел ли HTTP-запрос дойти до
        сервера строго до/после дедлайна — сетевой/event-loop джиттер в
        доли секунды мог дать elapsed=8.97 вместо ровно 9.0, round()
        занижал секунду).

        is_deadline_completion=True (нормальное автозавершение — lazy
        finalizer, вызывается ТОЛЬКО когда timing.phase уже DONE, то есть
        now>=total_end_at уже гарантирован этим условием на call site; или
        complete_session с abandoned=False — единственный вызывающий это
        IntervalLiveScreen.tsx's deadline-эффект, срабатывающий только
        когда клиент уже считает phase='done'): completed_at/
        actual_duration_seconds — ВСЕГДА ровно total_end_at/
        planned_duration_seconds, детерминированно, независимо от
        фактического now.

        is_deadline_completion=False (ручное раннее прерывание —
        complete_session с abandoned=True, IntervalLiveScreen.tsx's
        BackButton): completed_at=now (реальный факт, тренировка правда
        закончилась раньше, actual_duration_seconds честно меньше
        planned)."""
        if is_deadline_completion:
            completed_at = total_end_at
            elapsed_seconds = protocol.total_duration_seconds
        else:
            completed_at = min(now, total_end_at)
            elapsed_seconds = (completed_at - execution_started_at).total_seconds()
        completed_cycles = calculate_completed_cycles(
            elapsed_seconds=elapsed_seconds, total_duration_seconds=protocol.total_duration_seconds,
            work_seconds=protocol.work_seconds, rest_seconds=protocol.rest_seconds,
        )
        return {
            "type": "interval",
            "started_at": execution_started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "planned_duration_seconds": protocol.total_duration_seconds,
            "actual_duration_seconds": round(elapsed_seconds),
            "completed_cycles": completed_cycles,
        }

    async def _parse_interval_blocks(self, detail: SessionDetail) -> list[tuple[int, ResolvedInterval]]:
        """Общая часть snapshot-парсинга для finalize_expired_interval_if_needed
        и complete_session — не дублировать между ними."""
        if detail.workout_snapshot is None:
            return []
        snapshot = TypeAdapter(WorkoutSnapshot).validate_python(detail.workout_snapshot)
        return [
            (block_detail.id, item_snapshot.protocol)
            for block_detail, item_snapshot in zip(detail.blocks, snapshot.items, strict=False)
            if item_snapshot.protocol.type == ProtocolType.INTERVAL
        ]

    async def finalize_expired_interval_if_needed(self, session_id: int, user_id: int) -> None:
        """Lazy completion для expired interval workouts (Phase B1, issue #215).
        Идемпотентен — повторный вызов безопасен (mark_completed уже
        идемпотентен по конструкции, см. app.services.live_session.py:277).

        Минимум два call site (по контракту Phase B1):
        1. GET /sessions/live/active (recovery path)
        2. Путь листинга сессий (если пользователь открывает Журнал без захода
           в Live, expired interval должен материализоваться и там).

        Не копирует finalization-логику между call sites — один helper,
        несколько вызовов."""
        detail = await self._sessions.get_for_user(session_id, user_id)
        if detail is None or detail.status != SessionStatus.STARTED:
            return

        interval_blocks = await self._parse_interval_blocks(detail)
        if not interval_blocks:
            return  # нет interval блоков — standard STEP/manual путь или не найдено

        # Проверка: expired? Один вызов compute_interval_timing на блок,
        # переиспользуется и для записи result, и для итоговой проверки
        # all_expired ниже — не пересчитывается дважды.
        now = datetime.now(UTC)
        timings = [
            (block_id, protocol, compute_interval_timing(
                performed_at=detail.performed_at, now=now,
                total_duration_seconds=protocol.total_duration_seconds,
                work_seconds=protocol.work_seconds, rest_seconds=protocol.rest_seconds,
            ))
            for block_id, protocol in interval_blocks
        ]

        for block_id, protocol, timing in timings:
            if timing.phase != IntervalPhase.DONE:
                continue
            # is_deadline_completion=True: гарантировано условием выше
            # (только DONE-блоки доходят сюда) — lazy finalizer по
            # определению вызывается для истёкших сессий.
            result = self._interval_result_dict(
                protocol, timing.execution_started_at, timing.total_end_at, now, is_deadline_completion=True,
            )
            await self._sessions.save_interval_block_result(block_id, result)

        # Финализация сессии целиком (если все interval-блоки истекли).
        # Идемпотентность повторного/параллельного вызова: result полностью
        # детерминирован входными (performed_at, protocol) — НЕ зависит от
        # того, какой из конкурентных вызовов "выиграл" гонку записи, оба
        # вычисляют и пишут байт-в-байт одинаковый result. mark_completed
        # (см. app.services.live_session.py:277) уже идемпотентен по
        # конструкции — конкурентные UPDATE на одну строку сериализуются
        # обычной row-level блокировкой PostgreSQL, дополнительная
        # distributed-lock машинерия не нужна.
        all_expired = all(timing.phase == IntervalPhase.DONE for _, _, timing in timings)

        if all_expired:
            await self._sessions.mark_completed(session_id)

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

        # Phase B2 gate fix (issue #215) — explicit complete (вызывается
        # фронтендом на дедлайне ИЛИ при раннем прерывании через
        # BackButton, IntervalLiveScreen.tsx) должен писать interval result
        # точно так же, как lazy finalizer — иначе SessionBlock.result
        # остаётся null для сессий, завершённых этим путём (найдено живой
        # проверкой, не гипотетически).
        #
        # is_deadline_completion = not abandoned: уже существующий флаг —
        # IntervalLiveScreen.tsx's deadline-эффект вызывает complete с
        # abandoned=False (нормальное автозавершение, семантика "ровно
        # запланированная длительность", независимо от того, на сколько
        # миллисекунд раньше/позже дедлайна сетевой запрос реально дошёл
        # до сервера — это и было корнем найденного бага: min(now,
        # total_end_at) зависел от таймингов запроса). BackButton вызывает
        # с abandoned=True (реальное раннее прерывание, честный elapsed).
        interval_blocks = await self._parse_interval_blocks(detail)
        if interval_blocks:
            now = datetime.now(UTC)
            for block_id, protocol in interval_blocks:
                timing = compute_interval_timing(
                    performed_at=detail.performed_at, now=now,
                    total_duration_seconds=protocol.total_duration_seconds,
                    work_seconds=protocol.work_seconds, rest_seconds=protocol.rest_seconds,
                )
                result = self._interval_result_dict(
                    protocol, timing.execution_started_at, timing.total_end_at, now,
                    is_deadline_completion=not abandoned,
                )
                await self._sessions.save_interval_block_result(block_id, result)

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
