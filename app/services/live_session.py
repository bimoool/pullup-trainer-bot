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
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
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
from app.db.repositories.users import UserRepository
from app.domain.block_execution import (
    interval_protocol,
    is_interval_protocol,
    rest_seconds_for_protocol,
    targets_for_protocol,
)
from app.domain.course_prescription import (
    normalize_progression_state,
    resolve_progression_block,
)
from app.domain.interval_timing import (
    IntervalPhase,
    calculate_completed_cycles,
    compute_interval_timing,
)
from app.domain.live_session import (
    DEFAULT_UNIT_BY_METRIC_TYPE,
    GET_READY_SECONDS,
    BlockPlan,
    PhaseState,
    SessionPhaseName,
    initial_phase,
    next_phase,
    previous_phase,
)
from app.domain.multi_program import INTERNAL_ROLE_SUBCATEGORIES, MetricType, SessionSource
from app.domain.plan_occurrence import MAIN_SLOT_KEY, InclusionStatus, PlanItemStatus, derive_slots
from app.domain.progression_strategy import ProgressionStrategyType
from app.domain.training_session_v2 import SessionSourceV2
from app.domain.workout_protocol import DefinitionProtocol, ResolvedInterval, ResolvedProtocol
from app.domain.workout_snapshot import (
    UnresolvedProgressionError,
    WorkoutItemSnapshot,
    WorkoutSnapshot,
    build_workout_snapshot,
    positional_snapshot_items,
)
from app.services.course_assessment import (
    AssessmentRequiredError,
    promote_if_assessed,
)
from app.services.plan_spacing import MainSpacingService, TooEarlyError  # noqa: F401 — re-export
from app.services.program_access import (  # noqa: F401 — re-export
    ProgramAccessService,
    SubscriptionRequiredError,
)
from app.services.session_log import (
    SessionProgressionResult,
    _apply_step_progression,
    _match_step_blocks,
    _session_block_input_from_detail,
)
from app.services.training_session_v2 import TrainingSessionV2Service


@dataclass(frozen=True)
class LiveSessionResult:
    session: SessionDetail


class PhaseBackConflictError(Exception):
    """#292: «назад» невозможно — роут -> 409 с машинным кодом: stale_phase
    (expected_phase_index не совпал), not_active (сессия не STARTED),
    no_previous_set (первый подход блока / блок не начат / interval)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ActiveSessionConflictError(Exception):
    """Старт тренировки по workout_id при уже идущей другой живой сессии
    (одна активная сессия на пользователя): роут -> 409 с id активной."""

    def __init__(self, active_session_id: int) -> None:
        super().__init__("Active live session already exists")
        self.active_session_id = active_session_id


STALE_PLAN_ITEM_MESSAGE = "План обновился — открой «Планы» и выбери тренировку заново"

# progression_skipped_reason повторного complete уже завершённой сессии:
# прогрессия была применена (или пропущена) первым завершением, не этим.
ALREADY_COMPLETED_REASON = "already_completed"


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


def block_started_at(detail: SessionDetail, index: int) -> datetime | None:
    """Когда начат блок index. Блок 0 начинается вместе с сессией (пользователь
    уже нажал "Начать"): started_at у него не хранится, читается как
    performed_at — так же ведут себя сессии до R1. NULL у остальных блоков —
    блок ещё не начат."""
    started_at = detail.blocks[index].started_at
    if started_at is None and index == 0:
        return detail.performed_at
    return started_at


def current_interval_timing(detail: SessionDetail, now: datetime):
    """Server-authoritative состояние ТЕКУЩЕГО interval-блока или None.
    Не начатый блок (нет started_at) и не interval-блок не проецируются как
    активное interval-состояние."""
    if detail.status != SessionStatus.STARTED or detail.current_block_index >= len(detail.blocks):
        return None
    index = detail.current_block_index
    item = positional_snapshot_items(detail.workout_snapshot, len(detail.blocks))[index]
    if item is None or not is_interval_protocol(item.protocol):
        return None
    started_at = block_started_at(detail, index)
    if started_at is None:
        return None
    protocol = interval_protocol(item.protocol)
    return compute_interval_timing(
        performed_at=started_at, now=now, total_duration_seconds=protocol.total_duration_seconds,
        work_seconds=protocol.work_seconds, rest_seconds=protocol.rest_seconds,
    )


def has_manual_block_transitions(detail: SessionDetail) -> bool:
    """Ручной старт блоков — только у Builder-сессий (есть замороженный
    снимок). STEP и legacy-комплексы без протокола идут по прежней
    автоматической схеме: их поведение R1 не меняет."""
    return detail.workout_snapshot is not None


def awaiting_block_start(detail: SessionDetail) -> bool:
    """STARTED-сессия Builder-тренировки стоит перед ещё не начатым блоком
    (interstitial)."""
    return (
        has_manual_block_transitions(detail)
        and detail.status == SessionStatus.STARTED
        and detail.current_block_index < len(detail.blocks)
        and block_started_at(detail, detail.current_block_index) is None
    )


def _utcnow() -> datetime:
    """«Сейчас» для проверки отдыха K1 при старте (подменяется в тестах)."""
    return datetime.now(UTC)


def _phase_ends_at_from_offset(offset_seconds: int | None) -> datetime | None:
    if offset_seconds is None:
        return None
    return datetime.now(UTC) + timedelta(seconds=offset_seconds)


# Пространство advisory-локов старта живой сессии (первый int4 ключа pg_advisory_xact_lock(int, int)).
_START_LOCK_NAMESPACE = 0x4C53


async def lock_user_starts(session: AsyncSession, user_id: int) -> None:
    """Транзакционный advisory-лок «старт / кредит занятия» пользователя (N1, #293). Его же берут
    удаление занятия и остановка своего плана (#304 B1/B3, app.services.plan_removal) ДО проверки
    кредита: старт, засчитывающий занятие, и его снятие/удаление сериализуются — проверка «есть ли
    кредит» не может проскочить мимо незакоммиченного старта, а старт видит уже снятое занятие.
    Порядок локов: этот, затем строка плана (lock_plan) — у старта плана-лока нет, у сходимости нет
    этого, цикла ожидания нет."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:ns, :uid)"), {"ns": _START_LOCK_NAMESPACE, "uid": user_id},
    )


class LiveSessionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._sessions = TrainingSessionRepository(session)
        self._plans = TrainingPlanRepository(session)
        self._programs = ProgramRepository(session)

    # --- Старт -----------------------------------------------------------

    async def start_session(
        self, *, user_id: int, client_session_id: uuid.UUID, plan_item_ids: list[int],
        workout_id: int | None = None, bypass_spacing: bool = False,
    ) -> LiveSessionResult | None:
        """Идемпотентный старт: две конкурентные транзакции с одним client_session_id (офлайн-повтор,
        двойной тап) оба проходят проверку «сессии нет» и вставляют; проигравший упирается в
        uq_training_sessions_client_session_id. Вставка идёт под SAVEPOINT — при конфликте
        возвращается сессия победителя (а не 500). Конфликт при отсутствии СВОЕЙ сессии с этим UUID
        (UUID занят другим пользователем) — ValueError -> 422, без раскрытия чужой сессии.

        bypass_spacing — админ (settings.is_admin): обход K1, как в legacy-путях."""
        # N1 (#293): два устройства с РАЗНЫМИ client_session_id оба проходят проверку «активной нет».
        # Сериализуем старты пользователя advisory-локом до проверки (транзакционный — снимается на
        # commit/rollback, миграции/уникального индекса не требует). Конкурент ждёт, затем видит
        # STARTED-сессию победителя и получает 409; повтор с тем же client_session_id — existing.
        await lock_user_starts(self._session, user_id)
        try:
            async with self._session.begin_nested():
                return await self._start_session(
                    user_id=user_id, client_session_id=client_session_id, plan_item_ids=plan_item_ids,
                    workout_id=workout_id, bypass_spacing=bypass_spacing,
                )
        except IntegrityError:
            existing = await self._sessions.get_by_client_session_id(user_id, client_session_id)
            if existing is None:
                raise ValueError("client_session_id уже использован") from None
            return await self._build_result(existing.id, user_id)

    async def _start_session(
        self, *, user_id: int, client_session_id: uuid.UUID, plan_item_ids: list[int],
        workout_id: int | None = None, bypass_spacing: bool = False,
    ) -> LiveSessionResult | None:
        """ValueError — недопустимый набор строк плана (роут -> 422).

        workout_id — «Начать» на Workout Detail: свободная (source=freeform) сессия из замороженного
        снимка тренировки, БЕЗ кредита плана (PL3, J7).

        issue #304 (PROGRAM_PLAN_V2 §5): старт из плана — ровно ОДНО занятие (PlanItem); сессия
        засчитывает именно его (training_sessions.plan_item_id), в какой бы неделе оно ни было (PL4,
        J12 — будущие недели стартуются, §6). Занятие, уже засчитанное другой сессией, повторно не
        засчитывается («Ещё раз» — без кредита). Замороженные агрегатные строки прошлого и выведенные
        из плана строки не стартуются (422 «план обновился»). Старт MAIN раньше available_from —
        TooEarlyError (K1)."""
        existing = await self._sessions.get_by_client_session_id(user_id, client_session_id)
        if existing is not None:
            return await self._build_result(existing.id, user_id)

        if workout_id is not None:
            return await self._start_workout_session(
                user_id=user_id, client_session_id=client_session_id, workout_id=workout_id,
            )

        plan = await self._plans.get_for_user(user_id)
        if plan is None:
            return None
        # R-4 (#289): как у workout-пути — одна активная сессия на пользователя. Повтор с тем же
        # client_session_id уже вернулся выше (existing), сюда доходит только НОВЫЙ id.
        active = await self._sessions.get_active_for_user(user_id)
        if active is not None:
            raise ActiveSessionConflictError(active.id)

        plan_items: list[PlanItem] = []
        for plan_item_id in plan_item_ids:
            plan_item = await self._plans.get_plan_item_for_user(plan_item_id, user_id)
            if plan_item is None or plan_item.training_plan_id != plan.id:
                return None
            if plan_item.status == PlanItemStatus.REMOVED or plan_item.legacy_aggregate:
                raise ValueError(STALE_PLAN_ITEM_MESSAGE)
            if (
                plan_item.program_inclusion_id is None and plan_item.complex_id is not None
                and not await self._plans.live_workout_ids([plan_item.complex_id], user_id)
            ):
                # #304 F (страховка): строка своего плана / ручная, чья тренировка удалена (архив) или
                # недоступна, не стартует, даже если строка ещё есть. Читается после лока стартов: удаление
                # тренировки держит тот же лок, поэтому старт видит уже закоммиченный архив.
                raise ValueError(STALE_PLAN_ITEM_MESSAGE)
            plan_items.append(plan_item)
        if not plan_items:
            raise ValueError("Не выбрано занятие плана")
        if len(plan_items) > 1 and any(item.occurrence_index is not None for item in plan_items):
            raise ValueError("Одна тренировка засчитывает одно занятие плана")

        resolved_blocks: list[SessionBlockInput] = []
        resolved_targets: list[list[SetTargetInput]] = []
        snapshots: list[WorkoutSnapshot | None] = []
        block_protocols: list[ResolvedProtocol | None] = []
        course_inclusion_ids: list[int] = []
        is_main = False
        for plan_item in plan_items:
            if plan_item.program_inclusion_id is not None:
                course_inclusion_ids.append(plan_item.program_inclusion_id)
            if plan_item.program_slot_key == MAIN_SLOT_KEY and plan_item.program_inclusion_id is not None:
                units = [await self._resolve_main_occurrence(plan_item)]
                is_main = True
            elif plan_item.program_slot_key is not None and plan_item.program_inclusion_id is not None:
                units = await self._resolve_program_occurrence(plan_item)
            else:
                units = [await self._resolve_blocks_for_plan_item(plan_item)]
            for blocks, targets, snapshot in units:
                resolved_blocks.extend(blocks)
                resolved_targets.extend(targets)
                snapshots.append(snapshot)
                if snapshot is not None:
                    block_protocols.extend(item.protocol for item in snapshot.items)
                else:
                    block_protocols.extend([None] * len(blocks))

        if course_inclusion_ids:
            await self._require_program_access(user_id, course_inclusion_ids)
        if is_main or await self._has_step_role_blocks(resolved_blocks):
            user = await UserRepository(self._session).get_by_id(user_id)
            await MainSpacingService(self._session).require_main_start_allowed(
                user, now=_utcnow(), bypass=bypass_spacing,
            )

        # Кредит — ровно одна строка: занятие (повторно не засчитывается) или, для строк старой формы,
        # которых converge_user_plan ещё не развернул (старый клиент/данные до первого GET /plan), первая
        # из запрошенных — как и раньше «засчитано на своей неделе», но без M2M (только чтение).
        credited: PlanItem | None = plan_items[0]
        if credited.occurrence_index is not None and await self._sessions.credits_for_plan_items([credited.id]):
            credited = None  # уже засчитано другой сессией — повтор без кредита

        workout_snapshot = self._combine_snapshots(snapshots)

        block_plans = [
            BlockPlan(sets_count=len(targets), rest_seconds=rest_seconds_for_protocol(protocol))
            for targets, protocol in zip(resolved_targets, block_protocols, strict=True)
        ]
        phase_state = initial_phase(block_plans)
        phase_ends_at = _phase_ends_at_from_offset(phase_state.ends_at_offset_seconds)

        performed_at = datetime.now(UTC)
        training_session = await self._sessions.create_live_session(
            user_id=user_id, client_session_id=client_session_id, source=SessionSource.PLAN,
            performed_at=performed_at, plan_item_ids=[],
            blocks=resolved_blocks, targets_by_block=resolved_targets, phase_ends_at=phase_ends_at,
            workout_snapshot=workout_snapshot, plan_item_id=credited.id if credited is not None else None,
        )
        # issue #307 (TRAINING_SESSION_V2 §2): planned_live — определение и снимок рецепта из занятия.
        # Строка старой формы (до сходимости #304) знает тренировку только через complex_id.
        definition_ids = {
            item.workout_definition_id or (item.complex_id if item.program_inclusion_id is None else None)
            for item in plan_items
        }
        await self._stamp_live_start(
            training_session.id, user_id, source=SessionSourceV2.PLANNED_LIVE, performed_at=performed_at,
            workout_definition_id=definition_ids.pop() if len(definition_ids) == 1 else None,
            program_inclusion_id=course_inclusion_ids[0] if len(set(course_inclusion_ids)) == 1 else None,
        )
        return await self._build_result(training_session.id, user_id)

    async def _stamp_live_start(
        self, session_id: int, user_id: int, *, source: SessionSourceV2, performed_at: datetime,
        workout_definition_id: int | None, program_inclusion_id: int | None,
    ) -> None:
        user = await UserRepository(self._session).get_by_id(user_id)
        await TrainingSessionV2Service(self._session).stamp_new(
            session_id, user_id, source=source, resolved_at=performed_at,
            workout_definition_id=workout_definition_id, program_inclusion_id=program_inclusion_id,
            started_at=performed_at, timezone=user.timezone if user is not None else None, engine_version=1,
        )

    async def _resolve_main_occurrence(
        self, plan_item: PlanItem,
    ) -> tuple[list[SessionBlockInput], list[list[SetTargetInput]], WorkoutSnapshot | None]:
        """Занятие main-слота «Подтягиваний» = блоки A + Б (AD-3) из ролей СНИМКА своей инклюзии.
        Числа подходов/целей — прежние (из progression_state); их корректность — #305."""
        inclusion = await self._plans.get_inclusion_by_id(plan_item.program_inclusion_id)
        roles = {item["role"]: item["exercise_id"] for item in (inclusion.snapshot or {}).get("exercises", [])}
        if not inclusion.is_active or "block_a" not in roles or "block_b" not in roles:
            raise ValueError(STALE_PLAN_ITEM_MESSAGE)
        await self._require_assessment(inclusion)
        blocks: list[SessionBlockInput] = []
        targets: list[list[SetTargetInput]] = []
        for role in ("block_a", "block_b"):
            role_blocks, role_targets = self._resolve_step_role_block(roles[role], inclusion, role)
            blocks.extend(role_blocks)
            targets.extend(role_targets)
        return blocks, targets, None

    async def _require_assessment(self, inclusion: ProgramInclusion) -> None:
        """issue #305 (PROGRAM_PLAN_V2 §3): main-блоки инклюзии в awaiting_assessment не стартуют, пока
        замер не записан. Записанный с тех пор замер переводит инклюзию в active тем же единственным
        переходом, что и convergence (promote_if_assessed), — старт не ждёт следующего GET /plan."""
        if inclusion.status != InclusionStatus.AWAITING_ASSESSMENT.value:
            return
        program = await self._programs.get_by_id(inclusion.program_id)
        if await promote_if_assessed(self._session, inclusion, program, now=_utcnow()):
            return
        protocol_id = (program.assessment or {}).get("protocol_id") if program is not None else None
        raise AssessmentRequiredError(inclusion.id, protocol_id)

    async def _resolve_program_occurrence(
        self, plan_item: PlanItem,
    ) -> list[tuple[list[SessionBlockInput], list[list[SetTargetInput]], WorkoutSnapshot | None]]:
        """Занятие слота курса = все элементы слота одной тренировкой (прежняя семантика карточки курса,
        где старт слал все строки группы). Слот — из СНИМКА инклюзии (derive_slots)."""
        inclusion = await self._plans.get_inclusion_by_id(plan_item.program_inclusion_id)
        program = await self._programs.get_by_id(inclusion.program_id)
        slots = derive_slots(
            inclusion.snapshot, program_slots=program.slots if program else None,
            program_frequency=program.frequency if program else None,
        )
        slot = next((slot for slot in slots if slot.key == plan_item.program_slot_key), None)
        if not inclusion.is_active or slot is None or not slot.members:
            raise ValueError(STALE_PLAN_ITEM_MESSAGE)
        units = []
        for member in slot.members:
            if member.complex_id is not None:
                units.append(await self._resolve_complex_blocks(member.complex_id))
            else:
                blocks, targets = await self._resolve_exercise_block_by_id(plan_item.training_plan_id, member.exercise_id)
                units.append((blocks, targets, None))
        return units

    async def _has_step_role_blocks(self, blocks: list[SessionBlockInput]) -> bool:
        exercise_ids = sorted({block.exercise_id for block in blocks if block.exercise_id is not None})
        if not exercise_ids:
            return False
        exercises = await self._programs.list_exercises_by_ids(exercise_ids)
        return any(exercise.subcategory in INTERNAL_ROLE_SUBCATEGORIES for exercise in exercises)

    async def _require_program_access(self, user_id: int, inclusion_ids: list[int]) -> None:
        """#300 / D6 + правило 2026-10-07: курсовая строка плана (program_inclusion_id) стартует, если её программа
        бесплатна («Подтягивания») или есть действующая подписка (trial/active и срок не истёк — считается из
        subscription_expires_at, кэш статуса не доверяем). Решение — ProgramAccessService (единый путь). Запрос
        со строкой платной программы без подписки отклоняется целиком (вместе со своими строками). Свои/ручные
        строки, Workout (workout_id) и факультатив не гейтятся."""
        user = await UserRepository(self._session).get_by_id(user_id)
        await ProgramAccessService(self._session).require_inclusions_training_access(
            user, inclusion_ids, now=datetime.now(UTC),
        )

    async def _start_workout_session(
        self, *, user_id: int, client_session_id: uuid.UUID, workout_id: int,
    ) -> LiveSessionResult | None:
        """None — тренировка не видна пользователю (PROJECT_SPEC §5) -> 404.
        Прогрессию курса и счётчики плана такая сессия не трогает (source=
        FREEFORM, SessionPlanItem не создаётся)."""
        if await self._programs.get_visible_workout_for_user(workout_id, user_id) is None:
            return None
        active = await self._sessions.get_active_for_user(user_id)
        if active is not None:
            raise ActiveSessionConflictError(active.id)

        blocks, targets, snapshot = await self._resolve_complex_blocks(workout_id)
        if not blocks:
            raise ValueError("В тренировке нет упражнений")
        block_protocols = [item.protocol for item in snapshot.items] if snapshot is not None else [None] * len(blocks)
        block_plans = [
            BlockPlan(sets_count=len(block_targets), rest_seconds=rest_seconds_for_protocol(protocol))
            for block_targets, protocol in zip(targets, block_protocols, strict=True)
        ]
        phase_state = initial_phase(block_plans)
        performed_at = datetime.now(UTC)
        training_session = await self._sessions.create_live_session(
            user_id=user_id, client_session_id=client_session_id, source=SessionSource.FREEFORM,
            performed_at=performed_at, plan_item_ids=[], blocks=blocks, targets_by_block=targets,
            phase_ends_at=_phase_ends_at_from_offset(phase_state.ends_at_offset_seconds),
            workout_snapshot=snapshot.model_dump(mode="json") if snapshot is not None else None,
        )
        # issue #307: direct_live — определение = эта тренировка, plan_item_id = None (PL3).
        await self._stamp_live_start(
            training_session.id, user_id, source=SessionSourceV2.DIRECT_LIVE, performed_at=performed_at,
            workout_definition_id=workout_id, program_inclusion_id=None,
        )
        return await self._build_result(training_session.id, user_id)

    @staticmethod
    def _combine_snapshots(snapshots: list[WorkoutSnapshot | None]) -> dict | None:
        """Один замороженный снимок на всю сессию, выровненный по позиции с
        её блоками. Несколько Builder Workout в одной сессии склеиваются;
        смесь Builder и обычных строк — нет (блоки без пункта снимка сломали
        бы позиционное соответствие)."""
        builder = [snapshot for snapshot in snapshots if snapshot is not None]
        if not builder:
            return None
        if len(builder) != len(snapshots):
            raise ValueError("Builder Workout нельзя смешивать с обычными строками плана в одной сессии")
        if len(builder) == 1:
            return builder[0].model_dump(mode="json")
        items = [item for snapshot in builder for item in snapshot.items]
        merged = WorkoutSnapshot(
            workout_id=builder[0].workout_id, title=builder[0].title,
            items=[item.model_copy(update={"order": index}) for index, item in enumerate(items)],
        )
        return merged.model_dump(mode="json")

    async def _resolve_blocks_for_plan_item(
        self, plan_item: PlanItem,
    ) -> tuple[list[SessionBlockInput], list[list[SetTargetInput]], WorkoutSnapshot | None]:
        """Блоки/targets/snapshot одного PlanItem. Snapshot — только у Builder
        Workout (все ComplexItem с protocol), None у legacy/STEP/manual."""
        if plan_item.complex_id is not None:
            return await self._resolve_complex_blocks(plan_item.complex_id)
        blocks, targets = await self._resolve_exercise_block(plan_item)
        return blocks, targets, None  # exercise path никогда не Builder

    async def resolve_workout(
        self, complex_id: int,
    ) -> tuple[list[SessionBlockInput], list[list[SetTargetInput]], WorkoutSnapshot | None]:
        """Рецепт тренировки ровно так, как его разрешает живой старт (блоки, цели, v1-снимок) —
        issue #307: ручная запись известной тренировки строит сессию ЭТИМ ЖЕ путём
        (app.services.manual_session), второго резолвера нет."""
        return await self._resolve_complex_blocks(complex_id)

    async def _resolve_complex_blocks(
        self, complex_id: int,
    ) -> tuple[list[SessionBlockInput], list[list[SetTargetInput]], WorkoutSnapshot | None]:
        """Один SessionBlock на каждый ComplexItem, по order_index.

        Builder-путь (REBUILD-1, R1): если у ВСЕХ ComplexItem есть protocol,
        workout замораживается в снимок (build_workout_snapshot), а цели
        подходов выводятся из resolved-протокола снимка — НЕ из
        ComplexItem.sets/target_value (interval -> ноль целей: таймер
        сервера). Legacy-путь (protocol=None) — прежнее поведение без
        снимка."""
        items = await self._programs.list_complex_items(complex_id)
        exercises = {
            exercise.id: exercise
            for exercise in await self._programs.list_exercises_by_ids(sorted({i.exercise_id for i in items}))
        }

        if items and all(item.protocol is not None for item in items):
            protocols = {
                item.id: TypeAdapter(DefinitionProtocol).validate_python(item.protocol) for item in items
            }
            complex_ = await self._programs.get_complex(complex_id)
            try:
                snapshot = build_workout_snapshot(
                    workout=complex_, items=items, exercises=exercises, protocols=protocols,
                    progression_resolver=None,
                )
            except UnresolvedProgressionError:
                snapshot = None  # program-authoring протокол без резолвера — прежний legacy-путь
            if snapshot is not None:
                blocks: list[SessionBlockInput] = []
                targets_by_block: list[list[SetTargetInput]] = []
                for snapshot_item in snapshot.items:
                    metric = exercises[snapshot_item.exercise_id].metric_type
                    blocks.append(SessionBlockInput(exercise_id=snapshot_item.exercise_id, sets=[]))
                    targets_by_block.append([
                        SetTargetInput(
                            set_number=t.set_number, metric_type=t.metric_type, value=Decimal(t.value),
                            unit=t.unit, is_max_set=t.is_max_set,
                        )
                        for t in targets_for_protocol(snapshot_item.protocol, metric)
                    ])
                return blocks, targets_by_block, snapshot

        blocks = []
        targets_by_block = []
        for item in items:
            metric_type = exercises[item.exercise_id].metric_type
            value = item.target_value if item.target_value is not None else Decimal(0)
            unit = item.target_unit if item.target_unit is not None else DEFAULT_UNIT_BY_METRIC_TYPE[metric_type]
            blocks.append(SessionBlockInput(exercise_id=item.exercise_id, sets=[]))
            targets_by_block.append([
                SetTargetInput(set_number=i + 1, metric_type=metric_type, value=value, unit=unit)
                for i in range(item.sets)
            ])
        return blocks, targets_by_block, None

    async def _resolve_exercise_block(
        self, plan_item: PlanItem,
    ) -> tuple[list[SessionBlockInput], list[list[SetTargetInput]]]:
        return await self._resolve_exercise_block_by_id(plan_item.training_plan_id, plan_item.exercise_id)

    async def _resolve_exercise_block_by_id(
        self, training_plan_id: int, exercise_id: int,
    ) -> tuple[list[SessionBlockInput], list[list[SetTargetInput]]]:
        step_match = await self._find_step_role_for_exercise(training_plan_id, exercise_id)
        if step_match is not None:
            await self._require_assessment(step_match[0])
            return self._resolve_step_role_block(exercise_id, *step_match)
        return await self._resolve_plain_exercise_block(exercise_id)

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
        """Подходы блока курса — ЕДИНСТВЕННЫЙ резолвер resolve_progression_block (issue #305,
        WORKOUT_DOMAIN_V2 §6): рабочих подходов ровно work_sets роли (обе роли; у block_b старых
        инклюзий поле дописывает normalize_progression_state — тот же источник STRENGTH_BLOCK.work_sets,
        что у миграции e3b9c5d7a2f1), без тихого «1» (D2), и последним — явный подход на максимум (OD-3
        решён: включать); его цель помечена is_max_set, так и пишется в SetLog (D3) и именно он — вход
        прогрессии (advance_step_progression)."""
        state = normalize_progression_state(inclusion.progression_state)
        prescriptions = resolve_progression_block(role, state)
        block = SessionBlockInput(exercise_id=exercise_id, sets=[])
        targets = [
            SetTargetInput(
                set_number=p.set_number, metric_type=MetricType.REPS, value=Decimal(p.target_reps), unit="reps",
                is_max_set=p.is_max_set,
            )
            for p in prescriptions
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

        if expected_phase_index == detail.phase_index and self._is_standard_block_running(detail):
            protocols = self._block_protocols(detail)
            blocks = [
                BlockPlan(
                    sets_count=len(block.set_targets),
                    rest_seconds=rest_seconds_for_protocol(protocol.protocol if protocol else None),
                )
                for block, protocol in zip(detail.blocks, protocols, strict=True)
            ]
            current = PhaseState(
                phase_name=_domain_phase(detail.phase_name), block_index=detail.current_block_index,
                set_number=detail.current_set_number, ends_at_offset_seconds=None,
            )
            new_state = next_phase(current, blocks)
            # Конец обычного блока в середине тренировки (R1, инвариант G):
            # сессия ПРОДВИГАЕТСЯ к следующему блоку, но не стартует его сама —
            # следующий блок ждёт явного "Начать" (start_block).
            crossed_block = (
                has_manual_block_transitions(detail)
                and new_state.phase_name != SessionPhaseName.DONE
                and new_state.block_index != current.block_index
            )
            await self._sessions.advance_phase(
                session_id, phase_name=_db_phase(new_state.phase_name),
                phase_ends_at=None if crossed_block else _phase_ends_at_from_offset(new_state.ends_at_offset_seconds),
                current_block_index=new_state.block_index, current_set_number=new_state.set_number,
                phase_index=detail.phase_index + 1,
            )
        # expected_phase_index != detail.phase_index (клиент отстал или
        # прислал индекс из будущего), либо текущий блок не "обычный бегущий"
        # (не начат / interval — у него своё server-authoritative время) —
        # НЕ переход, просто отдаём текущее состояние (офлайн-контракт:
        # никогда не 409, никогда откат).
        return await self._build_result(session_id, user_id)

    # --- Шаг назад на предыдущий подход (#292) --------------------------------

    async def back_phase(
        self, *, session_id: int, user_id: int, expected_phase_index: int,
    ) -> LiveSessionResult | None:
        """None — чужая/несуществующая сессия (404). Никогда не удаляет и не
        правит SetLog: фаза возвращается на `go` предыдущего подхода, повторное
        «Готово» клиента перезаписывает ту же строку (set_index). phase_index
        растёт (+1), не откатывается — старые phase/next из офлайн-очереди с
        прежним индексом после этого становятся no-op."""
        detail = await self._sessions.get_for_user(session_id, user_id)
        if detail is None:
            return None
        await self._sessions.lock_session(session_id)
        detail = await self._sessions.get_for_user(session_id, user_id)
        if detail.status != SessionStatus.STARTED:
            raise PhaseBackConflictError("not_active")
        if expected_phase_index != detail.phase_index:
            raise PhaseBackConflictError("stale_phase")
        if not self._is_standard_block_running(detail):
            raise PhaseBackConflictError("no_previous_set")
        current = PhaseState(
            phase_name=_domain_phase(detail.phase_name), block_index=detail.current_block_index,
            set_number=detail.current_set_number, ends_at_offset_seconds=None,
        )
        previous = previous_phase(current)
        if previous is None:
            raise PhaseBackConflictError("no_previous_set")
        await self._sessions.advance_phase(
            session_id, phase_name=_db_phase(previous.phase_name),
            phase_ends_at=_phase_ends_at_from_offset(previous.ends_at_offset_seconds),
            current_block_index=previous.block_index, current_set_number=previous.set_number,
            phase_index=detail.phase_index + 1,
        )
        return await self._build_result(session_id, user_id)

    # --- Ручной старт блока (R1) ---------------------------------------------

    async def start_block(
        self, *, session_id: int, user_id: int, expected_block_index: int,
    ) -> LiveSessionResult | None:
        """Явный "Начать" следующего блока. Идемпотентен: повторный/
        конкурентный вызов, устаревший или чужой expected_block_index,
        уже начатый блок — отдаёт текущее состояние, не меняя его (двойной
        клик стартует блок ровно один раз, started_at не перезаписывается)."""
        detail = await self._sessions.get_for_user(session_id, user_id)
        if detail is None or detail.status != SessionStatus.STARTED:
            return None
        await self._sessions.lock_session(session_id)
        detail = await self._sessions.get_for_user(session_id, user_id)

        index = detail.current_block_index
        if awaiting_block_start(detail) and index == expected_block_index:
            now = datetime.now(UTC)
            await self._sessions.mark_block_started(detail.blocks[index].id, now)
            await self._sessions.advance_phase(
                session_id, phase_name=SessionPhase.GET_READY,
                phase_ends_at=now + timedelta(seconds=GET_READY_SECONDS),
                current_block_index=index, current_set_number=1, phase_index=detail.phase_index + 1,
            )
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
        # Lazy finalization для истёкшего interval-блока: в середине
        # тренировки продвигает сессию к следующему (не начатому) блоку,
        # последний блок — завершает сессию. /sessions/live/active
        # семантически означает "есть, что продолжить", поэтому завершённую
        # сессию не отдаём — фронт идёт в Summary/Journal обычным путём.
        await self.finalize_expired_interval_if_needed(training_session.id, user_id)
        result = await self._build_result(training_session.id, user_id)
        if result is not None and result.session.status != SessionStatus.STARTED:
            return None
        return result

    def _interval_result_dict(
        self, protocol: ResolvedInterval, execution_started_at: datetime, total_end_at: datetime, now: datetime,
        *, is_deadline_completion: bool,
    ) -> dict:
        """Два разных случая, разная семантика completed_at/
        actual_duration_seconds (не угадывается из `now` относительно
        `total_end_at` — сетевой/event-loop джиттер в доли секунды раньше
        занижал секунду).

        is_deadline_completion=True (нормальное автозавершение: блок уже
        DONE): completed_at/actual_duration_seconds — ровно total_end_at/
        planned_duration_seconds, детерминированно.

        is_deadline_completion=False (ручное раннее прерывание):
        completed_at=now, actual_duration_seconds честно меньше planned."""
        if is_deadline_completion:
            completed_at = total_end_at
            elapsed_seconds = protocol.total_duration_seconds
        else:
            completed_at = min(now, total_end_at)
            elapsed_seconds = max(0.0, (completed_at - execution_started_at).total_seconds())
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

    @staticmethod
    def _block_protocols(detail: SessionDetail) -> list[WorkoutItemSnapshot | None]:
        return positional_snapshot_items(detail.workout_snapshot, len(detail.blocks))

    def _is_standard_block_running(self, detail: SessionDetail) -> bool:
        """Фазовая машина (get_ready/go/rest) применима только к НАЧАТОМУ
        обычному (не interval) блоку."""
        index = detail.current_block_index
        if index >= len(detail.blocks):
            return False
        if has_manual_block_transitions(detail) and block_started_at(detail, index) is None:
            return False
        item = self._block_protocols(detail)[index]
        return not (item is not None and is_interval_protocol(item.protocol))

    async def finalize_expired_interval_if_needed(self, session_id: int, user_id: int) -> None:
        """Lazy completion истёкшего interval-блока (идемпотентно). Вызывается
        из GET /sessions/live/active и из листинга сессий — один helper на
        все места."""
        await self._finalize_due_interval(session_id, user_id)

    async def _finalize_due_interval(self, session_id: int, user_id: int) -> str:
        """"none" | "advanced" | "completed". Только ТЕКУЩИЙ, начатый interval-
        блок и только если его время вышло: пишет result, затем либо
        продвигает current_block_index к следующему (не начатому) блоку, либо
        — если блок последний — завершает сессию. Незапущенный interval-блок
        никогда не финализируется (у него нет таймера)."""
        detail = await self._sessions.get_for_user(session_id, user_id)
        if detail is None or detail.status != SessionStatus.STARTED:
            return "none"
        index = detail.current_block_index
        if index >= len(detail.blocks):
            return "none"
        item = self._block_protocols(detail)[index]
        if item is None or not is_interval_protocol(item.protocol):
            return "none"
        started_at = block_started_at(detail, index)
        if started_at is None:
            return "none"

        protocol = interval_protocol(item.protocol)
        now = datetime.now(UTC)
        timing = compute_interval_timing(
            performed_at=started_at, now=now, total_duration_seconds=protocol.total_duration_seconds,
            work_seconds=protocol.work_seconds, rest_seconds=protocol.rest_seconds,
        )
        if timing.phase != IntervalPhase.DONE:
            return "none"

        await self._sessions.lock_session(session_id)
        detail = await self._sessions.get_for_user(session_id, user_id)
        if detail.status != SessionStatus.STARTED or detail.current_block_index != index:
            return "none"  # конкурентный вызов уже продвинул сессию

        # Результат детерминирован входными (started_at, protocol) — повтор/
        # гонка пишут байт-в-байт одно и то же.
        if detail.blocks[index].result is None:
            result = self._interval_result_dict(
                protocol, timing.execution_started_at, timing.total_end_at, now, is_deadline_completion=True,
            )
            await self._sessions.save_interval_block_result(detail.blocks[index].id, result)

        if index >= len(detail.blocks) - 1:
            await self._sessions.mark_completed(session_id, completed_at=timing.total_end_at)
            return "completed"
        await self._sessions.advance_phase(
            session_id, phase_name=SessionPhase.GET_READY, phase_ends_at=None,
            current_block_index=index + 1, current_set_number=1, phase_index=detail.phase_index + 1,
        )
        return "advanced"

    async def finish_interval_block(
        self, *, session_id: int, user_id: int, expected_block_index: int,
    ) -> tuple[CompleteResult | None, bool]:
        """Клиент дошёл до дедлайна interval-блока. Середина тренировки —
        сессия продвигается к следующему блоку и остаётся STARTED; последний
        блок — обычное завершение (со всем, что делает complete_session).
        Не дедлайн / устаревший индекс — отдаёт текущее состояние без
        изменений. Второй элемент — сессия не найдена (роут -> 404)."""
        detail = await self._sessions.get_for_user(session_id, user_id)
        if detail is None:
            return None, True
        if detail.status == SessionStatus.STARTED and detail.current_block_index == expected_block_index:
            index = detail.current_block_index
            is_last = index >= len(detail.blocks) - 1
            item = self._block_protocols(detail)[index] if index < len(detail.blocks) else None
            if is_last and item is not None and is_interval_protocol(item.protocol):
                started_at = block_started_at(detail, index)
                protocol = interval_protocol(item.protocol)
                if started_at is not None:
                    timing = compute_interval_timing(
                        performed_at=started_at, now=datetime.now(UTC),
                        total_duration_seconds=protocol.total_duration_seconds,
                        work_seconds=protocol.work_seconds, rest_seconds=protocol.rest_seconds,
                    )
                    if timing.phase == IntervalPhase.DONE:
                        return await self.complete_session(session_id=session_id, user_id=user_id, abandoned=False)
            else:
                await self._finalize_due_interval(session_id, user_id)
        final = await self._sessions.get_for_user(session_id, user_id)
        return CompleteResult(session=final, progression_result=None, progression_skipped_reason=None), False

    # --- Завершение -------------------------------------------------------

    async def complete_session(
        self, *, session_id: int, user_id: int, abandoned: bool,
        effort: Decimal | None = None, comment: str | None = None, active_elapsed_ms: int | None = None,
    ) -> tuple[CompleteResult | None, bool]:
        """Второй элемент — True, если сессия не найдена/не принадлежит
        пользователю (роут превращает в 404) — тот же (result, not_found)
        приём, что TrainingSessionLogService.record_session уже использует
        для program_inclusion_id (app.services.session_log).

        issue #307 — канонический интерфейс завершения (TRAINING_SESSION_V2 §8, в т.ч. для движка v2
        #306): active_elapsed_ms — измеренная движком активная длительность (паузы исключены);
        без неё — стенные часы старт → завершение в окне [1 мин, 6 ч] (R3). Повтор — тот же ответ, без
        второй прогрессии и без смены длительности."""
        detail = await self._sessions.get_for_user(session_id, user_id)
        if detail is None:
            return None, True

        # Идемпотентность завершения (fix/concurrent-set-batch): двойной
        # флаш (реконнект + "Завершить") или повтор после потерянного ответа
        # присылают complete второй раз. Под блокировкой строки сессии (тот
        # же lock_session, что у sets:batch) перечитываем статус: уже
        # завершённая сессия — 200 с текущим состоянием, БЕЗ повторной
        # прогрессии/interval result (иначе цель курса сдвинулась бы дважды).
        await self._sessions.lock_session(session_id)
        detail = await self._sessions.get_for_user(session_id, user_id)
        if detail.status != SessionStatus.STARTED:
            if effort is not None or comment is not None:
                await self._sessions.save_workout_review(session_id, effort=effort, comment=comment)
                detail = await self._sessions.get_for_user(session_id, user_id)
            return (
                CompleteResult(
                    session=detail, progression_result=None, progression_skipped_reason=ALREADY_COMPLETED_REASON,
                ),
                False,
            )

        await self._sessions.mark_completed(session_id, active_elapsed_ms=active_elapsed_ms)
        if effort is not None or comment is not None:
            await self._sessions.save_workout_review(session_id, effort=effort, comment=comment)

        # Явное завершение пишет interval result для ТЕКУЩЕГО начатого
        # interval-блока (предыдущие уже финализированы при переходе, ещё не
        # начатые не выполнялись). Нормальное автозавершение (не abandoned И
        # время блока реально вышло) — детерминированный planned result;
        # ручное раннее — честный elapsed.
        index = detail.current_block_index
        if index < len(detail.blocks) and detail.blocks[index].result is None:
            item = self._block_protocols(detail)[index]
            started_at = block_started_at(detail, index)
            if item is not None and is_interval_protocol(item.protocol) and started_at is not None:
                protocol = interval_protocol(item.protocol)
                now = datetime.now(UTC)
                timing = compute_interval_timing(
                    performed_at=started_at, now=now, total_duration_seconds=protocol.total_duration_seconds,
                    work_seconds=protocol.work_seconds, rest_seconds=protocol.rest_seconds,
                )
                result = self._interval_result_dict(
                    protocol, timing.execution_started_at, timing.total_end_at, now,
                    is_deadline_completion=not abandoned and timing.phase == IntervalPhase.DONE,
                )
                await self._sessions.save_interval_block_result(detail.blocks[index].id, result)

        progression_result: SessionProgressionResult | None = None
        skipped_reason: str | None = None
        if abandoned:
            skipped_reason = "abandoned"
        elif detail.source != SessionSource.PLAN:
            # «Начать» с Workout Detail (freeform): прогрессию курса не трогает.
            skipped_reason = "not_plan_session"
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
                    # PROGRAM_PLAN_V2 §2: +1 ревизия на каждую применённую прогрессию; курсор
                    # последовательности сдвигается засчитанным занятием main-слота.
                    inclusion.progression_state_rev = (inclusion.progression_state_rev or 0) + 1
                    if detail.plan_item_id is not None and inclusion.sequence_cursor is not None:
                        inclusion.sequence_cursor += 1

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
