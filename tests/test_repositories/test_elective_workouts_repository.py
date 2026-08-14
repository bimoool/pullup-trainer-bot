from datetime import UTC, datetime, timedelta

from app.db.models import User
from app.db.repositories.elective_workouts import ElectiveWorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.electives import ElectiveType


async def test_create_and_list_for_user(session, user: User):
    repo = ElectiveWorkoutRepository(session)
    await repo.create(
        user_id=user.id, elective_type=ElectiveType.MAX_REPS_LADDER, performed_at=datetime.now(UTC),
        total_reps=30, reps_sequence=[10, 8, 7, 5], equipment_type=EquipmentType.BODYWEIGHT,
    )

    history = await repo.list_for_user(user.id)
    assert len(history) == 1
    assert history[0].total_reps == 30
    assert history[0].reps_sequence == [10, 8, 7, 5]


async def test_create_volume_target_stores_null_sequence(session, user: User):
    repo = ElectiveWorkoutRepository(session)
    elective = await repo.create(
        user_id=user.id, elective_type=ElectiveType.VOLUME_TARGET, performed_at=datetime.now(UTC),
        total_reps=52, reps_sequence=None, equipment_type=EquipmentType.BAND,
    )
    assert elective.reps_sequence is None
    assert elective.total_reps == 52


async def test_list_types_for_user_is_chronological(session, user: User):
    repo = ElectiveWorkoutRepository(session)
    await repo.create(
        user_id=user.id, elective_type=ElectiveType.W_LADDER, performed_at=datetime(2026, 1, 1, tzinfo=UTC),
        total_reps=20, reps_sequence=[5, 4, 3], equipment_type=EquipmentType.BODYWEIGHT,
    )
    await repo.create(
        user_id=user.id, elective_type=ElectiveType.THREE_MINUTES, performed_at=datetime(2026, 1, 5, tzinfo=UTC),
        total_reps=15, reps_sequence=[5, 5, 5], equipment_type=EquipmentType.BODYWEIGHT,
    )

    types = await repo.list_types_for_user(user.id)
    assert types == [ElectiveType.W_LADDER, ElectiveType.THREE_MINUTES]


async def test_count_since_only_counts_within_window(session, user: User):
    repo = ElectiveWorkoutRepository(session)
    now = datetime.now(UTC)
    await repo.create(
        user_id=user.id, elective_type=ElectiveType.MAX_REPS_LADDER, performed_at=now - timedelta(days=10),
        total_reps=20, reps_sequence=[5, 5, 5, 5], equipment_type=EquipmentType.BODYWEIGHT,
    )
    await repo.create(
        user_id=user.id, elective_type=ElectiveType.W_LADDER, performed_at=now - timedelta(days=2),
        total_reps=20, reps_sequence=[5, 5, 5, 5], equipment_type=EquipmentType.BODYWEIGHT,
    )

    count = await repo.count_since(user.id, now - timedelta(days=7))
    assert count == 1


async def test_count_since_zero_when_no_recent_entries(session, user: User):
    repo = ElectiveWorkoutRepository(session)
    assert await repo.count_since(user.id, datetime.now(UTC) - timedelta(days=7)) == 0
