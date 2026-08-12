"""Часть 10, п. 33 (Блок E) — «после нажатия inline-кнопки в многошаговом
сценарии клавиатура предыдущего сообщения не убирается». Проверяет реальным
aiogram-роутингом, что переход шагов действительно шлёт
editMessageReplyMarkup для сообщения с предыдущей клавиатурой — не только
что следующий шаг появился, это уже покрыто другими тестами."""

from datetime import UTC, datetime

from aiogram import Bot, Dispatcher
from aiogram.methods import EditMessageReplyMarkup

from app.bot.states import BackdateStates, EquipmentStates, WorkoutStates
from app.db.models import User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from tests.test_bot.conftest import make_callback_update

_STALE_MESSAGE_ID = 100


def _callback_update(*, telegram_id: int, data: str):
    return make_callback_update(telegram_id=telegram_id, data=data, message_id=_STALE_MESSAGE_ID)


def _cleared_the_stale_message(bot: Bot) -> bool:
    return any(
        isinstance(m, EditMessageReplyMarkup) and m.message_id == _STALE_MESSAGE_ID and m.reply_markup is None
        for m in bot.session.sent_methods
    )


async def test_equipment_type_choice_clears_previous_keyboard(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(EquipmentStates.waiting_for_type)
    await fsm.update_data(
        equipment_flow="live", equipment_queue=["a"], equipment_results={}, baseline_reps=None,
        workout_set_id=1, target_a=10, target_b=4, target_a_override=None, target_b_override=None,
    )

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="equip:bodyweight"), session=session,
    )

    assert _cleared_the_stale_message(bot)


async def test_backdate_back_to_date_clears_previous_keyboard(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(BackdateStates.waiting_for_block_a)
    await fsm.update_data(backdate_performed_at=datetime.now(UTC).isoformat())

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="backdate_back:date"), session=session,
    )

    assert _cleared_the_stale_message(bot)


async def test_workout_back_to_block_b_clears_previous_keyboard(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(WorkoutStates.waiting_for_comment)
    await fsm.update_data(
        workout_set_id=workout_set.id,
        target_a=10, target_b=4, target_a_override=None, target_b_override=None,
        block_a_working_reps=[10, 10, 10], block_a_max_reps=11,
        equipment_results={
            "a": {"type": "bodyweight", "value": None, "item_id": None},
            "b": {"type": "bodyweight", "value": None, "item_id": None},
        },
    )

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="wk_back:block_b"), session=session,
    )

    assert _cleared_the_stale_message(bot)
    assert await fsm.get_state() == WorkoutStates.waiting_for_block_b.state


async def test_end_cycle_confirm_clears_confirmation_keyboard(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="end_cycle_confirm"), session=session,
    )

    assert _cleared_the_stale_message(bot)
