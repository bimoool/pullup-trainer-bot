""""🚀 Личный кабинет" в нижнем меню (Mini App, Этап 0, issue #15) — видна
только когда MINI_APP_URL заполнен реальным https://-адресом (Telegram не
даст открыть WebAppInfo иначе), тот же паттерн условной видимости, что и
"🛠 Админка" (см. test_bottom_menu_admin.py)."""

from datetime import UTC, datetime

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser

from app.bot import texts
from app.bot.keyboards import BOTTOM_MENU_MINI_APP
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


async def test_mini_app_button_hidden_when_url_not_configured(
    session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    monkeypatch.setattr(settings, "mini_app_url", "")
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    await dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id).clear()

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="/start"), session=session)

    [welcome] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text == texts.WELCOME_BACK
    ]
    assert BOTTOM_MENU_MINI_APP not in _bottom_menu_labels(welcome.reply_markup)


async def test_mini_app_button_visible_and_opens_web_app_when_url_configured(
    session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    monkeypatch.setattr(settings, "mini_app_url", "https://app.bimoool.com")
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    await dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id).clear()

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="/start"), session=session)

    [welcome] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text == texts.WELCOME_BACK
    ]
    [button] = [
        b for row in welcome.reply_markup.keyboard for b in row if b.text == BOTTOM_MENU_MINI_APP
    ]
    assert button.web_app.url == "https://app.bimoool.com"
