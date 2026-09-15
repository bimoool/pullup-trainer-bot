"""Сидирование фиксированных пользователей для Playwright E2E-набора Mini
App (issue #126, webapp-frontend/e2e/) — по одному вызову на сценарий
перед стартом Playwright, тем же кодом (repositories/services), что уже
используют tests/test_web/*.py (см. _make_returning_user в
tests/test_web/test_workout.py — сценарий "ready" здесь дословно
повторяет тот же рецепт), не отдельный сервисный слой заново: E2E не
должен рассинхронизироваться с реальной формой данных в БД.

Первая итерация — только 3 сценария, согласованные в issue (остальные
пять — отдельными issue после того, как инфраструктура обкатана):
  - not_onboarded — ничего не сидирует, статус берётся из отсутствия строки
    users (см. app/web/routes.py::get_hello/get_workout_plan).
  - first_workout — анкета пройдена, ни одной тренировки ещё не было.
  - ready — одна прошлая тренировка 5 дней назад, обычный день тренировки.

Использование (тот же DATABASE_URL/BOT_TOKEN, что у app/web/main.py):
    python scripts/e2e_seed.py ready 900003
"""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import async_session_factory
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.session import BlockLog
from app.services.subscription import SubscriptionService

BAND_VALUE = Decimal("15.0")


async def seed_not_onboarded(session: AsyncSession, telegram_id: int) -> None:
    """Нарочно пустая функция — "не онбордился" означает отсутствие строки
    users вообще (см. app/web/routes.py::get_hello), не отдельное
    состояние, которое нужно создавать."""


async def seed_first_workout(session: AsyncSession, telegram_id: int) -> None:
    user = await UserRepository(session).create(telegram_id=telegram_id, username="e2e")
    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))


async def seed_ready(session: AsyncSession, telegram_id: int) -> None:
    """Один пользователь с ровно одной прошлой тренировкой 5 дней назад —
    снаряд (BAND, значение ниже порога смены обоих блоков) уже известен для
    обоих блоков, needs_new_equipment=False на следующей (см.
    app/db/repositories/workouts.py::_resolve_next_state) — GET
    /api/workout/plan отдаёт status="ready" с work_sets_a=3/work_sets_b=4,
    подтверждено tests/test_web/test_workout.py::
    test_plan_ready_shows_target_and_equipment."""
    user = await UserRepository(session).create(telegram_id=telegram_id, username="e2e")
    now = datetime.now(UTC)
    await SubscriptionService(session).start_trial(user.id, now=now)

    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=now, reps=10)
    workout_set = await WorkoutSetRepository(session).create(
        user_id=user.id, started_from_baseline_id=baseline.id,
    )
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=now - timedelta(days=5),
        block_a_reps=BlockLog(working_reps=(10, 10, 10), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )


SCENARIOS = {
    "not_onboarded": seed_not_onboarded,
    "first_workout": seed_first_workout,
    "ready": seed_ready,
}


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("scenario", choices=sorted(SCENARIOS))
    parser.add_argument("telegram_id", type=int)
    args = parser.parse_args()

    async with async_session_factory() as session:
        existing = await UserRepository(session).get_by_telegram_id(args.telegram_id)
        if existing is not None:
            # CI гоняет это против свежей БД (сервис postgres поднимается
            # заново на каждый workflow run) — здесь только защита от
            # повторного локального прогона на непустой БД, где повторная
            # запись того же telegram_id упала бы на UNIQUE-констрейнте.
            print(
                f"telegram_id={args.telegram_id} уже сидирован, пропускаю "
                "(нужна чистая БД для пересидирования)"
            )
            return
        await SCENARIOS[args.scenario](session, args.telegram_id)
        await session.commit()
    print(f"готово: {args.scenario} -> telegram_id={args.telegram_id}")


if __name__ == "__main__":
    asyncio.run(main())
