"""Вход в браузере через бота (WEB-AUTH): запросы входа (device-code) и браузерные сессии.

Модель угроз — в docs/audit/ux-ref-20261018/checkpoints/WEB-AUTH.md. Главное:
- секрет браузера и токен сессии в БД только как SHA-256; сравнение — compare_digest;
- каждый переход статуса — один условный UPDATE ... WHERE status=... RETURNING (атомарно, без гонок двойного
  подтверждения / двойного использования);
- подтверждает только пользователь Telegram, первым открывший ссылку (telegram_id берётся из callback.from_user).
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import User, WebLoginRequest, WebSession
from app.db.repositories.users import UserRepository

REQUEST_TTL = timedelta(minutes=5)
SESSION_IDLE_TTL = timedelta(days=14)
SESSION_ABSOLUTE_TTL = timedelta(days=30)
SESSION_TOUCH_INTERVAL = timedelta(seconds=60)

MAX_BAD_SECRETS_PER_REQUEST = 5
MAX_POLLS_PER_REQUEST = 400
IP_WINDOW = timedelta(minutes=10)

START_PAYLOAD_PREFIX = "weblogin_"
REQUEST_ID_HEX_LEN = 32


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def is_valid_request_id(value: str) -> bool:
    return len(value) == REQUEST_ID_HEX_LEN and all(c in "0123456789abcdef" for c in value)


@dataclass(frozen=True)
class CreatedLoginRequest:
    request_id: str
    browser_secret: str
    code: str
    expires_at: datetime


class RateLimited(Exception):
    pass


async def create_login_request(
    session: AsyncSession, *, ip_prefix: str | None, now: datetime | None = None,
) -> CreatedLoginRequest:
    now = now or datetime.now(UTC)
    if ip_prefix is not None:
        recent = (await session.execute(
            select(WebLoginRequest.id).where(
                WebLoginRequest.ip_prefix == ip_prefix, WebLoginRequest.created_at >= now - IP_WINDOW,
            ).limit(settings.web_auth_ip_request_limit)
        )).all()
        if len(recent) >= settings.web_auth_ip_request_limit:
            raise RateLimited
    request_id = secrets.token_hex(16)
    browser_secret = secrets.token_urlsafe(32)
    code = f"{secrets.randbelow(10000):04d}"
    expires_at = now + REQUEST_TTL
    session.add(WebLoginRequest(
        request_id=request_id, secret_hash=sha256_hex(browser_secret), code=code, status="pending",
        ip_prefix=ip_prefix, created_at=now, expires_at=expires_at,
    ))
    await session.flush()
    return CreatedLoginRequest(request_id, browser_secret, code, expires_at)


async def _get_request(session: AsyncSession, request_id: str) -> WebLoginRequest | None:
    if not is_valid_request_id(request_id):
        return None
    return (await session.execute(
        select(WebLoginRequest).where(WebLoginRequest.request_id == request_id)
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()


# ---- сторона бота -------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class OpenResult:
    status: str  # ok | gone | taken
    code: str | None = None


async def open_request(session: AsyncSession, request_id: str, telegram_id: int, now: datetime | None = None) -> OpenResult:
    """/start weblogin_<id>: привязать запрос к первому открывшему. Чужой повторный заход — taken."""
    now = now or datetime.now(UTC)
    if not is_valid_request_id(request_id):
        return OpenResult("gone")
    row = (await session.execute(
        update(WebLoginRequest)
        .where(
            WebLoginRequest.request_id == request_id, WebLoginRequest.status == "pending",
            WebLoginRequest.expires_at > now,
            (WebLoginRequest.opened_by_telegram_id.is_(None)) | (WebLoginRequest.opened_by_telegram_id == telegram_id),
        )
        .values(opened_by_telegram_id=telegram_id)
        .returning(WebLoginRequest.code)
    )).first()
    if row is not None:
        return OpenResult("ok", row[0])
    existing = await _get_request(session, request_id)
    if existing is not None and existing.status == "pending" and existing.expires_at > now:
        return OpenResult("taken")
    return OpenResult("gone")


async def approve_request(
    session: AsyncSession, request_id: str, *, telegram_id: int, first_name: str | None, username: str | None,
    now: datetime | None = None,
) -> bool:
    """Подтверждение: telegram_id — ТОЛЬКО из callback.from_user. True — подтверждено сейчас; False — уже
    обработан / истёк / открыт другим пользователем. Пользователь get-or-create по telegram_id (как /start)."""
    now = now or datetime.now(UTC)
    if not is_valid_request_id(request_id):
        return False
    users = UserRepository(session)
    if await users.get_by_telegram_id(telegram_id) is None:
        await users.create(telegram_id=telegram_id, username=username)
    row = (await session.execute(
        update(WebLoginRequest)
        .where(
            WebLoginRequest.request_id == request_id, WebLoginRequest.status == "pending",
            WebLoginRequest.expires_at > now, WebLoginRequest.opened_by_telegram_id == telegram_id,
        )
        .values(status="approved", telegram_id=telegram_id, first_name=first_name, approved_at=now)
        .returning(WebLoginRequest.id)
    )).first()
    return row is not None


async def deny_request(session: AsyncSession, request_id: str, *, telegram_id: int, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    if not is_valid_request_id(request_id):
        return False
    row = (await session.execute(
        update(WebLoginRequest)
        .where(
            WebLoginRequest.request_id == request_id, WebLoginRequest.status == "pending",
            WebLoginRequest.opened_by_telegram_id == telegram_id,
        )
        .values(status="denied")
        .returning(WebLoginRequest.id)
    )).first()
    return row is not None


# ---- сторона браузера ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class PollResult:
    status: str  # not_found | pending | denied | expired | signed_in | too_many
    session_token: str | None = None


async def poll_request(
    session: AsyncSession, request_id: str, browser_secret: str | None, *,
    user_agent: str | None, ip_prefix: str | None, now: datetime | None = None,
) -> PollResult:
    now = now or datetime.now(UTC)
    req = await _get_request(session, request_id)
    if req is None or not browser_secret:
        return PollResult("not_found")
    if req.status == "locked":
        return PollResult("not_found")
    if not hmac.compare_digest(req.secret_hash, sha256_hex(browser_secret)):
        # Неверный секрет: считаем попытки на запрос; после порога запрос блокируется целиком.
        bad = (await session.execute(
            update(WebLoginRequest).where(WebLoginRequest.id == req.id)
            .values(bad_secret_count=WebLoginRequest.bad_secret_count + 1)
            .returning(WebLoginRequest.bad_secret_count)
        )).scalar_one()
        if bad >= MAX_BAD_SECRETS_PER_REQUEST:
            await session.execute(
                update(WebLoginRequest).where(WebLoginRequest.id == req.id, WebLoginRequest.status != "consumed")
                .values(status="locked")
            )
        return PollResult("not_found")
    polls = (await session.execute(
        update(WebLoginRequest).where(WebLoginRequest.id == req.id)
        .values(poll_count=WebLoginRequest.poll_count + 1).returning(WebLoginRequest.poll_count)
    )).scalar_one()
    if polls > MAX_POLLS_PER_REQUEST:
        return PollResult("too_many")
    if req.status == "denied":
        return PollResult("denied")
    if req.status == "consumed" or req.expires_at <= now:
        return PollResult("expired")
    if req.status != "approved":
        return PollResult("pending")
    # Атомарное единовременное потребление.
    claimed = (await session.execute(
        update(WebLoginRequest)
        .where(WebLoginRequest.id == req.id, WebLoginRequest.status == "approved", WebLoginRequest.expires_at > now)
        .values(status="consumed", consumed_at=now)
        .returning(WebLoginRequest.telegram_id, WebLoginRequest.first_name)
    )).first()
    if claimed is None:
        return PollResult("expired")
    user = await UserRepository(session).get_by_telegram_id(claimed[0])
    if user is None:
        return PollResult("expired")
    token = await create_session(session, user_id=user.id, first_name=claimed[1], user_agent=user_agent,
                                 ip_prefix=ip_prefix, now=now)
    return PollResult("signed_in", token)


# ---- сессии -------------------------------------------------------------------------------------------------------

async def create_session(
    session: AsyncSession, *, user_id: int, first_name: str | None, user_agent: str | None, ip_prefix: str | None,
    now: datetime | None = None,
) -> str:
    now = now or datetime.now(UTC)
    token = secrets.token_urlsafe(32)
    session.add(WebSession(
        user_id=user_id, token_hash=sha256_hex(token), first_name=first_name, created_at=now, last_seen_at=now,
        expires_at=now + SESSION_ABSOLUTE_TTL,
        user_agent_hash=sha256_hex(user_agent) if user_agent else None, ip_prefix=ip_prefix,
    ))
    await session.flush()
    return token


@dataclass(frozen=True)
class ResolvedSession:
    session_id: int
    user_id: int
    telegram_id: int
    first_name: str | None


async def resolve_session(session: AsyncSession, token: str | None, now: datetime | None = None) -> ResolvedSession | None:
    """None — нет/неверный/отозван/истёк (idle или absolute) / пользователь удалён."""
    if not token:
        return None
    now = now or datetime.now(UTC)
    row = (await session.execute(
        select(WebSession, User)
        .join(User, User.id == WebSession.user_id)
        .where(WebSession.token_hash == sha256_hex(token))
        .execution_options(populate_existing=True)
    )).first()
    if row is None:
        return None
    web_session, user = row
    if web_session.revoked_at is not None or web_session.expires_at <= now:
        return None
    if now - web_session.last_seen_at >= SESSION_IDLE_TTL:
        return None
    if now - web_session.last_seen_at >= SESSION_TOUCH_INTERVAL:
        web_session.last_seen_at = now
        await session.flush()
    return ResolvedSession(web_session.id, user.id, user.telegram_id, web_session.first_name or user.username)


async def revoke_session(session: AsyncSession, token: str | None, now: datetime | None = None) -> None:
    if not token:
        return
    now = now or datetime.now(UTC)
    await session.execute(
        update(WebSession).where(WebSession.token_hash == sha256_hex(token), WebSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )


async def revoke_all_sessions(session: AsyncSession, user_id: int, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    await session.execute(
        update(WebSession).where(WebSession.user_id == user_id, WebSession.revoked_at.is_(None)).values(revoked_at=now)
    )
