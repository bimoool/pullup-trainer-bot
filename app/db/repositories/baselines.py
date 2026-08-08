from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Baseline, Branch, EquipmentType


class BaselineRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        user_id: int,
        performed_at: datetime,
        branch_result: Branch,
        equipment_type: EquipmentType,
        reps: int,
        band_thickness_mm: Decimal | None = None,
        weight_kg: Decimal | None = None,
    ) -> Baseline:
        baseline = Baseline(
            user_id=user_id,
            performed_at=performed_at,
            branch_result=branch_result,
            equipment_type=equipment_type,
            reps=reps,
            band_thickness_mm=band_thickness_mm,
            weight_kg=weight_kg,
        )
        self._session.add(baseline)
        await self._session.flush()
        return baseline

    async def get_by_id(self, baseline_id: int) -> Baseline | None:
        return await self._session.get(Baseline, baseline_id)

    async def get_latest_for_user(self, user_id: int) -> Baseline | None:
        result = await self._session.execute(
            select(Baseline).where(Baseline.user_id == user_id).order_by(Baseline.performed_at.desc()).limit(1),
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: int) -> list[Baseline]:
        result = await self._session.execute(
            select(Baseline).where(Baseline.user_id == user_id).order_by(Baseline.performed_at),
        )
        return list(result.scalars().all())
