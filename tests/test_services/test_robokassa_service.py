from datetime import UTC, datetime

from app.db.models import PendingPaymentStatus, SubscriptionSource, SubscriptionStatus, User
from app.db.repositories.pending_payments import PendingPaymentRepository
from app.db.repositories.subscriptions import SubscriptionRepository
from app.db.repositories.users import UserRepository
from app.services.robokassa import SUBSCRIPTION_DAYS, RobokassaAPIError, RobokassaService

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class FakeRobokassaClient:
    """Тестовый двойник RobokassaClientProtocol — реальный Robokassa API в
    тестах не участвует, только наша БД-логика вокруг него.

    Статусы задаются напрямую по inv_id ("paid"/"failed"/"pending" или
    исключение) — эта подделка НЕ проверяет реальные числовые коды
    OpState (100/10), только то, что RobokassaService правильно
    реагирует на каждый из трёх исходов get_operation_state."""

    def __init__(self) -> None:
        self.statuses: dict[int, str | Exception] = {}
        self.built_urls: list[dict] = []

    def build_payment_url(self, *, out_sum: str, inv_id: int, description: str) -> str:
        self.built_urls.append({"out_sum": out_sum, "inv_id": inv_id, "description": description})
        return f"https://auth.robokassa.ru/Merchant/Index.aspx?InvId={inv_id}"

    async def get_operation_state(self, inv_id: int) -> str:
        outcome = self.statuses.get(inv_id, "pending")
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


async def test_create_payment_link_records_pending_payment(session, user: User):
    client = FakeRobokassaClient()
    service = RobokassaService(session, client)

    link = await service.create_payment_link(user.id)

    pending = await PendingPaymentRepository(session).list_pending()
    assert len(pending) == 1
    assert pending[0].external_order_id == str(pending[0].id)
    assert pending[0].days == SUBSCRIPTION_DAYS
    assert pending[0].status == PendingPaymentStatus.PENDING
    assert client.built_urls[0]["inv_id"] == pending[0].id
    assert client.built_urls[0]["out_sum"] == "990.00"
    assert str(pending[0].id) in link


async def test_sync_confirms_paid_order_and_extends_subscription(session, user: User):
    client = FakeRobokassaClient()
    service = RobokassaService(session, client)
    await service.create_payment_link(user.id)
    pending = await PendingPaymentRepository(session).list_pending()
    client.statuses[pending[0].id] = "paid"

    confirmed_count = await service.sync_pending_payments(now=NOW)

    assert confirmed_count == 1
    assert await PendingPaymentRepository(session).list_pending() == []

    updated_user = await UserRepository(session).get_by_id(user.id)
    assert updated_user.subscription_status == SubscriptionStatus.ACTIVE

    subscriptions = await SubscriptionRepository(session).list_for_user(user.id)
    assert subscriptions[0].source == SubscriptionSource.ROBOKASSA
    assert subscriptions[0].payment_reference == str(pending[0].id)


async def test_sync_leaves_still_pending_order_untouched(session, user: User):
    client = FakeRobokassaClient()
    service = RobokassaService(session, client)
    await service.create_payment_link(user.id)  # остаётся "pending" у клиента

    confirmed_count = await service.sync_pending_payments(now=NOW)

    assert confirmed_count == 0
    pending = await PendingPaymentRepository(session).list_pending()
    assert len(pending) == 1
    assert pending[0].status == PendingPaymentStatus.PENDING

    updated_user = await UserRepository(session).get_by_id(user.id)
    assert updated_user.subscription_status == SubscriptionStatus.NONE


async def test_sync_marks_failed_order_without_extending_subscription(session, user: User):
    client = FakeRobokassaClient()
    service = RobokassaService(session, client)
    await service.create_payment_link(user.id)
    pending = await PendingPaymentRepository(session).list_pending()
    client.statuses[pending[0].id] = "failed"

    confirmed_count = await service.sync_pending_payments(now=NOW)

    assert confirmed_count == 0
    assert await PendingPaymentRepository(session).list_pending() == []  # ушёл, но не через confirmed

    updated_user = await UserRepository(session).get_by_id(user.id)
    assert updated_user.subscription_status == SubscriptionStatus.NONE


async def test_sync_processes_multiple_orders_independently(session, user: User):
    client = FakeRobokassaClient()
    service = RobokassaService(session, client)
    await service.create_payment_link(user.id)
    await service.create_payment_link(user.id)
    pending_before = await PendingPaymentRepository(session).list_pending()
    paid_id, still_pending_id = pending_before[0].id, pending_before[1].id
    client.statuses[paid_id] = "paid"
    # still_pending_id остаётся "pending"

    confirmed_count = await service.sync_pending_payments(now=NOW)

    assert confirmed_count == 1
    remaining = await PendingPaymentRepository(session).list_pending()
    assert [p.id for p in remaining] == [still_pending_id]


async def test_sync_skips_payment_with_api_error_without_blocking_others(session, user: User):
    """Ошибка запроса (неверная подпись/конфигурация) по одному платежу не
    должна останавливать проверку остальных pending-заказов в этом же
    проходе — платёж с ошибкой остаётся pending для следующего цикла."""
    client = FakeRobokassaClient()
    service = RobokassaService(session, client)
    await service.create_payment_link(user.id)
    await service.create_payment_link(user.id)
    pending_before = await PendingPaymentRepository(session).list_pending()
    broken_id, paid_id = pending_before[0].id, pending_before[1].id
    client.statuses[broken_id] = RobokassaAPIError(1, "invalid signature")
    client.statuses[paid_id] = "paid"

    confirmed_count = await service.sync_pending_payments(now=NOW)

    assert confirmed_count == 1
    remaining = await PendingPaymentRepository(session).list_pending()
    assert [p.id for p in remaining] == [broken_id]
