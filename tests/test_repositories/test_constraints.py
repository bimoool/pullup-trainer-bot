from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    Achievement,
    Block,
    BlockType,
    Branch,
    EquipmentType,
    User,
    Workout,
    WorkoutStatus,
)
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.workout_sets import WorkoutSetRepository


async def _make_set(session, user: User) -> int:
    baseline = await BaselineRepository(session).create(
        user_id=user.id, performed_at=datetime(2025, 12, 1, tzinfo=UTC),
        branch_result=Branch.BAND, equipment_type=EquipmentType.BAND, reps=18,
    )
    workout_set = await WorkoutSetRepository(session).create(
        user_id=user.id, started_from_baseline_id=baseline.id,
    )
    return workout_set.id


async def test_unique_workout_sequence_number_is_deferred_until_commit(session, user: User):
    """UNIQUE(user_id, sequence_number) объявлен DEFERRABLE INITIALLY DEFERRED
    намеренно (см. WorkoutRepository._find_insertion_index) — при перенумерации
    задним числом строки временно делят один sequence_number внутри
    транзакции. Здесь это проверяется напрямую, в обход репозитория: два
    workout с одинаковым sequence_number должны спокойно пройти flush(),
    но упасть на commit(), если конфликт не разрешён до конца транзакции."""
    workout_set_id = await _make_set(session, user)

    session.add(Workout(
        user_id=user.id, workout_set_id=workout_set_id,
        performed_at=datetime(2026, 1, 1, tzinfo=UTC), status=WorkoutStatus.COMPLETED, sequence_number=1,
    ))
    session.add(Workout(
        user_id=user.id, workout_set_id=workout_set_id,
        performed_at=datetime(2026, 1, 2, tzinfo=UTC), status=WorkoutStatus.COMPLETED, sequence_number=1,
    ))

    await session.flush()  # не должно упасть — проверка отложена

    with pytest.raises(IntegrityError):
        await session.commit()


async def test_unique_blocks_workout_block_type_is_immediate(session, user: User):
    """В отличие от sequence_number, UNIQUE(workout_id, block_type) не
    отложен — конфликт ловится сразу на flush(), без выполнения повторного
    полного цикла пересчёта."""
    workout_set_id = await _make_set(session, user)
    workout = Workout(
        user_id=user.id, workout_set_id=workout_set_id,
        performed_at=datetime(2026, 1, 1, tzinfo=UTC), status=WorkoutStatus.COMPLETED, sequence_number=1,
    )
    session.add(workout)
    await session.flush()

    session.add(Block(
        workout_id=workout.id, block_type=BlockType.A, working_reps=[15, 15, 15],
        max_reps=16, target_before=15, target_after=16, band_thickness_mm=22.0,
    ))
    session.add(Block(
        workout_id=workout.id, block_type=BlockType.A, working_reps=[15, 15, 15],
        max_reps=17, target_before=15, target_after=17, band_thickness_mm=22.0,
    ))

    with pytest.raises(IntegrityError):
        await session.flush()


async def test_unique_achievements_user_code_is_immediate(session, user: User):
    session.add(Achievement(user_id=user.id, code="first_baseline"))
    session.add(Achievement(user_id=user.id, code="first_baseline"))

    with pytest.raises(IntegrityError):
        await session.flush()
