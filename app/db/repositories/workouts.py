from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Block, BlockType, Workout, WorkoutStatus
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.domain.constants import BLOCK_A, BLOCK_B
from app.domain.progression import recalculate_cascade, recalculate_target
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
        ),
        block_b=BlockAssignment(
            log=_block_to_log(block_b),
            target_before=block_b.target_before,
            target_after=block_b.target_after,
            equipment_changed=block_b.equipment_changed,
        ),
        comment=workout.comment,
    )


def _apply_cascade_result(workout: Workout, record: WorkoutRecord) -> None:
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
        """Только COMPLETED-тренировки (sequence_number проставлен), в
        хронологическом порядке. Тренировки в статусе STARTED ещё не заняли
        место в цепочке прогрессии и в эту выборку не попадают."""
        result = await self._session.execute(
            select(Workout)
            .where(Workout.user_id == user_id, Workout.sequence_number.is_not(None))
            .options(selectinload(Workout.blocks))
            .order_by(Workout.sequence_number),
        )
        return list(result.scalars().all())

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
        band_thickness_mm: Decimal,
        weight_kg: Decimal,
        comment: str | None = None,
    ) -> Workout:
        """start_workout + complete_workout в одном вызове — основной путь,
        когда обе части результата известны сразу (так тесты и, позже, бот
        будут создавать подавляющее большинство тренировок)."""
        workout = await self.start_workout(
            user_id=user_id, workout_set_id=workout_set_id, performed_at=performed_at, comment=comment,
        )
        return await self.complete_workout(
            workout_id=workout.id,
            block_a_reps=block_a_reps,
            block_b_reps=block_b_reps,
            band_thickness_mm=band_thickness_mm,
            weight_kg=weight_kg,
        )

    async def complete_workout(
        self,
        *,
        workout_id: int,
        block_a_reps: BlockLog,
        block_b_reps: BlockLog,
        band_thickness_mm: Decimal,
        weight_kg: Decimal,
        comment: str | None = None,
    ) -> Workout:
        """Прикрепляет результаты блоков к ранее начатой (start_workout)
        тренировке: определяет её место в хронологии по performed_at (даже
        если это бэкдейт), считает target_before/after через
        domain.recalculate_target и каскадом пересчитывает все более поздние
        тренировки пользователя через domain.recalculate_cascade."""
        workout = await self.get_by_id(workout_id)
        if workout is None:
            raise ValueError(f"workout {workout_id} not found")

        existing = await self.list_for_user(workout.user_id)
        insertion_index = self._find_insertion_index(existing, workout.performed_at)
        target_before_a, target_before_b, prev_volume_a, prev_volume_b = self._preceding_state(
            existing, insertion_index,
        )

        result_a = recalculate_target(
            BLOCK_A, target_before_a, block_a_reps.max_reps, block_a_reps.volume, prev_volume_a,
        )
        result_b = recalculate_target(
            BLOCK_B, target_before_b, block_b_reps.max_reps, block_b_reps.volume, prev_volume_b,
        )

        if comment is not None:
            workout.comment = comment
        workout.status = WorkoutStatus.COMPLETED
        workout.sequence_number = insertion_index + 1

        self._session.add(
            Block(
                workout_id=workout.id,
                block_type=BlockType.A,
                working_reps=list(block_a_reps.working_reps),
                max_reps=block_a_reps.max_reps,
                target_before=target_before_a,
                target_after=result_a.new_target,
                equipment_changed=result_a.equipment_changed,
                band_thickness_mm=band_thickness_mm,
            ),
        )
        self._session.add(
            Block(
                workout_id=workout.id,
                block_type=BlockType.B,
                working_reps=list(block_b_reps.working_reps),
                max_reps=block_b_reps.max_reps,
                target_before=target_before_b,
                target_after=result_b.new_target,
                equipment_changed=result_b.equipment_changed,
                weight_kg=weight_kg,
            ),
        )

        following = existing[insertion_index:]
        if following:
            records = [_workout_to_record(w) for w in following]
            cascaded = recalculate_cascade(
                result_a.new_target, result_b.new_target, block_a_reps.volume, block_b_reps.volume, records,
            )
            for db_workout, new_record in zip(following, cascaded, strict=True):
                db_workout.sequence_number += 1
                _apply_cascade_result(db_workout, new_record)

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
        """Редактирует уже введённые повторения завершённой тренировки (не
        дату — сдвиг даты потребовал бы повторного определения позиции в
        цепочке, это отдельная операция, здесь не реализована) и каскадом
        пересчитывает все более поздние тренировки."""
        workout = await self.get_by_id(workout_id)
        if workout is None:
            raise ValueError(f"workout {workout_id} not found")
        if workout.sequence_number is None:
            raise ValueError("cannot edit a workout that was never completed")

        all_for_user = await self.list_for_user(workout.user_id)
        position = next(i for i, w in enumerate(all_for_user) if w.id == workout.id)

        block_a, block_b = _find_block(workout, BlockType.A), _find_block(workout, BlockType.B)
        new_block_a_reps = block_a_reps or _block_to_log(block_a)
        new_block_b_reps = block_b_reps or _block_to_log(block_b)

        target_before_a, target_before_b, prev_volume_a, prev_volume_b = self._preceding_state(
            all_for_user, position,
        )
        result_a = recalculate_target(
            BLOCK_A, target_before_a, new_block_a_reps.max_reps, new_block_a_reps.volume, prev_volume_a,
        )
        result_b = recalculate_target(
            BLOCK_B, target_before_b, new_block_b_reps.max_reps, new_block_b_reps.volume, prev_volume_b,
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

        following = all_for_user[position + 1 :]
        if following:
            records = [_workout_to_record(w) for w in following]
            cascaded = recalculate_cascade(
                result_a.new_target,
                result_b.new_target,
                new_block_a_reps.volume,
                new_block_b_reps.volume,
                records,
            )
            for db_workout, new_record in zip(following, cascaded, strict=True):
                _apply_cascade_result(db_workout, new_record)

        await self._session.flush()
        await self._session.refresh(workout, attribute_names=["blocks"])
        return workout

    @staticmethod
    def _find_insertion_index(existing: list[Workout], performed_at: datetime) -> int:
        for i, w in enumerate(existing):
            if w.performed_at > performed_at:
                return i
        return len(existing)

    @staticmethod
    def _preceding_state(existing: list[Workout], insertion_index: int) -> tuple[int, int, int, int]:
        if insertion_index == 0:
            return BLOCK_A.base_target, BLOCK_B.base_target, 0, 0
        preceding = existing[insertion_index - 1]
        block_a, block_b = _find_block(preceding, BlockType.A), _find_block(preceding, BlockType.B)
        return (
            block_a.target_after,
            block_b.target_after,
            _block_to_log(block_a).volume,
            _block_to_log(block_b).volume,
        )
