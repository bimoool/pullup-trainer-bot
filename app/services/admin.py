from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SubscriptionSource, User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.subscriptions import SubscriptionRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workouts import NextBlockState, WorkoutRepository

# Порядок важен — "застрял на шаге X" вычисляется как ПОСЛЕДНИЙ достигнутый
# шаг в этом списке (см. AdminService._reached_step).
FUNNEL_STEPS: list[str] = ["Старт", "Замер", "Анкета", "Первая тренировка", "Триал", "Подписка"]


@dataclass(frozen=True)
class FunnelResult:
    """steps[название шага] — пользователи, у которых это САМЫЙ ДАЛЬНИЙ
    достигнутый шаг (то есть буквально "застряли" именно здесь), а не все,
    кто когда-либо через него проходил."""

    steps: dict[str, list[User]]


@dataclass(frozen=True)
class UserCard:
    user: User
    baseline_count: int
    workout_count: int
    target_a: NextBlockState
    target_b: NextBlockState


class AdminService:
    def __init__(self, session: AsyncSession) -> None:
        self._users = UserRepository(session)
        self._baselines = BaselineRepository(session)
        self._workouts = WorkoutRepository(session)
        self._subscriptions = SubscriptionRepository(session)

    async def compute_funnel(self) -> FunnelResult:
        all_users = await self._users.list_all()
        steps: dict[str, list[User]] = {name: [] for name in FUNNEL_STEPS}
        for user in all_users:
            steps[await self._reached_step(user)].append(user)
        return FunnelResult(steps=steps)

    async def _reached_step(self, user: User) -> str:
        if not await self._baselines.list_for_user(user.id):
            return "Старт"
        if user.onboarding_completed_at is None:
            return "Замер"
        if not await self._workouts.list_for_user(user.id):
            return "Анкета"
        subscriptions = await self._subscriptions.list_for_user(user.id)
        if not subscriptions:
            return "Первая тренировка"
        if not any(s.source != SubscriptionSource.TRIAL for s in subscriptions):
            return "Триал"
        return "Подписка"

    async def build_user_card(self, user: User) -> UserCard:
        baselines = await self._baselines.list_for_user(user.id)
        workouts = await self._workouts.list_for_user(user.id)
        target_a, target_b = await self._workouts.resolve_next_targets(user.id)
        return UserCard(
            user=user, baseline_count=len(baselines), workout_count=len(workouts),
            target_a=target_a, target_b=target_b,
        )
