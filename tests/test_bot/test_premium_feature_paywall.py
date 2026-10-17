"""Решение владельца 2026-10-17: в боте факультатив и свободные подтягивания — по подписке. Кнопки остаются видимыми;
без подписки вход показывает объяснение (бесплатная «Подтягивания» остаётся бесплатной) и клавиатуру оплаты, FSM не
начинается и ничего не записывается. Ввод, начатый при подписке, дописывается и сохраняется после её истечения.
Основная тренировка «Подтягиваний» (legacy-каскад) — без пейволла (tests/test_bot/test_free_pullups_program.py)."""

from datetime import UTC, datetime, timedelta

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage

from app.bot import texts
from app.bot.states import ElectiveStates
from app.db.models import SubscriptionStatus, User
from app.db.repositories.elective_workouts import ElectiveWorkoutRepository
from app.db.repositories.users import UserRepository
from app.domain.electives import ElectiveType
from tests.test_bot.conftest import make_callback_update as _callback_update
from tests.test_bot.test_electives import _make_history, _message_update


async def _set(session, user: User, status: SubscriptionStatus, expires_in: timedelta | None) -> None:
    expires_at = None if expires_in is None else datetime.now(UTC) + expires_in
    await UserRepository(session).update_subscription_cache(user.id, status=status, expires_at=expires_at)


def _paywall_messages(bot: Bot, feature: str) -> list[SendMessage]:
    return [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text.startswith(feature) and "«Подтягивания» остаётся бесплатной" in m.text
    ]


async def test_unsubscribed_elective_entry_shows_paywall_and_starts_nothing(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await _make_history(session, user)
    await _set(session, user, SubscriptionStatus.EXPIRED, timedelta(days=-1))
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.clear()

    await dispatcher.feed_update(bot, _callback_update(telegram_id=user.telegram_id, data="electives_start"), session=session)

    assert await fsm.get_state() is None
    [paywall] = _paywall_messages(bot, texts.PREMIUM_FEATURE_ELECTIVE)
    callbacks = {b.callback_data for row in paywall.reply_markup.inline_keyboard for b in row}
    assert "pay_stars" in callbacks
    assert "быстрее" not in paywall.text.lower()
    assert not any(isinstance(m, SendMessage) and m.text == texts.ELECTIVE_MENU_INTRO for m in bot.session.sent_methods)


async def test_never_subscribed_free_workout_entry_shows_paywall(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await _set(session, user, SubscriptionStatus.NONE, None)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.clear()

    await dispatcher.feed_update(bot, _callback_update(telegram_id=user.telegram_id, data="free_workout_start"), session=session)

    assert await fsm.get_state() is None
    assert _paywall_messages(bot, texts.PREMIUM_FEATURE_FREE_WORKOUT)


async def test_elective_started_before_expiry_is_saved_after_expiry(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await _make_history(session, user)
    await _set(session, user, SubscriptionStatus.TRIAL, timedelta(days=3))
    await dispatcher.feed_update(bot, _callback_update(telegram_id=user.telegram_id, data="electives_start"), session=session)
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data=f"elective:{ElectiveType.MAX_REPS_LADDER.value}"),
        session=session,
    )
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == ElectiveStates.waiting_for_reps.state

    await _set(session, user, SubscriptionStatus.EXPIRED, timedelta(days=-1))  # истекла посреди ввода
    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="12 10 8 6"), session=session)

    assert await fsm.get_state() is None
    [elective] = await ElectiveWorkoutRepository(session).list_for_user(user.id)
    assert elective.total_reps == 36
