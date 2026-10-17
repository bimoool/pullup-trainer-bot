"""ЕДИНСТВЕННЫЙ путь решения «можно ли тренироваться по программе / пользоваться Premium-функцией» на сервере
(правила владельца 2026-10-07 и 2026-10-17, app/domain/program_access.py). Все гейты старта/записи тренировки и
создания платного контента идут сюда, а не к SubscriptionService.is_entitled напрямую: бесплатная программа
(«Подтягивания») доступна без Premium, всё остальное — только при действующем entitlement (D6/#300)."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.repositories.programs import ProgramRepository
from app.domain.program_access import (
    EXTRA_TRAINING_ACCESS_LEVEL,
    LEGACY_PULLUP_CASCADE_ACCESS_LEVEL,
    premium_feature_allowed,
    program_training_allowed,
    programs_training_allowed,
)
from app.services.subscription import SubscriptionService


class SubscriptionRequiredError(Exception):
    """Старт/запись тренировки платной (Premium) программы или доп. тренировки, создание своего контента без
    действующей подписки (#300, PROJECT_SPEC, D6, решение 2026-10-17): роут -> 402 {"code": "subscription_required"},
    бот -> пейволл."""

    def __init__(self) -> None:
        super().__init__("Subscription required")


class ProgramAccessService:
    def __init__(self, session: AsyncSession) -> None:
        self._programs = ProgramRepository(session)

    async def inclusions_training_allowed(self, user: User, inclusion_ids: list[int], *, now: datetime) -> bool:
        """Тренировка по строкам этих инклюзий разрешена, если разрешена по каждой из их программ. Инклюзия, чья
        программа не найдена, считается платной (fail closed)."""
        return await self.training_parts_allowed(user, inclusion_ids, now=now)

    async def training_parts_allowed(
        self, user: User, inclusion_ids: list[int | None], *, now: datetime,
    ) -> bool:
        """Одна тренировка из частей: id инклюзии (занятие программы) или None (доп. часть — строка плана без
        программы, тренировка вне курса). Разрешено, только если разрешена каждая часть: смешанный старт
        «Подтягивания» + доп. строка без подписки отклоняется целиком."""
        ids = sorted({inclusion_id for inclusion_id in inclusion_ids if inclusion_id is not None})
        levels_by_inclusion = await self._programs.access_levels_for_inclusions(ids)
        levels = [
            levels_by_inclusion.get(inclusion_id) if inclusion_id is not None else EXTRA_TRAINING_ACCESS_LEVEL
            for inclusion_id in inclusion_ids
        ]
        return programs_training_allowed(levels, entitled=SubscriptionService.is_entitled(user, now=now))

    async def require_inclusions_training_access(self, user: User, inclusion_ids: list[int], *, now: datetime) -> None:
        if not await self.inclusions_training_allowed(user, inclusion_ids, now=now):
            raise SubscriptionRequiredError

    async def require_training_parts_access(
        self, user: User, inclusion_ids: list[int | None], *, now: datetime,
    ) -> None:
        if not await self.training_parts_allowed(user, inclusion_ids, now=now):
            raise SubscriptionRequiredError

    async def program_allowed(self, user: User, program_id: int, *, now: datetime) -> bool:
        """Добавить программу в план / тренироваться по ней (решение 2026-10-17: «другие программы» — Premium).
        Неизвестная программа — платная (fail closed; 404 решает вызывающий)."""
        program = await self._programs.get_by_id(program_id)
        level = program.access_level if program is not None else None
        return program_training_allowed(level, entitled=SubscriptionService.is_entitled(user, now=now))

    @staticmethod
    def premium_feature_allowed(user: User, *, now: datetime) -> bool:
        """Premium-функция вне бесплатной программы: факультатив, доп./свободная тренировка, своё упражнение /
        тренировка / план, добавление в план, «Повторить» в Журнале."""
        return premium_feature_allowed(entitled=SubscriptionService.is_entitled(user, now=now))

    @classmethod
    def require_premium_feature(cls, user: User, *, now: datetime) -> None:
        if not cls.premium_feature_allowed(user, now=now):
            raise SubscriptionRequiredError

    @staticmethod
    def legacy_pullup_cascade_allowed(user: User, *, now: datetime) -> bool:
        """Legacy-каскад подтягиваний (бот, старые /api/workout/*) — та же программа «Подтягивания»
        (LEGACY_PULLUP_CASCADE_ACCESS_LEVEL), то же решение."""
        return program_training_allowed(
            LEGACY_PULLUP_CASCADE_ACCESS_LEVEL, entitled=SubscriptionService.is_entitled(user, now=now),
        )
