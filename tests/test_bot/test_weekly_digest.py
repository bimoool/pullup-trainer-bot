"""Еженедельный дайджест новостей продукта (Часть 12) — механика:
воскресный воркер шлёт админу напоминание и выставляет FSM-состояние
программно (не через колбэк, нет входящего Update), следующее сообщение
админа в этом состоянии ловится как ответ на ИМЕННО это напоминание и
рассылается через тот же механизм, что и ручная "📢 Рассылка всем".
Реальным aiogram-роутингом, как test_admin_grants.py — плюс прямой вызов
send_weekly_digest_reminder (не через Update, как настоящий APScheduler)."""

from datetime import UTC, datetime, timedelta

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser

from app.bot import texts
from app.bot.states import AdminStates
from app.config import settings
from app.db.models import User
from app.db.repositories.users import UserRepository
from app.db.repositories.weekly_digests import WeeklyDigestRepository
from app.workers.weekly_digest import send_weekly_digest_reminder


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


async def _make_admin(session, telegram_id: int) -> User:
    return await UserRepository(session).create(telegram_id=telegram_id, username="the_admin")


async def test_reminder_sent_and_links_state_to_admin(session, bot: Bot, dispatcher: Dispatcher, monkeypatch):
    admin = await _make_admin(session, 8101)
    monkeypatch.setattr(settings, "admin_ids", str(admin.telegram_id))

    await send_weekly_digest_reminder(bot, dispatcher)

    [reminder] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.chat_id == admin.telegram_id
    ]
    assert reminder.text == texts.ADMIN_WEEKLY_DIGEST_REMINDER

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=admin.telegram_id, user_id=admin.telegram_id)
    assert await fsm.get_state() == AdminStates.waiting_for_weekly_digest_text.state
    data = await fsm.get_data()
    assert "weekly_digest_reminder_sent_at" in data


async def test_reminder_noop_when_no_admins_configured(session, bot: Bot, dispatcher: Dispatcher, monkeypatch):
    monkeypatch.setattr(settings, "admin_ids", "")

    await send_weekly_digest_reminder(bot, dispatcher)  # не должно упасть

    assert bot.session.sent_methods == []


async def test_reminder_send_failure_does_not_set_state(session, bot: Bot, dispatcher: Dispatcher, monkeypatch):
    admin = await _make_admin(session, 8102)
    monkeypatch.setattr(settings, "admin_ids", str(admin.telegram_id))

    async def _raise_forbidden(chat_id, text, **kwargs):
        raise TelegramForbiddenError(SendMessage(chat_id=chat_id, text=text), "Forbidden: bot was blocked")

    monkeypatch.setattr(bot, "send_message", _raise_forbidden)

    await send_weekly_digest_reminder(bot, dispatcher)

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=admin.telegram_id, user_id=admin.telegram_id)
    assert await fsm.get_state() is None


async def test_reply_within_deadline_broadcasts_via_shared_mechanism(
    session, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    admin = await _make_admin(session, 8103)
    monkeypatch.setattr(settings, "admin_ids", str(admin.telegram_id))

    onboarded = await UserRepository(session).create(telegram_id=8104, username="onboarded_user")
    await UserRepository(session).complete_onboarding(onboarded.id, datetime.now(UTC))
    not_onboarded = await UserRepository(session).create(telegram_id=8105, username="fresh_user")

    await send_weekly_digest_reminder(bot, dispatcher)
    await dispatcher.feed_update(
        bot, _message_update(telegram_id=admin.telegram_id, text="На этой неделе: разгрузочные тренировки!"),
        session=session,
    )

    delivered = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text == "На этой неделе: разгрузочные тренировки!"
    ]
    assert [m.chat_id for m in delivered] == [onboarded.telegram_id]
    assert not any(m.chat_id == not_onboarded.telegram_id for m in delivered)

    [confirmation] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.chat_id == admin.telegram_id and m.text == texts.ADMIN_BROADCAST_DONE.format(sent=1, total=1)
    ]
    assert confirmation is not None

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=admin.telegram_id, user_id=admin.telegram_id)
    assert await fsm.get_state() is None

    last_sent_at = await WeeklyDigestRepository(session).get_last_sent_at()
    assert last_sent_at is not None
    assert (datetime.now(UTC) - last_sent_at) < timedelta(seconds=10)


async def test_reply_after_deadline_is_skipped_silently_not_broadcast(
    session, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    admin = await _make_admin(session, 8106)
    monkeypatch.setattr(settings, "admin_ids", str(admin.telegram_id))
    onboarded = await UserRepository(session).create(telegram_id=8107, username="onboarded_user_2")
    await UserRepository(session).complete_onboarding(onboarded.id, datetime.now(UTC))

    await send_weekly_digest_reminder(bot, dispatcher)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=admin.telegram_id, user_id=admin.telegram_id)
    # Симулируем, что напоминание было отправлено больше суток назад —
    # не гоняем реальные 25 часов в тесте, просто подменяем метку времени,
    # которую реальный воркер выставил бы естественно раньше.
    stale_sent_at = datetime.now(UTC) - timedelta(hours=25)
    await fsm.update_data(weekly_digest_reminder_sent_at=stale_sent_at.isoformat())

    await dispatcher.feed_update(
        bot, _message_update(telegram_id=admin.telegram_id, text="Опоздавший дайджест"), session=session,
    )

    # Молча пропускаем — не рассылаем СТАРЫЙ текст, и не шлём его пользователю.
    delivered_to_user = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.chat_id == onboarded.telegram_id
    ]
    assert delivered_to_user == []

    [expired_notice] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.chat_id == admin.telegram_id
        and m.text.startswith("Прошло больше суток")
    ]
    assert expired_notice is not None

    assert await fsm.get_state() is None
    # Просроченный ответ не пишет в журнал — иначе last_digest_sent_at
    # сдвигался бы неделя за неделей без единой реальной рассылки.
    assert await WeeklyDigestRepository(session).get_last_sent_at() is None
