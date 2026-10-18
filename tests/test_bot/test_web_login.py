"""Вход в браузере через бота: настоящий aiogram-роутинг (Dispatcher.feed_update), без моков хендлеров.

Ключевой инвариант CLAUDE.md: подтверждает тот, кто НАЖАЛ кнопку (callback.from_user), а не автор сообщения с кнопкой
(callback.message.from_user — всегда бот)."""

from datetime import UTC, datetime

from aiogram import Bot, Dispatcher
from aiogram.methods import EditMessageText, SendMessage
from aiogram.types import Chat, Message, MessageEntity, Update
from aiogram.types import User as TgUser
from sqlalchemy import select

from app.bot import texts
from app.db.models import User, WebLoginRequest
from app.services import web_login
from tests.test_bot.conftest import BOT_TELEGRAM_ID, make_callback_update

TG = 55_001


def _start_update(telegram_id: int, payload: str) -> Update:
    text = f"/start {payload}"
    return Update(update_id=1, message=Message(
        message_id=7, date=datetime.now(UTC), chat=Chat(id=telegram_id, type="private"),
        from_user=TgUser(id=telegram_id, is_bot=False, first_name="Кирилл", username="kir"),
        text=text, entities=[MessageEntity(type="bot_command", offset=0, length=6)],
    ))


async def _request(session) -> tuple[str, str]:
    created = await web_login.create_login_request(session, ip_prefix=None)
    return created.request_id, created.code


def _sent_texts(bot: Bot) -> list[str]:
    return [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage | EditMessageText)]


async def test_start_with_payload_shows_code_and_buttons(session, bot: Bot, dispatcher: Dispatcher):
    rid, code = await _request(session)
    await dispatcher.feed_update(bot, _start_update(TG, f"weblogin_{rid}"), session=session)
    [msg] = [m for m in bot.session.sent_methods if isinstance(m, SendMessage)]
    assert code in msg.text and "только если вы сами открыли сайт" in msg.text
    buttons = [b.callback_data for row in msg.reply_markup.inline_keyboard for b in row]
    assert buttons == [f"wl:ok:{rid}", f"wl:no:{rid}"]
    assert len(max(buttons, key=len).encode()) <= 64


async def test_confirm_uses_the_presser_not_the_message_author(session, bot: Bot, dispatcher: Dispatcher):
    rid, _ = await _request(session)
    await dispatcher.feed_update(bot, _start_update(TG, f"weblogin_{rid}"), session=session)
    # make_callback_update: message.from_user = БОТ, нажавший = TG (как в реальном Telegram)
    await dispatcher.feed_update(bot, make_callback_update(telegram_id=TG, data=f"wl:ok:{rid}"), session=session)
    row = (await session.execute(select(WebLoginRequest))).scalar_one()
    assert row.status == "approved" and row.telegram_id == TG != BOT_TELEGRAM_ID
    assert texts.WEB_LOGIN_APPROVED in _sent_texts(bot)
    users = (await session.execute(select(User).where(User.telegram_id == TG))).scalars().all()
    assert len(users) == 1


async def test_second_user_cannot_confirm_someone_elses_open_link(session, bot: Bot, dispatcher: Dispatcher):
    rid, _ = await _request(session)
    await dispatcher.feed_update(bot, _start_update(TG, f"weblogin_{rid}"), session=session)
    await dispatcher.feed_update(bot, make_callback_update(telegram_id=TG + 1, data=f"wl:ok:{rid}"), session=session)
    row = (await session.execute(select(WebLoginRequest))).scalar_one()
    assert row.status == "pending" and row.telegram_id is None
    assert texts.WEB_LOGIN_GONE in _sent_texts(bot)


async def test_second_user_opening_the_link_is_told_it_is_taken(session, bot: Bot, dispatcher: Dispatcher):
    rid, _ = await _request(session)
    await dispatcher.feed_update(bot, _start_update(TG, f"weblogin_{rid}"), session=session)
    bot.session.sent_methods.clear()
    await dispatcher.feed_update(bot, _start_update(TG + 1, f"weblogin_{rid}"), session=session)
    assert _sent_texts(bot) == [texts.WEB_LOGIN_TAKEN]


async def test_cancel_marks_request_denied(session, bot: Bot, dispatcher: Dispatcher):
    rid, _ = await _request(session)
    await dispatcher.feed_update(bot, _start_update(TG, f"weblogin_{rid}"), session=session)
    await dispatcher.feed_update(bot, make_callback_update(telegram_id=TG, data=f"wl:no:{rid}"), session=session)
    row = (await session.execute(select(WebLoginRequest))).scalar_one()
    assert row.status == "denied"
    assert texts.WEB_LOGIN_DENIED in _sent_texts(bot)


async def test_double_confirm_is_idempotent_and_reports_stale(session, bot: Bot, dispatcher: Dispatcher):
    rid, _ = await _request(session)
    await dispatcher.feed_update(bot, _start_update(TG, f"weblogin_{rid}"), session=session)
    for _ in range(2):
        await dispatcher.feed_update(bot, make_callback_update(telegram_id=TG, data=f"wl:ok:{rid}"), session=session)
    assert _sent_texts(bot).count(texts.WEB_LOGIN_APPROVED) == 1
    assert _sent_texts(bot).count(texts.WEB_LOGIN_GONE) == 1


async def test_unknown_or_malformed_payload_is_gone_and_creates_no_user(session, bot: Bot, dispatcher: Dispatcher):
    for payload in ("weblogin_" + "0" * 32, "weblogin_zzz", "weblogin_"):
        bot.session.sent_methods.clear()
        await dispatcher.feed_update(bot, _start_update(TG, payload), session=session)
        assert _sent_texts(bot) == [texts.WEB_LOGIN_GONE]
    assert (await session.execute(select(User).where(User.telegram_id == TG))).first() is None


async def test_plain_start_is_not_hijacked_by_web_login(session, bot: Bot, dispatcher: Dispatcher):
    await dispatcher.feed_update(bot, _start_update(TG, "").model_copy(), session=session)
    assert texts.WEB_LOGIN_GONE not in _sent_texts(bot)
    assert (await session.execute(select(User).where(User.telegram_id == TG))).scalar_one()
