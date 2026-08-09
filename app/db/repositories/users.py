from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SubscriptionStatus, User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, telegram_id: int, username: str | None = None) -> User:
        user = User(telegram_id=telegram_id, username=username)
        self._session.add(user)
        await self._session.flush()
        return user

    async def get_by_id(self, user_id: int) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        result = await self._session.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()

    async def list_onboarded(self) -> list[User]:
        """Пользователи, завершившие анкету — адресаты еженедельной рассылки
        (app/workers/weekly_report.py) и других проактивных уведомлений."""
        result = await self._session.execute(select(User).where(User.onboarding_completed_at.is_not(None)))
        return list(result.scalars().all())

    async def list_all(self) -> list[User]:
        """Для админки (Часть 7) — выборка на фокус-группу 10-20 человек,
        пагинация сознательно не нужна (см. respec)."""
        result = await self._session.execute(select(User).order_by(User.created_at))
        return list(result.scalars().all())

    async def update_profile(
        self,
        user_id: int,
        *,
        weight_kg: Decimal | None = None,
        height_cm: int | None = None,
        age: int | None = None,
        timezone: str | None = None,
    ) -> User:
        user = await self._session.get_one(User, user_id)
        if weight_kg is not None:
            user.weight_kg = weight_kg
        if height_cm is not None:
            user.height_cm = height_cm
        if age is not None:
            user.age = age
        if timezone is not None:
            user.timezone = timezone
        await self._session.flush()
        return user

    async def complete_onboarding(self, user_id: int, completed_at: datetime) -> User:
        user = await self._session.get_one(User, user_id)
        user.onboarding_completed_at = completed_at
        await self._session.flush()
        return user

    async def update_subscription_cache(
        self, user_id: int, *, status: SubscriptionStatus, expires_at: datetime | None,
    ) -> User:
        user = await self._session.get_one(User, user_id)
        user.subscription_status = status
        user.subscription_expires_at = expires_at
        await self._session.flush()
        return user

    async def adjust_coins_balance(self, user_id: int, delta: int) -> User:
        user = await self._session.get_one(User, user_id)
        user.coins_balance += delta
        await self._session.flush()
        return user
