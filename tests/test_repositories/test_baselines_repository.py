from datetime import UTC, datetime

from app.db.models import User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository


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


async def test_list_since_returns_only_newer_ids_across_all_users(session, user: User):
    other = await UserRepository(session).create(telegram_id=9101, username="other")
    repo = BaselineRepository(session)
    first = await repo.create(user_id=user.id, performed_at=datetime(2026, 1, 1, tzinfo=UTC), reps=15)
    second = await repo.create(user_id=other.id, performed_at=datetime(2026, 1, 2, tzinfo=UTC), reps=10)
    third = await repo.create(user_id=user.id, performed_at=datetime(2026, 3, 1, tzinfo=UTC), reps=20)

    assert [b.id for b in await repo.list_since(0, limit=10)] == [first.id, second.id, third.id]
    assert [b.id for b in await repo.list_since(first.id, limit=10)] == [second.id, third.id]
    assert await repo.list_since(third.id, limit=10) == []


async def test_list_since_respects_limit_for_pagination(session, user: User):
    repo = BaselineRepository(session)
    for i in range(3):
        await repo.create(user_id=user.id, performed_at=datetime(2026, 1, i + 1, tzinfo=UTC), reps=10 + i)

    page = await repo.list_since(0, limit=2)
    assert len(page) == 2
