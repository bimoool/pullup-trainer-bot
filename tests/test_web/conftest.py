from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from app.db.models import SubscriptionStatus, User
from app.db.repositories.users import UserRepository


@pytest.fixture
def plan_calendar():
    """Explicit local-calendar fixture for plan tests, separate from engine time."""
    from tests.support.plan_calendar import install_plan_calendar
    at = datetime.now(UTC)
    restore = install_plan_calendar(at, {1001})
    yield at
    restore()


@pytest_asyncio.fixture
async def user(session) -> User:
    """Пользователь веб-тестов — с действующим триалом (#300): старт курсовой тренировки требует подписки, а
    остальные v2-тесты проверяют не её. Тесты подписки задают статус явно (tests/test_web/test_v2_subscription_gate.py)."""
    repo = UserRepository(session)
    created = await repo.create(telegram_id=1001, username="tester")
    return await repo.update_subscription_cache(
        created.id, status=SubscriptionStatus.TRIAL, expires_at=datetime.now(UTC) + timedelta(days=14),
    )
