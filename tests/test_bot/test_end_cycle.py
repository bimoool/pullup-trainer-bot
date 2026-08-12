"""«Завершить цикл и начать заново» (Профиль) — проверяет реальным
aiogram-роутингом, что подтверждение закрывает активный WorkoutSet статусом
ABANDONED и переводит диалог в тот же RetestStates.waiting_for_baseline_reps,
что уже используется для просроченного замера (переиспользование флоу,
см. app/bot/handlers/workout.py::handle_end_cycle_confirm)."""

from datetime import UTC, datetime

from aiogram import Bot, Dispatcher

from app.bot.states import RetestStates
from app.db.models import User, WorkoutSetStatus
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from tests.test_bot.conftest import make_callback_update as _callback_update


async def _make_active_set(session, user: User) -> int:
    baseline = await BaselineRepository(session).create(
        user_id=user.id, performed_at=datetime(2026, 1, 1, tzinfo=UTC), reps=10,
    )
    workout_set = await WorkoutSetRepository(session).create(
        user_id=user.id, started_from_baseline_id=baseline.id,
    )
    return workout_set.id


async def test_end_cycle_confirm_abandons_set_and_starts_retest_flow(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    active_set_id = await _make_active_set(session, user)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="end_cycle_confirm"), session=session,
    )

    workout_sets = WorkoutSetRepository(session)
    reloaded = await workout_sets.get_by_id(active_set_id)
    assert reloaded.status == WorkoutSetStatus.ABANDONED
    assert await workout_sets.get_active_for_user(user.id) is None

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == RetestStates.waiting_for_baseline_reps.state


async def test_end_cycle_confirm_with_no_active_set_does_not_crash(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    # никакого активного сета не создаём

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(None)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="end_cycle_confirm"), session=session,
    )

    # состояние не тронуто — сценарий вежливо остановился на проверке,
    # а не упал и не увёл в ретест без реального цикла
    assert await fsm.get_state() is None
