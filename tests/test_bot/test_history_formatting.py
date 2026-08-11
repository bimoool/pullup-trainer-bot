"""Читаемая формулировка истории тренировок (Часть 10) — раньше:
"объём св.вес макс 21→цель 13, сила отягощ. 48.00кг макс 4→цель 4"."""

from datetime import UTC, datetime
from decimal import Decimal

from app.bot.handlers.history import format_history_entry
from app.db.models import User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.session import BlockLog


async def _make_workout(session, user: User, *, comment: str | None = None):
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    return await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=datetime(2026, 1, 5, tzinfo=UTC),
        block_a_reps=BlockLog(working_reps=(20, 20, 20), max_reps=21),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=4),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=Decimal("48.00"),
        comment=comment,
    )


async def test_history_entry_is_readable_and_strips_trailing_zeros(session, user: User):
    workout = await _make_workout(session, user)

    entry = format_history_entry(workout)

    assert "Объём (свой вес): максимум 21, следующая цель" in entry
    assert "Сила (отягощение 48 кг): максимум 4, следующая цель" in entry
    assert "48.00" not in entry
    assert "48.0" not in entry


async def test_history_entry_shows_comment_when_present(session, user: User):
    workout = await _make_workout(session, user, comment="тяжело шло сегодня")

    entry = format_history_entry(workout)

    assert "Комментарий: тяжело шло сегодня" in entry


async def test_history_entry_omits_comment_line_when_absent(session, user: User):
    workout = await _make_workout(session, user, comment=None)

    entry = format_history_entry(workout)

    assert "Комментарий" not in entry


async def test_history_entry_marks_backdated_workouts(session, user: User):
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    workout = await WorkoutRepository(session).record_backdated_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=datetime(2026, 1, 5, tzinfo=UTC),
        block_a_reps=BlockLog(working_reps=(10, 10, 10), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.BODYWEIGHT, block_b_equipment_value=None,
    )

    entry = format_history_entry(workout)

    assert "(задним числом)" in entry
