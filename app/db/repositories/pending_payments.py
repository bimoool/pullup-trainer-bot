from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PendingPayment, PendingPaymentProvider, PendingPaymentStatus


class PendingPaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, *, user_id: int, provider: PendingPaymentProvider, external_order_id: str, days: int,
    ) -> PendingPayment:
        payment = PendingPayment(
            user_id=user_id, provider=provider, external_order_id=external_order_id, days=days,
        )
        self._session.add(payment)
        await self._session.flush()
        return payment

    async def list_pending(self, provider: PendingPaymentProvider | None = None) -> list[PendingPayment]:
        query = select(PendingPayment).where(PendingPayment.status == PendingPaymentStatus.PENDING)
        if provider is not None:
            query = query.where(PendingPayment.provider == provider)
        result = await self._session.execute(query.order_by(PendingPayment.created_at))
        return list(result.scalars().all())

    async def set_external_order_id(self, payment_id: int, external_order_id: str) -> PendingPayment:
        """Робокасса не выдаёт свой order id заранее — используем id самой
        записи pending_payments как InvId, но узнаём его только после
        создания строки (см. RobokassaService.create_payment_link)."""
        payment = await self._session.get_one(PendingPayment, payment_id)
        payment.external_order_id = external_order_id
        await self._session.flush()
        return payment

    async def mark_confirmed(self, payment_id: int, *, resolved_at: datetime) -> PendingPayment:
        payment = await self._session.get_one(PendingPayment, payment_id)
        payment.status = PendingPaymentStatus.CONFIRMED
        payment.resolved_at = resolved_at
        await self._session.flush()
        return payment

    async def mark_failed(self, payment_id: int, *, resolved_at: datetime) -> PendingPayment:
        payment = await self._session.get_one(PendingPayment, payment_id)
        payment.status = PendingPaymentStatus.FAILED
        payment.resolved_at = resolved_at
        await self._session.flush()
        return payment
