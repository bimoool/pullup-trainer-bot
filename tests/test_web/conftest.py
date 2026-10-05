from datetime import UTC, datetime, timedelta

import pytest_asyncio

from app.db.models import SubscriptionStatus, User
from app.db.repositories.users import UserRepository


@pytest_asyncio.fixture
async def user(session) -> User:
    """Пользователь веб-тестов — с действующим триалом (#300): старт курсовой тренировки требует подписки, а
    остальные v2-тесты проверяют не её. Тесты подписки задают статус явно (tests/test_web/test_v2_subscription_gate.py)."""
    repo = UserRepository(session)
    created = await repo.create(telegram_id=1001, username="tester")
    return await repo.update_subscription_cache(
        created.id, status=SubscriptionStatus.TRIAL, expires_at=datetime.now(UTC) + timedelta(days=14),
    )
