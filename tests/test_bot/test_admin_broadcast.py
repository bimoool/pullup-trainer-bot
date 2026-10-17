""""📢 Рассылка всем" — приём статьи → копия только админу → отдельное
подтверждение → копирование всем зарегистрированным, кроме админа.

История: раньше рассылка уходила ВСЕМ сразу по первому же сообщению админа
и пересобиралась заново (send_message/send_photo/send_media_group с
parse_mode=None) — у пересланной статьи терялись форматирование, ссылки и
видео/документы, предпросмотра и защиты от повтора не было (прод-инциденты
issue #69 и #72 были про эту пересборку). Теперь сохраняются id исходных
сообщений, а доставка — copyMessages (Telegram копирует их как есть).

Реальным aiogram-роутингом (dispatcher.feed_update), как test_admin_dm.py.
asyncio.gather имитирует конкурентную обработку апдейтов aiogram polling
(handle_as_tasks=True): части статьи и двойное нажатие кнопки приходят
параллельно, а не по очереди."""

import asyncio
from datetime import UTC, datetime

import pytest
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import CopyMessages, SendMediaGroup, SendMessage, SendPhoto
from aiogram.types import Chat, Message, MessageEntity, PhotoSize, Update
from aiogram.types import User as TgUser

from app.bot import texts
from app.bot.handlers import admin as admin_handlers
from app.config import settings
from app.db.models import User
from app.db.repositories.users import UserRepository
from tests.test_bot.conftest import make_callback_update as _callback_update


@pytest.fixture(autouse=True)
def _no_send_interval(monkeypatch):
    monkeypatch.setattr(admin_handlers, "BROADCAST_SEND_INTERVAL_SECONDS", 0, raising=False)
    monkeypatch.setattr("app.bot.middlewares.ALBUM_DEBOUNCE_SECONDS", 0.05)


def _forwarded_text_update(*, telegram_id: int, message_id: int, text: str) -> Update:
    """Пересланный пост канала с разметкой (жирный + ссылка)."""
    return Update(
        update_id=message_id,
        message=Message(
            message_id=message_id, date=datetime.now(UTC),
            chat=Chat(id=telegram_id, type="private"),
            from_user=TgUser(id=telegram_id, is_bot=False, first_name="Tester"),
            text=text,
            entities=[
                MessageEntity(type="bold", offset=0, length=5),
                MessageEntity(type="text_link", offset=6, length=4, url="https://example.com"),
            ],
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


async def _setup(session, monkeypatch, admin_tg: int) -> tuple[User, User, User]:
    """Админ + прошедший онбординг + НЕ прошедший онбординг: аудитория —
    все зарегистрированные, кроме админа, независимо от онбординга."""
    repo = UserRepository(session)
    admin = await repo.create(telegram_id=admin_tg, username="the_admin")
    monkeypatch.setattr(settings, "admin_ids", str(admin.telegram_id))
    onboarded = await repo.create(telegram_id=admin_tg + 1, username="onboarded")
    await repo.complete_onboarding(onboarded.id, datetime.now(UTC))
    fresh = await repo.create(telegram_id=admin_tg + 2, username="fresh")
    return admin, onboarded, fresh


async def _press(dispatcher, bot, session, admin_tg: int, data: str) -> None:
    await dispatcher.feed_update(bot, _callback_update(telegram_id=admin_tg, data=data), session=session)


def _content_to_others(bot: Bot, admin_tg: int) -> list:
    """Всё, что могло донести контент до кого-то, кроме админа."""
    return [
        m for m in bot.session.sent_methods
        if isinstance(m, CopyMessages | SendMessage | SendPhoto | SendMediaGroup)
        and getattr(m, "chat_id", admin_tg) != admin_tg
    ]


async def _collect_and_preview(dispatcher, bot, session, admin_tg: int) -> None:
    await _press(dispatcher, bot, session, admin_tg, "admin_broadcast")
    await dispatcher.feed_update(
        bot, _forwarded_text_update(telegram_id=admin_tg, message_id=301, text="Новое тест статьи"), session=session,
    )
    await dispatcher.feed_update(
        bot, _forwarded_text_update(telegram_id=admin_tg, message_id=302, text="Часть второй статьи"), session=session,
    )
    await _press(dispatcher, bot, session, admin_tg, "admin_broadcast_preview")


async def test_receiving_article_sends_nothing_to_anyone(session, bot: Bot, dispatcher: Dispatcher, monkeypatch):
    """Старое поведение: первое же сообщение админа уходило всем сразу."""
    admin, _, _ = await _setup(session, monkeypatch, 8301)
    await _press(dispatcher, bot, session, admin.telegram_id, "admin_broadcast")
    await dispatcher.feed_update(
        bot, _forwarded_text_update(telegram_id=admin.telegram_id, message_id=301, text="Новое тест статьи"),
        session=session,
    )

    assert _content_to_others(bot, admin.telegram_id) == []
    assert not [m for m in bot.session.sent_methods if isinstance(m, CopyMessages)]


async def test_preview_copies_original_messages_only_to_admin(session, bot: Bot, dispatcher: Dispatcher, monkeypatch):
    admin, _, _ = await _setup(session, monkeypatch, 8311)
    await _collect_and_preview(dispatcher, bot, session, admin.telegram_id)

    [preview] = [m for m in bot.session.sent_methods if isinstance(m, CopyMessages)]
    # Копия исходных сообщений (оформление/медиа не пересобираются) и только админу.
    assert preview.chat_id == admin.telegram_id
    assert preview.from_chat_id == admin.telegram_id
    assert list(preview.message_ids) == [301, 302]
    assert _content_to_others(bot, admin.telegram_id) == []

    [confirm] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text == texts.ADMIN_BROADCAST_CONFIRM.format(recipients=2)
    ]
    callbacks = [b.callback_data for row in confirm.reply_markup.inline_keyboard for b in row]
    assert callbacks == ["admin_broadcast_send", "admin_broadcast_cancel"]


async def test_confirm_copies_to_all_registered_except_admin(session, bot: Bot, dispatcher: Dispatcher, monkeypatch):
    admin, onboarded, fresh = await _setup(session, monkeypatch, 8321)
    await _collect_and_preview(dispatcher, bot, session, admin.telegram_id)
    await _press(dispatcher, bot, session, admin.telegram_id, "admin_broadcast_send")

    copies = [m for m in bot.session.sent_methods if isinstance(m, CopyMessages)]
    by_chat = {m.chat_id: list(m.message_ids) for m in copies}
    assert by_chat == {admin.telegram_id: [301, 302], onboarded.telegram_id: [301, 302], fresh.telegram_id: [301, 302]}
    # Админу — ровно одна копия (предпросмотр), на массовом шаге его нет.
    assert sum(1 for m in copies if m.chat_id == admin.telegram_id) == 1

    report = texts.ADMIN_BROADCAST_REPORT.format(sent=2, total=2, blocked=0, failed=0)
    assert [m for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text == report]


async def test_double_confirm_sends_only_once(session, bot: Bot, dispatcher: Dispatcher, monkeypatch):
    admin, onboarded, _ = await _setup(session, monkeypatch, 8331)
    await _collect_and_preview(dispatcher, bot, session, admin.telegram_id)

    await asyncio.gather(
        _press(dispatcher, bot, session, admin.telegram_id, "admin_broadcast_send"),
        _press(dispatcher, bot, session, admin.telegram_id, "admin_broadcast_send"),
    )
    # И ещё раз — старая кнопка после завершения.
    await _press(dispatcher, bot, session, admin.telegram_id, "admin_broadcast_send")

    to_user = [m for m in bot.session.sent_methods if isinstance(m, CopyMessages) and m.chat_id == onboarded.telegram_id]
    assert len(to_user) == 1


async def test_send_without_preview_sends_nothing(session, bot: Bot, dispatcher: Dispatcher, monkeypatch):
    admin, _, _ = await _setup(session, monkeypatch, 8341)
    await _press(dispatcher, bot, session, admin.telegram_id, "admin_broadcast")
    await dispatcher.feed_update(
        bot, _forwarded_text_update(telegram_id=admin.telegram_id, message_id=301, text="Новое тест статьи"),
        session=session,
    )
    await _press(dispatcher, bot, session, admin.telegram_id, "admin_broadcast_send")

    assert not [m for m in bot.session.sent_methods if isinstance(m, CopyMessages)]
    assert _content_to_others(bot, admin.telegram_id) == []


async def test_cancel_after_preview_sends_nothing(session, bot: Bot, dispatcher: Dispatcher, monkeypatch):
    admin, _, _ = await _setup(session, monkeypatch, 8351)
    await _collect_and_preview(dispatcher, bot, session, admin.telegram_id)
    await _press(dispatcher, bot, session, admin.telegram_id, "admin_broadcast_cancel")
    await _press(dispatcher, bot, session, admin.telegram_id, "admin_broadcast_send")

    assert _content_to_others(bot, admin.telegram_id) == []
    assert [m for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text == texts.ADMIN_BROADCAST_CANCELLED]


async def test_non_admin_cannot_preview_or_send(session, bot: Bot, dispatcher: Dispatcher, monkeypatch):
    admin, onboarded, _ = await _setup(session, monkeypatch, 8361)
    await _collect_and_preview(dispatcher, bot, session, admin.telegram_id)
    bot.session.sent_methods.clear()

    await _press(dispatcher, bot, session, onboarded.telegram_id, "admin_broadcast_send")
    await _press(dispatcher, bot, session, onboarded.telegram_id, "admin_broadcast_preview")

    assert not [m for m in bot.session.sent_methods if isinstance(m, CopyMessages)]


async def test_album_parts_arriving_concurrently_are_all_kept(session, bot: Bot, dispatcher: Dispatcher, monkeypatch):
    """Части альбома и отдельные сообщения статьи приходят параллельными
    задачами — ни один id не должен потеряться при записи в FSM."""
    admin, _, _ = await _setup(session, monkeypatch, 8371)
    await _press(dispatcher, bot, session, admin.telegram_id, "admin_broadcast")

    updates = [
        _forwarded_text_update(telegram_id=admin.telegram_id, message_id=400, text="Новое тест статьи"),
        _album_photo_update(telegram_id=admin.telegram_id, message_id=401, media_group_id="g", file_id="p1"),
        _album_photo_update(telegram_id=admin.telegram_id, message_id=402, media_group_id="g", file_id="p2", caption="x"),
        _forwarded_text_update(telegram_id=admin.telegram_id, message_id=403, text="Часть второй статьи"),
    ]
    await asyncio.gather(*(dispatcher.feed_update(bot, u, session=session) for u in updates))
    await _press(dispatcher, bot, session, admin.telegram_id, "admin_broadcast_preview")

    [preview] = [m for m in bot.session.sent_methods if isinstance(m, CopyMessages)]
    assert list(preview.message_ids) == [400, 401, 402, 403]
    assert _content_to_others(bot, admin.telegram_id) == []


class _FlakyBot:
    """copy_messages: один получатель заблокировал бота, у другого — иная ошибка."""

    def __init__(self, blocked: int, broken: int) -> None:
        self.blocked, self.broken, self.calls = blocked, broken, []

    async def copy_messages(self, *, chat_id, from_chat_id, message_ids):
        self.calls.append(chat_id)
        if chat_id == self.blocked:
            raise TelegramForbiddenError(method=None, message="Forbidden: bot was blocked by the user")
        if chat_id == self.broken:
            from aiogram.exceptions import TelegramBadRequest
            raise TelegramBadRequest(method=None, message="Bad Request: chat not found")
        return []


async def test_copy_to_users_counts_blocked_and_failed():
    users = [User(telegram_id=i) for i in (1, 2, 3, 4)]
    bot = _FlakyBot(blocked=2, broken=3)

    report = await admin_handlers._copy_to_users(bot, from_chat_id=99, message_ids=[5], users=users)

    assert bot.calls == [1, 2, 3, 4]  # ошибка одного получателя не останавливает рассылку
    assert (report.total, report.sent, report.blocked, report.failed) == (4, 2, 1, 1)
