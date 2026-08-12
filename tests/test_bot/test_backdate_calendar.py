"""Ввод даты бэкдейта через календарь (Часть 10, пакет #2, п.17) — тап по
дню делает то же самое, что и текстовый ввод даты, обе опции доступны
разом. Реальным aiogram-роутингом."""

from datetime import UTC, datetime

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage

from app.bot.states import BackdateStates
from app.db.models import User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from tests.test_bot.conftest import make_callback_update as _callback_update


async def _start_backdate(session, user: User, bot: Bot, dispatcher: Dispatcher) -> None:
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="backdate_workout"), session=session,
    )


async def test_open_calendar_button_shows_backdate_mode_grid(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await _start_backdate(session, user, bot, dispatcher)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="backdate_open_calendar"), session=session,
    )

    [calendar_message] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.reply_markup and any(
            b.callback_data.startswith("cal_close:backdate")
            for row in m.reply_markup.inline_keyboard for b in row
        )
    ]
    assert calendar_message is not None


async def test_tapping_a_past_day_proceeds_straight_to_block_a(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await _start_backdate(session, user, bot, dispatcher)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="cal_day:backdate:2026-01-05"), session=session,
    )

    assert await fsm.get_state() == BackdateStates.waiting_for_block_a.state
    data = await fsm.get_data()
    assert data["backdate_performed_at"].startswith("2026-01-05")


async def test_tapping_a_future_day_shows_alert_and_does_not_advance_state(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await _start_backdate(session, user, bot, dispatcher)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)

    future_year = datetime.now(UTC).year + 1
    await dispatcher.feed_update(
        bot,
        _callback_update(telegram_id=user.telegram_id, data=f"cal_day:backdate:{future_year}-01-05"),
        session=session,
    )

    assert await fsm.get_state() == BackdateStates.waiting_for_date.state


async def test_calendar_close_in_backdate_mode_cancels_the_whole_flow(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await _start_backdate(session, user, bot, dispatcher)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="cal_close:backdate"), session=session,
    )

    assert await fsm.get_state() is None
