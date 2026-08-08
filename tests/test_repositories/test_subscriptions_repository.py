from datetime import UTC, datetime, timedelta

from app.db.models import SubscriptionSource, SubscriptionStatus, User
from app.db.repositories.subscriptions import SubscriptionRepository


async def test_create_and_get_latest(session, user: User):
    repo = SubscriptionRepository(session)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    await repo.create(
        user_id=user.id, status=SubscriptionStatus.TRIAL, source=SubscriptionSource.TRIAL,
        started_at=now, ends_at=now + timedelta(days=14),
    )
    active = await repo.create(
        user_id=user.id, status=SubscriptionStatus.ACTIVE, source=SubscriptionSource.STARS,
        started_at=now + timedelta(days=14), ends_at=now + timedelta(days=44),
        payment_reference="stars_charge_123",
    )

    latest = await repo.get_latest_for_user(user.id)
    assert latest is not None
    assert latest.id == active.id
    assert latest.payment_reference == "stars_charge_123"


async def test_list_for_user_ordered_by_started_at(session, user: User):
    repo = SubscriptionRepository(session)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    trial = await repo.create(
        user_id=user.id, status=SubscriptionStatus.TRIAL, source=SubscriptionSource.TRIAL,
        started_at=now, ends_at=now + timedelta(days=14),
    )
    paid = await repo.create(
        user_id=user.id, status=SubscriptionStatus.ACTIVE, source=SubscriptionSource.COINS,
        started_at=now + timedelta(days=14), ends_at=now + timedelta(days=44),
    )

    subscriptions = await repo.list_for_user(user.id)
    assert [s.id for s in subscriptions] == [trial.id, paid.id]


async def test_get_latest_for_user_with_no_subscriptions(session, user: User):
    repo = SubscriptionRepository(session)
    assert await repo.get_latest_for_user(user.id) is None
