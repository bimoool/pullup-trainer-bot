"""ЕДИНСТВЕННЫЙ путь решения «можно ли тренироваться по программе» на сервере (правило владельца 2026-10-07,
app/domain/program_access.py). Все гейты старта/записи тренировки курса идут сюда, а не к
SubscriptionService.is_entitled напрямую: бесплатная программа («Подтягивания») доступна без Premium,
всё остальное — только при действующем entitlement (D6/#300)."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.repositories.programs import ProgramRepository
from app.domain.program_access import (
    LEGACY_PULLUP_CASCADE_ACCESS_LEVEL,
    program_training_allowed,
    programs_training_allowed,
)
from app.services.subscription import SubscriptionService


class SubscriptionRequiredError(Exception):
    """Старт/запись тренировки платной (Premium) программы без действующей подписки (#300, PROJECT_SPEC, D6):
    роут -> 402 {"code": "subscription_required"}."""

    def __init__(self) -> None:
        super().__init__("Subscription required to start a course workout")


class ProgramAccessService:
    def __init__(self, session: AsyncSession) -> None:
        self._programs = ProgramRepository(session)

    async def inclusions_training_allowed(self, user: User, inclusion_ids: list[int], *, now: datetime) -> bool:
        """Тренировка по строкам этих инклюзий разрешена, если разрешена по каждой из их программ. Инклюзия, чья
        программа не найдена, считается платной (fail closed)."""
        levels_by_inclusion = await self._programs.access_levels_for_inclusions(sorted(set(inclusion_ids)))
        levels = [levels_by_inclusion.get(inclusion_id) for inclusion_id in set(inclusion_ids)]
        return programs_training_allowed(levels, entitled=SubscriptionService.is_entitled(user, now=now))

    async def require_inclusions_training_access(self, user: User, inclusion_ids: list[int], *, now: datetime) -> None:
        if not await self.inclusions_training_allowed(user, inclusion_ids, now=now):
            raise SubscriptionRequiredError

    @staticmethod
    def legacy_pullup_cascade_allowed(user: User, *, now: datetime) -> bool:
        """Legacy-каскад подтягиваний (бот, старые /api/workout/*) — та же программа «Подтягивания»
        (LEGACY_PULLUP_CASCADE_ACCESS_LEVEL), то же решение."""
        return program_training_allowed(
            LEGACY_PULLUP_CASCADE_ACCESS_LEVEL, entitled=SubscriptionService.is_entitled(user, now=now),
        )
