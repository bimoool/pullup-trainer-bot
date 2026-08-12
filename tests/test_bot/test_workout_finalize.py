"""Диагностика бага "кнопка «Пропустить» у комментария не срабатывает"
(Часть 10, п. 21) — состояние теперь очищается ДО записи в БД, а не после:
повторный тап по той же (уже неактуальной) кнопке не должен создавать
вторую тренировку, а должен тихо ничего не делать (дальше состояние не
совпадает с фильтром WorkoutStates.waiting_for_comment)."""

from datetime import UTC, datetime

from aiogram import Bot, Dispatcher

from app.bot.states import WorkoutStates
from app.db.models import User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from tests.test_bot.conftest import make_callback_update as _callback_update


async def _put_user_at_comment_step(session, user: User, bot: Bot, dispatcher: Dispatcher) -> None:
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(WorkoutStates.waiting_for_comment)
    await fsm.update_data(
        workout_set_id=workout_set.id,
        target_a=10, target_b=4, target_a_override=None, target_b_override=None,
        block_a_working_reps=[10, 10, 10], block_a_max_reps=11,
        block_b_working_reps=[3, 3, 3, 3], block_b_max_reps=3,
        equipment_results={
            "a": {"type": "bodyweight", "value": None, "item_id": None},
            "b": {"type": "bodyweight", "value": None, "item_id": None},
        },
    )


async def test_skip_comment_records_exactly_one_workout(session, user: User, bot: Bot, dispatcher: Dispatcher):
    """Часть 10, повторное всплытие бага: сквозная проверка до записи в БД,
    не только "хендлер что-то ответил" — callback.message.from_user в
    реальном Telegram это бот, не нажавший кнопку (см.
    tests/test_bot/conftest.py::make_callback_update), и раньше
    _finalize_workout брал telegram_id именно оттуда, теряя тренировку
    молча (AttributeError после state.clear(), проглоченный aiogram)."""
    await _put_user_at_comment_step(session, user, bot, dispatcher)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="skip_comment"), session=session,
    )

    history = await WorkoutRepository(session).list_for_user(user.id)
    assert len(history) == 1
    assert history[0].comment is None


async def test_repeat_tap_on_stale_skip_button_does_not_duplicate_workout(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await _put_user_at_comment_step(session, user, bot, dispatcher)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="skip_comment"), session=session,
    )
    # Тот же тап повторно — состояние уже очищено первым, второй просто не
    # находит подходящий хендлер (никакой ошибки, но и второй записи тоже).
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="skip_comment"), session=session,
    )

    history = await WorkoutRepository(session).list_for_user(user.id)
    assert len(history) == 1

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() is None
