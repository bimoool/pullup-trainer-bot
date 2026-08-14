""""🛠 Админка" в постоянном нижнем меню — по запросу автора, тот же паттерн
условной видимости, что уже есть у "🧪 Полный сброс (админ)" в Профиле
(is_admin через settings.is_admin). Ведёт туда же, куда команда /admin —
общий обработчик, не отдельный сценарий."""

from datetime import UTC, datetime

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser

from app.bot import texts
from app.bot.keyboards import BOTTOM_MENU_ADMIN
from app.config import settings
from app.db.models import User
from app.db.repositories.users import UserRepository


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


def _bottom_menu_labels(reply_markup) -> set[str]:
    return {button.text for row in reply_markup.keyboard for button in row}


async def test_admin_button_visible_in_bottom_menu_for_admin(
    session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    monkeypatch.setattr(settings, "admin_ids", str(user.telegram_id))
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    # Общий dispatcher/telegram_id между файлами tests/test_bot/ (см.
    # conftest.py) — состояние из другого теста иначе просачивается сюда
    # (тот же паттерн, что в test_edit_calendar.py).
    await dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id).clear()

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="/start"), session=session)

    [welcome] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text == texts.WELCOME_BACK
    ]
    assert BOTTOM_MENU_ADMIN in _bottom_menu_labels(welcome.reply_markup)


async def test_admin_button_hidden_in_bottom_menu_for_regular_user(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    await dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id).clear()

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="/start"), session=session)

    [welcome] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text == texts.WELCOME_BACK
    ]
    assert BOTTOM_MENU_ADMIN not in _bottom_menu_labels(welcome.reply_markup)


async def test_admin_button_press_opens_the_same_admin_menu_as_the_command(
    session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    monkeypatch.setattr(settings, "admin_ids", str(user.telegram_id))
    await dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id).clear()

    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text=BOTTOM_MENU_ADMIN), session=session,
    )

    [menu] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text == texts.ADMIN_MENU_HEADER
    ]
    buttons = {b.text: b.callback_data for row in menu.reply_markup.inline_keyboard for b in row}
    assert buttons["👥 Пользователи"] == "admin_users"


async def test_admin_button_text_denied_for_non_admin(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id).clear()

    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text=BOTTOM_MENU_ADMIN), session=session,
    )

    texts_sent = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage)]
    assert texts_sent == [texts.ADMIN_ACCESS_DENIED]
