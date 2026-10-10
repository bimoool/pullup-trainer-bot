"""K1 — серверная проверка отдыха между стартами MAIN (issue #304, PROGRAM_PLAN_V2 §4, LIVE §7).

Один источник для ВСЕХ путей старта основной тренировки «Подтягиваний»: v2 live (занятие плана),
legacy `/api/workout/plan`, бот («Начать тренировку», статус «сегодня отдых»), напоминание и
статус Dashboard. Админы обходят проверку так же, как раньше (решает вызывающий: `settings.is_admin`).

Правило (OD-2, решение владельца 2026-10-08): «2 дня отдыха» = ДВА ПОЛНЫХ дня отдыха →
`available_from = local_date(последний старт MAIN) + min_days_between_starts`, значение 3 (Пн → Чт).
Даты — в часовом поясе пользователя. Значение читается из конфига: `programs.constraints` программы
(активное STEP-включение пользователя, иначе каталожные «Подтягивания»), фолбэк —
`settings.main_min_days_between_starts`. Не путать со старым `MIN_REST_DAYS = 2` (Пн → Ср).

«Последний старт MAIN» — максимум из:
* legacy `workouts` (завершённые; вся история старой схемы — это основная тренировка);
* v2 `training_sessions` (завершённые): засчитавшие занятие main-слота (plan_item_id) ИЛИ с блоком
  роли STEP (block_a/block_b) и хотя бы одним записанным подходом в нём. Пустые (без единого
  подхода) брошенные сессии отдых не сдвигают. Ручная запись/копия (source_v2 = manual_*) — не старт
  MAIN даже со скопированными блоками ролей (#307; TrainingSessionRepository.main_session_predicate).
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import User
from app.db.repositories.programs import ProgramRepository
from app.db.repositories.training_sessions import TrainingSessionRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.plan_occurrence import (
    MAIN_SPACING_GROUP,
    available_from,
    is_too_early,
    spacing_days_by_group,
)
from app.services.training_analytics import resolve_timezone


class TooEarlyError(Exception):
    """Старт MAIN раньше available_from (K1) — роут → 409 {code: too_early, available_from}."""

    def __init__(self, available: date) -> None:
        super().__init__(f"too_early: available_from={available.isoformat()}")
        self.available_from = available


@dataclass(frozen=True)
class SpacingStatus:
    spacing_group: str
    min_days_between_starts: int
    last_start_at: datetime | None
    last_start_date: date | None
    available_from: date | None
    today: date

    @property
    def too_early(self) -> bool:
        return is_too_early(self.today, self.available_from)

    def available_from_at(self, user_timezone: str | None) -> datetime | None:
        """Начало дня available_from в поясе пользователя (UTC) — для «через N ч» в боте."""
        if self.available_from is None:
            return None
        return datetime.combine(self.available_from, time(0), tzinfo=resolve_timezone(user_timezone)).astimezone(UTC)


class MainSpacingService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def min_days_between_starts(self, user_id: int, group: str = MAIN_SPACING_GROUP) -> int:
        constraints = await self._program_constraints(user_id)
        return spacing_days_by_group(constraints, default_main=settings.main_min_days_between_starts).get(
            group, settings.main_min_days_between_starts,
        )

    async def spacing_by_group(self, user_id: int) -> dict[str, int]:
        constraints = await self._program_constraints(user_id)
        return spacing_days_by_group(constraints, default_main=settings.main_min_days_between_starts)

    async def _program_constraints(self, user_id: int) -> list | None:
        """constraints программы активного включения пользователя; иначе каталожные «Подтягивания»
        (тот же источник для legacy-путей без включения); иначе None → фолбэк конфига."""
        return await ProgramRepository(self._session).spacing_constraints_for_user(user_id)

    async def last_main_start_at(self, user_id: int) -> datetime | None:
        legacy = await WorkoutRepository(self._session).latest_completed_performed_at(user_id)
        native = await TrainingSessionRepository(self._session).latest_main_session_at(user_id)
        candidates = [value for value in (legacy, native) if value is not None]
        return max(candidates) if candidates else None

    async def count_native_main_sessions(self, user_id: int) -> int:
        return await TrainingSessionRepository(self._session).count_main_sessions(user_id)

    async def status(self, user: User, *, now: datetime, group: str = MAIN_SPACING_GROUP) -> SpacingStatus:
        tz = resolve_timezone(user.timezone)
        min_days = await self.min_days_between_starts(user.id, group)
        last = await self.last_main_start_at(user.id)
        last_date = last.astimezone(tz).date() if last is not None else None
        return SpacingStatus(
            spacing_group=group, min_days_between_starts=min_days, last_start_at=last,
            last_start_date=last_date, available_from=available_from(last_date, min_days),
            today=now.astimezone(tz).date(),
        )

    async def require_main_start_allowed(self, user: User, *, now: datetime, bypass: bool) -> None:
        """K1: TooEarlyError, если старт MAIN сейчас раньше available_from. bypass — админ."""
        if bypass:
            return
        status = await self.status(user, now=now)
        if status.too_early:
            raise TooEarlyError(status.available_from)
