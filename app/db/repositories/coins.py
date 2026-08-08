from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Coin, CoinReason


class CoinRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_transaction(
        self,
        *,
        user_id: int,
        amount: int,
        reason: CoinReason,
        related_achievement_id: int | None = None,
    ) -> Coin:
        coin = Coin(
            user_id=user_id, amount=amount, reason=reason, related_achievement_id=related_achievement_id,
        )
        self._session.add(coin)
        await self._session.flush()
        return coin

    async def list_for_user(self, user_id: int) -> list[Coin]:
        result = await self._session.execute(
            select(Coin).where(Coin.user_id == user_id).order_by(Coin.created_at),
        )
        return list(result.scalars().all())

    async def get_balance(self, user_id: int) -> int:
        """Настоящий баланс из леджера — для сверки с денормализованным
        users.coins_balance (используется в тестах/админке, не в hot-path)."""
        result = await self._session.execute(
            select(func.coalesce(func.sum(Coin.amount), 0)).where(Coin.user_id == user_id),
        )
        return result.scalar_one()
