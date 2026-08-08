from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PendingPaymentProvider, SubscriptionSource
from app.db.repositories.pending_payments import PendingPaymentRepository
from app.services.subscription import SubscriptionService

TRIBUTE_BASE_URL = "https://tribute.tg/api/v1"

# Продуктовая константа (990₽/мес), не секрет и не тренировочный домен —
# поэтому не в .env и не в app/domain/constants.py, а здесь, рядом с
# единственным местом, где используется.
SUBSCRIPTION_PRICE_RUB = 990
SUBSCRIPTION_DAYS = 30
SUBSCRIPTION_TITLE = "Подписка Pull-Up Trainer"
SUBSCRIPTION_DESCRIPTION = f"Доступ на {SUBSCRIPTION_DAYS} дней"

# Статусы заказа, как их возвращает Tribute (GET /shop/orders/{uuid}/status)
_STATUS_PAID = "paid"
_STATUS_FAILED = "failed"


@dataclass(frozen=True)
class TributeOrder:
    uuid: str
    payment_url: str | None
    webapp_payment_url: str | None
    status: str


class TributeClientProtocol(Protocol):
    """Форма, которую должен повторить TributeClient — против неё же
    тестируется TributeService через фейковую реализацию, без обращения
    к реальному Tribute API."""

    async def create_order(
        self, *, amount: int, currency: str, title: str, description: str,
    ) -> TributeOrder: ...

    async def get_order_status(self, order_uuid: str) -> str: ...


class TributeClient:
    """Тонкая обёртка над Tribute Shop API — без бизнес-логики, только
    HTTP. Аутентификация — заголовок Api-Key."""

    def __init__(self, api_key: str, *, base_url: str = TRIBUTE_BASE_URL) -> None:
        self._api_key = api_key
        self._base_url = base_url

    async def create_order(
        self, *, amount: int, currency: str, title: str, description: str,
    ) -> TributeOrder:
        payload = {"amount": amount, "currency": currency, "title": title, "description": description}
        async with (
            aiohttp.ClientSession() as http,
            http.post(f"{self._base_url}/shop/orders", headers={"Api-Key": self._api_key}, json=payload) as response,
        ):
            response.raise_for_status()
            data = await response.json()
        return TributeOrder(
            uuid=data["uuid"],
            payment_url=data.get("paymentUrl"),
            webapp_payment_url=data.get("webappPaymentUrl"),
            status=data["status"],
        )

    async def get_order_status(self, order_uuid: str) -> str:
        async with aiohttp.ClientSession() as http, http.get(
            f"{self._base_url}/shop/orders/{order_uuid}/status",
            headers={"Api-Key": self._api_key},
        ) as response:
            response.raise_for_status()
            data = await response.json()
        return data["status"]


class TributeService:
    """Оркестрация: создание заказа на оплату + отметка pending_payments, и
    периодическая сверка (вызывается воркером) — при статусе paid продлевает
    подписку через SubscriptionService, при failed просто закрывает заказ."""

    def __init__(self, session: AsyncSession, client: TributeClientProtocol) -> None:
        self._pending_payments = PendingPaymentRepository(session)
        self._subscriptions = SubscriptionService(session)
        self._client = client

    async def create_payment_link(self, user_id: int) -> TributeOrder:
        order = await self._client.create_order(
            amount=SUBSCRIPTION_PRICE_RUB,
            currency="rub",
            title=SUBSCRIPTION_TITLE,
            description=SUBSCRIPTION_DESCRIPTION,
        )
        await self._pending_payments.create(
            user_id=user_id,
            provider=PendingPaymentProvider.TRIBUTE,
            external_order_id=order.uuid,
            days=SUBSCRIPTION_DAYS,
        )
        return order

    async def sync_pending_payments(self, *, now: datetime) -> int:
        """Опрашивает все pending-заказы Tribute. Возвращает число
        подтверждённых за этот проход (для лога воркера)."""
        confirmed = 0
        for payment in await self._pending_payments.list_pending(PendingPaymentProvider.TRIBUTE):
            status = await self._client.get_order_status(payment.external_order_id)
            if status == _STATUS_PAID:
                await self._subscriptions.extend(
                    payment.user_id,
                    now=now,
                    days=payment.days,
                    source=SubscriptionSource.TRIBUTE,
                    payment_reference=payment.external_order_id,
                )
                await self._pending_payments.mark_confirmed(payment.id, resolved_at=now)
                confirmed += 1
            elif status == _STATUS_FAILED:
                await self._pending_payments.mark_failed(payment.id, resolved_at=now)
        return confirmed
