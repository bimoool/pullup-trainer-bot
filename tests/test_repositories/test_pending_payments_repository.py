from datetime import UTC, datetime

from app.db.models import PendingPaymentProvider, PendingPaymentStatus, User
from app.db.repositories.pending_payments import PendingPaymentRepository

NOW = datetime(2026, 1, 1, tzinfo=UTC)


async def test_create_and_list_pending(session, user: User):
    repo = PendingPaymentRepository(session)
    created = await repo.create(
        user_id=user.id, provider=PendingPaymentProvider.TRIBUTE, external_order_id="order-1", days=30,
    )

    pending = await repo.list_pending()
    assert [p.id for p in pending] == [created.id]
    assert created.status == PendingPaymentStatus.PENDING
    assert created.resolved_at is None


async def test_list_pending_filters_by_provider(session, user: User):
    repo = PendingPaymentRepository(session)
    await repo.create(user_id=user.id, provider=PendingPaymentProvider.TRIBUTE, external_order_id="a", days=30)

    assert len(await repo.list_pending(PendingPaymentProvider.TRIBUTE)) == 1


async def test_list_pending_filters_by_provider_excludes_other_providers(session, user: User):
    repo = PendingPaymentRepository(session)
    await repo.create(user_id=user.id, provider=PendingPaymentProvider.TRIBUTE, external_order_id="a", days=30)
    robokassa_payment = await repo.create(
        user_id=user.id, provider=PendingPaymentProvider.ROBOKASSA, external_order_id="", days=30,
    )

    result = await repo.list_pending(PendingPaymentProvider.ROBOKASSA)

    assert [p.id for p in result] == [robokassa_payment.id]


async def test_set_external_order_id_updates_existing_payment(session, user: User):
    repo = PendingPaymentRepository(session)
    payment = await repo.create(
        user_id=user.id, provider=PendingPaymentProvider.ROBOKASSA, external_order_id="", days=30,
    )

    updated = await repo.set_external_order_id(payment.id, str(payment.id))

    assert updated.external_order_id == str(payment.id)
    pending = await repo.list_pending()
    assert pending[0].external_order_id == str(payment.id)


async def test_mark_confirmed_removes_from_pending_list(session, user: User):
    repo = PendingPaymentRepository(session)
    payment = await repo.create(
        user_id=user.id, provider=PendingPaymentProvider.TRIBUTE, external_order_id="order-2", days=30,
    )

    resolved = await repo.mark_confirmed(payment.id, resolved_at=NOW)

    assert resolved.status == PendingPaymentStatus.CONFIRMED
    assert resolved.resolved_at == NOW
    assert await repo.list_pending() == []


async def test_mark_failed_removes_from_pending_list(session, user: User):
    repo = PendingPaymentRepository(session)
    payment = await repo.create(
        user_id=user.id, provider=PendingPaymentProvider.TRIBUTE, external_order_id="order-3", days=30,
    )

    resolved = await repo.mark_failed(payment.id, resolved_at=NOW)

    assert resolved.status == PendingPaymentStatus.FAILED
    assert await repo.list_pending() == []
