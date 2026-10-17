"""Решение владельца 2026-10-17: факультатив и свободные подтягивания — Premium. Тесты их поведения (не подписки)
дают пользователю действующий триал этой фикстурой; гейт бота — tests/test_bot/test_premium_feature_paywall.py."""

from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import SubscriptionStatus, User
from app.db.repositories.users import UserRepository


@pytest.fixture(autouse=True)
async def _premium_user(session, user: User) -> None:
    await UserRepository(session).update_subscription_cache(
        user.id, status=SubscriptionStatus.TRIAL, expires_at=datetime.now(UTC) + timedelta(days=14),
    )
