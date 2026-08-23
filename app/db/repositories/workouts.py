from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Block, BlockType, Workout, WorkoutStatus
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.domain.constants import (
    DELOAD_INTERVAL_DAYS,
    STRENGTH_BLOCK,
    VOLUME_BLOCK,
    VOLUME_TARGET_CEILING,
    VOLUME_WEIGHT_START_KG,
    VOLUME_WORK_SETS_CEILING,
    EquipmentType,
)
from app.domain.progression import (
    TransitionOutcome,
    check_transition_outcome,
    count_consecutive_stalled_workouts,
    count_consecutive_weak_trainings,
    grow_volume_weight_kg,
    recalculate_cascade,
    recalculate_target,
    recalculate_volume_block,
)
from app.domain.session import BlockAssignment, BlockLog, WorkoutRecord

# Запись/пересчёт blocks намеренно НЕ вынесена в отдельный репозиторий (см.
# blocks.py) — target_before/target_after/equipment_changed вычисляются
# доменом и должны оставаться согласованы с sequence_number всей цепочки
# тренировок пользователя. Держать это в одном месте (здесь) проще, чем
# полагаться на то, что вызывающий код всегда будет дергать два репозитория
# в правильном порядке.


def _block_to_log(block: Block) -> BlockLog:
    return BlockLog(working_reps=tuple(block.working_reps), max_reps=block.max_reps)


def _find_block(workout: Workout, block_type: BlockType) -> Block:
    return next(b for b in workout.blocks if b.block_type == block_type)


def _weak_streak(history: list[Workout], block_type: BlockType) -> int:
    """Сколько подряд слабых тренировок (Часть 10, пакет #2, п.13) стоят в
    конце history для данного блока — вычисляется из уже загруженной
    истории каждый раз заново, отдельной сущности в БД нет (см.
    count_consecutive_weak_trainings)."""
    volumes = [_block_to_log(_find_block(w, block_type)).volume for w in history]
    return count_consecutive_weak_trainings(volumes)


def _work_sets_after(block: Block) -> int:
    """work_sets_after — NULL для записей до ревизии формулы прогрессии
    (число подходов тогда ещё не хранилось явно, было фиксированной
    константой VOLUME_BLOCK.work_sets) — трактуем NULL как стартовое."""
    return block.work_sets_after if block.work_sets_after is not None else VOLUME_BLOCK.work_sets


def _stall_streak(history: list[Workout]) -> int:
    """Застой блока на объём (иерархия роста, часть 2) — сколько подряд
    тренировок в конце НЕ вырастили ни цель, ни число рабочих подходов.
    Только для блока A; history должна быть уже отфильтрована от
    разгрузочных записей вызывающим кодом (см. _exclude_deload_entries —
    is_deload не участвует в пересчёте прогрессии)."""
    grew_flags = []
    for w in history:
        block = _find_block(w, BlockType.A)
        work_sets_before = block.work_sets_before if block.work_sets_before is not None else VOLUME_BLOCK.work_sets
        grew_flags.append(block.target_after > block.target_before or _work_sets_after(block) > work_sets_before)
    return count_consecutive_stalled_workouts(grew_flags)


def _exclude_deload_entries(workouts: list[Workout]) -> list[Workout]:
    """Разгрузочные тренировки блока на объём (часть 4 ревизии формулы) не
    участвуют в пересчёте его прогрессии — фильтровать перед тем, как
    считать состояние/стрики блока A (тот же приём, что и
    _exclude_free_entries для свободных подтягиваний)."""
    return [w for w in workouts if not _find_block(w, BlockType.A).is_deload]


def _previous_avg_working(
    history: list[Workout], block_type: BlockType, *, before: datetime | None = None,
) -> float | None:
    """Среднее рабочих подходов последней (по performed_at) тренировки
    этого блока — метрика для проверки "резкого скачка" (пакет #4,
    app.domain.anomalies.detect_anomalies). history уже отсортирована
    list_for_user по performed_at.

    before — строго ДО этой даты (используется при правке: сравнивать
    нужно с тем, что было ДО редактируемой записи, а не с глобально
    последней — иначе правка старой записи сравнивалась бы с тем, что
    случилось уже ПОСЛЕ неё). None — просто последняя запись в history.

    None, если истории нет или у найденной записи working_reps пуст
    (например, свободный ввод одним числом) — сравнивать не с чем."""
    candidates = history if before is None else [w for w in history if w.performed_at < before]
    if not candidates:
        return None
    log = _block_to_log(_find_block(candidates[-1], block_type))
    if not log.working_reps:
        return None
    return sum(log.working_reps) / len(log.working_reps)


def _exclude_free_entries(workouts: list[Workout]) -> list[Workout]:
    """"➕ Внести свободные подтягивания" (Часть 10, п. 18) — попадает в
    статистику/список истории как обычно (list_for_user не фильтрует), но
    НЕ должна становиться "последним известным снарядом/целью" для
    следующей структурированной тренировки: снаряд там всегда bodyweight
    независимо от того, чем реально прогрессирует пользователь. Вызывать
    перед тем, как вывести из истории текущее состояние прогрессии
    (resolve_next_targets/complete_workout), не перед показом истории."""
    return [w for w in workouts if not w.is_free_entry]


def _workout_to_record(workout: Workout) -> WorkoutRecord:
    block_a, block_b = _find_block(workout, BlockType.A), _find_block(workout, BlockType.B)
    return WorkoutRecord(
        performed_at=workout.performed_at,
        block_a=BlockAssignment(
            log=_block_to_log(block_a),
            target_before=block_a.target_before,
            target_after=block_a.target_after,
            equipment_changed=block_a.equipment_changed,
            equipment_type=block_a.equipment_type,
            equipment_value=block_a.equipment_value,
            equipment_item_id=block_a.equipment_item_id,
            transition_failed=block_a.transition_failed,
            work_sets_before=block_a.work_sets_before,
            work_sets_after=block_a.work_sets_after,
            is_deload=block_a.is_deload,
        ),
        block_b=BlockAssignment(
            log=_block_to_log(block_b),
            target_before=block_b.target_before,
            target_after=block_b.target_after,
            equipment_changed=block_b.equipment_changed,
            equipment_type=block_b.equipment_type,
            equipment_value=block_b.equipment_value,
            equipment_item_id=block_b.equipment_item_id,
            transition_failed=block_b.transition_failed,
        ),
        comment=workout.comment,
        workout_set_id=workout.workout_set_id,
        exercise_type=workout.exercise_type,
    )


@dataclass(frozen=True)
class NextBlockState:
    target: int
    volume: int
    equipment_type: EquipmentType
    equipment_value: Decimal | None
    equipment_item_id: int | None
    needs_new_equipment: bool
    # True — предыдущая тренировка сообщила equipment_changed (или истории
    # нет вовсе): снаряд для СЛЕДУЮЩЕЙ тренировки ещё не известен, вызывающий
    # код (хендлер) должен спросить пользователя, а не использовать
    # equipment_type/equipment_value отсюда как есть — это старый снаряд.
    work_sets: int = VOLUME_BLOCK.work_sets
    # Только для блока A (иерархия роста, часть 2) — растущее число рабочих
    # подходов. Для блока B всегда STRENGTH_BLOCK.work_sets (фиксировано).


def _apply_cascade_result(workout: Workout, record: WorkoutRecord) -> None:
    # equipment_type/equipment_value/transition_failed каскад не трогает —
    # это факт того, что реально использовалось, он не переигрывается.
    # is_deload тоже не трогает — это тоже факт (была ли ЭТА тренировка
    # разгрузочной), каскад его не переигрывает, только пересчитывает
    # target/work_sets, которые для is_deload-записи и так остаются
    # неизменными (см. recalculate_cascade).
    block_a, block_b = _find_block(workout, BlockType.A), _find_block(workout, BlockType.B)
    block_a.target_before = record.block_a.target_before
    block_a.target_after = record.block_a.target_after
    block_a.equipment_changed = record.block_a.equipment_changed
    block_a.work_sets_before = record.block_a.work_sets_before
    block_a.work_sets_after = record.block_a.work_sets_after
    block_b.target_before = record.block_b.target_before
    block_b.target_after = record.block_b.target_after
    block_b.equipment_changed = record.block_b.equipment_changed


class WorkoutRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._workout_sets = WorkoutSetRepository(session)

    async def get_by_id(self, workout_id: int) -> Workout | None:
        result = await self._session.execute(
            select(Workout).where(Workout.id == workout_id).options(selectinload(Workout.blocks)),
        )
        return result.scalar_one_or_none()

    async def list_since(self, after_id: int, *, limit: int) -> list[Workout]:
        """Все завершённые тренировки ЛЮБОГО пользователя с id > after_id,
        по возрастанию id — вход для app.workers.sheets_sync.py (лист
        "workouts", тот же пагинированный по курсору паттерн, что и
        EventRepository.list_since)."""
        result = await self._session.execute(
            select(Workout)
            .where(Workout.id > after_id, Workout.status == WorkoutStatus.COMPLETED)
            .options(selectinload(Workout.blocks))
            .order_by(Workout.id)
            .limit(limit),
        )
        return list(result.scalars().all())

    async def list_for_user(self, user_id: int) -> list[Workout]:
        """ВСЕ завершённые тренировки, любого происхождения (включая
        внесённые задним числом), в хронологическом порядке ПО ДАТЕ
        ПРОВЕДЕНИЯ. Это источник для "текущего состояния" (какая цель
        сейчас действует, история, статистика) — внесённые задним числом
        тренировки здесь НЕ фильтруются: последняя по дате тренировка любого
        происхождения определяет текущую цель. Для каскада используется
        отдельная, отфильтрованная выборка — см. _cascade_chain."""
        result = await self._session.execute(
            select(Workout)
            .where(Workout.user_id == user_id, Workout.status == WorkoutStatus.COMPLETED)
            .options(selectinload(Workout.blocks))
            .order_by(Workout.performed_at),
        )
        return list(result.scalars().all())

    async def _cascade_chain(self, user_id: int) -> list[Workout]:
        """Только тренировки, участвующие в каскаде (participates_in_cascade),
        в порядке sequence_number. Внесённые задним числом сюда не попадают
        вовсе — они не занимают место в этой цепочке и не сдвигают её."""
        result = await self._session.execute(
            select(Workout)
            .where(
                Workout.user_id == user_id,
                Workout.participates_in_cascade.is_(True),
                Workout.sequence_number.is_not(None),
            )
            .options(selectinload(Workout.blocks))
            .order_by(Workout.sequence_number),
        )
        return list(result.scalars().all())

    async def resolve_next_targets(
        self, user_id: int, *, bypass_transition_wait: bool = False,
    ) -> tuple[NextBlockState, NextBlockState]:
        """Публичный вход для хендлеров: состояние (цель/объём/снаряд), с
        которого начнётся следующая тренировка обоих блоков — то же самое,
        что использует complete_workout внутри себя. Нужен хендлеру, чтобы
        показать план и спросить снаряд ДО того, как тренировка реально
        записана (см. app/bot/handlers/workout.py).

        bypass_transition_wait — только для админ-тестирования (Часть 9):
        вызывающий бот-хендлер решает, передавать ли True, сам репозиторий
        ничего не знает про admin_ids. Не влияет на target/volume (которые
        читает complete_workout) — только на equipment_source/
        needs_new_equipment в _resolve_next_state, см. там."""
        history = _exclude_free_entries(await self.list_for_user(user_id))
        return (
            self._resolve_next_state(
                history, BlockType.A, VOLUME_BLOCK, bypass_transition_wait=bypass_transition_wait,
            ),
            self._resolve_next_state(
                history, BlockType.B, STRENGTH_BLOCK, bypass_transition_wait=bypass_transition_wait,
            ),
        )

    async def is_volume_deload_due(self, user_id: int, *, now: datetime) -> bool:
        """Пора ли следующая тренировка блока на объём быть ежемесячной
        разгрузочной (часть 4 ревизии формулы) — публичный вход для
        хендлера (workout.py), вызывается ДО показа плана, наравне с
        resolve_next_targets.

        Отсчёт DELOAD_INTERVAL_DAYS (30) — от даты последней разгрузочной
        тренировки блока A; если разгрузки ещё не было ни разу — от старта
        первого сета пользователя (естественнее, чем сразу в первый день:
        разгружать нечего, если тренировок ещё не было). Без сетов вообще
        (только что онбординг) — разгрузка неприменима."""
        history = await self.list_for_user(user_id)
        last_deload = next(
            (w for w in reversed(history) if _find_block(w, BlockType.A).is_deload), None,
        )
        if last_deload is not None:
            anchor = last_deload.performed_at
        else:
            workout_sets = await self._workout_sets.list_for_user(user_id)
            if not workout_sets:
                return False
            anchor = workout_sets[0].started_at
        return (now - anchor).days >= DELOAD_INTERVAL_DAYS

    async def get_previous_avg_working(
        self, user_id: int, block_type: BlockType, *, before: datetime | None = None,
    ) -> float | None:
        """Публичный вход для хендлеров (пакет #4) — среднее рабочих
        подходов последней структурированной (не свободной) тренировки
        этого блока, для проверки "резкого скачка" перед записью нового
        результата. Свободные записи исключены той же _exclude_free_entries,
        что и resolve_next_targets — другая шкала, сравнивать некорректно."""
        history = _exclude_free_entries(await self.list_for_user(user_id))
        return _previous_avg_working(history, block_type, before=before)

    async def get_previous_free_avg_working(self, user_id: int) -> float | None:
        """То же самое, но для свободных подтягиваний — сравнение только с
        прошлым свободным входом (is_free_entry=True), не со структурным
        блоком A: разные шкалы, свободный вход не участвует в прогрессии."""
        history = [w for w in await self.list_for_user(user_id) if w.is_free_entry]
        return _previous_avg_working(history, BlockType.A)

    async def list_for_set(self, workout_set_id: int) -> list[Workout]:
        result = await self._session.execute(
            select(Workout)
            .where(Workout.workout_set_id == workout_set_id)
            .options(selectinload(Workout.blocks))
            .order_by(Workout.performed_at),
        )
        return list(result.scalars().all())

    async def list_records_for_user(self, user_id: int) -> list[WorkoutRecord]:
        """list_for_user(), сконвертированный в чистые доменные WorkoutRecord —
        вход для app/domain/reports.py (отчёты не должны знать про ORM)."""
        return [_workout_to_record(w) for w in await self.list_for_user(user_id)]

    async def list_records_for_set(self, workout_set_id: int) -> list[WorkoutRecord]:
        return [_workout_to_record(w) for w in await self.list_for_set(workout_set_id)]

    async def start_workout(
        self, *, user_id: int, workout_set_id: int, performed_at: datetime, comment: str | None = None,
    ) -> Workout:
        workout = Workout(
            user_id=user_id,
            workout_set_id=workout_set_id,
            performed_at=performed_at,
            status=WorkoutStatus.STARTED,
            comment=comment,
        )
        self._session.add(workout)
        await self._session.flush()
        # blocks — пустая коллекция и без запроса к БД (это только что
        # созданный объект), но async-сессия не умеет лениво подгружать
        # атрибуты при обычном обращении вне greenlet-контекста — явно
        # фиксируем состояние, чтобы workout.blocks было безопасно читать сразу.
        await self._session.refresh(workout, attribute_names=["blocks"])
        return workout

    async def record_workout(
        self,
        *,
        user_id: int,
        workout_set_id: int,
        performed_at: datetime,
        block_a_reps: BlockLog,
        block_b_reps: BlockLog,
        block_a_equipment_type: EquipmentType,
        block_a_equipment_value: Decimal | None,
        block_b_equipment_type: EquipmentType,
        block_b_equipment_value: Decimal | None,
        block_a_equipment_item_id: int | None = None,
        block_b_equipment_item_id: int | None = None,
        target_a_override: int | None = None,
        target_b_override: int | None = None,
        is_deload_a: bool = False,
        comment: str | None = None,
    ) -> Workout:
        """start_workout + complete_workout в одном вызове — основной путь
        для живой (не задним числом) тренировки."""
        workout = await self.start_workout(
            user_id=user_id, workout_set_id=workout_set_id, performed_at=performed_at, comment=comment,
        )
        return await self.complete_workout(
            workout_id=workout.id,
            block_a_reps=block_a_reps,
            block_b_reps=block_b_reps,
            block_a_equipment_type=block_a_equipment_type,
            block_a_equipment_value=block_a_equipment_value,
            block_b_equipment_type=block_b_equipment_type,
            block_b_equipment_value=block_b_equipment_value,
            block_a_equipment_item_id=block_a_equipment_item_id,
            block_b_equipment_item_id=block_b_equipment_item_id,
            target_a_override=target_a_override,
            target_b_override=target_b_override,
            is_deload_a=is_deload_a,
        )

    async def complete_workout(
        self,
        *,
        workout_id: int,
        block_a_reps: BlockLog,
        block_b_reps: BlockLog,
        block_a_equipment_type: EquipmentType,
        block_a_equipment_value: Decimal | None,
        block_b_equipment_type: EquipmentType,
        block_b_equipment_value: Decimal | None,
        block_a_equipment_item_id: int | None = None,
        block_b_equipment_item_id: int | None = None,
        target_a_override: int | None = None,
        target_b_override: int | None = None,
        is_deload_a: bool = False,
        comment: str | None = None,
    ) -> Workout:
        """Прикрепляет результаты блоков к ранее начатой (start_workout)
        живой тренировке — всегда встаёт В КОНЕЦ цепочки каскада (живая
        тренировка происходит "сейчас", раньше уже записанных быть не
        может; вставка в середину цепочки была нужна только для бэкдейта,
        а он в цепочку больше не попадает вовсе — см. record_backdated_workout).

        Снаряд, который РЕАЛЬНО использовался (block_*_equipment_type/value),
        передаёт вызывающий код — репозиторий не подбирает его сам, только
        проверяет (check_transition_outcome), не провалена ли первая
        тренировка на новом снаряде, и если да — откатывает цель и снаряд
        на предыдущие, не сбрасывая на base_target.

        target_*_override — для отката после долгого перерыва
        (domain.rules.TrainingReadiness.GAP_ROLLBACK) и полного сброса после
        ретеста (GAP_RETEST_REQUIRED): вызывающий код (хендлер) уже посчитал
        скорректированную цель ДО того, как показал план пользователю, и эта
        же цель должна лечь в target_before, а не заново выведенная из
        истории — иначе показанный план разойдётся с тем, что реально
        запишется. Число подходов override не поддерживает (gap-rollback
        трогает только цель, не структуру блока — вне scope этой ревизии).

        is_deload_a — ежемесячная разгрузочная тренировка блока на объём
        (часть 4 ревизии формулы): target/work_sets блока A проходят БЕЗ
        пересчёта (target_after=target_before, work_sets_after=work_sets_before),
        проверка перехода снаряда для блока A тоже не выполняется — это не
        решение о смене снаряда, а разовая тренировка без веса вне обычной
        структуры. Блок B (силовой) разгрузку не знает вообще, считается
        как обычно."""
        workout = await self.get_by_id(workout_id)
        if workout is None:
            raise ValueError(f"workout {workout_id} not found")

        history = _exclude_free_entries(await self.list_for_user(workout.user_id))
        history_a = _exclude_deload_entries(history)
        preceding = history[-1] if history else None
        preceding_a = history_a[-1] if history_a else None

        state_a = self._resolve_next_state(history, BlockType.A, VOLUME_BLOCK)
        state_b = self._resolve_next_state(history, BlockType.B, STRENGTH_BLOCK)
        target_before_a = target_a_override if target_a_override is not None else state_a.target
        target_before_b = target_b_override if target_b_override is not None else state_b.target
        work_sets_before_a = state_a.work_sets

        result_b = recalculate_target(
            STRENGTH_BLOCK, target_before_b, block_b_reps.working_reps, block_b_reps.max_reps,
            block_b_reps.volume, state_b.volume,
            consecutive_weak_before=_weak_streak(history, BlockType.B),
        )
        transition_b = self._check_transition(preceding, BlockType.B, STRENGTH_BLOCK, block_b_reps.max_reps)
        target_after_b, equipment_changed_b, failed_b = self._apply_transition_outcome(
            transition_b, result_b, preceding, BlockType.B,
        )

        if is_deload_a:
            target_after_a, work_sets_after_a, equipment_changed_a, failed_a = (
                target_before_a, work_sets_before_a, False, False,
            )
        else:
            result_a = recalculate_volume_block(
                target_before_a, work_sets_before_a, block_a_reps.working_reps, block_a_reps.max_reps,
                block_a_reps.volume, state_a.volume, block_a_equipment_type,
                consecutive_weak_before=_weak_streak(history_a, BlockType.A),
                consecutive_stall_before=_stall_streak(history_a),
            )
            transition_a = self._check_transition(preceding_a, BlockType.A, VOLUME_BLOCK, block_a_reps.max_reps)
            if transition_a == TransitionOutcome.FAILED:
                preceding_a_block = _find_block(preceding_a, BlockType.A)
                target_after_a = preceding_a_block.target_before
                work_sets_before_preceding = preceding_a_block.work_sets_before
                work_sets_after_a = (
                    work_sets_before_preceding if work_sets_before_preceding is not None else VOLUME_BLOCK.work_sets
                )
                equipment_changed_a, failed_a = False, True
            else:
                target_after_a = result_a.new_target
                work_sets_after_a = result_a.new_work_sets
                equipment_changed_a, failed_a = result_a.equipment_changed, False

        if comment is not None:
            workout.comment = comment
        workout.status = WorkoutStatus.COMPLETED

        cascade_chain = await self._cascade_chain(workout.user_id)
        workout.sequence_number = len(cascade_chain) + 1

        self._session.add(
            Block(
                workout_id=workout.id,
                block_type=BlockType.A,
                working_reps=list(block_a_reps.working_reps),
                max_reps=block_a_reps.max_reps,
                target_before=target_before_a,
                target_after=target_after_a,
                equipment_changed=equipment_changed_a,
                equipment_type=block_a_equipment_type,
                equipment_value=block_a_equipment_value,
                equipment_item_id=block_a_equipment_item_id,
                transition_failed=failed_a,
                work_sets_before=work_sets_before_a,
                work_sets_after=work_sets_after_a,
                is_deload=is_deload_a,
            ),
        )
        self._session.add(
            Block(
                workout_id=workout.id,
                block_type=BlockType.B,
                working_reps=list(block_b_reps.working_reps),
                max_reps=block_b_reps.max_reps,
                target_before=target_before_b,
                target_after=target_after_b,
                equipment_changed=equipment_changed_b,
                equipment_type=block_b_equipment_type,
                equipment_value=block_b_equipment_value,
                equipment_item_id=block_b_equipment_item_id,
                transition_failed=failed_b,
            ),
        )

        await self._session.flush()
        await self._workout_sets.increment_completed(workout.workout_set_id, completed_at=workout.performed_at)
        await self._session.refresh(workout, attribute_names=["blocks"])
        return workout

    async def record_backdated_workout(
        self,
        *,
        user_id: int,
        workout_set_id: int,
        performed_at: datetime,
        block_a_reps: BlockLog,
        block_b_reps: BlockLog,
        block_a_equipment_type: EquipmentType,
        block_a_equipment_value: Decimal | None,
        block_b_equipment_type: EquipmentType,
        block_b_equipment_value: Decimal | None,
        block_a_equipment_item_id: int | None = None,
        block_b_equipment_item_id: int | None = None,
        comment: str | None = None,
    ) -> Workout:
        """Тренировка, внесённая задним числом: пополняет историю/объём, но
        НЕ участвует в каскаде (participates_in_cascade=False,
        sequence_number остаётся NULL — как и у STARTED-тренировок, эта
        запись просто не занимает места в цепочке). target_before/after
        считаются один раз, от текущего состояния на момент вызова (не
        переигрываются позже правкой других тренировок и сами не запускают
        каскад по уже существующим).

        Если вносится несколько тренировок задним числом подряд, каждая
        следующая учитывает предыдущую внесённую (list_for_user видит уже
        сохранённую) — это соответствует "они пополняют статистику" без
        участия в каскаде: между собой хронология всё равно соблюдается,
        просто не через sequence_number/цепочку живых тренировок."""
        history = await self.list_for_user(user_id)
        history_a = _exclude_deload_entries(history)
        state_a = self._resolve_next_state(history, BlockType.A, VOLUME_BLOCK)
        state_b = self._resolve_next_state(history, BlockType.B, STRENGTH_BLOCK)

        result_a = recalculate_volume_block(
            state_a.target, state_a.work_sets, block_a_reps.working_reps, block_a_reps.max_reps,
            block_a_reps.volume, state_a.volume, block_a_equipment_type,
            consecutive_weak_before=_weak_streak(history_a, BlockType.A),
            consecutive_stall_before=_stall_streak(history_a),
        )
        result_b = recalculate_target(
            STRENGTH_BLOCK, state_b.target, block_b_reps.working_reps, block_b_reps.max_reps,
            block_b_reps.volume, state_b.volume,
            consecutive_weak_before=_weak_streak(history, BlockType.B),
        )

        workout = Workout(
            user_id=user_id,
            workout_set_id=workout_set_id,
            performed_at=performed_at,
            status=WorkoutStatus.COMPLETED,
            comment=comment,
            participates_in_cascade=False,
        )
        self._session.add(workout)
        await self._session.flush()

        self._session.add(
            Block(
                workout_id=workout.id, block_type=BlockType.A,
                working_reps=list(block_a_reps.working_reps), max_reps=block_a_reps.max_reps,
                target_before=state_a.target, target_after=result_a.new_target,
                equipment_changed=result_a.equipment_changed,
                equipment_type=block_a_equipment_type, equipment_value=block_a_equipment_value,
                equipment_item_id=block_a_equipment_item_id,
                work_sets_before=state_a.work_sets, work_sets_after=result_a.new_work_sets,
            ),
        )
        self._session.add(
            Block(
                workout_id=workout.id, block_type=BlockType.B,
                working_reps=list(block_b_reps.working_reps), max_reps=block_b_reps.max_reps,
                target_before=state_b.target, target_after=result_b.new_target,
                equipment_changed=result_b.equipment_changed,
                equipment_type=block_b_equipment_type, equipment_value=block_b_equipment_value,
                equipment_item_id=block_b_equipment_item_id,
            ),
        )

        await self._session.flush()
        await self._workout_sets.increment_completed(workout.workout_set_id, completed_at=workout.performed_at)
        await self._session.refresh(workout, attribute_names=["blocks"])
        return workout

    async def record_free_workout(
        self,
        *,
        user_id: int,
        workout_set_id: int,
        performed_at: datetime,
        block_a_reps: BlockLog,
        equipment_type: EquipmentType,
        equipment_value: Decimal | None = None,
        equipment_item_id: int | None = None,
        comment: str | None = None,
    ) -> Workout:
        """"➕ Внести свободные подтягивания" (Часть 10, пакет #2, п.21) —
        произвольная тренировка вне схемы: попадает в общую
        статистику/объём (list_for_user её не фильтрует), но НЕ в сет из 12
        (increment_completed не вызывается — в отличие от
        record_backdated_workout) и НЕ в цепочку каскада
        (participates_in_cascade=False). Цель заморожена на текущей
        (resolve_next_targets уже сам исключает такие записи из истории —
        см. _exclude_free_entries) — эта запись её не двигает и не
        участвует в подборе снаряда для следующей структурированной
        тренировки.

        block_a_reps — произвольное количество подходов (не фиксированные
        3+1, как в основной схеме — сколько реально сделал, столько и
        ввёл), volume считается как обычно через BlockLog.volume. Снаряд
        теперь тоже указывается явно (раньше подразумевался собственный
        вес всегда) — блок "b" по-прежнему нулевой, свободные подтягивания
        не относятся к силовому блоку."""
        history = _exclude_free_entries(await self.list_for_user(user_id))
        state_a = self._resolve_next_state(history, BlockType.A, VOLUME_BLOCK)
        state_b = self._resolve_next_state(history, BlockType.B, STRENGTH_BLOCK)

        workout = Workout(
            user_id=user_id,
            workout_set_id=workout_set_id,
            performed_at=performed_at,
            status=WorkoutStatus.COMPLETED,
            comment=comment,
            participates_in_cascade=False,
            is_free_entry=True,
        )
        self._session.add(workout)
        await self._session.flush()

        self._session.add(
            Block(
                workout_id=workout.id, block_type=BlockType.A,
                working_reps=list(block_a_reps.working_reps), max_reps=block_a_reps.max_reps,
                target_before=state_a.target, target_after=state_a.target,
                equipment_changed=False, equipment_type=equipment_type,
                equipment_value=equipment_value, equipment_item_id=equipment_item_id,
                work_sets_before=state_a.work_sets, work_sets_after=state_a.work_sets,
            ),
        )
        self._session.add(
            Block(
                workout_id=workout.id, block_type=BlockType.B,
                working_reps=[], max_reps=0,
                target_before=state_b.target, target_after=state_b.target,
                equipment_changed=False, equipment_type=EquipmentType.BODYWEIGHT,
            ),
        )

        await self._session.flush()
        await self._session.refresh(workout, attribute_names=["blocks"])
        return workout

    async def edit_workout(
        self,
        *,
        workout_id: int,
        block_a_reps: BlockLog | None = None,
        block_b_reps: BlockLog | None = None,
        comment: str | None = None,
    ) -> Workout:
        """Редактирует уже введённые повторения завершённой тренировки,
        участвующей в каскаде (не бэкдейт — у тех цепочки нет вовсе), и
        каскадом пересчитывает все более поздние тренировки ИЗ ТОЙ ЖЕ
        цепочки (внесённые задним числом каскад пропускает: не входят в
        _cascade_chain, значит не сдвигаются и не пересчитываются)."""
        workout = await self.get_by_id(workout_id)
        if workout is None:
            raise ValueError(f"workout {workout_id} not found")
        if workout.sequence_number is None or not workout.participates_in_cascade:
            raise ValueError("cannot edit a workout that is not part of the cascade chain")

        chain = await self._cascade_chain(workout.user_id)
        position = next(i for i, w in enumerate(chain) if w.id == workout.id)

        block_a, block_b = _find_block(workout, BlockType.A), _find_block(workout, BlockType.B)
        new_block_a_reps = block_a_reps or _block_to_log(block_a)
        new_block_b_reps = block_b_reps or _block_to_log(block_b)

        target_before_a, target_before_b, prev_volume_a, prev_volume_b, work_sets_before_a = (
            self._preceding_chain_state(chain, position)
        )
        # Стрик "слабых" тренировок (Часть 10, пакет #2, п.13) до
        # редактируемой записи — из цепочки ДО её позиции, тем же приёмом,
        # что и target_before/prev_volume выше. Для застоя блока A цепочка
        # дополнительно фильтруется от разгрузочных записей — они не в счёт.
        weak_streak_before_a = _weak_streak(_exclude_deload_entries(chain[:position]), BlockType.A)
        weak_streak_before_b = _weak_streak(chain[:position], BlockType.B)
        stall_streak_before_a = _stall_streak(_exclude_deload_entries(chain[:position]))

        if block_a.is_deload:
            # Разгрузка не пересчитывается даже при редактировании — только
            # правится фактический ввод (для статистики), состояние
            # прогрессии остаётся замороженным, как и было.
            target_after_a, work_sets_after_a, equipment_changed_a = target_before_a, work_sets_before_a, False
        else:
            result_a = recalculate_volume_block(
                target_before_a, work_sets_before_a, new_block_a_reps.working_reps, new_block_a_reps.max_reps,
                new_block_a_reps.volume, prev_volume_a, block_a.equipment_type,
                consecutive_weak_before=weak_streak_before_a, consecutive_stall_before=stall_streak_before_a,
            )
            target_after_a, work_sets_after_a, equipment_changed_a = (
                result_a.new_target, result_a.new_work_sets, result_a.equipment_changed
            )

        result_b = recalculate_target(
            STRENGTH_BLOCK, target_before_b, new_block_b_reps.working_reps, new_block_b_reps.max_reps,
            new_block_b_reps.volume, prev_volume_b,
            consecutive_weak_before=weak_streak_before_b,
        )

        block_a.working_reps = list(new_block_a_reps.working_reps)
        block_a.max_reps = new_block_a_reps.max_reps
        block_a.target_before = target_before_a
        block_a.target_after = target_after_a
        block_a.equipment_changed = equipment_changed_a
        block_a.work_sets_before = work_sets_before_a
        block_a.work_sets_after = work_sets_after_a

        block_b.working_reps = list(new_block_b_reps.working_reps)
        block_b.max_reps = new_block_b_reps.max_reps
        block_b.target_before = target_before_b
        block_b.target_after = result_b.new_target
        block_b.equipment_changed = result_b.equipment_changed

        if comment is not None:
            workout.comment = comment
        workout.updated_at = datetime.now(UTC)

        following = chain[position + 1 :]
        if following:
            records = [_workout_to_record(w) for w in following]
            # Стрик, который переходит В цепочку после отредактированной
            # записи, учитывает и её саму — была ли она слабой/застойной по
            # НОВЫМ (только что введённым) данным. Разгрузка сама по себе
            # никогда не бывает "слабой"/"застойной" — is_deload здесь
            # исключён логикой transition_a выше (та ветка не трогает
            # weak/stall streak вообще, они остаются от before-состояния).
            if block_a.is_deload:
                weak_streak_a, stall_streak_a = weak_streak_before_a, stall_streak_before_a
            else:
                weak_streak_a = weak_streak_before_a + 1 if new_block_a_reps.volume < prev_volume_a else 0
                grew_a = target_after_a > target_before_a or work_sets_after_a > work_sets_before_a
                stall_streak_a = 0 if grew_a else stall_streak_before_a + 1
            weak_streak_b = weak_streak_before_b + 1 if new_block_b_reps.volume < prev_volume_b else 0
            cascaded = recalculate_cascade(
                target_after_a, result_b.new_target,
                new_block_a_reps.volume, new_block_b_reps.volume, records,
                starting_weak_streak_a=weak_streak_a, starting_weak_streak_b=weak_streak_b,
                starting_work_sets_a=work_sets_after_a, starting_stall_streak_a=stall_streak_a,
            )
            for db_workout, new_record in zip(following, cascaded, strict=True):
                _apply_cascade_result(db_workout, new_record)

        await self._session.flush()
        await self._session.refresh(workout, attribute_names=["blocks"])
        return workout

    async def correct_block_equipment(
        self,
        *,
        workout_id: int,
        block_type: BlockType,
        equipment_type: EquipmentType | None = None,
        equipment_value: Decimal | None = None,
        equipment_item_id: int | None = None,
    ) -> Workout:
        """Правка снаряда уже записанной тренировки задним числом —
        исправление ошибки ВВОДА, не решение о смене снаряда: каскад не
        запускается, прогрессия (target_before/after) не пересчитывается
        (см. recalculate_target — снаряд там только equipment_type для
        потолка на своём весе, а не сама эта запись).

        equipment_type обычно НЕ передаётся — штатный сценарий "правка
        веса/резины" в правке тренировки (Часть 10) специально не меняет
        тип, только опечатку в цифре/резине. Параметр существует для
        редких разовых исправлений исторически неверно записанного ТИПА
        снаряда (например, случайный тап не на ту кнопку при бэкдейте) —
        такой правкой пользуется только разовый скрипт/консоль, не бот."""
        workout = await self.get_by_id(workout_id)
        if workout is None:
            raise ValueError(f"workout {workout_id} not found")

        block = _find_block(workout, block_type)
        if equipment_type is not None:
            block.equipment_type = equipment_type
        if equipment_value is not None:
            block.equipment_value = equipment_value
        if equipment_item_id is not None:
            block.equipment_item_id = equipment_item_id

        await self._session.flush()
        await self._session.refresh(workout, attribute_names=["blocks"])
        return workout

    def _resolve_next_state(
        self, history: list[Workout], block_type: BlockType, block_config, *, bypass_transition_wait: bool = False,
    ) -> NextBlockState:
        """Цель/объём/снаряд, от которых считать СЛЕДУЮЩУЮ тренировку —
        по хронологически последней записи ЛЮБОГО происхождения (см.
        list_for_user). Если последняя запись отмечена transition_failed —
        снаряд для следующей тренировки берём с шага ЕЩЁ РАНЬШЕ (та
        тренировка, что была ДО неудачной попытки смены) — target_after
        неудачной попытки уже содержит правильно откаченное значение,
        а вот equipment_type/value на ней — это как раз тот снаряд,
        который не подошёл, его предлагать снова не нужно. В этом случае
        needs_new_equipment=False — снаряд уже известен (прежний),
        спрашивать заново нечего.

        bypass_transition_wait=True (только для админ-тестирования, см.
        resolve_next_targets) — не откатывает снаряд молча, а сразу просит
        выбрать новый: needs_new_equipment=True вместо False. Естественный
        механизм "подожди, пока порог наберётся снова" (это НЕ отдельный
        счётчик тренировок — TRANSITION_RETRY_WORKOUTS/is_retry_allowed в
        домене на практике нигде не вызываются, эта ветка — фактическая
        точка, где перепопытка перехода сейчас притормаживается) для админа
        пропускается.

        Для блока A (иерархия роста, часть 2-3) history сначала фильтруется
        от разгрузочных тренировок (is_deload) — они не должны становиться
        "последним известным состоянием" ни по цели, ни по подходам, ни по
        снаряду. Отдельно: если последняя (нерazгрузочная) запись блока A
        уже достигла потолка и по цели, и по подходам (VOLUME_TARGET_CEILING/
        VOLUME_WORK_SETS_CEILING) — либо это первый раз (снаряд ещё не
        WEIGHT) и предлагается автоматический переход на отягощение с
        VOLUME_WEIGHT_START_KG, либо снаряд уже WEIGHT и предлагается
        следующий вес по формуле роста (grow_volume_weight_kg) — в обоих
        случаях needs_new_equipment=False: это не "спросить снаряд у
        пользователя", а прямое решение приложения, аналогично тому, как
        цель/объём для обычного роста не спрашиваются, а вычисляются."""
        if block_type == BlockType.A:
            history = _exclude_deload_entries(history)

        if not history:
            return NextBlockState(
                target=block_config.base_target, volume=0,
                equipment_type=EquipmentType.BAND, equipment_value=None, equipment_item_id=None,
                needs_new_equipment=True, work_sets=block_config.work_sets,
            )

        last_block = _find_block(history[-1], block_type)
        equipment_source = last_block
        needs_new_equipment = last_block.equipment_changed
        if last_block.transition_failed:
            if bypass_transition_wait:
                needs_new_equipment = True
            elif len(history) >= 2:
                equipment_source = _find_block(history[-2], block_type)
                needs_new_equipment = False

        work_sets = block_config.work_sets
        equipment_type = equipment_source.equipment_type
        equipment_value = equipment_source.equipment_value

        if block_type == BlockType.A:
            work_sets = _work_sets_after(last_block)
            at_ceiling = last_block.target_after >= VOLUME_TARGET_CEILING and work_sets >= VOLUME_WORK_SETS_CEILING
            if at_ceiling:
                needs_new_equipment = False
                if last_block.equipment_type == EquipmentType.WEIGHT:
                    equipment_type = EquipmentType.WEIGHT
                    equipment_value = grow_volume_weight_kg(last_block.equipment_value or VOLUME_WEIGHT_START_KG)
                else:
                    equipment_type = EquipmentType.WEIGHT
                    equipment_value = VOLUME_WEIGHT_START_KG

        return NextBlockState(
            target=last_block.target_after,
            volume=_block_to_log(last_block).volume,
            equipment_type=equipment_type,
            equipment_value=equipment_value,
            equipment_item_id=equipment_source.equipment_item_id,
            needs_new_equipment=needs_new_equipment,
            work_sets=work_sets,
        )

    @staticmethod
    def _check_transition(
        preceding: Workout | None, block_type: BlockType, block_config, max_reps: int,
    ) -> TransitionOutcome:
        if preceding is None:
            return TransitionOutcome.NOT_APPLICABLE
        preceding_block = _find_block(preceding, block_type)
        return check_transition_outcome(
            block_config, max_reps, is_first_workout_on_new_gear=preceding_block.equipment_changed,
        )

    @staticmethod
    def _apply_transition_outcome(
        outcome: TransitionOutcome, result, preceding: Workout | None, block_type: BlockType,
    ) -> tuple[int, bool, bool]:
        """(target_after, equipment_changed, transition_failed) с учётом
        возможного отката. При FAILED цель откатывается на target_before
        предыдущей тренировки (это и есть "последний результат на прежнем
        снаряде" — до того как предыдущая тренировка сама переключилась на
        новый снаряд, у неё ещё было старое target_before)."""
        if outcome != TransitionOutcome.FAILED:
            return result.new_target, result.equipment_changed, False
        preceding_block = _find_block(preceding, block_type)
        return preceding_block.target_before, False, True

    @staticmethod
    def _preceding_chain_state(chain: list[Workout], position: int) -> tuple[int, int, int, int, int]:
        """Только для edit_workout — цепочка каскада, а не полная история.
        work_sets_before_a (иерархия роста, часть 2) читается из
        work_sets_after предыдущей записи цепочки — если та сама была
        разгрузочной (is_deload), её work_sets_after по построению равен
        work_sets_before (разгрузка не двигает состояние), так что читать
        напрямую безопасно без отдельного случая."""
        if position == 0:
            return VOLUME_BLOCK.base_target, STRENGTH_BLOCK.base_target, 0, 0, VOLUME_BLOCK.work_sets
        preceding = chain[position - 1]
        block_a, block_b = _find_block(preceding, BlockType.A), _find_block(preceding, BlockType.B)
        return (
            block_a.target_after,
            block_b.target_after,
            _block_to_log(block_a).volume,
            _block_to_log(block_b).volume,
            _work_sets_after(block_a),
        )
