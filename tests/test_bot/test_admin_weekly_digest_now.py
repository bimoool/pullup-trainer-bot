"""Кнопка "🗞 Разослать дайджест сейчас" в админ-меню (issue #86) — ручной
запуск ТОГО ЖЕ процесса, что и воскресный крон (app/workers/weekly_digest.py),
без дублирования сбора коммитов/issues или логики рассылки: хендлер только
вызывает send_weekly_digest_reminder напрямую. Реальным aiogram-роутингом,
как test_admin_test_payment.py."""

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage

from app.bot import texts
from app.bot.states import AdminStates
from app.config import settings
from app.db.models import User
from tests.test_bot.conftest import make_callback_update as _callback_update


async def test_admin_menu_lists_weekly_digest_now_button(
    session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    monkeypatch.setattr(settings, "admin_ids", str(user.telegram_id))

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="admin_menu"), session=session,
    )

    [menu] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text == texts.ADMIN_MENU_HEADER
    ]
    buttons = {b.text: b.callback_data for row in menu.reply_markup.inline_keyboard for b in row}
    assert buttons["🗞 Разослать дайджест сейчас"] == "admin_weekly_digest_now"


async def test_weekly_digest_now_denied_for_non_admin(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id).clear()

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="admin_weekly_digest_now"), session=session,
    )

    sent_texts = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage)]
    assert texts.ADMIN_WEEKLY_DIGEST_REMINDER not in sent_texts
    assert await dispatcher.fsm.get_context(
        bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id,
    ).get_state() is None


async def test_weekly_digest_now_triggers_the_same_reminder_as_the_scheduled_job(
    session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    monkeypatch.setattr(settings, "admin_ids", str(user.telegram_id))
    await dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id).clear()

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="admin_weekly_digest_now"), session=session,
    )

    # GITHUB_TOKEN не настроен в тестах — секции "недоступно", как и у
    # обычного напоминания без github_client (см. test_weekly_digest.py).
    [reminder] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.chat_id == user.telegram_id
        and m.text.startswith(texts.ADMIN_WEEKLY_DIGEST_REMINDER)
    ]
    assert reminder is not None

    # Тот же путь подтверждения ответом, что и у планового дайджеста —
    # handle_weekly_digest_reply ловит следующий текст админа по этому
    # состоянию, значит кнопка не завела свой отдельный сценарий рассылки.
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == AdminStates.waiting_for_weekly_digest_text.state
