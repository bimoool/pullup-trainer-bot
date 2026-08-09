from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Baseline


class BaselineRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, user_id: int, performed_at: datetime, reps: int) -> Baseline:
        baseline = Baseline(user_id=user_id, performed_at=performed_at, reps=reps)
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
