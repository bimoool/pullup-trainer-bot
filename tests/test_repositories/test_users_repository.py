from datetime import UTC, datetime

from app.db.models import SubscriptionStatus, User
from app.db.repositories.users import UserRepository


async def test_create_and_get_by_id(session):
    repo = UserRepository(session)
    created = await repo.create(telegram_id=42, username="alice")

    fetched = await repo.get_by_id(created.id)

    assert fetched is not None
    assert fetched.telegram_id == 42
    assert fetched.username == "alice"
    assert fetched.subscription_status == SubscriptionStatus.NONE
    assert fetched.coins_balance == 0


async def test_get_by_telegram_id(session, user: User):
    repo = UserRepository(session)
    fetched = await repo.get_by_telegram_id(user.telegram_id)
    assert fetched is not None
    assert fetched.id == user.id


async def test_get_by_telegram_id_missing_returns_none(session):
    repo = UserRepository(session)
    assert await repo.get_by_telegram_id(999999) is None


async def test_update_profile_partial(session, user: User):
    repo = UserRepository(session)
    await repo.update_profile(user.id, weight_kg=80, height_cm=180)
    updated = await repo.get_by_id(user.id)
    assert updated.weight_kg == 80
    assert updated.height_cm == 180
    assert updated.age is None

    await repo.update_profile(user.id, age=30)
    updated_again = await repo.get_by_id(user.id)
    assert updated_again.weight_kg == 80  # не затёрлось
    assert updated_again.age == 30


async def test_update_subscription_cache(session, user: User):
    repo = UserRepository(session)
    updated = await repo.update_subscription_cache(user.id, status=SubscriptionStatus.TRIAL, expires_at=None)
    assert updated.subscription_status == SubscriptionStatus.TRIAL


async def test_adjust_coins_balance(session, user: User):
    repo = UserRepository(session)
    await repo.adjust_coins_balance(user.id, 10)
    after_earn = await repo.get_by_id(user.id)
    assert after_earn.coins_balance == 10

    await repo.adjust_coins_balance(user.id, -3)
    after_spend = await repo.get_by_id(user.id)
    assert after_spend.coins_balance == 7


async def test_list_onboarded_excludes_users_without_completed_onboarding(session, user: User):
    repo = UserRepository(session)
    onboarded = await repo.create(telegram_id=555, username="onboarded")
    await repo.complete_onboarding(onboarded.id, datetime(2026, 1, 1, tzinfo=UTC))

    result = await repo.list_onboarded()

    assert [u.id for u in result] == [onboarded.id]
