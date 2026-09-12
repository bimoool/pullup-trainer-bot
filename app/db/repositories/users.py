from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Gender, SubscriptionStatus, User


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
        gender: Gender | None = None,
        birth_date: date | None = None,
        timezone: str | None = None,
    ) -> User:
        user = await self._session.get_one(User, user_id)
        if weight_kg is not None:
            user.weight_kg = weight_kg
        if height_cm is not None:
            user.height_cm = height_cm
        if gender is not None:
            user.gender = gender
        if birth_date is not None:
            user.birth_date = birth_date
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

    async def update_timer_preference(self, user_id: int, *, field: str, value: int) -> User:
        """Персистентная настройка таймера Mini App (issue #59, волна 2;
        sound_volume_percent — issue #90) — field один из
        "rest_seconds_block_a"/"rest_seconds_block_b"/"big_break_seconds"/
        "sound_volume_percent" (валидация значения — в app/web/routes.py,
        здесь только запись одного из полей на месте)."""
        user = await self._session.get_one(User, user_id)
        setattr(user, field, value)
        await self._session.flush()
        return user

    async def set_leaderboard_display_name(self, user_id: int, display_name: str | None) -> User:
        """В отличие от update_profile, None здесь валидное значение —
        "стать анонимным" (issue #67), не "пропустить поле" — поэтому
        отдельный метод, а не переиспользование update_profile с его
        семантикой частичного обновления."""
        user = await self._session.get_one(User, user_id)
        user.leaderboard_display_name = display_name
        await self._session.flush()
        return user
