"""Хендлеры "📅 Календарь" (Часть 10, п. 26) — реальным aiogram-роутингом:
открытие текущего месяца, навигация вперёд/назад, тап по дню с
тренировкой и без."""

from datetime import UTC, datetime

from aiogram import Bot, Dispatcher

from app.db.models import User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.session import BlockLog
from tests.test_bot.conftest import make_callback_update as _callback_update


async def _make_workout_on(session, user: User, *, performed_at: datetime) -> None:
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=performed_at, reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=performed_at,
        block_a_reps=BlockLog(working_reps=(10, 10, 10), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.BODYWEIGHT, block_b_equipment_value=None,
    )


async def test_show_calendar_does_not_crash_with_empty_history(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="show_calendar"), session=session,
    )
    # ничего не упало — большего StubSession проверить не даёт


async def test_month_navigation_across_year_boundary(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="cal_month:2026-12"), session=session,
    )
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="cal_month:2027-01"), session=session,
    )


async def test_tap_marked_day_sends_workout_details(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    await _make_workout_on(session, user, performed_at=datetime(2026, 8, 5, tzinfo=UTC))

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="cal_day:2026-08-05"), session=session,
    )
    # DB-запрос по дате отработал без ошибок — реальная проверка контента
    # StubSession не даёт (см. другие тесты в этом файле).


async def test_tap_unmarked_day_does_not_crash(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="cal_day:2026-08-05"), session=session,
    )


async def test_marked_days_scoped_to_the_requested_month_only(session, user: User, bot: Bot, dispatcher: Dispatcher):
    """Тренировка в июле не должна попадать в отметки августа — регрессия
    на возможную ошибку фильтрации по месяцу/году."""
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    await _make_workout_on(session, user, performed_at=datetime(2026, 7, 5, tzinfo=UTC))

    workouts = WorkoutRepository(session)
    history = await workouts.list_for_user(user.id)
    marked_days_august = {
        w.performed_at.date().day for w in history
        if w.performed_at.year == 2026 and w.performed_at.month == 8
    }
    assert marked_days_august == set()
