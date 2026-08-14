from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Subscription, SubscriptionSource, SubscriptionStatus


class SubscriptionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        user_id: int,
        status: SubscriptionStatus,
        source: SubscriptionSource,
        started_at: datetime,
        ends_at: datetime,
        payment_reference: str | None = None,
    ) -> Subscription:
        subscription = Subscription(
            user_id=user_id,
            status=status,
            source=source,
            started_at=started_at,
            ends_at=ends_at,
            payment_reference=payment_reference,
        )
        self._session.add(subscription)
        await self._session.flush()
        return subscription

    async def get_latest_for_user(self, user_id: int) -> Subscription | None:
        # created_at (server_default now()) может совпасть у двух строк,
        # вставленных в одном тесте/транзакции — id как надёжный tie-break.
        result = await self._session.execute(
            select(Subscription)
            .where(Subscription.user_id == user_id)
            .order_by(Subscription.created_at.desc(), Subscription.id.desc())
            .limit(1),
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: int) -> list[Subscription]:
        result = await self._session.execute(
            select(Subscription).where(Subscription.user_id == user_id).order_by(Subscription.started_at),
        )
        return list(result.scalars().all())

    async def list_since(self, after_id: int, *, limit: int) -> list[Subscription]:
        """Подписки ЛЮБОГО пользователя с id > after_id — вход для
        app.workers.sheets_sync.py (лист "subscriptions")."""
        result = await self._session.execute(
            select(Subscription).where(Subscription.id > after_id).order_by(Subscription.id).limit(limit),
        )
        return list(result.scalars().all())
