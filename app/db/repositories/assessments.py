from datetime import datetime
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import AssessmentProtocol, AssessmentResult


class AssessmentRepository:
    """Тесты (AssessmentProtocol) и замеры пользователя (AssessmentResult).
    Методы по результату фильтруют по user_id — чужое неотличимо от отсутствующего."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_protocols(self) -> list[AssessmentProtocol]:
        result = await self._session.execute(select(AssessmentProtocol).order_by(AssessmentProtocol.id))
        return list(result.scalars().all())

    async def get_protocol(self, protocol_id: int) -> AssessmentProtocol | None:
        return await self._session.get(AssessmentProtocol, protocol_id)

    async def list_results_for_user(self, user_id: int, protocol_id: int | None = None) -> list[AssessmentResult]:
        """Новые первыми (по дате замера, при равенстве — по id)."""
        stmt = select(AssessmentResult).where(AssessmentResult.user_id == user_id)
        if protocol_id is not None:
            stmt = stmt.where(AssessmentResult.protocol_id == protocol_id)
        result = await self._session.execute(
            stmt.order_by(AssessmentResult.performed_at.desc(), AssessmentResult.id.desc()),
        )
        return list(result.scalars().all())

    async def get_result(self, user_id: int, result_id: int) -> AssessmentResult | None:
        result = await self._session.execute(
            select(AssessmentResult).where(AssessmentResult.id == result_id, AssessmentResult.user_id == user_id),
        )
        return result.scalar_one_or_none()

    async def create_result(
        self, user_id: int, protocol_id: int, performed_at: datetime, value: Decimal, unit: str, note: str | None,
    ) -> AssessmentResult:
        row = AssessmentResult(
            user_id=user_id, protocol_id=protocol_id, performed_at=performed_at, value=value, unit=unit, note=note,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def delete_result(self, user_id: int, result_id: int) -> bool:
        deleted = await self._session.execute(
            delete(AssessmentResult)
            .where(AssessmentResult.id == result_id, AssessmentResult.user_id == user_id)
            .returning(AssessmentResult.id),
        )
        return deleted.first() is not None
