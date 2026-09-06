""""📢 Рассылка всем" (handle_admin_broadcast_text) — прод-инцидент issue #69:
админ разослал сообщение с картинкой, рассылка упала на
`SendMessage.text=None`. У сообщения с фото Telegram кладёт подпись в
message.caption, а message.text остаётся None — код брал message.text
напрямую и передавал None в send_message. Реальным aiogram-роутингом, как
test_admin_dm.py."""

from datetime import UTC, datetime

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage, SendPhoto
from aiogram.types import Chat, Message, PhotoSize, Update
from aiogram.types import User as TgUser

from app.bot import texts
from app.config import settings
from app.db.models import User
from app.db.repositories.users import UserRepository
from tests.test_bot.conftest import make_callback_update as _callback_update


def _text_update(*, telegram_id: int, text: str) -> Update:
    return Update(
        update_id=1,
        message=Message(
            message_id=101, date=datetime.now(UTC),
            chat=Chat(id=telegram_id, type="private"),
            from_user=TgUser(id=telegram_id, is_bot=False, first_name="Tester"),
            text=text,
        ),
    )


def _photo_update(*, telegram_id: int, caption: str) -> Update:
    return Update(
        update_id=1,
        message=Message(
            message_id=101, date=datetime.now(UTC),
            chat=Chat(id=telegram_id, type="private"),
            from_user=TgUser(id=telegram_id, is_bot=False, first_name="Tester"),
            photo=[PhotoSize(file_id="photo1", file_unique_id="u1", width=100, height=100)],
            caption=caption,
        ),
    )


async def _make_admin(session, telegram_id: int) -> User:
    return await UserRepository(session).create(telegram_id=telegram_id, username="the_admin")


async def test_broadcast_delivers_text_message(session, bot: Bot, dispatcher: Dispatcher, monkeypatch):
    admin = await _make_admin(session, 8201)
    monkeypatch.setattr(settings, "admin_ids", str(admin.telegram_id))
    onboarded = await UserRepository(session).create(telegram_id=8202, username="onboarded_user")
    await UserRepository(session).complete_onboarding(onboarded.id, datetime.now(UTC))

    await dispatcher.feed_update(bot, _callback_update(telegram_id=admin.telegram_id, data="admin_broadcast"), session=session)
    await dispatcher.feed_update(bot, _text_update(telegram_id=admin.telegram_id, text="Запустили Mini App!"), session=session)

    delivered = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.chat_id == onboarded.telegram_id and m.text == "Запустили Mini App!"
    ]
    assert len(delivered) == 1


async def test_broadcast_with_photo_delivers_via_send_photo_not_send_message(
    session, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    """Раньше это падало: message.text is None для сообщения с картинкой,
    а _broadcast_to_onboarded_users передавал его напрямую в
    bot.send_message(..., text=None) — pydantic-валидация SendMessage
    отклоняет None. Теперь фото пересылается через send_photo(caption=...)."""
    admin = await _make_admin(session, 8203)
    monkeypatch.setattr(settings, "admin_ids", str(admin.telegram_id))
    onboarded = await UserRepository(session).create(telegram_id=8204, username="onboarded_user_2")
    await UserRepository(session).complete_onboarding(onboarded.id, datetime.now(UTC))

    await dispatcher.feed_update(bot, _callback_update(telegram_id=admin.telegram_id, data="admin_broadcast"), session=session)
    await dispatcher.feed_update(
        bot, _photo_update(telegram_id=admin.telegram_id, caption="Запустили Mini App! 🚀"), session=session,
    )

    delivered = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendPhoto) and m.chat_id == onboarded.telegram_id
    ]
    assert len(delivered) == 1
    assert delivered[0].caption == "Запустили Mini App! 🚀"
    assert delivered[0].photo == "photo1"

    # Ни один SendMessage с text=None не мог случиться — pydantic бы уже
    # упал при его конструировании, но явная проверка documents intent.
    broken = [m for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.chat_id == onboarded.telegram_id]
    assert broken == []

    [confirmation] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.chat_id == admin.telegram_id
        and m.text == texts.ADMIN_BROADCAST_DONE.format(sent=1, total=1)
    ]
    assert confirmation is not None
