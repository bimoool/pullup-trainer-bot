"""Личное сообщение пользователю из /admin ("✉️ Написать" в карточке) —
диагностика по запросу автора: существует ли ещё этот флоу и реально ли
шлёт сообщение через bot.send_message. Реальным aiogram-роутингом, как
test_admin_grants.py. Плюс заготовка про инцидент (кнопка "⚠️ Использовать
заготовку про инцидент" в приглашении ввести текст)."""

import asyncio
from datetime import UTC, datetime

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMediaGroup, SendMessage
from aiogram.types import Chat, Message, PhotoSize, Update
from aiogram.types import User as TgUser

from app.bot import texts
from app.bot.states import AdminStates
from app.config import settings
from app.db.models import User
from app.db.repositories.users import UserRepository
from tests.test_bot.conftest import make_callback_update as _callback_update


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


def _album_photo_update(
    *, telegram_id: int, message_id: int, media_group_id: str, file_id: str, caption: str | None = None,
) -> Update:
    return Update(
        update_id=message_id,
        message=Message(
            message_id=message_id, date=datetime.now(UTC),
            chat=Chat(id=telegram_id, type="private"),
            from_user=TgUser(id=telegram_id, is_bot=False, first_name="Tester"),
            photo=[PhotoSize(file_id=file_id, file_unique_id=f"u{file_id}", width=100, height=100)],
            caption=caption,
            media_group_id=media_group_id,
        ),
    )


async def _make_admin(session, telegram_id: int) -> User:
    return await UserRepository(session).create(telegram_id=telegram_id, username="the_admin")


async def test_dm_prompt_offers_template_button(session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch):
    admin = await _make_admin(session, 8001)
    monkeypatch.setattr(settings, "admin_ids", str(admin.telegram_id))

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=admin.telegram_id, data=f"admin_dm:{user.id}"), session=session,
    )

    [prompt] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text == texts.ADMIN_DM_PROMPT.format(name=f"@{user.username}")
    ]
    buttons = {b.text: b.callback_data for row in prompt.reply_markup.inline_keyboard for b in row}
    assert buttons["⚠️ Использовать заготовку про инцидент"] == f"admin_dm_template:{user.id}"
    assert buttons["❌ Отмена"] == "cancel_flow"


async def test_dm_actually_delivers_message_to_target_user(
    session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    """Диагностика: подтверждает по факту (не по памяти), что флоу не
    сломался за время последующих правок — bot.send_message реально
    вызывается с telegram_id получателя и введённым текстом."""
    admin = await _make_admin(session, 8002)
    monkeypatch.setattr(settings, "admin_ids", str(admin.telegram_id))

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=admin.telegram_id, data=f"admin_dm:{user.id}"), session=session,
    )
    await dispatcher.feed_update(
        bot, _message_update(telegram_id=admin.telegram_id, text="Привет, тестовое сообщение"), session=session,
    )

    delivered = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.chat_id == user.telegram_id and m.text == "Привет, тестовое сообщение"
    ]
    assert len(delivered) == 1

    [confirmation] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.chat_id == admin.telegram_id and m.text == texts.ADMIN_DM_DONE
    ]
    assert confirmation is not None

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=admin.telegram_id, user_id=admin.telegram_id)
    assert await fsm.get_state() is None


async def test_dm_template_button_sends_template_to_admin_not_target(
    session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    admin = await _make_admin(session, 8003)
    monkeypatch.setattr(settings, "admin_ids", str(admin.telegram_id))

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=admin.telegram_id, data=f"admin_dm:{user.id}"), session=session,
    )
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=admin.telegram_id, data=f"admin_dm_template:{user.id}"), session=session,
    )

    template_messages = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text == texts.ADMIN_DM_INCIDENT_TEMPLATE
    ]
    assert len(template_messages) == 1
    assert template_messages[0].chat_id == admin.telegram_id  # не пользователю — только админу, для копирования

    # Заготовка ничего не отправила получателю и не сдвинула состояние —
    # следующий текст всё ещё уходит через обычный DM-флоу.
    sent_to_target = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.chat_id == user.telegram_id
    ]
    assert sent_to_target == []

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=admin.telegram_id, user_id=admin.telegram_id)
    assert await fsm.get_state() == AdminStates.waiting_for_dm_text.state

    await dispatcher.feed_update(
        bot, _message_update(telegram_id=admin.telegram_id, text="Отредактированная заготовка"), session=session,
    )
    delivered = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.chat_id == user.telegram_id and m.text == "Отредактированная заготовка"
    ]
    assert len(delivered) == 1


async def test_dm_with_album_delivers_via_send_media_group_not_per_photo(
    session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    """Тот же класс бага, что и в рассылке (issue #72) — DM тоже читает
    message.photo и без буферизации по media_group_id отправил бы каждое
    фото альбома отдельным DM (конкурентные задачи aiogram polling)."""
    monkeypatch.setattr("app.bot.middlewares.ALBUM_DEBOUNCE_SECONDS", 0.05)

    admin = await _make_admin(session, 8005)
    monkeypatch.setattr(settings, "admin_ids", str(admin.telegram_id))

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=admin.telegram_id, data=f"admin_dm:{user.id}"), session=session,
    )

    media_group_id = "dm-album-72"
    updates = [
        _album_photo_update(
            telegram_id=admin.telegram_id, message_id=301, media_group_id=media_group_id,
            file_id="dm_photo_1", caption="Смотри!",
        ),
        _album_photo_update(
            telegram_id=admin.telegram_id, message_id=302, media_group_id=media_group_id, file_id="dm_photo_2",
        ),
    ]
    await asyncio.gather(*(dispatcher.feed_update(bot, u, session=session) for u in updates))

    delivered_groups = [m for m in bot.session.sent_methods if isinstance(m, SendMediaGroup) and m.chat_id == user.telegram_id]
    assert len(delivered_groups) == 1
    [group] = delivered_groups
    assert [item.media for item in group.media] == ["dm_photo_1", "dm_photo_2"]
    assert group.media[0].caption == "Смотри!"

    confirmations = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.chat_id == admin.telegram_id and m.text == texts.ADMIN_DM_DONE
    ]
    assert len(confirmations) == 1


async def test_dm_denied_for_non_admin(session, user: User, bot: Bot, dispatcher: Dispatcher):
    other_user = await UserRepository(session).create(telegram_id=8004, username="not_admin")

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=other_user.telegram_id, data=f"admin_dm:{user.id}"), session=session,
    )

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=other_user.telegram_id, user_id=other_user.telegram_id)
    assert await fsm.get_state() is None
    sent_to_target = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.chat_id == user.telegram_id
    ]
    assert sent_to_target == []
