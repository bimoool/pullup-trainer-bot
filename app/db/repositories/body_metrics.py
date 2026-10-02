from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BodyMetric, User, UserBodyMetric


class LastBodyMetricError(Exception):
    """Нельзя удалить единственный замер: User.weight_kg/height_cm читают
    GTO/WSF/лидерборд, зеркалу не к чему откатываться (issue #270)."""


class BodyMetricRepository:
    """История веса/роста (issue #270). Единственное место, которое пишет
    user_body_metrics и зеркалит последний замер в User.weight_kg/height_cm."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_user(self, user_id: int, metric: BodyMetric) -> list[UserBodyMetric]:
        """Новые сверху: measured_at, затем id (стабильный порядок на равных датах)."""
        result = await self._session.execute(
            select(UserBodyMetric)
            .where(UserBodyMetric.user_id == user_id, UserBodyMetric.metric == metric.value)
            .order_by(UserBodyMetric.measured_at.desc(), UserBodyMetric.id.desc()),
        )
        return list(result.scalars().all())

    async def get_owned(self, user_id: int, entry_id: int) -> UserBodyMetric | None:
        """None и для чужой записи — вызывающий отдаёт 404 (PROJECT_SPEC §5)."""
        entry = await self._session.get(UserBodyMetric, entry_id)
        if entry is None or entry.user_id != user_id:
            return None
        return entry

    async def add(
        self, user_id: int, metric: BodyMetric, value: Decimal, measured_at: datetime | None = None,
    ) -> UserBodyMetric:
        entry = UserBodyMetric(
            user_id=user_id, metric=metric.value, value=value, measured_at=measured_at or datetime.now(UTC),
        )
        self._session.add(entry)
        await self._session.flush()
        await self.sync_user(user_id, metric)
        return entry

    async def update(
        self, entry: UserBodyMetric, *, value: Decimal | None = None, measured_at: datetime | None = None,
    ) -> UserBodyMetric:
        if value is not None:
            entry.value = value
        if measured_at is not None:
            entry.measured_at = measured_at
        await self._session.flush()
        await self.sync_user(entry.user_id, BodyMetric(entry.metric))
        return entry

    async def delete(self, entry: UserBodyMetric) -> None:
        user_id, metric = entry.user_id, BodyMetric(entry.metric)
        if len(await self.list_for_user(user_id, metric)) <= 1:
            raise LastBodyMetricError
        await self._session.delete(entry)
        await self._session.flush()
        await self.sync_user(user_id, metric)

    async def sync_user(self, user_id: int, metric: BodyMetric) -> None:
        """Зеркалит последний замер в User; без замеров поле не трогаем."""
        entries = await self.list_for_user(user_id, metric)
        if not entries:
            return
        user = await self._session.get_one(User, user_id)
        if metric is BodyMetric.WEIGHT_KG:
            user.weight_kg = entries[0].value
        else:
            user.height_cm = int(entries[0].value)
        await self._session.flush()
