"""WEB-AUTH: вход в браузере через бота (device-code) — backend и модель угроз.

HTTP идёт через настоящее приложение (app.web.main.app); БД — реальный Postgres; подтверждение со стороны бота
делается тем же сервисом, что вызывает хендлер (tests/test_bot/test_web_login.py проверяет сам хендлер)."""

import hashlib
import logging
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update

from app.config import settings
from app.db.models import User, WebLoginRequest, WebSession
from app.db.repositories.users import UserRepository
from app.services import web_login
from app.web import web_auth
from app.web.db import get_session
from app.web.main import app

TG = 42_001
SENTINEL = {"X-Telegram-Init-Data": "web-session"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "bot_username", "pullup_test_bot")
    monkeypatch.setattr(settings, "web_auth_cookie_secure", True)
    web_auth.poll_limiter.reset()
    web_auth.bad_poll_limiter.reset()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
async def client(session):
    async def _session():
        yield session

    app.dependency_overrides[get_session] = _session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        yield c


async def _new_request(client):
    r = await client.post("/api/web-auth/login-requests")
    assert r.status_code == 200, r.text
    return r.json()


def _poll(client, req, secret=None):
    headers = {"X-Web-Login-Secret": secret if secret is not None else req["browser_secret"]}
    return client.post(f"/api/web-auth/login-requests/{req['request_id']}/poll", headers=headers)


async def _approve(session, req, telegram_id=TG, first_name="Кирилл"):
    opened = await web_login.open_request(session, req["request_id"], telegram_id)
    assert opened.status == "ok"
    return await web_login.approve_request(
        session, req["request_id"], telegram_id=telegram_id, first_name=first_name, username="kir",
    )


async def _login(client, session, telegram_id=TG):
    req = await _new_request(client)
    assert await _approve(session, req, telegram_id)
    r = await _poll(client, req)
    assert r.json()["status"] == "signed_in"
    return req


# ---- создание запроса ------------------------------------------------------------------------------------------------

async def test_create_returns_code_secret_and_link_and_stores_only_hash(client, session):
    req = await _new_request(client)
    assert len(req["code"]) == 4 and req["code"].isdigit()
    assert len(req["request_id"]) == 32
    assert req["expires_in_seconds"] == 300
    assert req["bot_link"] == f"https://t.me/pullup_test_bot?start=weblogin_{req['request_id']}"
    row = (await session.execute(select(WebLoginRequest))).scalar_one()
    assert row.secret_hash == hashlib.sha256(req["browser_secret"].encode()).hexdigest()
    assert req["browser_secret"] not in {row.secret_hash, row.request_id, row.code}
    assert row.status == "pending"
    assert timedelta(minutes=4, seconds=59) < row.expires_at - row.created_at <= timedelta(minutes=5)


async def test_create_rate_limited_per_ip(client):
    for _ in range(web_login.MAX_REQUESTS_PER_IP_WINDOW):
        assert (await client.post("/api/web-auth/login-requests")).status_code == 200
    assert (await client.post("/api/web-auth/login-requests")).status_code == 429


# ---- полный путь, один и тот же аккаунт ----------------------------------------------------------------------------

async def test_full_flow_signs_in_same_account_and_never_duplicates_user(client, session):
    existing = await UserRepository(session).create(telegram_id=TG, username="kir")
    req = await _new_request(client)

    assert (await _poll(client, req)).json() == {"status": "pending", "first_name": None}

    assert await _approve(session, req)
    r = await _poll(client, req)
    assert r.status_code == 200 and r.json()["status"] == "signed_in"

    # Тот же пользователь, ни одного нового ряда.
    assert (await session.execute(select(func.count()).select_from(User).where(User.telegram_id == TG))).scalar_one() == 1
    sess = (await session.execute(select(WebSession))).scalar_one()
    assert sess.user_id == existing.id

    info = (await client.get("/api/web-auth/session")).json()
    assert info == {"authenticated": True, "first_name": "Кирилл"}
    hello = await client.get("/api/hello", headers=SENTINEL)
    assert hello.status_code == 200, hello.text
    assert hello.json()["name"] == "Кирилл"


async def test_approval_for_unknown_telegram_id_creates_exactly_one_user(client, session):
    req = await _new_request(client)
    assert await _approve(session, req, telegram_id=77_001)
    assert await web_login.approve_request(  # повторно не подтверждается и не создаёт второго
        session, req["request_id"], telegram_id=77_001, first_name="x", username=None) is False
    assert (await session.execute(select(func.count()).select_from(User).where(User.telegram_id == 77_001))).scalar_one() == 1


async def test_cookie_flags(client, session):
    req = await _new_request(client)
    await _approve(session, req)
    r = await _poll(client, req)
    cookie = r.headers["set-cookie"].lower()
    assert cookie.startswith("pullup_web_session=")
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    assert "max-age=2592000" in cookie  # абсолютный срок 30 дней


async def test_cookie_secure_can_be_disabled_for_local_http(client, session, monkeypatch):
    monkeypatch.setattr(settings, "web_auth_cookie_secure", False)
    req = await _new_request(client)
    await _approve(session, req)
    cookie = (await _poll(client, req)).headers["set-cookie"].lower()
    assert "secure" not in cookie.replace("samesite", "")


async def test_token_is_never_in_body_url_or_db_plaintext(client, session):
    req = await _new_request(client)
    await _approve(session, req)
    r = await _poll(client, req)
    token = client.cookies.get("pullup_web_session")
    assert token and token not in r.text and token not in str(r.url)
    sess = (await session.execute(select(WebSession))).scalar_one()
    assert sess.token_hash == hashlib.sha256(token.encode()).hexdigest() and sess.token_hash != token


# ---- единственное использование, истечение, секрет ------------------------------------------------------------------

async def test_single_use(client, session):
    req = await _new_request(client)
    await _approve(session, req)
    assert (await _poll(client, req)).json()["status"] == "signed_in"
    again = await _poll(client, req)
    assert again.json()["status"] == "expired"
    assert "set-cookie" not in again.headers
    assert (await session.execute(select(func.count()).select_from(WebSession))).scalar_one() == 1


async def test_wrong_missing_and_unknown_give_identical_404(client):
    req = await _new_request(client)
    wrong = await _poll(client, req, secret="not-the-secret")
    missing = await client.post(f"/api/web-auth/login-requests/{req['request_id']}/poll")
    unknown = await client.post(
        "/api/web-auth/login-requests/" + "0" * 32 + "/poll", headers={"X-Web-Login-Secret": req["browser_secret"]},
    )
    garbage = await client.post("/api/web-auth/login-requests/../poll", headers={"X-Web-Login-Secret": "x"})
    for r in (wrong, missing, unknown):
        assert r.status_code == 404 and r.json() == {"status": "not_found", "first_name": None}
    assert garbage.status_code in (404, 405)


async def test_wrong_secret_never_signs_in_even_when_approved(client, session):
    req = await _new_request(client)
    await _approve(session, req)
    assert (await _poll(client, req, secret="stolen-guess")).status_code == 404
    assert (await session.execute(select(func.count()).select_from(WebSession))).scalar_one() == 0


async def test_request_expiry_blocks_poll_and_approval(client, session):
    req = await _new_request(client)
    await session.execute(update(WebLoginRequest).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    assert (await _poll(client, req)).json()["status"] == "expired"
    assert (await web_login.open_request(session, req["request_id"], TG)).status == "gone"
    assert await web_login.approve_request(
        session, req["request_id"], telegram_id=TG, first_name="x", username=None) is False


async def test_approved_but_expired_request_does_not_sign_in(client, session):
    req = await _new_request(client)
    await _approve(session, req)
    await session.execute(update(WebLoginRequest).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    assert (await _poll(client, req)).json()["status"] == "expired"
    assert (await session.execute(select(func.count()).select_from(WebSession))).scalar_one() == 0


# ---- кто и сколько раз может подтвердить ------------------------------------------------------------------------------

async def test_cannot_approve_twice(client, session):
    req = await _new_request(client)
    assert await _approve(session, req)
    assert await web_login.approve_request(
        session, req["request_id"], telegram_id=TG, first_name="x", username=None) is False


async def test_only_the_user_who_opened_the_link_can_approve(client, session):
    req = await _new_request(client)
    assert (await web_login.open_request(session, req["request_id"], TG)).status == "ok"
    assert (await web_login.open_request(session, req["request_id"], TG + 1)).status == "taken"
    assert await web_login.approve_request(
        session, req["request_id"], telegram_id=TG + 1, first_name="Чужой", username=None) is False
    assert await web_login.deny_request(session, req["request_id"], telegram_id=TG + 1) is False
    row = (await session.execute(select(WebLoginRequest))).scalar_one()
    assert row.status == "pending" and row.telegram_id is None


async def test_approve_without_opening_the_link_fails(client, session):
    req = await _new_request(client)
    assert await web_login.approve_request(
        session, req["request_id"], telegram_id=TG, first_name="x", username=None) is False


async def test_deny_marks_request_and_blocks_later_approval(client, session):
    req = await _new_request(client)
    await web_login.open_request(session, req["request_id"], TG)
    assert await web_login.deny_request(session, req["request_id"], telegram_id=TG)
    assert (await _poll(client, req)).json()["status"] == "denied"
    assert await web_login.approve_request(
        session, req["request_id"], telegram_id=TG, first_name="x", username=None) is False
    assert (await session.execute(select(func.count()).select_from(WebSession))).scalar_one() == 0


async def test_cannot_deny_after_approval(client, session):
    req = await _new_request(client)
    await _approve(session, req)
    assert await web_login.deny_request(session, req["request_id"], telegram_id=TG) is False


async def test_malformed_request_id_in_bot_path_is_gone(session):
    for bad in ("", "xyz", "G" * 32, "a" * 31, "'; DROP TABLE users;--"):
        assert (await web_login.open_request(session, bad, TG)).status == "gone"


# ---- перебор -------------------------------------------------------------------------------------------------------------

async def test_per_request_lockout_after_bad_secrets(client, session):
    req = await _new_request(client)
    await _approve(session, req)
    for _ in range(web_login.MAX_BAD_SECRETS_PER_REQUEST):
        assert (await _poll(client, req, secret="guess")).status_code == 404
    # Даже верный секрет больше не работает: запрос заблокирован целиком.
    assert (await _poll(client, req)).status_code == 404
    assert (await session.execute(select(func.count()).select_from(WebSession))).scalar_one() == 0


async def test_per_ip_limit_on_bad_polls(client):
    reqs = [await _new_request(client) for _ in range(3)]
    statuses = []
    for i in range(web_auth.bad_poll_limiter.limit + 3):
        statuses.append((await _poll(client, reqs[i % 3], secret="guess")).status_code)
    assert statuses[0] == 404 and statuses[-1] == 429


async def test_per_ip_poll_rate_limit(client, monkeypatch):
    monkeypatch.setattr(web_auth, "poll_limiter", web_auth.SlidingWindowLimiter(limit=3, window_seconds=60))
    req = await _new_request(client)
    codes = [(await _poll(client, req)).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3:] == [429, 429]


async def test_per_request_poll_cap(client, session, monkeypatch):
    monkeypatch.setattr(web_login, "MAX_POLLS_PER_REQUEST", 2)
    req = await _new_request(client)
    codes = [(await _poll(client, req)).status_code for _ in range(4)]
    assert codes == [200, 200, 429, 429]


# ---- сессии ---------------------------------------------------------------------------------------------------------------

async def test_logout_revokes_session_and_clears_cookie(client, session):
    await _login(client, session)
    r = await client.post("/api/web-auth/logout", headers=SENTINEL)
    assert r.status_code == 200
    assert "max-age=0" in r.headers["set-cookie"].lower() or "expires=" in r.headers["set-cookie"].lower()
    sess = (await session.execute(select(WebSession))).scalar_one()
    assert sess.revoked_at is not None
    assert (await client.get("/api/hello", headers=SENTINEL)).status_code == 401
    assert (await client.get("/api/web-auth/session")).json() == {"authenticated": False, "first_name": None}


async def test_revoked_token_is_rejected_even_if_replayed(client, session):
    await _login(client, session)
    stolen = client.cookies.get("pullup_web_session")
    await client.post("/api/web-auth/logout", headers=SENTINEL)
    client.cookies.clear()
    client.cookies.set("pullup_web_session", stolen)
    assert (await client.get("/api/hello", headers=SENTINEL)).status_code == 401


async def test_logout_requires_the_custom_header(client, session):
    await _login(client, session)
    assert (await client.post("/api/web-auth/logout")).status_code == 403
    sess = (await session.execute(select(WebSession))).scalar_one()
    assert sess.revoked_at is None


async def test_logout_all_revokes_every_session_of_the_user(client, session):
    await _login(client, session)
    other = await UserRepository(session).get_by_telegram_id(TG)
    await web_login.create_session(session, user_id=other.id, first_name=None, user_agent="b", ip_prefix=None)
    assert (await client.post("/api/web-auth/logout-all", headers=SENTINEL)).status_code == 200
    rows = (await session.execute(select(WebSession))).scalars().all()
    assert len(rows) == 2 and all(r.revoked_at is not None for r in rows)


async def test_idle_expiry_after_14_days(client, session):
    await _login(client, session)
    await session.execute(update(WebSession).values(last_seen_at=datetime.now(UTC) - timedelta(days=14, minutes=1)))
    assert (await client.get("/api/hello", headers=SENTINEL)).status_code == 401


async def test_activity_inside_idle_window_keeps_session_alive(client, session):
    await _login(client, session)
    await session.execute(update(WebSession).values(last_seen_at=datetime.now(UTC) - timedelta(days=13)))
    assert (await client.get("/api/hello", headers=SENTINEL)).status_code == 200
    sess = (await session.execute(select(WebSession).execution_options(populate_existing=True))).scalar_one()
    assert datetime.now(UTC) - sess.last_seen_at < timedelta(minutes=1)


async def test_absolute_expiry_after_30_days_even_when_active(client, session):
    await _login(client, session)
    await session.execute(update(WebSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    assert (await client.get("/api/hello", headers=SENTINEL)).status_code == 401


async def test_deleted_user_session_is_rejected(client, session):
    await _login(client, session)
    user = await UserRepository(session).get_by_telegram_id(TG)
    await session.delete(user)
    await session.flush()
    assert (await client.get("/api/hello", headers=SENTINEL)).status_code == 401
    assert (await client.get("/api/web-auth/session")).json()["authenticated"] is False


async def test_session_does_not_leak_to_another_user(client, session):
    await _login(client, session, telegram_id=TG)
    await UserRepository(session).create(telegram_id=TG + 5, username="other")
    hello = await client.get("/api/hello", headers=SENTINEL)
    assert hello.json()["name"] == "Кирилл"  # имя именно этой сессии


# ---- sentinel / CSRF / CORS ----------------------------------------------------------------------------------------------

async def test_sentinel_without_cookie_is_401(client):
    r = await client.get("/api/hello", headers=SENTINEL)
    assert r.status_code == 401


async def test_sentinel_with_garbage_cookie_is_401(client):
    client.cookies.set("pullup_web_session", "not-a-real-token")
    assert (await client.get("/api/hello", headers=SENTINEL)).status_code == 401


async def test_cookie_alone_without_header_is_rejected(client, session):
    await _login(client, session)
    r = await client.get("/api/hello")  # без X-Telegram-Init-Data (как кросс-сайтовый запрос)
    assert r.status_code in (401, 422)


async def test_cookie_with_forged_non_sentinel_header_is_401(client, session):
    await _login(client, session)
    r = await client.get("/api/hello", headers={"X-Telegram-Init-Data": "user=%7B%22id%22%3A1%7D&hash=00"})
    assert r.status_code == 401


async def test_no_permissive_cors(client):
    r = await client.options(
        "/api/hello",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET",
                 "Access-Control-Request-Headers": "x-telegram-init-data"},
    )
    assert "access-control-allow-origin" not in r.headers
    r2 = await client.get("/api/web-auth/session", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r2.headers
    assert not any(type(m).__name__ == "CORSMiddleware" or getattr(m, "cls", None).__name__ == "CORSMiddleware"
                   for m in app.user_middleware)


# ---- журналы -------------------------------------------------------------------------------------------------------------

async def test_no_secret_or_token_in_logs(client, session, caplog):
    caplog.set_level(logging.DEBUG)
    req = await _new_request(client)
    await _approve(session, req)
    await _poll(client, req)
    token = client.cookies.get("pullup_web_session")
    await client.get("/api/hello", headers=SENTINEL)
    await _poll(client, req, secret="wrong-secret-xyz")
    blob = caplog.text
    for secret in (req["browser_secret"], token, "wrong-secret-xyz"):
        assert secret not in blob


# ---- тестовый вход: строго закрыт ---------------------------------------------------------------------------------------

def _has_route(a, path):
    return any(getattr(r, "path", None) == path for r in a.routes) or any(
        getattr(sub, "path", None) == path for r in a.routes for sub in getattr(getattr(r, "original_router", None), "routes", [])
    )


async def test_test_login_route_is_absent_by_default(client):
    assert settings.web_auth_test_login is False
    r = await client.post("/api/web-auth/test-login", json={"telegram_id": TG})
    assert r.status_code in (404, 405)
    assert not _has_route(app, "/api/web-auth/test-login")


@pytest.mark.parametrize(("flag", "token", "registered"), [
    (False, "e2e-test-token", False),
    (True, "123456:real-looking-token", False),
    (True, "e2e-test-token", True),
])
def test_test_login_registration_needs_both_flag_and_e2e_token(monkeypatch, flag, token, registered):
    monkeypatch.setattr(settings, "web_auth_test_login", flag)
    monkeypatch.setattr(settings, "bot_token", token)
    fresh = FastAPI()
    web_auth.register_web_auth(fresh)
    assert _has_route(fresh, "/api/web-auth/test-login") is registered


async def test_test_login_is_rechecked_at_request_time(session, monkeypatch):
    monkeypatch.setattr(settings, "web_auth_test_login", True)
    monkeypatch.setattr(settings, "bot_token", "e2e-test-token")
    fresh = FastAPI()
    web_auth.register_web_auth(fresh)

    async def _session():
        yield session

    fresh.dependency_overrides[get_session] = _session
    async with AsyncClient(transport=ASGITransport(app=fresh), base_url="https://test") as c:
        ok = await c.post("/api/web-auth/test-login", json={"telegram_id": TG})
        assert ok.status_code == 200 and "pullup_web_session" in ok.headers["set-cookie"]
        monkeypatch.setattr(settings, "bot_token", "something-else")
        assert (await c.post("/api/web-auth/test-login", json={"telegram_id": TG})).status_code == 404
        monkeypatch.setattr(settings, "bot_token", "e2e-test-token")
        monkeypatch.setattr(settings, "web_auth_test_login", False)
        assert (await c.post("/api/web-auth/test-login", json={"telegram_id": TG})).status_code == 404


def test_test_login_is_not_enabled_in_deploy_files():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    for f in list(root.glob("docker-compose*.y*ml")) + list((root / "deploy").rglob("*")):
        if f.is_file():
            assert "WEB_AUTH_TEST_LOGIN" not in f.read_text(errors="ignore"), f
