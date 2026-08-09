from datetime import UTC, datetime

from app.db.models import User, WorkoutSetStatus
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.domain.constants import SET_LENGTH


async def _make_baseline(session, user: User) -> int:
    baseline = await BaselineRepository(session).create(
        user_id=user.id, performed_at=datetime(2026, 1, 1, tzinfo=UTC), reps=18,
    )
    return baseline.id


async def test_create_assigns_first_set_number(session, user: User):
    baseline_id = await _make_baseline(session, user)
    repo = WorkoutSetRepository(session)

    workout_set = await repo.create(user_id=user.id, started_from_baseline_id=baseline_id)

    assert workout_set.set_number == 1
    assert workout_set.status == WorkoutSetStatus.ACTIVE
    assert workout_set.workouts_completed == 0


async def test_second_set_gets_incremented_number(session, user: User):
    baseline_id = await _make_baseline(session, user)
    repo = WorkoutSetRepository(session)

    first = await repo.create(user_id=user.id, started_from_baseline_id=baseline_id)
    second = await repo.create(user_id=user.id, started_from_baseline_id=baseline_id)

    assert first.set_number == 1
    assert second.set_number == 2


async def test_get_active_for_user(session, user: User):
    baseline_id = await _make_baseline(session, user)
    repo = WorkoutSetRepository(session)
    created = await repo.create(user_id=user.id, started_from_baseline_id=baseline_id)

    active = await repo.get_active_for_user(user.id)
    assert active is not None
    assert active.id == created.id


async def test_increment_completed_below_set_length_stays_active(session, user: User):
    baseline_id = await _make_baseline(session, user)
    repo = WorkoutSetRepository(session)
    workout_set = await repo.create(user_id=user.id, started_from_baseline_id=baseline_id)

    updated = await repo.increment_completed(workout_set.id, completed_at=datetime(2026, 1, 3, tzinfo=UTC))

    assert updated.workouts_completed == 1
    assert updated.status == WorkoutSetStatus.ACTIVE
    assert updated.completed_at is None


async def test_increment_completed_reaching_set_length_closes_set(session, user: User):
    baseline_id = await _make_baseline(session, user)
    repo = WorkoutSetRepository(session)
    workout_set = await repo.create(user_id=user.id, started_from_baseline_id=baseline_id)

    for _ in range(SET_LENGTH - 1):
        await repo.increment_completed(workout_set.id, completed_at=datetime(2026, 1, 3, tzinfo=UTC))
    final = await repo.increment_completed(workout_set.id, completed_at=datetime(2026, 3, 1, tzinfo=UTC))

    assert final.workouts_completed == SET_LENGTH
    assert final.status == WorkoutSetStatus.COMPLETED
    assert final.completed_at == datetime(2026, 3, 1, tzinfo=UTC)


async def test_mark_abandoned(session, user: User):
    baseline_id = await _make_baseline(session, user)
    repo = WorkoutSetRepository(session)
    workout_set = await repo.create(user_id=user.id, started_from_baseline_id=baseline_id)

    abandoned = await repo.mark_abandoned(workout_set.id, abandoned_at=datetime(2026, 2, 1, tzinfo=UTC))

    assert abandoned.status == WorkoutSetStatus.ABANDONED
