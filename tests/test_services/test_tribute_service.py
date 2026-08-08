from datetime import UTC, datetime

from app.db.models import PendingPaymentStatus, SubscriptionSource, SubscriptionStatus, User
from app.db.repositories.pending_payments import PendingPaymentRepository
from app.db.repositories.subscriptions import SubscriptionRepository
from app.db.repositories.users import UserRepository
from app.services.tribute import SUBSCRIPTION_DAYS, TributeOrder, TributeService

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class FakeTributeClient:
    """Тестовый двойник TributeClientProtocol — реальный Tribute API в
    тестах не участвует, только наша БД-логика вокруг него."""

    def __init__(self) -> None:
        self.statuses: dict[str, str] = {}
        self.created_orders: list[dict] = []
        self._next_uuid = 0

    async def create_order(self, *, amount: int, currency: str, title: str, description: str) -> TributeOrder:
        self._next_uuid += 1
        uuid = f"order-{self._next_uuid}"
        self.created_orders.append(
            {"amount": amount, "currency": currency, "title": title, "description": description},
        )
        self.statuses[uuid] = "pending"
        return TributeOrder(
            uuid=uuid, payment_url=f"https://tribute.tg/pay/{uuid}", webapp_payment_url=None, status="pending",
        )

    async def get_order_status(self, order_uuid: str) -> str:
        return self.statuses[order_uuid]


async def test_create_payment_link_records_pending_payment(session, user: User):
    client = FakeTributeClient()
    service = TributeService(session, client)

    order = await service.create_payment_link(user.id)

    assert client.created_orders[0]["currency"] == "rub"
    assert client.created_orders[0]["amount"] == 990

    pending = await PendingPaymentRepository(session).list_pending()
    assert len(pending) == 1
    assert pending[0].external_order_id == order.uuid
    assert pending[0].days == SUBSCRIPTION_DAYS
    assert pending[0].status == PendingPaymentStatus.PENDING


async def test_sync_confirms_paid_order_and_extends_subscription(session, user: User):
    client = FakeTributeClient()
    service = TributeService(session, client)
    order = await service.create_payment_link(user.id)
    client.statuses[order.uuid] = "paid"

    confirmed_count = await service.sync_pending_payments(now=NOW)

    assert confirmed_count == 1
    pending = await PendingPaymentRepository(session).list_pending()
    assert pending == []

    updated_user = await UserRepository(session).get_by_id(user.id)
    assert updated_user.subscription_status == SubscriptionStatus.ACTIVE

    subscriptions = await SubscriptionRepository(session).list_for_user(user.id)
    assert subscriptions[0].source == SubscriptionSource.TRIBUTE
    assert subscriptions[0].payment_reference == order.uuid


async def test_sync_leaves_still_pending_order_untouched(session, user: User):
    client = FakeTributeClient()
    service = TributeService(session, client)
    await service.create_payment_link(user.id)  # остаётся "pending" у клиента

    confirmed_count = await service.sync_pending_payments(now=NOW)

    assert confirmed_count == 0
    pending = await PendingPaymentRepository(session).list_pending()
    assert len(pending) == 1
    assert pending[0].status == PendingPaymentStatus.PENDING

    updated_user = await UserRepository(session).get_by_id(user.id)
    assert updated_user.subscription_status == SubscriptionStatus.NONE


async def test_sync_marks_failed_order_without_extending_subscription(session, user: User):
    client = FakeTributeClient()
    service = TributeService(session, client)
    order = await service.create_payment_link(user.id)
    client.statuses[order.uuid] = "failed"

    confirmed_count = await service.sync_pending_payments(now=NOW)

    assert confirmed_count == 0
    pending = await PendingPaymentRepository(session).list_pending()
    assert pending == []  # ушёл из pending, но не через confirmed

    updated_user = await UserRepository(session).get_by_id(user.id)
    assert updated_user.subscription_status == SubscriptionStatus.NONE


async def test_sync_processes_multiple_orders_independently(session, user: User):
    client = FakeTributeClient()
    service = TributeService(session, client)
    paid_order = await service.create_payment_link(user.id)
    still_pending_order = await service.create_payment_link(user.id)
    client.statuses[paid_order.uuid] = "paid"
    # still_pending_order остаётся "pending"

    confirmed_count = await service.sync_pending_payments(now=NOW)

    assert confirmed_count == 1
    remaining = await PendingPaymentRepository(session).list_pending()
    assert [p.external_order_id for p in remaining] == [still_pending_order.uuid]
