"""«➕ Внести свободные подтягивания» (Часть 10, п. 18) — реальным
aiogram-роутингом: одно число, вне плана и вне сета из 12, попадает в
статистику."""

from datetime import UTC, datetime

from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update
from aiogram.types import User as TgUser

from app.bot.states import FreeWorkoutStates
from app.db.models import User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository


def _callback_update(*, telegram_id: int, data: str) -> Update:
    message = Message(
        message_id=100, date=datetime.now(UTC),
        chat=Chat(id=telegram_id, type="private"),
        from_user=TgUser(id=telegram_id, is_bot=False, first_name="Tester"),
        text="stub",
    )
    return Update(
        update_id=1,
        callback_query=CallbackQuery(
            id="1",
            from_user=TgUser(id=telegram_id, is_bot=False, first_name="Tester"),
            chat_instance="1",
            data=data,
            message=message,
        ),
    )


def _message_update(*, telegram_id: int, text: str) -> Update:
    return Update(
        update_id=1,
        message=Message(
            message_id=101, date=datetime.now(UTC),
            chat=Chat(id=telegram_id, type="private"),
            from_user=TgUser(id=telegram_id, is_bot=False, first_name="Tester"),
            text=text,
        ),
    )


async def test_free_workout_start_sets_waiting_state(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="free_workout_start"), session=session,
    )
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == FreeWorkoutStates.waiting_for_reps.state


async def test_free_workout_reps_records_and_creates_set_if_needed(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(FreeWorkoutStates.waiting_for_reps)

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="8"), session=session)

    history = await WorkoutRepository(session).list_for_user(user.id)
    assert len(history) == 1
    assert history[0].is_free_entry is True

    workout_sets = await WorkoutSetRepository(session).list_for_user(user.id)
    assert len(workout_sets) == 1
    assert workout_sets[0].workouts_completed == 0  # не входит в сет из 12

    assert await fsm.get_state() is None


async def test_free_workout_invalid_input_does_not_advance(session, user: User, bot: Bot, dispatcher: Dispatcher):
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(FreeWorkoutStates.waiting_for_reps)

    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="не число"), session=session,
    )

    assert await fsm.get_state() == FreeWorkoutStates.waiting_for_reps.state
    history = await WorkoutRepository(session).list_for_user(user.id)
    assert history == []
