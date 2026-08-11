"""«💬 Сообщить о проблеме» (❓ Помощь) — проверяет, что текст пользователя
одновременно (1) уходит событием в events (не теряется, даже если личное
уведомление админу не доставится) и (2) переводит диалог обратно в None,
не оставляя пользователя подвешенным в FeedbackStates."""

from datetime import UTC, datetime

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update
from aiogram.types import User as TgUser

from app.bot.states import FeedbackStates
from app.config import settings
from app.db.models import User
from app.db.repositories.events import EventRepository
from app.db.repositories.users import UserRepository


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
            from_user=TgUser(id=telegram_id, is_bot=False, first_name="Tester", username="tester"),
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
            from_user=TgUser(id=telegram_id, is_bot=False, first_name="Tester", username="tester"),
            text=text,
        ),
    )


async def test_report_problem_start_sets_waiting_state(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="report_problem"), session=session,
    )

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == FeedbackStates.waiting_for_text.state


async def test_feedback_text_creates_event_and_clears_state(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(FeedbackStates.waiting_for_text)

    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="кнопка не работает"), session=session,
    )

    events = await EventRepository(session).list_for_user(user.id)
    feedback_events = [e for e in events if e.event_type == "feedback_reported"]
    assert len(feedback_events) == 1
    assert feedback_events[0].payload["text"] == "кнопка не работает"
    assert feedback_events[0].payload["user_id"] == user.id

    assert await fsm.get_state() is None


async def test_admin_notification_has_reply_button_with_user_id(
    session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    # Часть 10, п. 23: кнопка "Ответить" под уведомлением админу ведёт в
    # уже существующий флоу личного сообщения (admin_dm:<user_id>).
    monkeypatch.setattr(settings, "admin_ids", "999999")
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(FeedbackStates.waiting_for_text)

    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="что-то сломалось"), session=session,
    )

    admin_notifications = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.chat_id == 999999
    ]
    assert len(admin_notifications) == 1
    keyboard = admin_notifications[0].reply_markup
    assert keyboard is not None
    reply_button = keyboard.inline_keyboard[0][0]
    assert reply_button.callback_data == f"admin_dm:{user.id}"
