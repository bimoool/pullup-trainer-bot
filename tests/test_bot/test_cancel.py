"""«Отмена» (кнопка и /cancel) — Часть 10, пакет #2, п.18: раньше слала два
сообщения подряд с одинаковым смыслом ("Отменено. Что делаем?" и
"С возвращением! Что делаем?", оба заканчивались одинаково). Реальным
aiogram-роутингом."""

from datetime import UTC, datetime

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage

from app.bot import texts
from app.db.models import User
from app.db.repositories.users import UserRepository
from tests.test_bot.conftest import make_callback_update as _callback_update


async def test_cancel_button_sends_exactly_one_message(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="cancel_flow"), session=session,
    )

    sent_texts = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]
    assert sent_texts == [texts.CANCELLED]


async def test_cancel_command_sends_exactly_one_message(session, user: User, bot: Bot, dispatcher: Dispatcher):
    from aiogram.types import Chat, Message, Update
    from aiogram.types import User as TgUser

    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))

    update = Update(
        update_id=1,
        message=Message(
            message_id=1, date=datetime.now(UTC),
            chat=Chat(id=user.telegram_id, type="private"),
            from_user=TgUser(id=user.telegram_id, is_bot=False, first_name="Tester"),
            text="/cancel",
        ),
    )
    await dispatcher.feed_update(bot, update, session=session)

    sent_texts = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]
    assert sent_texts == [texts.CANCELLED]
