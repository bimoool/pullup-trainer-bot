from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Block, BlockType, Workout, WorkoutStatus
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.domain.constants import STRENGTH_BLOCK, VOLUME_BLOCK, EquipmentType
from app.domain.progression import (
    TransitionOutcome,
    check_transition_outcome,
    recalculate_cascade,
    recalculate_target,
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
            transition_failed=block_a.transition_failed,
        ),
        block_b=BlockAssignment(
            log=_block_to_log(block_b),
            target_before=block_b.target_before,
            target_after=block_b.target_after,
            equipment_changed=block_b.equipment_changed,
            equipment_type=block_b.equipment_type,
            transition_failed=block_b.transition_failed,
        ),
        comment=workout.comment,
    )


@dataclass(frozen=True)
class NextBlockState:
    target: int
    volume: int
    equipment_type: EquipmentType
    equipment_value: Decimal | None
    needs_new_equipment: bool
    # True — предыдущая тренировка сообщила equipment_changed (или истории
    # нет вовсе): снаряд для СЛЕДУЮЩЕЙ тренировки ещё не известен, вызывающий
    # код (хендлер) должен спросить пользователя, а не использовать
    # equipment_type/equipment_value отсюда как есть — это старый снаряд.


def _apply_cascade_result(workout: Workout, record: WorkoutRecord) -> None:
    # equipment_type/equipment_value/transition_failed каскад не трогает —
    # это факт того, что реально использовалось, он не переигрывается.
    block_a, block_b = _find_block(workout, BlockType.A), _find_block(workout, BlockType.B)
    block_a.target_before = record.block_a.target_before
    block_a.target_after = record.block_a.target_after
    block_a.equipment_changed = record.block_a.equipment_changed
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

    async def resolve_next_targets(self, user_id: int) -> tuple[NextBlockState, NextBlockState]:
        """Публичный вход для хендлеров: состояние (цель/объём/снаряд), с
        которого начнётся следующая тренировка обоих блоков — то же самое,
        что использует complete_workout внутри себя. Нужен хендлеру, чтобы
        показать план и спросить снаряд ДО того, как тренировка реально
        записана (см. app/bot/handlers/workout.py)."""
        history = await self.list_for_user(user_id)
        return (
            self._resolve_next_state(history, BlockType.A, VOLUME_BLOCK),
            self._resolve_next_state(history, BlockType.B, STRENGTH_BLOCK),
        )

    async def list_for_set(self, workout_set_id: int) -> list[Workout]:
        result = await self._session.execute(
            select(Workout)
            .where(Workout.workout_set_id == workout_set_id)
            .options(selectinload(Workout.blocks))
            .order_by(Workout.performed_at),
        )
        return list(result.scalars().all())

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
        target_a_override: int | None = None,
        target_b_override: int | None = None,
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
            target_a_override=target_a_override,
            target_b_override=target_b_override,
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
        target_a_override: int | None = None,
        target_b_override: int | None = None,
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
        запишется."""
        workout = await self.get_by_id(workout_id)
        if workout is None:
            raise ValueError(f"workout {workout_id} not found")

        history = await self.list_for_user(workout.user_id)
        preceding = history[-1] if history else None

        state_a = self._resolve_next_state(history, BlockType.A, VOLUME_BLOCK)
        state_b = self._resolve_next_state(history, BlockType.B, STRENGTH_BLOCK)
        target_before_a = target_a_override if target_a_override is not None else state_a.target
        target_before_b = target_b_override if target_b_override is not None else state_b.target

        result_a = recalculate_target(
            VOLUME_BLOCK, target_before_a, block_a_reps.working_reps, block_a_reps.max_reps,
            block_a_reps.volume, state_a.volume, block_a_equipment_type,
        )
        result_b = recalculate_target(
            STRENGTH_BLOCK, target_before_b, block_b_reps.working_reps, block_b_reps.max_reps,
            block_b_reps.volume, state_b.volume, block_b_equipment_type,
        )

        transition_a = self._check_transition(preceding, BlockType.A, VOLUME_BLOCK, block_a_reps.max_reps)
        transition_b = self._check_transition(preceding, BlockType.B, STRENGTH_BLOCK, block_b_reps.max_reps)

        target_after_a, equipment_changed_a, failed_a = self._apply_transition_outcome(
            transition_a, result_a, preceding, BlockType.A,
        )
        target_after_b, equipment_changed_b, failed_b = self._apply_transition_outcome(
            transition_b, result_b, preceding, BlockType.B,
        )

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
                transition_failed=failed_a,
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
        state_a = self._resolve_next_state(history, BlockType.A, VOLUME_BLOCK)
        state_b = self._resolve_next_state(history, BlockType.B, STRENGTH_BLOCK)

        result_a = recalculate_target(
            VOLUME_BLOCK, state_a.target, block_a_reps.working_reps, block_a_reps.max_reps,
            block_a_reps.volume, state_a.volume, block_a_equipment_type,
        )
        result_b = recalculate_target(
            STRENGTH_BLOCK, state_b.target, block_b_reps.working_reps, block_b_reps.max_reps,
            block_b_reps.volume, state_b.volume, block_b_equipment_type,
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
            ),
        )
        self._session.add(
            Block(
                workout_id=workout.id, block_type=BlockType.B,
                working_reps=list(block_b_reps.working_reps), max_reps=block_b_reps.max_reps,
                target_before=state_b.target, target_after=result_b.new_target,
                equipment_changed=result_b.equipment_changed,
                equipment_type=block_b_equipment_type, equipment_value=block_b_equipment_value,
            ),
        )

        await self._session.flush()
        await self._workout_sets.increment_completed(workout.workout_set_id, completed_at=workout.performed_at)
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

        target_before_a, target_before_b, prev_volume_a, prev_volume_b = self._preceding_chain_state(chain, position)
        result_a = recalculate_target(
            VOLUME_BLOCK, target_before_a, new_block_a_reps.working_reps, new_block_a_reps.max_reps,
            new_block_a_reps.volume, prev_volume_a, block_a.equipment_type,
        )
        result_b = recalculate_target(
            STRENGTH_BLOCK, target_before_b, new_block_b_reps.working_reps, new_block_b_reps.max_reps,
            new_block_b_reps.volume, prev_volume_b, block_b.equipment_type,
        )

        block_a.working_reps = list(new_block_a_reps.working_reps)
        block_a.max_reps = new_block_a_reps.max_reps
        block_a.target_before = target_before_a
        block_a.target_after = result_a.new_target
        block_a.equipment_changed = result_a.equipment_changed

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
            cascaded = recalculate_cascade(
                result_a.new_target, result_b.new_target,
                new_block_a_reps.volume, new_block_b_reps.volume, records,
            )
            for db_workout, new_record in zip(following, cascaded, strict=True):
                _apply_cascade_result(db_workout, new_record)

        await self._session.flush()
        await self._session.refresh(workout, attribute_names=["blocks"])
        return workout

    def _resolve_next_state(
        self, history: list[Workout], block_type: BlockType, block_config,
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
        спрашивать заново нечего."""
        if not history:
            return NextBlockState(
                target=block_config.base_target, volume=0,
                equipment_type=EquipmentType.BAND, equipment_value=None,
                needs_new_equipment=True,
            )

        last_block = _find_block(history[-1], block_type)
        equipment_source = last_block
        needs_new_equipment = last_block.equipment_changed
        if last_block.transition_failed and len(history) >= 2:
            equipment_source = _find_block(history[-2], block_type)
            needs_new_equipment = False

        return NextBlockState(
            target=last_block.target_after,
            volume=_block_to_log(last_block).volume,
            equipment_type=equipment_source.equipment_type,
            equipment_value=equipment_source.equipment_value,
            needs_new_equipment=needs_new_equipment,
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
    def _preceding_chain_state(chain: list[Workout], position: int) -> tuple[int, int, int, int]:
        """Только для edit_workout — цепочка каскада, а не полная история."""
        if position == 0:
            return VOLUME_BLOCK.base_target, STRENGTH_BLOCK.base_target, 0, 0
        preceding = chain[position - 1]
        block_a, block_b = _find_block(preceding, BlockType.A), _find_block(preceding, BlockType.B)
        return (
            block_a.target_after,
            block_b.target_after,
            _block_to_log(block_a).volume,
            _block_to_log(block_b).volume,
        )
