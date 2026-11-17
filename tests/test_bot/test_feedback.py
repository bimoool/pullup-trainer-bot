"""«💬 Сообщить о проблеме» (❓ Помощь) — проверяет, что текст пользователя
одновременно (1) уходит событием в events (не теряется, даже если личное
уведомление админу не доставится) и (2) переводит диалог обратно в None,
не оставляя пользователя подвешенным в FeedbackStates."""

from datetime import UTC, datetime

import pytest
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser

from app.bot.states import FeedbackStates
from app.config import settings
from app.db.models import User
from app.db.repositories.events import EventRepository
from app.db.repositories.users import UserRepository
from tests.test_bot.conftest import make_callback_update as _callback_update


def _message_update(*, telegram_id: int, text: str, username: str | None = "tester") -> Update:
    return Update(
        update_id=1,
        message=Message(
            message_id=101, date=datetime.now(UTC),
            chat=Chat(id=telegram_id, type="private"),
            from_user=TgUser(id=telegram_id, is_bot=False, first_name="Tester", username=username),
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


@pytest.mark.parametrize("username", [None, "synthetic_private_handle"])
async def test_feedback_identifies_author_only_by_internal_id(
    session, user, bot, dispatcher, monkeypatch, username,
):
    monkeypatch.setattr(settings, "admin_ids", "999999")
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(FeedbackStates.waiting_for_text)
    update = _message_update(telegram_id=user.telegram_id, text="synthetic feedback", username=username)
    await dispatcher.feed_update(bot, update, session=session)
    notification = next(m for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.chat_id == 999999)
    assert f"пользователь #{user.id}" in notification.text
    assert str(user.telegram_id) not in notification.text
    assert "synthetic_private_handle" not in notification.text
    assert notification.reply_markup.inline_keyboard[0][0].callback_data == f"admin_dm:{user.id}"
    assert await fsm.get_state() is None


async def test_feedback_delivery_failure_does_not_log_report_or_exception_text(
    session, user, bot, dispatcher, monkeypatch, caplog,
):
    monkeypatch.setattr(settings, "admin_ids", "999999,999998")
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(FeedbackStates.waiting_for_text)
    private_text = "synthetic-private-support-note"
    original_request = bot.session.make_request

    async def fail_first_admin(bot, method, timeout=None):
        if isinstance(method, SendMessage) and method.chat_id == 999999:
            raise TelegramBadRequest(method=method, message=private_text)
        return await original_request(bot, method, timeout)

    monkeypatch.setattr(bot.session, "make_request", fail_first_admin)
    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text=private_text), session=session,
    )
    assert private_text not in caplog.text
    assert "TelegramBadRequest" in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
    events = await EventRepository(session).list_for_user(user.id)
    assert [event.payload["text"] for event in events if event.event_type == "feedback_reported"] == [private_text]
    sent = [m for m in bot.session.sent_methods if isinstance(m, SendMessage)]
    assert any(m.chat_id == 999998 and private_text in m.text for m in sent)
    assert any(m.chat_id == user.telegram_id for m in sent)
    assert await fsm.get_state() is None
