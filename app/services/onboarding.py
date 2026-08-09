from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Baseline, User, WorkoutSet
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.domain.achievements import AchievementCode, check_first_baseline
from app.services.gamification import GamificationService
from app.services.subscription import SubscriptionService

# Суммы монет за ачивки не определены (Этап 1: "coins_reward — в Этап 6") —
# фиксируем разблокировку с наградой 0, сумму подставим позже в одном месте.
ACHIEVEMENT_COINS = 0


class OnboardingService:
    """Оркестрирует онбординг за две операции (замер и анкета — разнесены,
    потому что между ними в реальном сценарии всегда есть хендлеры анкеты):
    1) замер + первый сет (веток больше нет — сет создаётся всегда);
    2) анкета + отметка онбординга завершённым + старт триала.

    Замер теперь — одно число (максимум на собственном весе), снаряды для
    обоих блоков подбирает не этот сервис, а domain.suggest_starting_equipment
    прямо в хендлере первой тренировки — здесь их незачем хранить заранее."""

    def __init__(self, session: AsyncSession) -> None:
        self._users = UserRepository(session)
        self._baselines = BaselineRepository(session)
        self._workout_sets = WorkoutSetRepository(session)
        self._subscriptions = SubscriptionService(session)
        self._gamification = GamificationService(session)

    async def record_baseline_and_start(
        self, *, user_id: int, performed_at: datetime, reps: int,
    ) -> tuple[Baseline, WorkoutSet, User]:
        is_first_baseline = await self._baselines.list_for_user(user_id) == []

        baseline = await self._baselines.create(user_id=user_id, performed_at=performed_at, reps=reps)

        if check_first_baseline(is_first_baseline):
            await self._gamification.unlock_achievement(
                user_id=user_id, code=AchievementCode.FIRST_BASELINE, coins_reward=ACHIEVEMENT_COINS,
            )

        workout_set = await self._workout_sets.create(user_id=user_id, started_from_baseline_id=baseline.id)
        user = await self._users.get_by_id(user_id)
        return baseline, workout_set, user

    async def complete_questionnaire_and_start_trial(
        self,
        *,
        user_id: int,
        weight_kg: Decimal,
        height_cm: int,
        age: int,
        timezone: str,
        now: datetime,
    ) -> User:
        await self._users.update_profile(
            user_id, weight_kg=weight_kg, height_cm=height_cm, age=age, timezone=timezone,
        )
        await self._users.complete_onboarding(user_id, now)
        return await self._subscriptions.start_trial(user_id, now=now)
