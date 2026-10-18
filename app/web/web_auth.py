"""Вход в браузере через бота (WEB-AUTH): эндпоинты /api/web-auth/*, cookie-сессия и зависимость для auth.py.

Схема и модель угроз — docs/audit/ux-ref-20261018/checkpoints/WEB-AUTH.md. Коротко: браузер создаёт запрос входа,
получает секрет (только он) и 4-значный код; пользователь подтверждает в боте; опрос браузера атомарно меняет
подтверждённый запрос на cookie-сессию. Остальные эндпоинты не меняются: фронтенд шлёт X-Telegram-Init-Data:
web-session, а app.web.auth.get_validated_init_data принимает этот маркер только вместе с действующей cookie.
"""

import ipaddress
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Annotated

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)
from pydantic import BaseModel

from app.config import settings
from app.db.repositories.users import UserRepository
from app.services import web_login
from app.web.db import get_session

logger = logging.getLogger(__name__)

SESSION_COOKIE = "pullup_web_session"
SESSION_SENTINEL = "web-session"
SECRET_HEADER = "X-Web-Login-Secret"
TEST_LOGIN_BOT_TOKEN = "e2e-test-token"
POLL_INTERVAL_SECONDS = 2


# ---- cookie-сессия как зависимость для auth.py --------------------------------------------------------------------

@dataclass(frozen=True)
class WebUser:
    id: int
    first_name: str | None = None


@dataclass(frozen=True)
class WebInitData:
    """Совместим с тем, что маршруты читают из InitData: init_data.user.id / .first_name."""

    user: WebUser


async def resolve_web_session(
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    db=Depends(get_session, scope="function"),
) -> WebInitData | None:
    resolved = await web_login.resolve_session(db, session_token)
    if resolved is None:
        return None
    return WebInitData(user=WebUser(id=resolved.telegram_id, first_name=resolved.first_name))


# ---- лимиты (в памяти процесса; запросы входа дополнительно ограничены по IP в БД) ---------------------------------

class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()


poll_limiter = SlidingWindowLimiter(limit=settings.web_auth_ip_poll_limit, window_seconds=60)
bad_poll_limiter = SlidingWindowLimiter(limit=settings.web_auth_ip_bad_poll_limit, window_seconds=600)


def client_ip_prefix(request: Request) -> str | None:
    raw = request.headers.get("x-real-ip") if settings.web_auth_trusted_proxy else None
    if not raw and request.client:
        raw = request.client.host
    if not raw:
        return None
    try:
        ip = ipaddress.ip_address(raw.strip())
    except ValueError:
        return None
    net = ipaddress.ip_network(f"{ip}/{24 if ip.version == 4 else 64}", strict=False)
    return str(net)


# ---- username бота ------------------------------------------------------------------------------------------------

_cached_bot_username: str | None = None


async def get_bot_username() -> str | None:
    global _cached_bot_username
    if settings.bot_username:
        return settings.bot_username.lstrip("@")
    if _cached_bot_username:
        return _cached_bot_username
    try:
        from aiogram import Bot

        bot = Bot(token=settings.bot_token)
        try:
            me = await bot.get_me()
        finally:
            await bot.session.close()
        _cached_bot_username = me.username
    except Exception:  # noqa: BLE001 - сеть/токен: ссылка просто не показывается, вход по коду остаётся описанным в UI
        logger.warning("web-auth: не удалось определить username бота (getMe)")
        return None
    return _cached_bot_username


# ---- cookie --------------------------------------------------------------------------------------------------------

def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, token, max_age=int(web_login.SESSION_ABSOLUTE_TTL.total_seconds()), path="/",
        httponly=True, secure=settings.web_auth_cookie_secure, samesite="lax",
    )


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE, path="/", httponly=True, secure=settings.web_auth_cookie_secure, samesite="lax",
    )


def _require_sentinel(x_telegram_init_data: str | None) -> None:
    """CSRF: кросс-сайтовая форма/img не может выставить кастомный заголовок, а CORS не настроен."""
    if x_telegram_init_data != SESSION_SENTINEL:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing session header")


# ---- API -----------------------------------------------------------------------------------------------------------

router = APIRouter(prefix="/api/web-auth", tags=["web-auth"])


class LoginRequestResponse(BaseModel):
    request_id: str
    browser_secret: str
    code: str
    expires_in_seconds: int
    poll_interval_seconds: int
    bot_link: str | None


class PollResponse(BaseModel):
    status: str
    first_name: str | None = None


class SessionResponse(BaseModel):
    authenticated: bool
    first_name: str | None = None


@router.post("/login-requests", response_model=LoginRequestResponse)
async def create_login_request(request: Request, db=Depends(get_session, scope="function")) -> LoginRequestResponse:
    try:
        created = await web_login.create_login_request(db, ip_prefix=client_ip_prefix(request))
    except web_login.RateLimited:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limited") from None
    username = await get_bot_username()
    link = f"https://t.me/{username}?start={web_login.START_PAYLOAD_PREFIX}{created.request_id}" if username else None
    return LoginRequestResponse(
        request_id=created.request_id, browser_secret=created.browser_secret, code=created.code,
        expires_in_seconds=int(web_login.REQUEST_TTL.total_seconds()), poll_interval_seconds=POLL_INTERVAL_SECONDS,
        bot_link=link,
    )


@router.post("/login-requests/{request_id}/poll", response_model=PollResponse)
async def poll_login_request(
    request_id: str, request: Request, response: Response,
    x_web_login_secret: Annotated[str | None, Header()] = None,
    db=Depends(get_session, scope="function"),
) -> PollResponse:
    ip = client_ip_prefix(request) or "unknown"
    if not poll_limiter.allow(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limited")
    result = await web_login.poll_request(
        db, request_id, x_web_login_secret,
        user_agent=request.headers.get("user-agent"), ip_prefix=client_ip_prefix(request),
    )
    if result.status == "not_found":
        # Единый ответ для «нет такого запроса» и «неверный секрет» — существование не раскрывается.
        if not bad_poll_limiter.allow(ip):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limited")
        # not_found не должен откатывать счётчик неверных попыток: возвращаем ответ, а не исключение.
        response.status_code = status.HTTP_404_NOT_FOUND
        return PollResponse(status="not_found")
    if result.status == "too_many":
        response.status_code = status.HTTP_429_TOO_MANY_REQUESTS
        return PollResponse(status="too_many")
    if result.status == "signed_in" and result.session_token:
        _set_cookie(response, result.session_token)
        return PollResponse(status="signed_in")
    return PollResponse(status=result.status)


@router.get("/session", response_model=SessionResponse)
async def get_session_info(
    web_user: WebInitData | None = Depends(resolve_web_session),
) -> SessionResponse:
    if web_user is None:
        return SessionResponse(authenticated=False)
    return SessionResponse(authenticated=True, first_name=web_user.user.first_name)


@router.post("/logout")
async def logout(
    response: Response,
    x_telegram_init_data: Annotated[str | None, Header()] = None,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    db=Depends(get_session, scope="function"),
) -> dict[str, bool]:
    _require_sentinel(x_telegram_init_data)
    await web_login.revoke_session(db, session_token)
    _clear_cookie(response)
    return {"ok": True}


@router.post("/logout-all")
async def logout_all(
    response: Response,
    x_telegram_init_data: Annotated[str | None, Header()] = None,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    db=Depends(get_session, scope="function"),
) -> dict[str, bool]:
    _require_sentinel(x_telegram_init_data)
    resolved = await web_login.resolve_session(db, session_token)
    if resolved is not None:
        await web_login.revoke_all_sessions(db, resolved.user_id)
    _clear_cookie(response)
    return {"ok": True}


# ---- тестовый вход (строго закрыт) --------------------------------------------------------------------------------

def e2e_login_enabled() -> bool:
    """Проверяется на КАЖДЫЙ запрос, не только при регистрации: оба условия обязательны."""
    return bool(settings.web_auth_test_login) and settings.bot_token == TEST_LOGIN_BOT_TOKEN


e2e_login_router = APIRouter(prefix="/api/web-auth", tags=["web-auth-test"])


class E2ELoginRequest(BaseModel):
    telegram_id: int


@e2e_login_router.post("/test-login", response_model=SessionResponse)
async def e2e_login(
    payload: E2ELoginRequest, request: Request, response: Response, db=Depends(get_session, scope="function"),
) -> SessionResponse:
    if not e2e_login_enabled():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    users = UserRepository(db)
    user = await users.get_by_telegram_id(payload.telegram_id)
    if user is None:
        user = await users.create(telegram_id=payload.telegram_id, username=None)
    token = await web_login.create_session(
        db, user_id=user.id, first_name=user.username, user_agent=request.headers.get("user-agent"),
        ip_prefix=client_ip_prefix(request),
    )
    _set_cookie(response, token)
    return SessionResponse(authenticated=True, first_name=user.username)


def register_web_auth(app: FastAPI) -> None:
    app.include_router(router)
    if e2e_login_enabled():
        app.include_router(e2e_login_router)
