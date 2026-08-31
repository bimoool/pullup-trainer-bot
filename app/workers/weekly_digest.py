import logging
from datetime import UTC, datetime, timedelta

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.states import AdminStates
from app.config import settings
from app.db.base import async_session_factory
from app.db.repositories.weekly_digests import WeeklyDigestRepository
from app.services.github import GitHubClient, GitHubClientProtocol, IssueSummary

logger = logging.getLogger(__name__)

JOB_ID = "weekly_digest_reminder"

GITHUB_OWNER = "bimoool"
GITHUB_REPO = "pullup-trainer-bot"
# Без единой прошлой рассылки (WeeklyDigestRepository.get_last_sent_at()
# вернул None — самый первый прогон воркера) диапазон "что раскатили"
# берём за последнюю неделю, тем же интервалом, что и сама рассылка,
# не глубже.
DEFAULT_LOOKBACK_DAYS = 7
MAX_COMMITS_SHOWN = 20
MAX_ISSUES_SHOWN = 20


async def _build_commits_section(client: GitHubClientProtocol, since: datetime) -> str:
    try:
        commits = await client.list_commits_since(since)
    except aiohttp.ClientResponseError as exc:
        logger.warning(
            "weekly_digest: failed to fetch commits — GitHub HTTP %s: %s",
            exc.status, exc.message,
        )
        return texts.ADMIN_WEEKLY_DIGEST_COMMITS_UNAVAILABLE
    except (aiohttp.ClientError, TimeoutError) as exc:
        logger.warning(
            "weekly_digest: failed to fetch commits — %s: %s", type(exc).__name__, exc,
        )
        return texts.ADMIN_WEEKLY_DIGEST_COMMITS_UNAVAILABLE
    if not commits:
        return texts.ADMIN_WEEKLY_DIGEST_COMMITS_EMPTY
    lines = [f"• {commit.message}" for commit in commits[:MAX_COMMITS_SHOWN]]
    if len(commits) > MAX_COMMITS_SHOWN:
        lines.append(f"… и ещё {len(commits) - MAX_COMMITS_SHOWN}")
    return texts.ADMIN_WEEKLY_DIGEST_COMMITS_HEADER.format(commits="\n".join(lines))


def _format_issue_line(issue: IssueSummary) -> str:
    if issue.labels:
        return f"• #{issue.number} {issue.title} ({', '.join(issue.labels)})"
    return f"• #{issue.number} {issue.title}"


async def _build_issues_section(client: GitHubClientProtocol) -> str:
    try:
        issues = await client.list_open_issues()
    except aiohttp.ClientResponseError as exc:
        logger.warning(
            "weekly_digest: failed to fetch issues — GitHub HTTP %s: %s",
            exc.status, exc.message,
        )
        return texts.ADMIN_WEEKLY_DIGEST_ISSUES_UNAVAILABLE
    except (aiohttp.ClientError, TimeoutError) as exc:
        logger.warning(
            "weekly_digest: failed to fetch issues — %s: %s", type(exc).__name__, exc,
        )
        return texts.ADMIN_WEEKLY_DIGEST_ISSUES_UNAVAILABLE
    if not issues:
        return texts.ADMIN_WEEKLY_DIGEST_ISSUES_EMPTY
    lines = [_format_issue_line(issue) for issue in issues[:MAX_ISSUES_SHOWN]]
    if len(issues) > MAX_ISSUES_SHOWN:
        lines.append(f"… и ещё {len(issues) - MAX_ISSUES_SHOWN}")
    return texts.ADMIN_WEEKLY_DIGEST_ISSUES_HEADER.format(issues="\n".join(lines))


async def _build_reminder_text(github_client: GitHubClientProtocol | None, since: datetime) -> str:
    """github_client=None — GITHUB_TOKEN не настроен (settings.github_token
    пуст): обе секции показывают "недоступно" без единого сетевого запроса,
    остальной воркер (напоминание, приём ответа, рассылка) работает как
    обычно, тем же принципом, что Robokassa при отсутствующих ключах.

    До этого фикса этот путь не логировал вообще ничего — "недоступно" в
    сообщении админу выглядело неотличимо от реального сбоя сети/GitHub
    API, хотя причина совсем другая (не настроен .env на сервере) и не
    требует расследования HTTP-ответов."""
    if github_client is None:
        logger.warning(
            "weekly_digest: GITHUB_TOKEN is not configured, commits/issues sections skipped",
        )
        return (
            texts.ADMIN_WEEKLY_DIGEST_REMINDER
            + texts.ADMIN_WEEKLY_DIGEST_COMMITS_UNAVAILABLE
            + texts.ADMIN_WEEKLY_DIGEST_ISSUES_UNAVAILABLE
        )
    commits_section = await _build_commits_section(github_client, since)
    issues_section = await _build_issues_section(github_client)
    return texts.ADMIN_WEEKLY_DIGEST_REMINDER + commits_section + issues_section


async def _resolve_lookback_since(session: AsyncSession, now: datetime) -> datetime:
    last_sent_at = await WeeklyDigestRepository(session).get_last_sent_at()
    return last_sent_at or (now - timedelta(days=DEFAULT_LOOKBACK_DAYS))


async def send_weekly_digest_reminder(
    bot: Bot,
    dispatcher: Dispatcher,
    *,
    github_client: GitHubClientProtocol | None = None,
    session: AsyncSession | None = None,
) -> None:
    """Не рассылка сама по себе — только напоминание админу(ам) её
    написать, дополненное автосбором "что раскатили" (коммиты с прошлой
    рассылки) и "что в работе" (открытые issues) через GitHub REST API —
    процесс бота на сервере не имеет ни .git, ни gh CLI (деплой-образ
    копирует только app/, см. CLAUDE.md), поэтому только живой HTTP.

    Ответ на напоминание приходит обычным сообщением в чат с ботом и
    ловится handle_weekly_digest_reply (app/bot/handlers/admin.py) через
    FSM-состояние AdminStates.waiting_for_weekly_digest_text, выставленное
    здесь программно (не через колбэк — тут нет входящего Update, только
    сработавший таймер): это и есть привязка ответа именно к ЭТОМУ
    напоминанию, не к случайному сообщению боту. weekly_digest_reminder_
    sent_at в данных состояния — момент отправки, от него хендлер
    отсчитывает WEEKLY_DIGEST_REPLY_DEADLINE_HOURS при получении ответа.

    dispatcher.fsm.get_context(bot=..., chat_id=..., user_id=...) — тот
    же способ получить FSMContext вне живого Update, что использует
    tests/test_bot/conftest.py для прямой проверки состояния в тестах;
    здесь тот же приём применяется по-настоящему, не только в тестах.

    github_client — параметр только для тестов (подмена реального
    GitHubClient фейком без сети, тот же приём, что RobokassaService
    принимает RobokassaClientProtocol); в бою всегда строится здесь же
    из settings.github_token. session — тем же принципом: тесты передают
    свою сессию (тестовую БД), в бою здесь же открывается своя через
    async_session_factory (тот же паттерн, что sync_robokassa_payments) —
    без инъекции воркер соединялся бы напрямую с DATABASE_URL из .env в
    обход тестовой БД, чего тесты не могут допустить."""
    now = datetime.now(UTC)

    if session is not None:
        since = await _resolve_lookback_since(session, now)
    else:
        async with async_session_factory() as db_session:
            since = await _resolve_lookback_since(db_session, now)

    if github_client is None and settings.github_token:
        github_client = GitHubClient(token=settings.github_token, owner=GITHUB_OWNER, repo=GITHUB_REPO)
    reminder_text = await _build_reminder_text(github_client, since)

    for admin_id in settings.admin_id_list:
        try:
            await bot.send_message(admin_id, reminder_text)
        except TelegramAPIError:
            logger.warning("weekly_digest: failed to send reminder to admin %s", admin_id, exc_info=True)
            continue

        fsm = dispatcher.fsm.get_context(bot=bot, chat_id=admin_id, user_id=admin_id)
        await fsm.set_state(AdminStates.waiting_for_weekly_digest_text)
        await fsm.update_data(weekly_digest_reminder_sent_at=now.isoformat())
        logger.info("weekly_digest: reminder sent to admin %s", admin_id)


def register(scheduler: AsyncIOScheduler, bot: Bot, dispatcher: Dispatcher) -> None:
    # Воскресенье, 18:00 UTC (~21:00 по Москве) — "вечер воскресенья" перед
    # началом рабочей недели пользователей.
    scheduler.add_job(
        send_weekly_digest_reminder, CronTrigger(day_of_week="sun", hour=18),
        id=JOB_ID, kwargs={"bot": bot, "dispatcher": dispatcher},
    )
