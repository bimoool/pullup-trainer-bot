from datetime import UTC, datetime, timedelta

from app.db.models import SubscriptionSource, SubscriptionStatus, User
from app.db.repositories.subscriptions import SubscriptionRepository
from app.db.repositories.users import UserRepository
from app.domain.constants import TRIAL_DAYS
from app.services.subscription import SubscriptionService

NOW = datetime(2026, 1, 1, tzinfo=UTC)


async def test_start_trial_sets_status_and_expiry(session, user: User):
    service = SubscriptionService(session)
    updated = await service.start_trial(user.id, now=NOW)

    assert updated.subscription_status == SubscriptionStatus.TRIAL
    assert updated.subscription_expires_at == NOW + timedelta(days=TRIAL_DAYS)

    subscriptions = await SubscriptionRepository(session).list_for_user(user.id)
    assert len(subscriptions) == 1
    assert subscriptions[0].source == SubscriptionSource.TRIAL


async def test_has_access_true_during_trial(session, user: User):
    service = SubscriptionService(session)
    await service.start_trial(user.id, now=NOW)

    assert await service.has_access(user.id, now=NOW + timedelta(days=1)) is True


async def test_has_access_false_after_trial_expires_and_flips_cache(session, user: User):
    service = SubscriptionService(session)
    await service.start_trial(user.id, now=NOW)

    after_expiry = NOW + timedelta(days=TRIAL_DAYS, hours=1)
    assert await service.has_access(user.id, now=after_expiry) is False

    user_after = await UserRepository(session).get_by_id(user.id)
    assert user_after.subscription_status == SubscriptionStatus.EXPIRED


async def test_refresh_status_does_not_downgrade_before_expiry(session, user: User):
    service = SubscriptionService(session)
    await service.start_trial(user.id, now=NOW)

    refreshed = await service.refresh_status(user.id, now=NOW + timedelta(days=1))
    assert refreshed.subscription_status == SubscriptionStatus.TRIAL


async def test_extend_via_coins_stacks_on_remaining_trial(session, user: User):
    service = SubscriptionService(session)
    await service.start_trial(user.id, now=NOW)  # ends NOW + 14d

    still_in_trial = NOW + timedelta(days=5)
    updated = await service.extend_via_coins(user.id, now=still_in_trial, days=30)

    expected_start = NOW + timedelta(days=TRIAL_DAYS)  # не still_in_trial — продление не сжигает остаток триала
    assert updated.subscription_expires_at == expected_start + timedelta(days=30)
    assert updated.subscription_status == SubscriptionStatus.ACTIVE

    subscriptions = await SubscriptionRepository(session).list_for_user(user.id)
    coin_sub = next(s for s in subscriptions if s.source == SubscriptionSource.COINS)
    assert coin_sub.started_at == expected_start


async def test_extend_with_no_active_subscription_starts_from_now(session, user: User):
    service = SubscriptionService(session)
    updated = await service.extend_via_coins(user.id, now=NOW, days=30)
    assert updated.subscription_expires_at == NOW + timedelta(days=30)


async def test_activate_via_stars_records_payment_reference(session, user: User):
    service = SubscriptionService(session)
    await service.activate_via_stars(user.id, now=NOW, days=30, payment_reference="star_charge_42")

    subscriptions = await SubscriptionRepository(session).list_for_user(user.id)
    assert subscriptions[0].source == SubscriptionSource.STARS
    assert subscriptions[0].payment_reference == "star_charge_42"


async def test_grant_by_admin_uses_admin_source(session, user: User):
    service = SubscriptionService(session)
    await service.grant_by_admin(user.id, now=NOW, days=7)

    subscriptions = await SubscriptionRepository(session).list_for_user(user.id)
    assert subscriptions[0].source == SubscriptionSource.ADMIN_GRANT
