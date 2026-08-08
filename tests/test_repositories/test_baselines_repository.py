from datetime import UTC, datetime

from app.db.models import Branch, Equipment, User
from app.db.repositories.baselines import BaselineRepository


async def test_create_and_get_by_id(session, user: User):
    repo = BaselineRepository(session)
    created = await repo.create(
        user_id=user.id,
        performed_at=datetime(2026, 1, 1, tzinfo=UTC),
        branch_result=Branch.BAND,
        equipment_type=Equipment.BAND,
        reps=18,
        band_thickness_mm=22.0,
    )

    fetched = await repo.get_by_id(created.id)
    assert fetched is not None
    assert fetched.reps == 18
    assert fetched.branch_result == Branch.BAND
    assert fetched.weight_kg is None


async def test_get_latest_for_user(session, user: User):
    repo = BaselineRepository(session)
    await repo.create(
        user_id=user.id, performed_at=datetime(2026, 1, 1, tzinfo=UTC),
        branch_result=Branch.BAND, equipment_type=Equipment.BAND, reps=15,
    )
    second = await repo.create(
        user_id=user.id, performed_at=datetime(2026, 3, 1, tzinfo=UTC),
        branch_result=Branch.BAND, equipment_type=Equipment.BAND, reps=20,
    )

    latest = await repo.get_latest_for_user(user.id)
    assert latest is not None
    assert latest.id == second.id


async def test_list_for_user_ordered_chronologically(session, user: User):
    repo = BaselineRepository(session)
    later = await repo.create(
        user_id=user.id, performed_at=datetime(2026, 3, 1, tzinfo=UTC),
        branch_result=Branch.BAND, equipment_type=Equipment.BAND, reps=20,
    )
    earlier = await repo.create(
        user_id=user.id, performed_at=datetime(2026, 1, 1, tzinfo=UTC),
        branch_result=Branch.BAND, equipment_type=Equipment.BAND, reps=15,
    )

    baselines = await repo.list_for_user(user.id)
    assert [b.id for b in baselines] == [earlier.id, later.id]


async def test_assisted_branch_uses_weight_free_band(session, user: User):
    repo = BaselineRepository(session)
    baseline = await repo.create(
        user_id=user.id, performed_at=datetime(2026, 1, 1, tzinfo=UTC),
        branch_result=Branch.ASSISTED, equipment_type=Equipment.BAND, reps=8,
        band_thickness_mm=32.0,
    )
    assert baseline.branch_result == Branch.ASSISTED
