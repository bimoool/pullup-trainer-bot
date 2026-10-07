"""Решение владельца 2026-10-07: Premium-триал — 7 дней; онбординг — ГАРАНТИЯ МИНИМУМА доступа, не перезапись
(SubscriptionService.start_trial). Проверяется настоящим путём завершения анкеты (OnboardingService) — тем же, что
бот (handle_timezone) и POST /api/onboarding/questionnaire."""

from datetime import UTC, date, datetime, timedelta

import pytest

from app.db.models import Gender, SubscriptionSource, SubscriptionStatus, User
from app.db.repositories.subscriptions import SubscriptionRepository
from app.db.repositories.users import UserRepository
from app.domain.constants import TRIAL_DAYS
from app.services.onboarding import OnboardingService
from app.services.subscription import SubscriptionService

NOW = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
WEEK = timedelta(days=7)


async def _onboard(session, user: User, *, now: datetime = NOW) -> User:
    return await OnboardingService(session).complete_questionnaire_and_start_trial(
        user_id=user.id, weight_kg=78, height_cm=180, gender=Gender.MALE, birth_date=date(1998, 5, 20),
        timezone="Europe/Moscow", now=now,
    )


async def _history(session, user: User) -> list[tuple[str, str, datetime]]:
    rows = await SubscriptionRepository(session).list_for_user(user.id)
    return [(r.status.value, r.source.value, r.ends_at) for r in rows]


async def _state(session, user: User) -> tuple[SubscriptionStatus, datetime | None]:
    fresh = await UserRepository(session).get_by_id(user.id)
    await session.refresh(fresh)
    return fresh.subscription_status, fresh.subscription_expires_at


def test_trial_is_seven_days():
    assert TRIAL_DAYS == 7


async def test_1_new_user_gets_seven_day_trial(session, user: User):
    updated = await _onboard(session, user)

    assert (updated.subscription_status, updated.subscription_expires_at) == (SubscriptionStatus.TRIAL, NOW + WEEK)
    assert await _history(session, user) == [("trial", "trial", NOW + WEEK)]


@pytest.mark.parametrize("status", [SubscriptionStatus.EXPIRED, SubscriptionStatus.TRIAL, SubscriptionStatus.ACTIVE])
async def test_2_expired_user_gets_seven_day_trial(session, user: User, status: SubscriptionStatus):
    """Истёкший доступ (в т.ч. залипший кэш trial/active со сроком в прошлом) — новый 7-дневный триал."""
    await UserRepository(session).update_subscription_cache(user.id, status=status, expires_at=NOW - timedelta(days=2))

    await _onboard(session, user)

    assert await _state(session, user) == (SubscriptionStatus.TRIAL, NOW + WEEK)
    assert (await _history(session, user))[-1] == ("trial", "trial", NOW + WEEK)


async def test_3_trial_with_three_days_left_is_topped_up_to_seven(session, user: User):
    await SubscriptionService(session).start_trial(user.id, now=NOW - timedelta(days=4))  # ends NOW + 3d

    await _onboard(session, user)

    status, expires_at = await _state(session, user)
    assert status == SubscriptionStatus.TRIAL and expires_at >= NOW + WEEK
    assert await _history(session, user) == [
        ("trial", "trial", NOW + timedelta(days=3)), ("trial", "trial", NOW + WEEK),
    ]


async def test_4_trial_with_twenty_days_left_is_unchanged_and_writes_no_row(session, user: User):
    long_trial_end = NOW + timedelta(days=20)
    await UserRepository(session).update_subscription_cache(
        user.id, status=SubscriptionStatus.TRIAL, expires_at=long_trial_end,
    )
    await SubscriptionRepository(session).create(
        user_id=user.id, status=SubscriptionStatus.TRIAL, source=SubscriptionSource.TRIAL,
        started_at=NOW - timedelta(days=1), ends_at=long_trial_end,
    )
    before = await _history(session, user)

    await _onboard(session, user)

    assert await _state(session, user) == (SubscriptionStatus.TRIAL, long_trial_end)
    assert await _history(session, user) == before


@pytest.mark.parametrize("days_left", [2, 30])
async def test_5_active_admin_grant_is_unchanged(session, user: User, days_left: int):
    """ACTIVE не понижается до TRIAL и не сокращается — даже если до конца меньше 7 дней."""
    granted = await SubscriptionService(session).grant_by_admin(user.id, now=NOW - timedelta(days=30 - days_left), days=30)
    before = await _history(session, user)

    await _onboard(session, user)

    assert await _state(session, user) == (SubscriptionStatus.ACTIVE, granted.subscription_expires_at)
    assert await _history(session, user) == before


async def test_6_active_payment_is_unchanged(session, user: User):
    paid = await SubscriptionService(session).activate_via_stars(
        user.id, now=NOW - timedelta(days=1), days=30, payment_reference="tg-charge-1",
    )
    before = await _history(session, user)

    await _onboard(session, user)

    assert await _state(session, user) == (SubscriptionStatus.ACTIVE, paid.subscription_expires_at)
    assert await _history(session, user) == before


async def test_6b_trial_then_payment_then_onboarding_keeps_payment(session, user: User):
    await _onboard(session, user, now=NOW - timedelta(days=3))
    paid = await SubscriptionService(session).activate_via_stars(user.id, now=NOW, days=30, payment_reference="x")

    await _onboard(session, user)

    assert await _state(session, user) == (SubscriptionStatus.ACTIVE, paid.subscription_expires_at)


async def test_7_repeated_onboarding_is_idempotent(session, user: User):
    await _onboard(session, user)
    first = (await _state(session, user), await _history(session, user))

    await _onboard(session, user)
    await _onboard(session, user)

    assert (await _state(session, user), await _history(session, user)) == first


async def test_7b_later_reonboarding_only_tops_up_to_now_plus_seven(session, user: User):
    """Правило B буквально: позже повторный онбординг доводит остаток триала до now + 7 дней (не дольше)."""
    await _onboard(session, user)
    later = NOW + timedelta(days=2)

    await _onboard(session, user, now=later)

    assert await _state(session, user) == (SubscriptionStatus.TRIAL, later + WEEK)


async def test_unbounded_entitlement_is_never_replaced(session, user: User):
    await UserRepository(session).update_subscription_cache(user.id, status=SubscriptionStatus.ACTIVE, expires_at=None)

    await _onboard(session, user)

    assert await _state(session, user) == (SubscriptionStatus.ACTIVE, None)
    assert await _history(session, user) == []
