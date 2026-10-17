"""Тестовые пользователи с действующим триалом (решение владельца 2026-10-17): свои тренировки, ручная запись,
факультатив, свободные подтягивания, свой план — Premium. Тесты, которые проверяют НЕ подписку, а поведение этих
функций, создают своих пользователей отсюда (как фикстура `user` в conftest.py); гейты подписки — в
test_subscription_feature_gates.py / test_v2_subscription_gate.py."""

from datetime import UTC, datetime, timedelta

from app.db.models import SubscriptionStatus, User
from app.db.repositories.users import UserRepository


async def create_premium_user(session, *, telegram_id: int, username: str | None = None) -> User:
    repo = UserRepository(session)
    created = await repo.create(telegram_id=telegram_id, username=username)
    return await repo.update_subscription_cache(
        created.id, status=SubscriptionStatus.TRIAL, expires_at=datetime.now(UTC) + timedelta(days=14),
    )


async def grant_premium(session, user: User) -> User:
    """Тот же действующий триал уже созданному пользователю (фикстура `user` корневого conftest — без подписки)."""
    return await UserRepository(session).update_subscription_cache(
        user.id, status=SubscriptionStatus.TRIAL, expires_at=datetime.now(UTC) + timedelta(days=14),
    )
