from datetime import UTC, datetime

from app.db.models import User
from app.db.repositories.baselines import BaselineRepository


async def test_create_and_get_by_id(session, user: User):
    repo = BaselineRepository(session)
    created = await repo.create(user_id=user.id, performed_at=datetime(2026, 1, 1, tzinfo=UTC), reps=18)

    fetched = await repo.get_by_id(created.id)
    assert fetched is not None
    assert fetched.reps == 18


async def test_get_latest_for_user(session, user: User):
    repo = BaselineRepository(session)
    await repo.create(user_id=user.id, performed_at=datetime(2026, 1, 1, tzinfo=UTC), reps=15)
    second = await repo.create(user_id=user.id, performed_at=datetime(2026, 3, 1, tzinfo=UTC), reps=20)

    latest = await repo.get_latest_for_user(user.id)
    assert latest is not None
    assert latest.id == second.id


async def test_list_for_user_ordered_chronologically(session, user: User):
    repo = BaselineRepository(session)
    later = await repo.create(user_id=user.id, performed_at=datetime(2026, 3, 1, tzinfo=UTC), reps=20)
    earlier = await repo.create(user_id=user.id, performed_at=datetime(2026, 1, 1, tzinfo=UTC), reps=15)

    baselines = await repo.list_for_user(user.id)
    assert [b.id for b in baselines] == [earlier.id, later.id]


async def test_get_latest_for_user_with_no_baselines(session, user: User):
    repo = BaselineRepository(session)
    assert await repo.get_latest_for_user(user.id) is None
