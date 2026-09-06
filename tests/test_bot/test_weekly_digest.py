"""Еженедельный дайджест новостей продукта (Часть 12) — механика:
воскресный воркер шлёт админу напоминание (дополненное автосбором "что
раскатили"/"что в работе" через GitHub REST API, см. app/services/
github.py) и выставляет FSM-состояние программно (не через колбэк, нет
входящего Update), следующее сообщение админа в этом состоянии ловится
как ответ на ИМЕННО это напоминание и рассылается через тот же механизм,
что и ручная "📢 Рассылка всем". Реальным aiogram-роутингом, как
test_admin_grants.py — плюс прямой вызов send_weekly_digest_reminder (не
через Update, как настоящий APScheduler).

session=session передаётся явно в send_weekly_digest_reminder — иначе
воркер открыл бы СВОЮ сессию через async_session_factory (DATABASE_URL
из .env, боевая БД), в обход тестовой; github_client=FakeGitHubClient(...)
— тем же принципом, реальная сеть в тестах не участвует."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage, SendPhoto
from aiogram.types import Chat, Message, PhotoSize, Update
from aiogram.types import User as TgUser

from app.bot import texts
from app.bot.states import AdminStates
from app.config import settings
from app.db.models import User
from app.db.repositories.users import UserRepository
from app.db.repositories.weekly_digests import WeeklyDigestRepository
from app.services.github import CommitSummary, IssueSummary
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


@dataclass
class FakeGitHubClient:
    """GitHubClientProtocol без сети — тот же приём, что FakeRobokassaClient
    в test_robokassa_service.py. received_since фиксирует, с каким since
    воркер реально вызвал list_commits_since — так тест может проверить
    саму границу диапазона (last_digest_sent_at либо DEFAULT_LOOKBACK_DAYS),
    не только факт вызова."""

    commits: list[CommitSummary] = field(default_factory=list)
    issues: list[IssueSummary] = field(default_factory=list)
    commits_error: Exception | None = None
    issues_error: Exception | None = None
    received_since: datetime | None = None

    async def list_commits_since(self, since: datetime) -> list[CommitSummary]:
        self.received_since = since
        if self.commits_error is not None:
            raise self.commits_error
        return self.commits

    async def list_open_issues(self) -> list[IssueSummary]:
        if self.issues_error is not None:
            raise self.issues_error
        return self.issues


async def test_reminder_sent_and_links_state_to_admin(session, bot: Bot, dispatcher: Dispatcher, monkeypatch):
    admin = await _make_admin(session, 8101)
    monkeypatch.setattr(settings, "admin_ids", str(admin.telegram_id))

    await send_weekly_digest_reminder(bot, dispatcher, session=session)

    [reminder] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.chat_id == admin.telegram_id
    ]
    # Без github_client (нет токена/не передан фейк) обе секции — "недоступно",
    # но вводная часть всегда неизменна.
    assert reminder.text.startswith(texts.ADMIN_WEEKLY_DIGEST_REMINDER)

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=admin.telegram_id, user_id=admin.telegram_id)
    assert await fsm.get_state() == AdminStates.waiting_for_weekly_digest_text.state
    data = await fsm.get_data()
    assert "weekly_digest_reminder_sent_at" in data


async def test_reminder_noop_when_no_admins_configured(session, bot: Bot, dispatcher: Dispatcher, monkeypatch):
    monkeypatch.setattr(settings, "admin_ids", "")

    await send_weekly_digest_reminder(bot, dispatcher, session=session)  # не должно упасть

    assert bot.session.sent_methods == []


async def test_reminder_send_failure_does_not_set_state(session, bot: Bot, dispatcher: Dispatcher, monkeypatch):
    admin = await _make_admin(session, 8102)
    monkeypatch.setattr(settings, "admin_ids", str(admin.telegram_id))

    async def _raise_forbidden(chat_id, text, **kwargs):
        raise TelegramForbiddenError(SendMessage(chat_id=chat_id, text=text), "Forbidden: bot was blocked")

    monkeypatch.setattr(bot, "send_message", _raise_forbidden)

    await send_weekly_digest_reminder(bot, dispatcher, session=session)

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

    await send_weekly_digest_reminder(bot, dispatcher, session=session)
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


async def test_reply_with_photo_broadcasts_via_send_photo_not_crash(
    session, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    """Прод-инцидент issue #69: дайджест с картинкой падал на
    `SendMessage.text=None`, потому что ответ-с-фото имеет message.text=None
    (подпись лежит в message.caption) и код передавал его напрямую в
    bot.send_message. Заодно WeeklyDigestRepository.record больше не
    пытается записать text=None в NOT NULL колонку."""
    admin = await _make_admin(session, 8115)
    monkeypatch.setattr(settings, "admin_ids", str(admin.telegram_id))
    onboarded = await UserRepository(session).create(telegram_id=8116, username="onboarded_user_3")
    await UserRepository(session).complete_onboarding(onboarded.id, datetime.now(UTC))

    await send_weekly_digest_reminder(bot, dispatcher, session=session)
    await dispatcher.feed_update(
        bot, _photo_update(telegram_id=admin.telegram_id, caption="Запустили Mini App! 🚀"), session=session,
    )

    delivered = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendPhoto) and m.chat_id == onboarded.telegram_id
    ]
    assert len(delivered) == 1
    assert delivered[0].caption == "Запустили Mini App! 🚀"

    last_sent_at = await WeeklyDigestRepository(session).get_last_sent_at()
    assert last_sent_at is not None


async def test_reply_after_deadline_is_skipped_silently_not_broadcast(
    session, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    admin = await _make_admin(session, 8106)
    monkeypatch.setattr(settings, "admin_ids", str(admin.telegram_id))
    onboarded = await UserRepository(session).create(telegram_id=8107, username="onboarded_user_2")
    await UserRepository(session).complete_onboarding(onboarded.id, datetime.now(UTC))

    await send_weekly_digest_reminder(bot, dispatcher, session=session)
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


# --- Автосбор "что раскатили"/"что в работе" (app/services/github.py) -------------


async def test_reminder_includes_commits_and_issues_sections_when_github_available(
    session, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    admin = await _make_admin(session, 8108)
    monkeypatch.setattr(settings, "admin_ids", str(admin.telegram_id))
    fake_github = FakeGitHubClient(
        commits=[
            CommitSummary(sha="a1", message="Починить баг с трёхзначными числами", author="bimoool",
                          committed_at=datetime.now(UTC)),
        ],
        issues=[IssueSummary(number=8, title="Формула прогрессии v4", labels=("done",))],
    )

    await send_weekly_digest_reminder(bot, dispatcher, session=session, github_client=fake_github)

    [reminder] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.chat_id == admin.telegram_id
    ]
    assert reminder.text.startswith(texts.ADMIN_WEEKLY_DIGEST_REMINDER)
    assert "Починить баг с трёхзначными числами" in reminder.text
    assert "#8 Формула прогрессии v4 (done)" in reminder.text


async def test_reminder_shows_empty_sections_when_no_commits_or_issues(
    session, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    admin = await _make_admin(session, 8109)
    monkeypatch.setattr(settings, "admin_ids", str(admin.telegram_id))
    fake_github = FakeGitHubClient(commits=[], issues=[])

    await send_weekly_digest_reminder(bot, dispatcher, session=session, github_client=fake_github)

    [reminder] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.chat_id == admin.telegram_id
    ]
    assert texts.ADMIN_WEEKLY_DIGEST_COMMITS_EMPTY in reminder.text
    assert texts.ADMIN_WEEKLY_DIGEST_ISSUES_EMPTY in reminder.text


async def test_reminder_degrades_gracefully_when_github_api_fails(
    session, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    """GitHub недоступен (сеть, лимит, просроченный токен) не должен
    блокировать само напоминание — только соответствующая секция
    заменяется коротким пояснением."""
    admin = await _make_admin(session, 8110)
    monkeypatch.setattr(settings, "admin_ids", str(admin.telegram_id))
    fake_github = FakeGitHubClient(
        commits_error=aiohttp.ClientConnectionError("GitHub API unreachable"),
        issues=[IssueSummary(number=1, title="Открытый issue", labels=())],
    )

    await send_weekly_digest_reminder(bot, dispatcher, session=session, github_client=fake_github)

    [reminder] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.chat_id == admin.telegram_id
    ]
    assert texts.ADMIN_WEEKLY_DIGEST_COMMITS_UNAVAILABLE in reminder.text
    assert "#1 Открытый issue" in reminder.text  # issues секция не пострадала от сбоя в commits


async def test_github_api_error_logs_status_and_message(
    session, bot: Bot, dispatcher: Dispatcher, monkeypatch, caplog,
):
    """До этого фикса сбой GitHub API логировался только как безликий
    traceback (exc_info=True) — по факту первого реального прод-инцидента
    (issue #15: обе секции дайджеста ушли "недоступно" без единого
    отличимого следа в логах) добавлено явное HTTP-код/текст в само
    сообщение лога, не только в traceback."""
    admin = await _make_admin(session, 8113)
    monkeypatch.setattr(settings, "admin_ids", str(admin.telegram_id))
    request_info = aiohttp.RequestInfo(
        url=aiohttp.client.URL("https://api.github.com/repos/bimoool/pullup-trainer-bot/commits"),
        method="GET", headers={}, real_url=aiohttp.client.URL("https://api.github.com/repos/bimoool/pullup-trainer-bot/commits"),
    )
    fake_github = FakeGitHubClient(
        commits_error=aiohttp.ClientResponseError(
            request_info, history=(), status=401, message="Bad credentials",
        ),
        issues=[],
    )

    with caplog.at_level("WARNING"):
        await send_weekly_digest_reminder(bot, dispatcher, session=session, github_client=fake_github)

    [commits_log] = [r for r in caplog.records if "failed to fetch commits" in r.message]
    assert "401" in commits_log.message
    assert "Bad credentials" in commits_log.message


async def test_missing_github_token_logs_explanation(session, bot: Bot, dispatcher: Dispatcher, monkeypatch, caplog):
    """github_client не передан и GITHUB_TOKEN пуст (реальный прод-путь) —
    раньше этот случай не оставлял вообще никакого следа в логах,
    неотличимо от того, будто воркер не запускался. См. issue #15."""
    admin = await _make_admin(session, 8114)
    monkeypatch.setattr(settings, "admin_ids", str(admin.telegram_id))
    monkeypatch.setattr(settings, "github_token", "")

    with caplog.at_level("WARNING"):
        await send_weekly_digest_reminder(bot, dispatcher, session=session)

    assert any("GITHUB_TOKEN is not configured" in r.message for r in caplog.records)


async def test_first_reminder_uses_default_lookback_when_no_prior_digest(
    session, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    admin = await _make_admin(session, 8111)
    monkeypatch.setattr(settings, "admin_ids", str(admin.telegram_id))
    fake_github = FakeGitHubClient()
    before = datetime.now(UTC)

    await send_weekly_digest_reminder(bot, dispatcher, session=session, github_client=fake_github)

    assert fake_github.received_since is not None
    expected_earliest = before - timedelta(days=7, seconds=5)
    expected_latest = before - timedelta(days=7) + timedelta(seconds=5)
    assert expected_earliest <= fake_github.received_since <= expected_latest


async def test_subsequent_reminder_uses_last_digest_sent_at_as_since(
    session, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    admin = await _make_admin(session, 8112)
    monkeypatch.setattr(settings, "admin_ids", str(admin.telegram_id))
    previous_digest_at = datetime.now(UTC) - timedelta(days=3)
    await WeeklyDigestRepository(session).record(
        sent_at=previous_digest_at, text="Прошлый дайджест", recipients_count=5,
    )
    fake_github = FakeGitHubClient()

    await send_weekly_digest_reminder(bot, dispatcher, session=session, github_client=fake_github)

    assert fake_github.received_since == previous_digest_at
