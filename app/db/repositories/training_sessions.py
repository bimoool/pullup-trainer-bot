import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import (
    Exercise,
    SessionBlock,
    SessionPhase,
    SessionPlanItem,
    SessionStatus,
    SetLog,
    SetTarget,
    TrainingSession,
)
from app.domain.live_session import DEFAULT_UNIT_BY_METRIC_TYPE
from app.domain.multi_program import MetricType, SessionSource


@dataclass(frozen=True)
class SetLogInput:
    set_number: int
    metric_type: MetricType
    value: Decimal
    unit: str
    is_max_set: bool = False
    effort: Decimal | None = None
    note: str | None = None


@dataclass(frozen=True)
class SessionBlockInput:
    sets: list[SetLogInput]
    exercise_id: int | None = None
    complex_id: int | None = None


@dataclass(frozen=True)
class SetTargetInput:
    """План на подход живой сессии — та же форма, что SetLogInput (факт),
    но без effort/note (план ещё не пройден, отмечать нечего) и с
    is_max_set по умолчанию False, как и SetLogInput."""

    set_number: int
    metric_type: MetricType
    value: Decimal
    unit: str
    is_max_set: bool = False


@dataclass(frozen=True)
class BatchSetLogInput:
    """Один элемент батча POST /sessions/live/{id}/sets:batch (issue #165,
    офлайн-контракт) — set_index (не set_number: set_index назначает
    клиент как стабильный ключ идемпотентности ПОДХОДА В СЕССИИ ЦЕЛИКОМ,
    set_number назначается сервером внутри блока при первой вставке, см.
    TrainingSessionRepository.upsert_set_logs_batch)."""

    set_index: int
    exercise_id: int
    value: Decimal
    effort: Decimal | None = None
    note: str | None = None


@dataclass(frozen=True)
class SessionSetLogDetail:
    set_number: int
    is_max_set: bool
    metric_type: MetricType
    value: Decimal
    unit: str
    effort: Decimal | None
    note: str | None


@dataclass(frozen=True)
class SessionSetTargetDetail:
    set_number: int
    is_max_set: bool
    metric_type: MetricType
    value: Decimal
    unit: str


@dataclass(frozen=True)
class SessionBlockDetail:
    """id — первичный ключ SessionBlock (не выставлялся до продолжения
    волны 3 "сессия — live"): нужен app.services.progression_cascade,
    чтобы адресовать конкретный SessionBlock при перезаписи SetLog правки
    исторической сессии (update_set_logs_for_blocks), не только для
    чтения."""

    id: int
    order_index: int
    exercise_id: int | None
    complex_id: int | None
    set_logs: list[SessionSetLogDetail] = field(default_factory=list)
    set_targets: list[SessionSetTargetDetail] = field(default_factory=list)
    result: dict | None = None


@dataclass(frozen=True)
class SessionDetail:
    """Агрегат TrainingSession + SessionBlock + SetTarget + SetLog, собранный
    из отдельных запросов (models_program.py волны 1 не заводит
    sqlalchemy.orm.relationship() между этими таблицами — только FK-колонки,
    см. докстринг модуля) — тот же принцип "репозиторий конвертирует ORM в
    датаклассы", что и WorkoutRecord/BlockLog у старой схемы, но здесь без
    домена: TrainingSession — не pull-up-специфичная сущность.

    client_session_id/phase_*/current_* — поля живой сессии (issue #165,
    продолжение волны 3); дефолты соответствуют "не живая" сессия — старый
    путь TrainingSessionLogService.record_session их не устанавливает
    явно, они приходят из server_default миграции 3d4e5f6a7b8c."""

    id: int
    source: SessionSource
    status: SessionStatus
    performed_at: datetime
    effort: Decimal | None
    comment: str | None
    client_session_id: uuid.UUID | None = None
    phase_name: SessionPhase = SessionPhase.DONE
    phase_ends_at: datetime | None = None
    current_block_index: int = 0
    current_set_number: int = 1
    phase_index: int = 0
    workout_snapshot: dict | None = None
    blocks: list[SessionBlockDetail] = field(default_factory=list)


class TrainingSessionRepository:
    """Агрегат TrainingSession + SessionBlock + SetTarget + SetLog + (косвенно)
    SessionPlanItem (issue #165, волна 3 + продолжение "сессия — live").
    Пишет только факт/план — пересчёт прогрессии не входит в этот
    репозиторий, им занимаются app.services.session_log/live_session/
    progression_cascade поверх ProgressionStrategy (волна 0)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_session(
        self, *, user_id: int, source: SessionSource, performed_at: datetime,
        effort: Decimal | None, comment: str | None, blocks: list[SessionBlockInput],
    ) -> TrainingSession:
        training_session = TrainingSession(
            user_id=user_id, source=source, status=SessionStatus.COMPLETED,
            performed_at=performed_at, effort=effort, comment=comment,
        )
        self._session.add(training_session)
        await self._session.flush()

        for order_index, block in enumerate(blocks):
            session_block = SessionBlock(
                session_id=training_session.id, order_index=order_index,
                exercise_id=block.exercise_id, complex_id=block.complex_id,
            )
            self._session.add(session_block)
            await self._session.flush()
            for set_log in block.sets:
                self._session.add(
                    SetLog(
                        session_block_id=session_block.id, set_number=set_log.set_number,
                        is_max_set=set_log.is_max_set, metric_type=set_log.metric_type,
                        value=set_log.value, unit=set_log.unit, effort=set_log.effort, note=set_log.note,
                    ),
                )
        await self._session.flush()
        return training_session

    async def create_live_session(
        self, *, user_id: int, client_session_id: uuid.UUID, source: SessionSource, performed_at: datetime,
        plan_item_ids: list[int], blocks: list[SessionBlockInput], targets_by_block: list[list[SetTargetInput]],
        phase_ends_at: datetime | None, workout_snapshot: dict | None = None,
    ) -> TrainingSession:
        """Старт живой сессии (POST /sessions/live) — status=STARTED,
        phase_name=GET_READY (уже применяется здесь, не через отдельный
        advance_phase сразу после create — избегаем лишней записи).
        blocks[i].sets игнорируется (для живой сессии подходы ещё не
        выполнены — targets_by_block[i] несёт план, SetLog появятся позже
        через upsert_set_logs_batch); SessionBlockInput переиспользуется
        целиком ради exercise_id/complex_id, не заводим отдельный тип.

        workout_snapshot (Phase B1, issue #215) — immutable WorkoutSnapshot для
        interval workouts, NULL для standard (STEP/manual) path. Сохраняется один
        раз при старте, не меняется при изменении ComplexItem.protocol после."""
        training_session = TrainingSession(
            user_id=user_id, source=source, status=SessionStatus.STARTED, performed_at=performed_at,
            effort=None, comment=None, client_session_id=client_session_id,
            phase_name=SessionPhase.GET_READY, phase_ends_at=phase_ends_at,
            current_block_index=0, current_set_number=1, phase_index=0,
            workout_snapshot=workout_snapshot,
        )
        self._session.add(training_session)
        await self._session.flush()

        for order_index, (block, targets) in enumerate(zip(blocks, targets_by_block, strict=True)):
            session_block = SessionBlock(
                session_id=training_session.id, order_index=order_index,
                exercise_id=block.exercise_id, complex_id=block.complex_id,
            )
            self._session.add(session_block)
            await self._session.flush()
            for target in targets:
                self._session.add(
                    SetTarget(
                        session_block_id=session_block.id, set_number=target.set_number,
                        is_max_set=target.is_max_set, metric_type=target.metric_type,
                        value=target.value, unit=target.unit,
                    ),
                )

        await self._create_session_plan_items(training_session.id, plan_item_ids)
        await self._session.flush()
        return training_session

    async def _create_session_plan_items(self, session_id: int, plan_item_ids: list[int]) -> None:
        for plan_item_id in plan_item_ids:
            self._session.add(SessionPlanItem(session_id=session_id, plan_item_id=plan_item_id))
        if plan_item_ids:
            await self._session.flush()

    async def list_plan_item_ids_by_session(self, session_ids: list[int]) -> dict[int, list[int]]:
        """Checkpoint 4C (issue #188) — первое чтение SessionPlanItem за всю
        историю таблицы (заполняется с Checkpoint 4A, до сих пор нигде не
        читалась — см. аудит Checkpoint 4). Один запрос на страницу
        Журнала, не по одному на сессию. Сессии, созданные до появления
        этой связи (или каким-то путём мимо create_live_session), просто не
        попадут в возвращаемый словарь — вызывающий код обязан сам решить
        фолбэк, эта функция не гадает."""
        if not session_ids:
            return {}
        result = await self._session.execute(
            select(SessionPlanItem).where(SessionPlanItem.session_id.in_(session_ids)),
        )
        by_session: dict[int, list[int]] = {}
        for row in result.scalars().all():
            by_session.setdefault(row.session_id, []).append(row.plan_item_id)
        return by_session

    async def get_by_client_session_id(self, user_id: int, client_session_id: uuid.UUID) -> TrainingSession | None:
        """Идемпотентность старта живой сессии (офлайн-контракт) — POST
        /sessions/live с уже виденным client_session_id должен вернуть
        существующую сессию, не создать вторую."""
        result = await self._session.execute(
            select(TrainingSession).where(
                TrainingSession.user_id == user_id, TrainingSession.client_session_id == client_session_id,
            ),
        )
        return result.scalar_one_or_none()

    async def get_active_for_user(self, user_id: int) -> TrainingSession | None:
        """GET /sessions/live/active — незавершённая (STARTED) сессия для
        баннера "продолжить/завершить" (раздел 10.8 docs/plan-and-specs.md).
        Самая свежая по performed_at, если их почему-то больше одной."""
        result = await self._session.execute(
            select(TrainingSession)
            .where(TrainingSession.user_id == user_id, TrainingSession.status == SessionStatus.STARTED)
            .order_by(TrainingSession.performed_at.desc(), TrainingSession.id.desc())
            .limit(1),
        )
        return result.scalar_one_or_none()

    async def advance_phase(
        self, session_id: int, *, phase_name: SessionPhase, phase_ends_at: datetime | None,
        current_block_index: int, current_set_number: int, phase_index: int,
    ) -> None:
        """Плоский UPDATE состояния фазы — вызывающий сервис уже посчитал
        новое состояние через app.domain.live_session.next_phase(), здесь
        только персистенция (тот же принцип разделения "домен считает,
        репозиторий пишет", что и update_progression_state у
        TrainingPlanRepository)."""
        training_session = await self._session.get(TrainingSession, session_id)
        training_session.phase_name = phase_name
        training_session.phase_ends_at = phase_ends_at
        training_session.current_block_index = current_block_index
        training_session.current_set_number = current_set_number
        training_session.phase_index = phase_index
        await self._session.flush()

    async def upsert_set_logs_batch(self, session_id: int, entries: list[BatchSetLogInput]) -> None:
        """Батч-эндпоинт офлайн-контракта — идемпотентен по (session_id,
        set_index): повтор с ТЕМИ ЖЕ значениями — no-op по результату
        (перезаписывает тем же самым), повтор с ДРУГИМИ значениями —
        осознанная правка (не просто дедуп, см. докстринг задачи волны:
        "тихо отбрасывает дубли" относится к отсутствию новой строки, не к
        отказу применить исправленное значение).

        set_number новых строк — (число уже существующих SetLog этого
        session_block_id) + 1 НА МОМЕНТ ОБРАБОТКИ, считается по ходу цикла
        (не одним запросом до цикла) — иначе батч из нескольких новых
        подходов одного блока получил бы одинаковый set_number вместо
        1,2,3."""
        blocks_result = await self._session.execute(
            select(SessionBlock).where(SessionBlock.session_id == session_id),
        )
        block_by_exercise_id: dict[int, SessionBlock] = {
            block.exercise_id: block for block in blocks_result.scalars().all() if block.exercise_id is not None
        }

        exercise_ids = {entry.exercise_id for entry in entries}
        exercises_result = await self._session.execute(select(Exercise).where(Exercise.id.in_(exercise_ids)))
        metric_type_by_exercise_id = {exercise.id: exercise.metric_type for exercise in exercises_result.scalars()}

        existing_logs_result = await self._session.execute(
            select(SetLog).where(SetLog.session_id == session_id),
        )
        existing_logs = list(existing_logs_result.scalars().all())
        existing_by_set_index: dict[int, SetLog] = {
            log.set_index: log for log in existing_logs if log.set_index is not None
        }
        count_by_block_id: dict[int, int] = {}
        for log in existing_logs:
            count_by_block_id[log.session_block_id] = count_by_block_id.get(log.session_block_id, 0) + 1

        for entry in entries:
            block = block_by_exercise_id.get(entry.exercise_id)
            if block is None:
                raise ValueError(
                    f"Упражнение {entry.exercise_id} не найдено среди блоков сессии {session_id}",
                )
            metric_type = metric_type_by_exercise_id[entry.exercise_id]
            unit = DEFAULT_UNIT_BY_METRIC_TYPE[metric_type]

            existing = existing_by_set_index.get(entry.set_index)
            if existing is not None:
                existing.value = entry.value
                existing.effort = entry.effort
                existing.note = entry.note
                existing.metric_type = metric_type
                existing.unit = unit
                continue

            count_by_block_id[block.id] = count_by_block_id.get(block.id, 0) + 1
            new_log = SetLog(
                session_block_id=block.id, session_id=session_id, set_index=entry.set_index,
                set_number=count_by_block_id[block.id], is_max_set=False, metric_type=metric_type,
                value=entry.value, unit=unit, effort=entry.effort, note=entry.note,
            )
            self._session.add(new_log)
            existing_by_set_index[entry.set_index] = new_log

        await self._session.flush()

    async def update_set_logs_for_blocks(
        self, *, session_block_ids_with_sets: list[tuple[int, list[SetLogInput]]],
    ) -> None:
        """Перезаписывает SetLog конкретных SessionBlock новыми значениями —
        используется правкой исторической сессии (app.services.
        progression_cascade.apply, раздел 10.6 docs/plan-and-specs.md
        "Редактирование сессии из плана"). DELETE+INSERT по
        session_block_id, не upsert по (session_id, set_index): сессии
        старого пути (POST /api/v2/sessions), которые единственно
        поддерживают правку на этой волне, никогда не заполняют
        session_id/set_index на своих SetLog (см. докстринг SetLog в
        app.db.models_program) — upsert-ключ живой сессии здесь неприменим."""
        for session_block_id, sets in session_block_ids_with_sets:
            await self._session.execute(delete(SetLog).where(SetLog.session_block_id == session_block_id))
            for set_log in sets:
                self._session.add(
                    SetLog(
                        session_block_id=session_block_id, set_number=set_log.set_number,
                        is_max_set=set_log.is_max_set, metric_type=set_log.metric_type,
                        value=set_log.value, unit=set_log.unit, effort=set_log.effort, note=set_log.note,
                    ),
                )
        await self._session.flush()

    async def mark_completed(self, session_id: int) -> None:
        """Завершение живой сессии — status/phase_name/phase_ends_at только;
        "зачтено ли что-то в прогрессию" (abandoned) — транзитная деталь
        запроса, не состояние сессии, поэтому не персистится здесь (решает
        app.services.live_session.complete_session, вызывающий этот метод
        одинаково в обоих случаях)."""
        training_session = await self._session.get(TrainingSession, session_id)
        training_session.status = SessionStatus.COMPLETED
        training_session.phase_name = SessionPhase.DONE
        training_session.phase_ends_at = None
        await self._session.flush()

    async def save_interval_block_result(self, block_id: int, result: dict) -> None:
        """Phase B1 (issue #215): сохранение result для interval SessionBlock
        после lazy finalization. Вызывается только для interval blocks, не
        для standard STEP/manual path (те не имеют result вообще)."""
        block = await self._session.get(SessionBlock, block_id)
        block.result = result
        await self._session.flush()

    async def _load_details(self, sessions: list[TrainingSession]) -> list[SessionDetail]:
        if not sessions:
            return []
        session_ids = [s.id for s in sessions]
        blocks_result = await self._session.execute(
            select(SessionBlock).where(SessionBlock.session_id.in_(session_ids)).order_by(
                SessionBlock.session_id, SessionBlock.order_index,
            ),
        )
        blocks = list(blocks_result.scalars().all())

        block_ids = [b.id for b in blocks]
        set_logs_by_block: dict[int, list[SetLog]] = {block_id: [] for block_id in block_ids}
        set_targets_by_block: dict[int, list[SetTarget]] = {block_id: [] for block_id in block_ids}
        if block_ids:
            logs_result = await self._session.execute(
                select(SetLog).where(SetLog.session_block_id.in_(block_ids)).order_by(
                    SetLog.session_block_id, SetLog.set_number,
                ),
            )
            for log in logs_result.scalars().all():
                set_logs_by_block[log.session_block_id].append(log)

            targets_result = await self._session.execute(
                select(SetTarget).where(SetTarget.session_block_id.in_(block_ids)).order_by(
                    SetTarget.session_block_id, SetTarget.set_number,
                ),
            )
            for target in targets_result.scalars().all():
                set_targets_by_block[target.session_block_id].append(target)

        blocks_by_session: dict[int, list[SessionBlock]] = {session_id: [] for session_id in session_ids}
        for block in blocks:
            blocks_by_session[block.session_id].append(block)

        details = []
        for session_row in sessions:
            block_details = [
                SessionBlockDetail(
                    id=block.id, order_index=block.order_index,
                    exercise_id=block.exercise_id, complex_id=block.complex_id,
                    set_logs=[
                        SessionSetLogDetail(
                            set_number=log.set_number, is_max_set=log.is_max_set, metric_type=log.metric_type,
                            value=log.value, unit=log.unit, effort=log.effort, note=log.note,
                        )
                        for log in set_logs_by_block[block.id]
                    ],
                    set_targets=[
                        SessionSetTargetDetail(
                            set_number=target.set_number, is_max_set=target.is_max_set,
                            metric_type=target.metric_type, value=target.value, unit=target.unit,
                        )
                        for target in set_targets_by_block[block.id]
                    ],
                    result=block.result,
                )
                for block in blocks_by_session[session_row.id]
            ]
            details.append(
                SessionDetail(
                    id=session_row.id, source=session_row.source, status=session_row.status,
                    performed_at=session_row.performed_at, effort=session_row.effort,
                    comment=session_row.comment, client_session_id=session_row.client_session_id,
                    phase_name=session_row.phase_name, phase_ends_at=session_row.phase_ends_at,
                    current_block_index=session_row.current_block_index,
                    current_set_number=session_row.current_set_number, phase_index=session_row.phase_index,
                    workout_snapshot=session_row.workout_snapshot,
                    blocks=block_details,
                ),
            )
        return details

    async def list_for_user(
        self, user_id: int, *, limit: int = 50, offset: int = 0, status: SessionStatus | None = None,
    ) -> list[SessionDetail]:
        """offset/limit — срез уже загруженного списка (тот же приём, что
        GET /api/history, issue #50), не отдельный SQL LIMIT/OFFSET —
        типичный объём истории одного пользователя не требует БД-пагинации,
        см. CLAUDE.md.

        status (Checkpoint 4C, issue #188) — опциональный фильтр, default
        None сохраняет старое поведение (и STARTED, и COMPLETED) для уже
        существующих потребителей (SessionV2Lab.tsx/SessionJournalScreen.tsx
        через GET /sessions без параметра). Журналу обычного пользователя
        нужны только завершённые — раздел 3 задачи явно требует не менять
        поведение без параметра."""
        query = select(TrainingSession).where(TrainingSession.user_id == user_id)
        if status is not None:
            query = query.where(TrainingSession.status == status)
        result = await self._session.execute(query.order_by(TrainingSession.performed_at.desc()))
        all_sessions = list(result.scalars().all())
        page = all_sessions[offset:offset + limit]
        return await self._load_details(page)

    async def get_for_user(self, session_id: int, user_id: int) -> SessionDetail | None:
        result = await self._session.execute(
            select(TrainingSession).where(TrainingSession.id == session_id, TrainingSession.user_id == user_id),
        )
        training_session = result.scalar_one_or_none()
        if training_session is None:
            return None
        details = await self._load_details([training_session])
        return details[0]

    async def list_for_user_by_exercise_ids(self, user_id: int, exercise_ids: list[int]) -> list[SessionDetail]:
        """Все сессии пользователя, у которых ЕСТЬ хотя бы один SessionBlock
        с exercise_id из exercise_ids — используется app.services.
        progression_cascade для сбора всей цепочки сессий STEP-роли
        block_a/block_b без прохода через SessionPlanItem/PlanItem
        (упрощённый путь, см. план задачи: "or more simply..."). Порядок
        по performed_at ВОЗРАСТАЮЩИЙ (не убывающий, как list_for_user) —
        цепочка прогрессии реплеится от старой сессии к новой."""
        if not exercise_ids:
            return []
        result = await self._session.execute(
            select(TrainingSession.id)
            .join(SessionBlock, SessionBlock.session_id == TrainingSession.id)
            .where(TrainingSession.user_id == user_id, SessionBlock.exercise_id.in_(exercise_ids))
            .distinct()
        )
        session_ids = [row[0] for row in result.all()]
        if not session_ids:
            return []
        sessions_result = await self._session.execute(
            select(TrainingSession).where(TrainingSession.id.in_(session_ids)).order_by(
                TrainingSession.performed_at,
            ),
        )
        return await self._load_details(list(sessions_result.scalars().all()))
