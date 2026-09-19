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
  - first_workout — анкета полностью пройдена, ни одной тренировки ещё не
    было.
  - ready — одна прошлая тренировка 5 дней назад, обычный день тренировки.

Обновление (issue #126, разбор повторного падения CI после мержа issue
#124 PR 2): оба сценария с сидированием раньше вызывали
SubscriptionService.start_trial напрямую и не отмечали
user.onboarding_completed_at вообще — до PR 2 issue #124 это было
достаточно (HelloResponse.is_onboarded значило просто "строка users
существует"). Теперь GET /api/hello (onboarding_step) проверяет
onboarding_completed_at ПЕРВЫМ, раньше истории тренировок — с
onboarding_completed_at=None App.tsx рендерит OnboardingScreen вместо
WorkoutScreen вообще, независимо от того, есть ли уже тренировки в
истории. Оба сценария теперь проходят через OnboardingService целиком
(record_baseline_and_start + complete_questionnaire_and_start_trial — тот
же путь, что и настоящий онбординг, start_trial внутри неё же, отдельный
вызов SubscriptionService.start_trial убран, чтобы не стартовать триал
дважды).

Использование (тот же DATABASE_URL/BOT_TOKEN, что у app/web/main.py):
    python scripts/e2e_seed.py ready 900003
"""

import argparse
import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import async_session_factory
from app.db.models import Gender
from app.db.repositories.users import UserRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.session import BlockLog
from app.services.onboarding import OnboardingService

BAND_VALUE = Decimal("15.0")

# Реальная демография значения не имеет для этих сценариев — заполняется
# только потому, что OnboardingService.complete_questionnaire_and_start_trial
# (issue #124) требует эти поля, чтобы отметить онбординг завершённым; без
# этого GET /api/hello никогда не вернёт onboarding_step="done", и App.tsx
# не покажет WorkoutScreen вообще.
_QUESTIONNAIRE_DEFAULTS = {
    "weight_kg": Decimal(75),
    "height_cm": 180,
    "gender": Gender.MALE,
    "birth_date": date(1995, 1, 1),
    "timezone": "Europe/Moscow",
}


async def seed_not_onboarded(session: AsyncSession, telegram_id: int) -> None:
    """Нарочно пустая функция — "не онбордился" означает отсутствие строки
    users вообще (см. app/web/routes.py::get_hello), не отдельное
    состояние, которое нужно создавать."""


async def seed_first_workout(session: AsyncSession, telegram_id: int) -> None:
    """Замер на 6 повторений — suggest_starting_equipment(6) даёт (BAND,
    BODYWEIGHT): блок A на резине, блок Б на собственном весе. Раньше здесь
    было 12 (даёт (BODYWEIGHT, WEIGHT)), специально ЧТОБЫ избежать резины —
    заведение резины в Mini App (issue #124, PR 3, BandItemSelect) тогда
    ещё не было сделано. Оно есть с PR 3 — теперь сценарий сознательно
    выбирает резину для одного из блоков, чтобы E2E реально проверял новый
    экран подтверждения стартового снаряда (issue #175,
    EquipmentPlanScreen.tsx) на случае, где снаряд нужно заранее подготовить
    (заведение резины через "+ Завести новую резину"), а не только на случае
    "снаряд не нужен". Анкета пройдена полностью (см. модульный докстрин
    выше), ни одной тренировки ещё не было — GET /api/workout/plan отдаёт
    status="ready" с is_first_workout=True."""
    user = await UserRepository(session).create(telegram_id=telegram_id, username="e2e")
    now = datetime.now(UTC)
    onboarding = OnboardingService(session)
    await onboarding.record_baseline_and_start(user_id=user.id, performed_at=now, reps=6)
    await onboarding.complete_questionnaire_and_start_trial(
        user_id=user.id, now=now, **_QUESTIONNAIRE_DEFAULTS,
    )


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
    onboarding = OnboardingService(session)
    _baseline, workout_set, _user = await onboarding.record_baseline_and_start(
        user_id=user.id, performed_at=now, reps=10,
    )
    await onboarding.complete_questionnaire_and_start_trial(
        user_id=user.id, now=now, **_QUESTIONNAIRE_DEFAULTS,
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
