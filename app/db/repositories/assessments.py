from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import AssessmentProtocol, AssessmentResult
from app.domain.peer_insights import (
    NEXT_TARGET_PERCENTILES,
    CohortLevel,
    CohortStats,
    birth_date_range,
)


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

    async def peer_cohorts(
        self, protocol_id: int, own_value: Decimal, gender: str | None, bucket: str | None, today: date,
    ) -> list[CohortStats]:
        """Агрегаты когорт для Peer Insights (#276) ОДНИМ запросом, от узкой к широкой:
        пол+ступень → пол → все. База — последний результат каждого пользователя по протоколу
        (DISTINCT ON); дальше только count/percentile_cont — ни id, ни значений других пользователей
        наружу не выходит, и в Python нет цикла по пользователям. Ступень задаётся диапазоном дат
        рождения (`app.domain.peer_insights.birth_date_range`, «сегодня» — параметр), без второго
        CASE по age(). Уровень без пола (или без ступени) в выдачу не попадает."""
        after, upto = birth_date_range(bucket, today) if bucket is not None else (None, None)
        quantile_levels = [0.5, *(p / 100 for p in NEXT_TARGET_PERCENTILES)]
        agg = (
            "count(*) AS n, "
            "percentile_cont(CAST(:levels AS float8[])) WITHIN GROUP (ORDER BY value) AS q, "
            "count(*) FILTER (WHERE value < :own) AS below, count(*) FILTER (WHERE value = :own) AS equal "
            "FROM latest"
        )
        sql = f"""
            WITH latest AS (
                SELECT DISTINCT ON (r.user_id)
                    CAST(r.value AS float8) AS value, CAST(u.gender AS text) AS gender, u.birth_date
                FROM assessment_results r
                JOIN users u ON u.id = r.user_id
                WHERE r.protocol_id = :protocol_id
                ORDER BY r.user_id, r.performed_at DESC, r.id DESC
            )
            SELECT 'gender_age' AS level, {agg}
              WHERE CAST(:gender AS text) IS NOT NULL AND CAST(:upto AS date) IS NOT NULL
                AND gender = CAST(:gender AS text)
                AND birth_date <= CAST(:upto AS date)
                AND (CAST(:after AS date) IS NULL OR birth_date > CAST(:after AS date))
            UNION ALL
            SELECT 'gender' AS level, {agg}
              WHERE CAST(:gender AS text) IS NOT NULL AND gender = CAST(:gender AS text)
            UNION ALL
            SELECT 'all' AS level, {agg}
        """
        result = await self._session.execute(
            text(sql),
            {
                "protocol_id": protocol_id, "own": float(own_value), "levels": quantile_levels,
                "gender": gender, "after": after, "upto": upto,
            },
        )
        stats: list[CohortStats] = []
        for row in result.all():
            if row.n == 0 or row.q is None:
                continue
            median, *quantiles = (Decimal(str(round(x, 2))) for x in row.q)
            stats.append(CohortStats(
                level=CohortLevel(row.level), size=row.n, median=median, quantiles=tuple(quantiles),
                below=row.below, equal=row.equal,
            ))
        return stats
