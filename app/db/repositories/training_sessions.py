import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import ColumnElement, and_, delete, distinct, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import (
    Exercise,
    ExerciseCategory,
    PlanItem,
    SessionBlock,
    SessionPhase,
    SessionPlanItem,
    SessionStatus,
    SetLog,
    SetTarget,
    TrainingSession,
)
from app.domain.constants import ExerciseType
from app.domain.exercise_identity import CATEGORY_LABELS, analytics_identity, exercise_display_label
from app.domain.live_session import DEFAULT_UNIT_BY_METRIC_TYPE
from app.domain.multi_program import INTERNAL_ROLE_SUBCATEGORIES, MetricType, SessionSource
from app.domain.plan_occurrence import MAIN_SLOT_KEY
from app.domain.training_session_v2 import (
    MANUAL_SOURCES,
    DurationSource,
    SessionKind,
    SessionOrigin,
    SessionSourceV2,
    SessionTimes,
    SetStatus,
    clone_source,
    legacy_source_v2,
    measured_duration,
    move_session_date,
)


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
    kind: str | None = None  # issue #307: SetKind цели


def target_kind(target: SetTargetInput) -> str:
    """SetKind цели (issue #307) из metric_type + is_max_set — то, что уже знает SetTarget."""
    time_based = target.metric_type == MetricType.TIME
    if target.is_max_set:
        return "max_time" if time_based else "max_reps"
    return "time" if time_based else "reps"


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
    # REBUILD-1 (R1): порядковый индекс блока, для которого клиент записал
    # подход. Нужен, потому что одно упражнение может встречаться в
    # тренировке несколько раз, а отложенный офлайн-батч может дойти уже
    # после перехода сервера к следующему блоку. None — старый клиент:
    # берётся текущий блок сессии.
    block_index: int | None = None
    # issue #264: подход сверх плана («+ Ещё подход»).
    is_extra: bool = False


@dataclass(frozen=True)
class SessionSetLogDetail:
    set_number: int
    is_max_set: bool
    metric_type: MetricType
    value: Decimal
    unit: str
    effort: Decimal | None
    note: str | None
    is_extra: bool = False
    # #292: ключ идемпотентности живой сессии — клиент перезаписывает ИМ ЖЕ
    # переоткрытый подход (None у записей не-live пути).
    set_index: int | None = None
    # issue #307: performed | not_performed (TRAINING_SESSION_V2 §3).
    status: str = SetStatus.PERFORMED.value


@dataclass(frozen=True)
class SessionSetTargetDetail:
    set_number: int
    is_max_set: bool
    metric_type: MetricType
    value: Decimal
    unit: str
    kind: str | None = None  # issue #307: SetKind цели; None у истории


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
    started_at: datetime | None = None
    block_key: str | None = None


@dataclass(frozen=True)
class SessionV2Stamp:
    """Поля TrainingSession v2 (issue #307, TRAINING_SESSION_V2 §2), которые пишет канонический слой
    app.services.training_session_v2 при создании сессии. source_v2/kind/origin задаются при создании и
    потом не выводятся заново (кроме детерминированного backfill строк старого кода)."""

    kind: str
    source_v2: str
    origin: str = SessionOrigin.NATIVE.value
    workout_definition_id: int | None = None
    workout_definition_version_id: int | None = None
    prescription_snapshot: dict | None = None
    program_inclusion_id: int | None = None
    started_at: datetime | None = None
    timezone: str | None = None
    duration_seconds: int | None = None
    duration_source: str | None = None
    distance_meters: int | None = None
    engine_version: int | None = None


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
    completed_at: datetime | None = None
    client_session_id: uuid.UUID | None = None
    phase_name: SessionPhase = SessionPhase.DONE
    phase_ends_at: datetime | None = None
    current_block_index: int = 0
    current_set_number: int = 1
    phase_index: int = 0
    workout_snapshot: dict | None = None
    activity_type: str | None = None
    duration_seconds: int | None = None
    blocks: list[SessionBlockDetail] = field(default_factory=list)
    # issue #304: явно засчитанное занятие плана (PL2); None — прямой старт / копия / ручная запись.
    plan_item_id: int | None = None
    # --- issue #307 (TRAINING_SESSION_V2 §2). source_v2/kind/origin всегда заполнены: у строки старого
    # кода (NULL в БД) — выведены тем же legacy_source_v2, что и backfill.
    kind: str = "strength"
    source_v2: str = SessionSourceV2.MANUAL_CUSTOM.value
    origin: str = SessionOrigin.NATIVE.value
    workout_definition_id: int | None = None
    workout_definition_version_id: int | None = None
    prescription_snapshot: dict | None = None
    program_inclusion_id: int | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_source: str | None = None
    timezone: str | None = None
    distance_meters: int | None = None
    revision: int = 0
    engine_version: int | None = None
    superseded_by_id: int | None = None
    legacy_id: int | None = None
    superseded_at: datetime | None = None
    identity_recovered_by: str | None = None


@dataclass(frozen=True)
class ExerciseCatalogInfo:
    """Каталожная идентичность блока для Журнала/Аналитики (E1/E2, #308): identity_id = analytics_identity,
    label — display_name идентичности (никогда не slug), category/subcategory — ключ или подпись категории
    САМОГО упражнения блока (человеческую подпись выдаёт app.domain.exercise_identity)."""

    id: int
    identity_id: int
    label: str
    category: str | None
    subcategory: str | None


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
        completed_at: datetime | None = None, activity_type: str | None = None,
        duration_seconds: int | None = None, targets_by_block: list[list[SetTargetInput]] | None = None,
        workout_snapshot: dict | None = None, client_session_id: uuid.UUID | None = None,
    ) -> TrainingSession:
        """Завершённая сессия одним запросом (ручная запись Журнала, запись программы).

        issue #307: targets_by_block — рецепт известной тренировки (manual_existing_workout; тот же
        резолв, что у живого старта). Тогда каждый факт связывается со своей целью ПО ПОРЯДКУ в блоке
        (set_target_id) и наследует её is_max_set (R2); цели без факта — невыполненные подходы (R1).
        Факты сверх числа целей пишутся как is_extra. workout_snapshot — тот же v1-снимок, что пишет
        живой старт. client_session_id — ключ идемпотентности ручной записи (тот же глобально
        уникальный столбец, что у живого старта)."""
        training_session = TrainingSession(
            user_id=user_id, source=source, status=SessionStatus.COMPLETED,
            performed_at=performed_at, effort=effort, comment=comment,
            completed_at=completed_at if completed_at is not None else datetime.now(UTC),
            activity_type=activity_type, duration_seconds=duration_seconds, client_session_id=client_session_id,
        )
        if workout_snapshot is not None:
            # JSONB: явный None записался бы JSON-значением 'null', а не SQL NULL — и предикаты
            # «workout_snapshot IS NULL» (отпечаток backfill-копий, история тренировки) перестали бы работать.
            training_session.workout_snapshot = workout_snapshot
        self._session.add(training_session)
        await self._session.flush()

        for order_index, block in enumerate(blocks):
            session_block = SessionBlock(
                session_id=training_session.id, order_index=order_index,
                exercise_id=block.exercise_id, complex_id=block.complex_id,
            )
            self._session.add(session_block)
            await self._session.flush()
            targets: list[SetTarget] = []
            for target in (targets_by_block[order_index] if targets_by_block is not None else []):
                row = SetTarget(
                    session_block_id=session_block.id, set_number=target.set_number,
                    is_max_set=target.is_max_set, metric_type=target.metric_type,
                    value=target.value, unit=target.unit, kind=target.kind or target_kind(target),
                )
                self._session.add(row)
                targets.append(row)
            if targets:
                await self._session.flush()
            for position, set_log in enumerate(sorted(block.sets, key=lambda s: s.set_number)):
                target = targets[position] if position < len(targets) else None
                self._session.add(
                    SetLog(
                        session_block_id=session_block.id, set_number=set_log.set_number,
                        set_target_id=target.id if target is not None else None,
                        is_max_set=set_log.is_max_set or (target is not None and target.is_max_set),
                        is_extra=targets_by_block is not None and target is None,
                        metric_type=set_log.metric_type,
                        value=set_log.value, unit=set_log.unit, effort=set_log.effort, note=set_log.note,
                    ),
                )
        await self._session.flush()
        return training_session

    async def create_live_session(
        self, *, user_id: int, client_session_id: uuid.UUID, source: SessionSource, performed_at: datetime,
        plan_item_ids: list[int], blocks: list[SessionBlockInput], targets_by_block: list[list[SetTargetInput]],
        phase_ends_at: datetime | None, workout_snapshot: dict | None = None, plan_item_id: int | None = None,
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
            workout_snapshot=workout_snapshot, plan_item_id=plan_item_id,
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
                        value=target.value, unit=target.unit, kind=target.kind or target_kind(target),
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
        by_session: dict[int, list[int]] = {}
        # issue #304: явный кредит (training_sessions.plan_item_id) — первым; старая M2M — история.
        explicit = await self._session.execute(
            select(TrainingSession.id, TrainingSession.plan_item_id).where(
                TrainingSession.id.in_(session_ids), TrainingSession.plan_item_id.is_not(None),
            ),
        )
        for session_id, plan_item_id in explicit.all():
            by_session.setdefault(session_id, []).append(plan_item_id)
        result = await self._session.execute(
            select(SessionPlanItem).where(SessionPlanItem.session_id.in_(session_ids)).order_by(SessionPlanItem.id),
        )
        for row in result.scalars().all():
            ids = by_session.setdefault(row.session_id, [])
            if row.plan_item_id not in ids:
                ids.append(row.plan_item_id)
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
        1,2,3.

        Конкурентность (fix/concurrent-set-batch): реконнект и тап
        "Завершить" могли одновременно дослать ОДИН И ТОТ ЖЕ батч — оба
        запроса видели "строки нет" и оба делали INSERT, второй падал на
        uq_set_logs_session_set_index (500). Теперь весь батч идёт под
        SELECT ... FOR UPDATE строки сессии (тот же lock_session, что у
        complete/start_block — единый порядок блокировок, без дедлоков):
        второй запрос ждёт коммита первого и в READ COMMITTED уже видит его
        строки — становится обычным идемпотентным повтором, и set_number
        считается по реальному, а не устаревшему содержимому блока. Новые
        строки вставляются INSERT ... ON CONFLICT (session_id, set_index)
        DO UPDATE — страховка на уровне БД: даже писатель в обход блокировки
        не может вернуть 500 на дубле, только сойтись к одной строке."""
        training_session = await self.lock_session(session_id)
        current_block_index = training_session.current_block_index
        blocks_result = await self._session.execute(
            select(SessionBlock).where(SessionBlock.session_id == session_id).order_by(SessionBlock.order_index),
        )
        blocks = list(blocks_result.scalars().all())

        # Повтор set_index внутри одного батча — последняя запись побеждает
        # (как и раньше: вторая перезаписывала первую), строка одна.
        unique_entries = list({entry.set_index: entry for entry in entries}.values())

        exercise_ids = {entry.exercise_id for entry in unique_entries}
        exercises_result = await self._session.execute(select(Exercise).where(Exercise.id.in_(exercise_ids)))
        metric_type_by_exercise_id = {exercise.id: exercise.metric_type for exercise in exercises_result.scalars()}

        # populate_existing: SetLog этой сессии могли попасть в identity map
        # раньше (get_for_user до блокировки) — после ожидания блокировки
        # нужны закоммиченные конкурентом значения, не кэш сессии.
        existing_logs_result = await self._session.execute(
            select(SetLog).where(SetLog.session_id == session_id).execution_options(populate_existing=True),
        )
        existing_logs = list(existing_logs_result.scalars().all())
        existing_by_set_index: dict[int, SetLog] = {
            log.set_index: log for log in existing_logs if log.set_index is not None
        }
        count_by_block_id: dict[int, int] = {}
        for log in existing_logs:
            count_by_block_id[log.session_block_id] = count_by_block_id.get(log.session_block_id, 0) + 1

        for entry in unique_entries:
            block = self._resolve_batch_block(blocks, entry, current_block_index)
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
                existing.is_extra = entry.is_extra
                continue

            count_by_block_id[block.id] = count_by_block_id.get(block.id, 0) + 1
            insert_stmt = pg_insert(SetLog).values(
                session_block_id=block.id, session_id=session_id, set_index=entry.set_index,
                set_number=count_by_block_id[block.id], is_max_set=False, metric_type=metric_type,
                value=entry.value, unit=unit, effort=entry.effort, note=entry.note, is_extra=entry.is_extra,
            )
            await self._session.execute(
                insert_stmt.on_conflict_do_update(
                    constraint="uq_set_logs_session_set_index",
                    set_={
                        "value": insert_stmt.excluded.value, "effort": insert_stmt.excluded.effort,
                        "note": insert_stmt.excluded.note, "metric_type": insert_stmt.excluded.metric_type,
                        "unit": insert_stmt.excluded.unit, "is_extra": insert_stmt.excluded.is_extra,
                    },
                ),
            )

        await self._session.flush()

    @staticmethod
    def _resolve_batch_block(
        blocks: list[SessionBlock], entry: BatchSetLogInput, current_block_index: int,
    ) -> SessionBlock | None:
        """REBUILD-1 (R1, инвариант H): подход адресуется БЛОКОМ, не только
        exercise_id — иначе повтор одного упражнения в тренировке писал бы
        все подходы в один и тот же блок. Явный block_index проверяется на
        совпадение упражнения (чужой/сбитый индекс — не запись в чужой блок,
        а ошибка); без block_index (старый клиент) — текущий блок сессии,
        если упражнение совпало, иначе первый блок с этим упражнением (как
        раньше)."""
        if entry.block_index is not None:
            block = next((b for b in blocks if b.order_index == entry.block_index), None)
            if block is None or block.exercise_id != entry.exercise_id:
                return None
            return block
        current = next((b for b in blocks if b.order_index == current_block_index), None)
        if current is not None and current.exercise_id == entry.exercise_id:
            return current
        return next((b for b in blocks if b.exercise_id == entry.exercise_id), None)

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

    async def save_workout_review(
        self, session_id: int, *, effort: Decimal | None, comment: str | None,
    ) -> None:
        """Оценка тренировки целиком (эффорт 1–5 + заметка) при завершении.
        None-значения никогда не затирают сохранённое: повторный complete
        без полей (или с другими) ничего не портит — заполняется только пустое."""
        training_session = await self._session.get(TrainingSession, session_id)
        if effort is not None and training_session.effort is None:
            training_session.effort = effort
        if comment is not None and training_session.comment is None:
            training_session.comment = comment
        await self._session.flush()

    async def mark_completed(
        self, session_id: int, completed_at: datetime | None = None, *, active_elapsed_ms: int | None = None,
    ) -> None:
        """Завершение живой сессии — status/phase_name/phase_ends_at;
        "зачтено ли что-то в прогрессию" (abandoned) — транзитная деталь
        запроса, не состояние сессии, поэтому не персистится здесь (решает
        app.services.live_session.complete_session, вызывающий этот метод
        одинаково в обоих случаях).

        issue #307 (R3): здесь же — ЕДИНСТВЕННОЕ место, где живая сессия получает ended_at и
        длительность (через него проходят complete, finish interval и ленивая финализация интервала).
        active_elapsed_ms — от движка v2 (#306, паузы исключены); без него — стенные часы
        started_at (или performed_at) → completed_at в окне [1 мин, 6 ч], иначе unknown."""
        training_session = await self._session.get(TrainingSession, session_id)
        training_session.status = SessionStatus.COMPLETED
        training_session.completed_at = completed_at if completed_at is not None else datetime.now(UTC)
        training_session.phase_name = SessionPhase.DONE
        training_session.phase_ends_at = None
        training_session.ended_at = training_session.completed_at
        duration = measured_duration(
            training_session.started_at or training_session.performed_at, training_session.ended_at,
            active_elapsed_ms=active_elapsed_ms,
        )
        training_session.duration_seconds = duration.seconds
        training_session.duration_source = duration.source.value
        await self._session.flush()

    async def set_prescription_snapshot(self, session_id: int, snapshot: dict) -> None:
        """Снимок рецепта пишется один раз (S1) — только туда, где его ещё нет."""
        training_session = await self._session.get(TrainingSession, session_id)
        if training_session.prescription_snapshot is None:
            training_session.prescription_snapshot = snapshot
            await self._session.flush()

    async def apply_v2_stamp(self, session_id: int, stamp: SessionV2Stamp) -> None:
        """Записывает поля v2 только что созданной сессии (тот же запрос/транзакция, что и создание)."""
        training_session = await self._session.get(TrainingSession, session_id)
        training_session.kind = stamp.kind
        training_session.source_v2 = stamp.source_v2
        training_session.origin = stamp.origin
        training_session.workout_definition_id = stamp.workout_definition_id
        training_session.workout_definition_version_id = stamp.workout_definition_version_id
        if stamp.prescription_snapshot is not None:  # JSONB: None — не JSON 'null' (см. create_session)
            training_session.prescription_snapshot = stamp.prescription_snapshot
        training_session.program_inclusion_id = stamp.program_inclusion_id
        training_session.started_at = stamp.started_at
        training_session.timezone = stamp.timezone
        training_session.distance_meters = stamp.distance_meters
        training_session.engine_version = stamp.engine_version
        if stamp.duration_source is not None:
            training_session.duration_seconds = stamp.duration_seconds
            training_session.duration_source = stamp.duration_source
        await self._session.flush()

    async def delete_session(self, session_id: int) -> None:
        """Удаляет ТОЛЬКО дерево TrainingSession: session_plan_items,
        session_blocks, set_targets, set_logs уходят каскадом FK (ondelete=
        CASCADE). Определения (Complex/ComplexItem/Exercise) и PlanItem не
        затрагиваются — на них у дерева сессии нет каскада."""
        await self._session.execute(delete(TrainingSession).where(TrainingSession.id == session_id))
        await self._session.flush()

    async def lock_session(self, session_id: int) -> TrainingSession | None:
        """SELECT ... FOR UPDATE строки сессии — сериализует конкурентные
        start/finish блока (двойной клик, два вкладки), батчи подходов и
        завершение, чтобы проверки ("блок ещё не начат", "строки ещё нет",
        "сессия ещё не завершена") и последующая запись не гонялись.
        populate_existing: после ожидания блокировки строка в identity map
        обновляется закоммиченным конкурентом состоянием (иначе status/
        current_block_index остались бы из снимка ДО блокировки)."""
        result = await self._session.execute(
            select(TrainingSession).where(TrainingSession.id == session_id).with_for_update()
            .execution_options(populate_existing=True),
        )
        return result.scalar_one_or_none()

    async def mark_block_started(self, block_id: int, started_at: datetime) -> None:
        block = await self._session.get(SessionBlock, block_id)
        block.started_at = started_at
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
            ).execution_options(populate_existing=True),
        )
        blocks = list(blocks_result.scalars().all())

        block_ids = [b.id for b in blocks]
        set_logs_by_block: dict[int, list[SetLog]] = {block_id: [] for block_id in block_ids}
        set_targets_by_block: dict[int, list[SetTarget]] = {block_id: [] for block_id in block_ids}
        if block_ids:
            logs_result = await self._session.execute(
                select(SetLog).where(SetLog.session_block_id.in_(block_ids)).order_by(
                    SetLog.session_block_id, SetLog.set_number,
                ).execution_options(populate_existing=True),
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
                            is_extra=log.is_extra, set_index=log.set_index, status=log.status,
                        )
                        for log in set_logs_by_block[block.id]
                    ],
                    set_targets=[
                        SessionSetTargetDetail(
                            set_number=target.set_number, is_max_set=target.is_max_set,
                            metric_type=target.metric_type, value=target.value, unit=target.unit,
                            kind=target.kind,
                        )
                        for target in set_targets_by_block[block.id]
                    ],
                    result=block.result, started_at=block.started_at, block_key=block.block_key,
                )
                for block in blocks_by_session[session_row.id]
            ]
            details.append(
                SessionDetail(
                    id=session_row.id, source=session_row.source, status=session_row.status,
                    performed_at=session_row.performed_at, effort=session_row.effort,
                    comment=session_row.comment, completed_at=session_row.completed_at, client_session_id=session_row.client_session_id,
                    phase_name=session_row.phase_name, phase_ends_at=session_row.phase_ends_at,
                    current_block_index=session_row.current_block_index,
                    current_set_number=session_row.current_set_number, phase_index=session_row.phase_index,
                    workout_snapshot=session_row.workout_snapshot,
                    activity_type=session_row.activity_type, duration_seconds=session_row.duration_seconds,
                    blocks=block_details, plan_item_id=session_row.plan_item_id,
                    kind=session_row.kind or ("external_activity" if session_row.activity_type else "strength"),
                    source_v2=session_row.source_v2 or legacy_source_v2(
                        legacy_source=SessionSource(session_row.source).value,
                        has_activity=session_row.activity_type is not None,
                        has_workout_snapshot=session_row.workout_snapshot is not None,
                        is_live=session_row.client_session_id is not None,
                    ).value,
                    origin=session_row.origin or (
                        SessionOrigin.LEGACY_ELECTIVE.value if session_row.source == SessionSource.ELECTIVE
                        else SessionOrigin.NATIVE.value
                    ),
                    workout_definition_id=session_row.workout_definition_id,
                    workout_definition_version_id=session_row.workout_definition_version_id,
                    prescription_snapshot=session_row.prescription_snapshot,
                    program_inclusion_id=session_row.program_inclusion_id,
                    started_at=session_row.started_at, ended_at=session_row.ended_at,
                    duration_source=session_row.duration_source, timezone=session_row.timezone,
                    distance_meters=session_row.distance_meters, revision=session_row.revision,
                    engine_version=session_row.engine_version, superseded_by_id=session_row.superseded_by_id,
                    legacy_id=session_row.legacy_id, superseded_at=session_row.superseded_at,
                    identity_recovered_by=session_row.identity_recovered_by,
                ),
            )
        return details

    async def list_for_user(
        self, user_id: int, *, limit: int = 50, offset: int = 0, status: SessionStatus | None = None,
        performed_from: datetime | None = None, performed_to: datetime | None = None,
        exclude_legacy_cards: bool = False,
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
        поведение без параметра.

        performed_from/performed_to (#256) — полуинтервал [from, to) по
        performed_at (Журнал по месяцам), оба необязательны.

        Замещённые (superseded_at) строки не возвращаются никогда (A6): удалённая/пересведённая legacy-запись
        не воскресает в списке.

        exclude_legacy_cards (#284 → #308) — скрыть нативные копии legacy Workout (origin = legacy_backfill):
        их показывает legacy-карточка («Изменить»/«Удалить» старой схемы). Это ПРЕДСТАВЛЕНИЕ, а не счёт:
        такие сессии входят в canonical_sessions и в каждый итог ровно один раз. Срез offset/limit
        считается уже после скрытия."""
        query = select(TrainingSession).where(TrainingSession.user_id == user_id, self.not_superseded())
        if exclude_legacy_cards:
            query = query.where(self.is_not_legacy_card())
        if status is not None:
            query = query.where(TrainingSession.status == status)
        if performed_from is not None:
            query = query.where(TrainingSession.performed_at >= performed_from)
        if performed_to is not None:
            query = query.where(TrainingSession.performed_at < performed_to)
        result = await self._session.execute(query.order_by(TrainingSession.performed_at.desc()))
        all_sessions = list(result.scalars().all())
        page = all_sessions[offset:offset + limit]
        return await self._load_details(page)

    async def completed_performed_at(
        self, user_id: int, performed_from: datetime, performed_to: datetime,
    ) -> list[datetime]:
        """Только моменты canonical_sessions в [from, to) — для календаря Журнала (без загрузки
        блоков/подходов). Тот же предикат, что у списка Журнала, Профиля и Аналитики (A1)."""
        query = select(TrainingSession.performed_at).where(
            TrainingSession.user_id == user_id, self.canonical_predicate(),
            TrainingSession.performed_at >= performed_from,
            TrainingSession.performed_at < performed_to,
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def count_completed(self, user_id: int) -> int:
        """total_workouts: число canonical_sessions пользователя (сводка Профиля, #277; A1) — целое,
        count(distinct id) по тому же предикату, что Журнал и Аналитика."""
        query = select(func.count(distinct(TrainingSession.id))).where(
            TrainingSession.user_id == user_id, self.canonical_predicate(),
        )
        result = await self._session.execute(query)
        return int(result.scalar_one())

    # --- canonical_sessions (TRAINING_SESSION_V2 §6, MIGRATION_V2 §4) -----------------------------

    @staticmethod
    def not_superseded() -> ColumnElement[bool]:
        """A6: строка не замещена (её legacy-запись удалена/пересведена или она дублирует нативную)."""
        return TrainingSession.superseded_at.is_(None)

    @classmethod
    def canonical_predicate(cls) -> ColumnElement[bool]:
        """ЕДИНСТВЕННЫЙ предикат «настоящая завершённая тренировка» (A1/A6): status = completed ∧ не
        замещена. Календарь/список Журнала, итог Профиля, Аналитика и экспорт читают его же — отдельных
        эвристик исключения (отпечатков, флагов по эндпоинтам) больше нет. «Не архивирована» в схеме
        TrainingSession выражается тем же superseded_at: архивирование определения (complexes.archived_at)
        сессии не скрывает."""
        return and_(TrainingSession.status == SessionStatus.COMPLETED, cls.not_superseded())

    @staticmethod
    def is_not_legacy_card() -> ColumnElement[bool]:
        """Представление Журнала: нативная копия legacy Workout (origin = legacy_backfill) показана
        legacy-карточкой старой схемы, v2-карточкой её не дублируем. Электив (legacy_elective) и всё
        нативное показываются v2-карточкой. Явный origin, а не отпечаток; строка без origin (код до #307
        в окне деплоя) читается как нативная — её классифицирует backfill-скрипт."""
        return or_(
            TrainingSession.origin.is_(None), TrainingSession.origin != SessionOrigin.LEGACY_BACKFILL.value,
        )

    @staticmethod
    def legacy_copy_fingerprint_for_recovery() -> ColumnElement[bool]:
        """ТОЛЬКО для восстановления (scripts/backfill_*): отпечаток копии legacy Workout, созданной
        backfill-ом до origin/legacy_id (#163/#284), — чтобы классифицировать строки, у которых origin ещё
        NULL (окно деплоя). Ни один читатель Журнала/Профиля/Аналитики его не использует (A6)."""
        block_a_first = exists().where(
            SessionBlock.session_id == TrainingSession.id, SessionBlock.order_index == 0,
            SessionBlock.exercise_id == Exercise.id,
            Exercise.category == ExerciseType.PULL_UPS.value, Exercise.subcategory == "block_a",
            Exercise.source_type == "system", Exercise.owner_user_id.is_(None),
        )
        has_plan_items = exists().where(SessionPlanItem.session_id == TrainingSession.id)
        return and_(
            TrainingSession.status == SessionStatus.COMPLETED,
            TrainingSession.source.in_((SessionSource.PLAN, SessionSource.FREEFORM, SessionSource.BACKDATED)),
            TrainingSession.client_session_id.is_(None),
            TrainingSession.workout_snapshot.is_(None),
            TrainingSession.activity_type.is_(None),
            TrainingSession.plan_item_id.is_(None),
            ~has_plan_items,
            block_a_first,
        )

    async def latest_completed_performed_at(self, user_id: int) -> datetime | None:
        query = select(func.max(TrainingSession.performed_at)).where(
            TrainingSession.user_id == user_id, self.canonical_predicate(),
        )
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def list_all_completed(self, user_id: int, *, exclude_legacy_cards: bool = False) -> list[SessionDetail]:
        """ВСЕ canonical_sessions пользователя (для аналитики) — не зависит от пагинации Журнала.
        Порядок — по performed_at по возрастанию. exclude_legacy_cards — как в list_for_user (CSV-экспорт:
        подробности перенесённой истории отдаёт legacy-таблица; аналитика его НЕ передаёт)."""
        query = select(TrainingSession).where(TrainingSession.user_id == user_id, self.canonical_predicate())
        if exclude_legacy_cards:
            query = query.where(self.is_not_legacy_card())
        result = await self._session.execute(query.order_by(TrainingSession.performed_at))
        return await self._load_details(list(result.scalars().all()))

    async def exercise_names(self, exercise_ids: set[int]) -> dict[int, str]:
        """Названия упражнений по id (фолбэк экспорта для сессий без снимка)."""
        if not exercise_ids:
            return {}
        result = await self._session.execute(select(Exercise.id, Exercise.name).where(Exercise.id.in_(exercise_ids)))
        return {row.id: row.name for row in result.all()}

    async def exercise_catalog(self, exercise_ids: set[int]) -> dict[int, ExerciseCatalogInfo]:
        """E1/E2 для набора упражнений блоков: analytics_identity, подпись идентичности (display_name,
        не slug) и категория/подкатегория самого упражнения (по category_id/subcategory_id, иначе — по
        старым строкам exercises.category/subcategory). Фиксированное число запросов."""
        if not exercise_ids:
            return {}
        own = (await self._session.execute(select(Exercise).where(Exercise.id.in_(exercise_ids)))).scalars().all()
        identity_ids = {analytics_identity(e.id, e.analytics_exercise_id) for e in own}
        by_id = {e.id: e for e in own}
        missing = identity_ids - set(by_id)
        if missing:
            for e in (await self._session.execute(select(Exercise).where(Exercise.id.in_(missing)))).scalars():
                by_id[e.id] = e
        category_ids = {e.category_id for e in own if e.category_id} | {e.subcategory_id for e in own if e.subcategory_id}
        categories = {}
        if category_ids:
            categories = {
                c.id: c for c in (
                    await self._session.execute(select(ExerciseCategory).where(ExerciseCategory.id.in_(category_ids)))
                ).scalars()
            }

        def category_key(category_id: int | None, legacy: str | None) -> str | None:
            row = categories.get(category_id) if category_id else None
            if row is None:
                return legacy
            return row.slug if row.slug in CATEGORY_LABELS else row.display_name

        result: dict[int, ExerciseCatalogInfo] = {}
        for e in own:
            identity_id = analytics_identity(e.id, e.analytics_exercise_id)
            identity = by_id.get(identity_id, e)
            result[e.id] = ExerciseCatalogInfo(
                id=e.id, identity_id=identity_id,
                label=exercise_display_label(identity.display_name, identity.name),
                category=category_key(e.category_id, e.category),
                subcategory=category_key(e.subcategory_id, e.subcategory),
            )
        return result

    async def exercise_categories(self, exercise_ids: set[int]) -> dict[int, tuple[str, str | None]]:
        """(category, subcategory) упражнений по id — для распределения аналитики (#274)."""
        if not exercise_ids:
            return {}
        result = await self._session.execute(
            select(Exercise.id, Exercise.category, Exercise.subcategory).where(Exercise.id.in_(exercise_ids)),
        )
        return {row.id: (row.category, row.subcategory) for row in result.all()}

    async def library_categories(self, user_id: int) -> list[tuple[str, str | None]]:
        """Различные (category, subcategory) каталога, видимого пользователю
        (system + собственные user-упражнения) — нулевые строки таблицы (#274)."""
        result = await self._session.execute(
            select(Exercise.category, Exercise.subcategory)
            .where((Exercise.source_type == "system") | (Exercise.owner_user_id == user_id))
            .distinct(),
        )
        return [(row.category, row.subcategory) for row in result.all()]

    async def list_completed_for_workout(self, user_id: int, workout_id: int) -> list[SessionDetail]:
        """Завершённые сессии пользователя этого Workout: явная идентичность (workout_definition_id,
        issue #307 — в т.ч. «Тренировку из моих») или, у строк до неё, замороженный workout_snapshot
        (workout_snapshot.workout_id). Новые первыми."""
        result = await self._session.execute(
            select(TrainingSession)
            .where(
                TrainingSession.user_id == user_id,
                self.canonical_predicate(),
                or_(
                    TrainingSession.workout_definition_id == workout_id,
                    TrainingSession.workout_snapshot["workout_id"].astext == str(workout_id),
                ),
            )
            .order_by(TrainingSession.performed_at.desc(), TrainingSession.id.desc()),
        )
        return await self._load_details(list(result.scalars().all()))

    async def get_for_user(self, session_id: int, user_id: int) -> SessionDetail | None:
        # populate_existing (здесь и в _load_details): повторное чтение после
        # lock_session обязано видеть закоммиченное конкурентом состояние, а
        # не кэш identity map из первого чтения в этом же запросе.
        result = await self._session.execute(
            select(TrainingSession).where(TrainingSession.id == session_id, TrainingSession.user_id == user_id)
            .execution_options(populate_existing=True),
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

    async def update_session_fields(
        self, session_id: int, *, performed_at: datetime | None = None,
        effort: tuple[Decimal | None] | None = None, comment: tuple[str | None] | None = None,
        duration_seconds: tuple[int | None] | None = None, activity_type: str | None = None,
        distance_meters: tuple[int | None] | None = None,
    ) -> None:
        """Правка завершённой сессии (#262, #307). Однокортежи отличают "не менять" (None) от
        "очистить" ((None,)). Блоки/подходы не трогаются.

        R4 (#307, D13): смена даты сдвигает performed_at и started/ended/completed_at на одну дельту
        (app.domain.training_session_v2.move_session_date) — duration_seconds не меняется. Раньше
        completed_at «подтягивался» к performed_at и стирал длительность. duration_seconds — введённая
        пользователем длительность (entered), (None,) — неизвестна. ED2: каждая правка — revision + 1."""
        training_session = await self._session.get(TrainingSession, session_id)
        if performed_at is not None:
            moved = move_session_date(
                SessionTimes(
                    performed_at=training_session.performed_at, started_at=training_session.started_at,
                    ended_at=training_session.ended_at, completed_at=training_session.completed_at,
                ),
                performed_at,
            )
            training_session.performed_at = moved.performed_at
            training_session.started_at = moved.started_at
            training_session.ended_at = moved.ended_at
            training_session.completed_at = moved.completed_at
        if effort is not None:
            training_session.effort = effort[0]
        if comment is not None:
            training_session.comment = comment[0]
        if duration_seconds is not None:
            training_session.duration_seconds = duration_seconds[0]
            training_session.duration_source = (
                DurationSource.ENTERED.value if duration_seconds[0] is not None else DurationSource.UNKNOWN.value
            )
        if activity_type is not None:
            training_session.activity_type = activity_type
        if distance_meters is not None:
            training_session.distance_meters = distance_meters[0]
        training_session.revision = (training_session.revision or 0) + 1
        training_session.updated_at = datetime.now(UTC)
        await self._session.flush()

    async def update_set_log(
        self, block_id: int, set_number: int, *, value: Decimal, effort: Decimal | None, note: str | None,
    ) -> bool:
        """Меняет value/effort/note существующего подхода на месте (set_target_id
        и set_index сохраняются). False — такого подхода нет."""
        result = await self._session.execute(
            select(SetLog).where(SetLog.session_block_id == block_id, SetLog.set_number == set_number),
        )
        set_log = result.scalar_one_or_none()
        if set_log is None:
            return False
        set_log.value = value
        set_log.effort = effort
        set_log.note = note
        await self._session.flush()
        return True

    # --- Явный кредит занятия и отдых MAIN (issue #304) -------------------------------------

    @staticmethod
    def main_session_predicate() -> ColumnElement[bool]:
        """«Завершённая v2-сессия — старт MAIN» (K1, app.services.plan_spacing): засчитала занятие
        main-слота (plan_item_id) ИЛИ содержит блок роли STEP (block_a/block_b) хотя бы с одним
        записанным подходом. Пустые брошенные сессии отдых не сдвигают.

        issue #307 (решение владельца): ручная/пост-фактум запись приложения (source_v2 =
        manual_existing_workout / manual_custom, origin = native) — это исторический повтор, не старт
        курса, даже если в ней (копии) есть блоки ролей STEP: она не двигает отдых MAIN, не входит в
        completed_main_sessions/last_main_session_at. Ветка ролей по-прежнему считает живые сессии курса,
        строки без source_v2 (старый код в окне деплоя) и копии legacy Workout (origin = legacy_backfill:
        так считалась история до #307 — счётчики старых пользователей не уменьшаются). Ручную запись с
        блоками ролей API не создаёт иначе как копией (#285)."""
        role_block_with_log = exists().where(
            SessionBlock.session_id == TrainingSession.id,
            SessionBlock.exercise_id == Exercise.id,
            Exercise.subcategory.in_(INTERNAL_ROLE_SUBCATEGORIES),
            exists().where(SetLog.session_block_id == SessionBlock.id),
        )
        manual_record = and_(
            # coalesce: строка без source_v2 (NULL) — не ручная; без него NOT(NULL) выкинул бы её из MAIN
            func.coalesce(TrainingSession.source_v2, "").in_([source.value for source in MANUAL_SOURCES]),
            TrainingSession.origin.is_distinct_from(SessionOrigin.LEGACY_BACKFILL.value),
        )
        credited_main = exists().where(
            PlanItem.id == TrainingSession.plan_item_id, PlanItem.program_slot_key == MAIN_SLOT_KEY,
        )
        return and_(
            TrainingSession.status == SessionStatus.COMPLETED,
            or_(credited_main, and_(role_block_with_log, ~manual_record)),
        )

    async def latest_main_session_at(self, user_id: int) -> datetime | None:
        result = await self._session.execute(
            select(func.max(TrainingSession.performed_at)).where(
                TrainingSession.user_id == user_id, self.main_session_predicate(),
            ),
        )
        return result.scalar_one_or_none()

    async def count_main_sessions(self, user_id: int) -> int:
        result = await self._session.execute(
            select(func.count(TrainingSession.id)).where(
                TrainingSession.user_id == user_id, self.main_session_predicate(),
            ),
        )
        return int(result.scalar_one())

    async def credits_for_plan_items(self, plan_item_ids: list[int]) -> list[tuple[int, int, SessionStatus, datetime]]:
        """(plan_item_id, session_id, status, performed_at) сессий, ЯВНО засчитавших занятия
        (training_sessions.plan_item_id) — STARTED и COMPLETED, по возрастанию performed_at."""
        if not plan_item_ids:
            return []
        result = await self._session.execute(
            select(
                TrainingSession.plan_item_id, TrainingSession.id, TrainingSession.status, TrainingSession.performed_at,
            )
            .where(TrainingSession.plan_item_id.in_(plan_item_ids))
            .order_by(TrainingSession.performed_at, TrainingSession.id),
        )
        return [(row[0], row[1], row[2], row[3]) for row in result.all()]

    async def credited_plan_item_ids(self, plan_item_ids: list[int]) -> set[int]:
        """Строки плана, на которые ссылается ХОТЬ ОДНА сессия (STARTED или COMPLETED): явный кредит
        (training_sessions.plan_item_id) или старая M2M-связь session_plan_items. Такая строка — история
        кредита: её нельзя удалить жёстко (FK SET NULL / CASCADE стёр бы кредит, а сходимость
        пересоздала бы занятие открытым — «1 из 2» → «0 из 2»), снять или убрать вместе с планом (#304 B1)."""
        if not plan_item_ids:
            return set()
        explicit = await self._session.execute(
            select(TrainingSession.plan_item_id).where(TrainingSession.plan_item_id.in_(plan_item_ids)),
        )
        legacy = await self._session.execute(
            select(SessionPlanItem.plan_item_id).where(SessionPlanItem.plan_item_id.in_(plan_item_ids)),
        )
        return {row[0] for row in explicit.all()} | {row[0] for row in legacy.all()}

    async def legacy_links_for_plan_items(
        self, plan_item_ids: list[int],
    ) -> list[tuple[int, int, SessionStatus, datetime, int | None]]:
        """(plan_item_id, session_id, status, performed_at, session.plan_item_id) по старой M2M-связи
        (только чтение истории) — вход разворота агрегатных строк в converge_user_plan."""
        if not plan_item_ids:
            return []
        result = await self._session.execute(
            select(
                SessionPlanItem.plan_item_id, TrainingSession.id, TrainingSession.status,
                TrainingSession.performed_at, TrainingSession.plan_item_id,
            )
            .join(TrainingSession, TrainingSession.id == SessionPlanItem.session_id)
            .where(SessionPlanItem.plan_item_id.in_(plan_item_ids))
            .order_by(TrainingSession.performed_at, TrainingSession.id),
        )
        return [(row[0], row[1], row[2], row[3], row[4]) for row in result.all()]

    async def set_plan_item_credit(self, session_id: int, plan_item_id: int | None) -> None:
        training_session = await self._session.get(TrainingSession, session_id)
        training_session.plan_item_id = plan_item_id
        await self._session.flush()

    async def clone_session(
        self, source_id: int, *, user_id: int, performed_at: datetime, stamp: SessionV2Stamp | None = None,
    ) -> TrainingSession:
        """Копия завершённой сессии (#262): новая COMPLETED-сессия source=BACKDATED
        с теми же блоками/целями/фактом/снимком, БЕЗ кредита плана (#304). Никакой
        прогрессии: ни пересчёта, ни связи с инклюзией.

        issue #307: stamp — поля v2 копии (source_v2 = manual_existing_workout / manual_custom /
        external_activity, то же определение и снимок рецепта, без plan_item_id и инклюзии,
        длительность — по правилу копии из app.services.training_session_v2). У внешней активности
        копируются тип/дистанция (раньше копия активности выходила пустой силовой записью)."""
        original = await self._session.get(TrainingSession, source_id)
        clone = TrainingSession(
            user_id=user_id, source=SessionSource.BACKDATED, status=SessionStatus.COMPLETED,
            performed_at=performed_at, completed_at=performed_at,
            effort=original.effort, comment=original.comment, workout_snapshot=original.workout_snapshot,
            activity_type=original.activity_type,
        )
        self._session.add(clone)
        await self._session.flush()

        blocks = (await self._session.execute(
            select(SessionBlock).where(SessionBlock.session_id == source_id).order_by(SessionBlock.order_index),
        )).scalars().all()
        for block in blocks:
            new_block = SessionBlock(
                session_id=clone.id, order_index=block.order_index, exercise_id=block.exercise_id,
                complex_id=block.complex_id, result=block.result, started_at=block.started_at,
                block_key=block.block_key, status=block.status, ended_at=block.ended_at,
            )
            self._session.add(new_block)
            await self._session.flush()
            target_map: dict[int, int] = {}
            targets = (await self._session.execute(
                select(SetTarget).where(SetTarget.session_block_id == block.id).order_by(SetTarget.set_number),
            )).scalars().all()
            for target in targets:
                new_target = SetTarget(
                    session_block_id=new_block.id, set_number=target.set_number, is_max_set=target.is_max_set,
                    metric_type=target.metric_type, value=target.value, unit=target.unit, kind=target.kind,
                )
                self._session.add(new_target)
                await self._session.flush()
                target_map[target.id] = new_target.id
            logs = (await self._session.execute(
                select(SetLog).where(SetLog.session_block_id == block.id).order_by(SetLog.set_number),
            )).scalars().all()
            for log in logs:
                self._session.add(SetLog(
                    session_block_id=new_block.id, set_target_id=target_map.get(log.set_target_id),
                    set_number=log.set_number, is_max_set=log.is_max_set, metric_type=log.metric_type,
                    value=log.value, unit=log.unit, effort=log.effort, note=log.note,
                    session_id=clone.id if log.set_index is not None else None, set_index=log.set_index,
                    is_extra=log.is_extra, status=log.status, round_index=log.round_index,
                    load_actual=log.load_actual,
                ))
        # issue #304 (D10, PL3): копия НЕ засчитывает занятия плана — ни явным plan_item_id, ни
        # копированием старой M2M-связи оригинала.
        await self._session.flush()
        if stamp is None:
            # Без явного stamp — то же правило копии (§2), что у app.services.training_session_v2.clone.
            kind = SessionKind(original.kind or ("external_activity" if original.activity_type else "strength"))
            stamp = SessionV2Stamp(
                kind=kind.value,
                source_v2=clone_source(original_kind=kind, workout_definition_id=original.workout_definition_id).value,
                workout_definition_id=original.workout_definition_id,
                workout_definition_version_id=original.workout_definition_version_id,
                prescription_snapshot=original.prescription_snapshot, timezone=original.timezone,
                duration_seconds=original.duration_seconds if kind is SessionKind.EXTERNAL_ACTIVITY else None,
                duration_source=(
                    DurationSource.ENTERED.value if kind is SessionKind.EXTERNAL_ACTIVITY and original.duration_seconds
                    else DurationSource.UNKNOWN.value
                ),
                distance_meters=original.distance_meters,
            )
        await self.apply_v2_stamp(clone.id, stamp)
        return clone
