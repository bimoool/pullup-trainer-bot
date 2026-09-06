""""📢 Рассылка всем" (handle_admin_broadcast_text) — прод-инцидент issue #69:
админ разослал сообщение с картинкой, рассылка упала на
`SendMessage.text=None`. У сообщения с фото Telegram кладёт подпись в
message.caption, а message.text остаётся None — код брал message.text
напрямую и передавал None в send_message. Реальным aiogram-роутингом, как
test_admin_dm.py.

test_broadcast_with_album_delivers_via_send_media_group_not_per_photo —
issue #72: несколько фото в одной рассылке Telegram доставляет боту не
одним апдейтом, а несколькими Update с общим media_group_id, и aiogram
polling обрабатывает их конкурентными задачами (handle_as_tasks=True по
умолчанию) — без буферизации (MediaGroupMiddleware, app/bot/middlewares.py)
каждое фото по отдельности ловило waiting_for_broadcast_text и запускало
рассылку само по себе. asyncio.gather имитирует именно эту конкурентность,
а не последовательный feed_update, как в остальных тестах файла."""

import asyncio
from datetime import UTC, datetime

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMediaGroup, SendMessage, SendPhoto
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


async def test_broadcast_with_album_delivers_via_send_media_group_not_per_photo(
    session, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    """issue #72: раньше альбом из нескольких фото уходил как одно фото с
    подписью (первый Update отработал полную рассылку до прихода второго) и
    остальные фото — отдельными сообщениями без текста (каждый следующий
    Update своей конкурентной задачей ловил то же FSM-состояние и запускал
    рассылку заново). Debounce MediaGroupMiddleware укорочен монкипатчем,
    чтобы не ждать боевые 0.7с в каждом прогоне теста."""
    monkeypatch.setattr("app.bot.middlewares.ALBUM_DEBOUNCE_SECONDS", 0.05)

    admin = await _make_admin(session, 8205)
    monkeypatch.setattr(settings, "admin_ids", str(admin.telegram_id))
    onboarded = await UserRepository(session).create(telegram_id=8206, username="onboarded_user_3")
    await UserRepository(session).complete_onboarding(onboarded.id, datetime.now(UTC))

    await dispatcher.feed_update(bot, _callback_update(telegram_id=admin.telegram_id, data="admin_broadcast"), session=session)

    media_group_id = "album-72"
    # Подпись — на ВТОРОМ сообщении альбома, не на первом по порядку
    # получения: в реальном Telegram она может оказаться на любой части, и
    # _album_caption обязана найти её независимо от порядка (см. admin.py).
    updates = [
        _album_photo_update(telegram_id=admin.telegram_id, message_id=201, media_group_id=media_group_id, file_id="album_photo_1"),
        _album_photo_update(
            telegram_id=admin.telegram_id, message_id=202, media_group_id=media_group_id,
            file_id="album_photo_2", caption="Новый релиз! 🎉",
        ),
    ]
    # asyncio.gather — не последовательные await, именно так aiogram polling
    # реально диспетчеризует части одного альбома (handle_as_tasks=True):
    # конкурентными задачами, не дожидаясь друг друга.
    await asyncio.gather(*(dispatcher.feed_update(bot, u, session=session) for u in updates))

    delivered_groups = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMediaGroup) and m.chat_id == onboarded.telegram_id
    ]
    assert len(delivered_groups) == 1
    [group] = delivered_groups
    assert [item.media for item in group.media] == ["album_photo_1", "album_photo_2"]
    assert group.media[0].caption == "Новый релиз! 🎉"
    assert group.media[1].caption is None

    # Ни одного SendPhoto по отдельности каждому фото — старый баг ровно это
    # и делал (одно фото с подписью, второе без текста отдельным сообщением).
    per_photo = [m for m in bot.session.sent_methods if isinstance(m, SendPhoto) and m.chat_id == onboarded.telegram_id]
    assert per_photo == []

    # Хендлер рассылки отработал ровно один раз на весь альбом, не дважды —
    # без буферизации второй Update запустил бы вторую полную рассылку и
    # вторую сессию с state.clear() поверх первой.
    confirmations = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.chat_id == admin.telegram_id
        and m.text == texts.ADMIN_BROADCAST_DONE.format(sent=1, total=1)
    ]
    assert len(confirmations) == 1
