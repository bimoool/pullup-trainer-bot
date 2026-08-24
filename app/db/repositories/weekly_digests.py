from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WeeklyDigest


class WeeklyDigestRepository:
    """Журнал фактически разосланных еженедельных дайджестов — источник
    last_digest_sent_at для будущего автосбора "что раскатили"/"что в
    работе" (диапазон git-истории/Issues с прошлой рассылки), см.
    WeeklyDigest в app/db/models.py."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_last_sent_at(self) -> datetime | None:
        result = await self._session.execute(
            select(WeeklyDigest.sent_at).order_by(WeeklyDigest.sent_at.desc()).limit(1),
        )
        return result.scalar_one_or_none()

    async def record(self, *, sent_at: datetime, text: str, recipients_count: int) -> WeeklyDigest:
        digest = WeeklyDigest(sent_at=sent_at, text=text, recipients_count=recipients_count)
        self._session.add(digest)
        await self._session.flush()
        return digest
