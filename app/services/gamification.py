from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Achievement, CoinReason
from app.db.repositories.achievements import AchievementRepository
from app.db.repositories.coins import CoinRepository
from app.db.repositories.users import UserRepository
from app.domain.achievements import AchievementCode


class GamificationService:
    """Начисление монет и разблокировка ачивок поверх domain/achievements.py.

    Конкретные суммы монет за тренировки/ачивки спекой не заданы (см. Этап 1:
    "coins_reward — в Этап 6") — здесь только механизм: суммы передаёт
    вызывающий код. Какие domain.achievements.check_* функции запускать и
    когда (например, сразу после сохранения тренировки) — решает Этап 3
    (там появляются реальные триггеры типа "тренировка завершена"), это
    сознательно не реализовано здесь.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._achievements = AchievementRepository(session)
        self._coins = CoinRepository(session)
        self._users = UserRepository(session)

    async def unlock_achievement(
        self,
        *,
        user_id: int,
        code: AchievementCode,
        coins_reward: int = 0,
        context: dict | None = None,
    ) -> Achievement | None:
        """Идемпотентно разблокирует ачивку и начисляет за неё монеты.
        Возвращает None, если ачивка уже была разблокирована — в этом
        случае монеты повторно не начисляются."""
        achievement = await self._achievements.unlock(user_id=user_id, code=code.value, context=context)
        if achievement is None:
            return None
        if coins_reward:
            await self._award_coins(
                user_id, coins_reward, CoinReason.ACHIEVEMENT_UNLOCKED, related_achievement_id=achievement.id,
            )
        return achievement

    async def award_workout_coins(self, user_id: int, coins: int) -> None:
        if coins:
            await self._award_coins(user_id, coins, CoinReason.WORKOUT_COMPLETED)

    async def spend_coins(
        self, user_id: int, amount: int, *, reason: CoinReason = CoinReason.SUBSCRIPTION_EXTENSION,
    ) -> None:
        """amount — положительное число монет к списанию (в леджер уйдёт со
        знаком минус). Списание сверх баланса запрещено — coins_balance не
        должен уходить в минус."""
        if amount <= 0:
            raise ValueError("amount must be positive")
        user = await self._users.get_by_id(user_id)
        if user.coins_balance < amount:
            raise ValueError(f"insufficient balance: have {user.coins_balance}, need {amount}")
        await self._award_coins(user_id, -amount, reason)

    async def _award_coins(
        self, user_id: int, delta: int, reason: CoinReason, *, related_achievement_id: int | None = None,
    ) -> None:
        await self._coins.create_transaction(
            user_id=user_id, amount=delta, reason=reason, related_achievement_id=related_achievement_id,
        )
        await self._users.adjust_coins_balance(user_id, delta)
