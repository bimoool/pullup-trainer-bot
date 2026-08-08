from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Baseline, Branch, Equipment, User, WorkoutSet
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.domain.achievements import AchievementCode, check_first_baseline
from app.domain.rules import determine_branch
from app.services.gamification import GamificationService
from app.services.subscription import SubscriptionService

# Суммы монет за ачивки не определены (Этап 1: "coins_reward — в Этап 6") —
# фиксируем разблокировку с наградой 0, сумму подставим позже в одном месте.
ACHIEVEMENT_COINS = 0


class OnboardingService:
    """Оркестрирует онбординг за две операции (замер и анкета — разнесены,
    потому что между ними в реальном сценарии всегда есть хендлеры анкеты):
    1) баллов + определение ветки + (только для BAND) первый сет;
    2) анкета + отметка онбординга завершённым + старт триала.
    Несколько таблиц должны стать согласованными за одну транзакцию — та же
    причина, по которой WorkoutRepository толще остальных репозиториев."""

    def __init__(self, session: AsyncSession) -> None:
        self._users = UserRepository(session)
        self._baselines = BaselineRepository(session)
        self._workout_sets = WorkoutSetRepository(session)
        self._subscriptions = SubscriptionService(session)
        self._gamification = GamificationService(session)

    async def record_baseline_and_start(
        self,
        *,
        user_id: int,
        performed_at: datetime,
        reps: int,
        band_thickness_mm: Decimal,
    ) -> tuple[Baseline, WorkoutSet | None, User]:
        """workout_set создаётся только для ветки BAND — структура workouts/
        blocks сейчас рассчитана только на неё (см. Этап 2). Что именно
        считать сетом в ASSISTED — решится в Этапе 4, поэтому здесь для неё
        просто не создаём набор, чтобы не зашивать несуществующее решение."""
        is_first_baseline = await self._baselines.list_for_user(user_id) == []
        branch = determine_branch(reps)

        baseline = await self._baselines.create(
            user_id=user_id,
            performed_at=performed_at,
            branch_result=branch,
            equipment_type=Equipment.BAND,
            reps=reps,
            band_thickness_mm=band_thickness_mm,
        )
        user = await self._users.set_branch(user_id, branch)

        if check_first_baseline(is_first_baseline):
            await self._gamification.unlock_achievement(
                user_id=user_id, code=AchievementCode.FIRST_BASELINE, coins_reward=ACHIEVEMENT_COINS,
            )

        workout_set = None
        if branch == Branch.BAND:
            workout_set = await self._workout_sets.create(user_id=user_id, started_from_baseline_id=baseline.id)

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
