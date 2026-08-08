from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SubscriptionSource, SubscriptionStatus, User
from app.db.repositories.subscriptions import SubscriptionRepository
from app.db.repositories.users import UserRepository
from app.domain.constants import TRIAL_DAYS

_ACTIVE_STATUSES = (SubscriptionStatus.TRIAL, SubscriptionStatus.ACTIVE)


class SubscriptionService:
    """Расчёт статуса подписки и поддержание кэша на users.subscription_*.

    users.subscription_status/_expires_at — денормализованный кэш поверх
    истории в subscriptions (решение согласовано на Этапе 2 при утверждении
    схемы). Этот сервис — единственное место, которое обновляет кэш, чтобы
    инвариант "кэш = последняя строка subscriptions" не расползался по коду.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._users = UserRepository(session)
        self._subscriptions = SubscriptionRepository(session)

    async def start_trial(self, user_id: int, *, now: datetime) -> User:
        """Стартует TRIAL_DAYS-дневный пробный период (обычно сразу по
        завершении онбординга)."""
        ends_at = now + timedelta(days=TRIAL_DAYS)
        await self._subscriptions.create(
            user_id=user_id,
            status=SubscriptionStatus.TRIAL,
            source=SubscriptionSource.TRIAL,
            started_at=now,
            ends_at=ends_at,
        )
        return await self._users.update_subscription_cache(
            user_id, status=SubscriptionStatus.TRIAL, expires_at=ends_at,
        )

    async def extend(
        self,
        user_id: int,
        *,
        now: datetime,
        days: int,
        source: SubscriptionSource,
        payment_reference: str | None = None,
    ) -> User:
        """Продлевает доступ — общий путь для Stars, монет и ручной выдачи
        администратором (источник различает их постфактум в истории).

        Новый период стартует от ТЕКУЩЕЙ даты окончания подписки, если она
        ещё не истекла (чтобы продление не сжигало уже оплаченные дни), и
        только иначе — от текущего момента. Это стандартное поведение для
        подписок (как и большинство SaaS), спека явно этого не описывает,
        но не описывает и альтернативы — беру это как разумный дефолт.
        """
        started_at = await self._effective_start(user_id, now)
        ends_at = started_at + timedelta(days=days)
        await self._subscriptions.create(
            user_id=user_id,
            status=SubscriptionStatus.ACTIVE,
            source=source,
            started_at=started_at,
            ends_at=ends_at,
            payment_reference=payment_reference,
        )
        return await self._users.update_subscription_cache(
            user_id, status=SubscriptionStatus.ACTIVE, expires_at=ends_at,
        )

    async def activate_via_stars(
        self, user_id: int, *, now: datetime, days: int, payment_reference: str,
    ) -> User:
        return await self.extend(
            user_id, now=now, days=days, source=SubscriptionSource.STARS, payment_reference=payment_reference,
        )

    async def extend_via_coins(self, user_id: int, *, now: datetime, days: int) -> User:
        """Оплата монетами продлевает ДОСТУП, Stars при этом не списываются
        (см. спеку монетизации) — списание самих монет делает
        GamificationService.spend_coins, здесь только продление подписки."""
        return await self.extend(user_id, now=now, days=days, source=SubscriptionSource.COINS)

    async def grant_by_admin(self, user_id: int, *, now: datetime, days: int) -> User:
        return await self.extend(user_id, now=now, days=days, source=SubscriptionSource.ADMIN_GRANT)

    async def refresh_status(self, user_id: int, *, now: datetime) -> User:
        """Ничто не переводит статус в EXPIRED проактивно по истечении
        времени — кэш остаётся TRIAL/ACTIVE, пока кто-то явно не пересчитает
        его. Вызывать перед любой проверкой доступа."""
        user = await self._users.get_by_id(user_id)
        if (
            user.subscription_status in _ACTIVE_STATUSES
            and user.subscription_expires_at is not None
            and user.subscription_expires_at <= now
        ):
            return await self._users.update_subscription_cache(
                user_id, status=SubscriptionStatus.EXPIRED, expires_at=user.subscription_expires_at,
            )
        return user

    async def has_access(self, user_id: int, *, now: datetime) -> bool:
        user = await self.refresh_status(user_id, now=now)
        return user.subscription_status in _ACTIVE_STATUSES

    async def _effective_start(self, user_id: int, now: datetime) -> datetime:
        user = await self._users.get_by_id(user_id)
        if user.subscription_expires_at is not None and user.subscription_expires_at > now:
            return user.subscription_expires_at
        return now
