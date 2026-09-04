"""GET /api/subscription + POST /api/subscription/pay — раздел подписки/
оплаты Mini App (issue #53, волна 1): те же RobokassaService/
SubscriptionService и тот же format_subscription_status/PRICING_TEXT, что
уже использует бот, не отдельная реализация."""

from dataclasses import dataclass
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient

from app.bot import texts
from app.db.repositories.pending_payments import PendingPaymentRepository
from app.db.repositories.users import UserRepository
from app.domain.constants import SUBSCRIPTION_DAYS, SUBSCRIPTION_PRICE_RUB
from app.services.subscription import SubscriptionService
from app.web.auth import get_validated_init_data
from app.web.db import get_session
from app.web.main import app


@dataclass
class _FakeWebAppUser:
    id: int
    first_name: str


@dataclass
class _FakeInitData:
    user: _FakeWebAppUser


def _override_dependencies(session, telegram_id: int) -> None:
    app.dependency_overrides[get_validated_init_data] = (
        lambda: _FakeInitData(user=_FakeWebAppUser(id=telegram_id, first_name="Тест"))
    )

    async def _override_session():
        yield session

    app.dependency_overrides[get_session] = _override_session


async def _get_subscription(session, telegram_id: int) -> dict:
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/subscription")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    return response.json()


async def _post_pay(session, telegram_id: int):
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.post("/api/subscription/pay")
    finally:
        app.dependency_overrides.clear()


def _set_robokassa_configured(monkeypatch, *, configured: bool) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "robokassa_merchant_login", "shop" if configured else "")
    monkeypatch.setattr(settings, "robokassa_password_1", "pass1" if configured else "")
    monkeypatch.setattr(settings, "robokassa_password_2", "pass2" if configured else "")


async def test_subscription_for_unknown_telegram_id_is_not_onboarded(session, monkeypatch):
    _set_robokassa_configured(monkeypatch, configured=True)
    body = await _get_subscription(session, telegram_id=52001)

    assert body["is_onboarded"] is False
    assert body["status"] is None
    assert body["status_label"] is None
    assert body["expires_at"] is None
    assert body["price_rub"] == SUBSCRIPTION_PRICE_RUB
    assert body["days"] == SUBSCRIPTION_DAYS
    assert body["pricing_text_html"] == texts.PRICING_TEXT
    assert body["robokassa_available"] is True


async def test_subscription_for_trial_user_matches_profile_status_label(session, monkeypatch):
    _set_robokassa_configured(monkeypatch, configured=True)
    user = await UserRepository(session).create(telegram_id=52002, username="trial")
    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))

    body = await _get_subscription(session, telegram_id=user.telegram_id)

    assert body["is_onboarded"] is True
    assert body["status"] == "trial"
    assert "пробный период" in body["status_label"]
    assert body["expires_at"] is not None


async def test_subscription_reports_unavailable_robokassa(session, monkeypatch):
    _set_robokassa_configured(monkeypatch, configured=False)
    body = await _get_subscription(session, telegram_id=52003)

    assert body["robokassa_available"] is False


async def test_pay_returns_503_when_robokassa_not_configured(session, monkeypatch):
    _set_robokassa_configured(monkeypatch, configured=False)
    user = await UserRepository(session).create(telegram_id=52004, username="nopay")

    response = await _post_pay(session, telegram_id=user.telegram_id)

    assert response.status_code == 503


async def test_pay_returns_404_for_unknown_user(session, monkeypatch):
    _set_robokassa_configured(monkeypatch, configured=True)

    response = await _post_pay(session, telegram_id=52005)

    assert response.status_code == 404


async def test_pay_creates_pending_payment_and_returns_url(session, monkeypatch):
    _set_robokassa_configured(monkeypatch, configured=True)
    user = await UserRepository(session).create(telegram_id=52006, username="payer")

    response = await _post_pay(session, telegram_id=user.telegram_id)

    assert response.status_code == 200
    body = response.json()
    assert "InvId" in body["payment_url"]

    pending = await PendingPaymentRepository(session).list_pending()
    assert len(pending) == 1
    assert pending[0].user_id == user.id
    assert pending[0].days == SUBSCRIPTION_DAYS
    assert str(pending[0].id) in body["payment_url"]


async def test_get_oferta_pdf_serves_same_file_as_bot():
    """GET /api/oferta.pdf (issue #57, п.2) — тот же файл, что бот
    отправляет по кнопке "Тарифы и реквизиты" (см. test_pricing_info.py::
    test_oferta_pdf_asset_exists_on_disk), не копия. Публичный — без
    dependency overrides на initData/сессию."""
    from app.bot.handlers.menu import OFERTA_PDF_PATH

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/oferta.pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content == OFERTA_PDF_PATH.read_bytes()
