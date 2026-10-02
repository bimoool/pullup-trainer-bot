from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import AssessmentProtocol, AssessmentResult
from app.domain.leaderboard import AGE_BUCKETS
from app.domain.peer_insights import (
    ALL_COHORT,
    MIN_COHORT_SIZE,
    NEXT_TARGET_PERCENTILES,
    CohortKey,
    CohortStats,
    birth_date_range,
    cell_cohort,
    gender_cohort,
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

    async def peer_cohorts(self, protocol_id: int, own_value: Decimal, today: date) -> dict[CohortKey, CohortStats]:
        """Агрегаты ВСЕХ когорт-кандидатов Peer Insights (#276, #284) ОДНИМ запросом:
        ALL, пол, пол × возрастная ступень (GROUPING SETS), только с размером >= MIN_COHORT_SIZE
        (меньшие никогда не показываются, а остатки считаются по размерам показываемых). Выбор
        когорты пользователя и комплементарное подавление узких — в домене
        (`app.domain.peer_insights.shown_cohorts` / `build_insight`), зритель в SQL не участвует:
        набор когорт зависит только от данных. База — последний результат каждого пользователя по
        протоколу (DISTINCT ON); наружу — только count/percentile_cont, ни id, ни значений других
        пользователей, цикла по пользователям в Python нет; строк в ответе не больше ~1+3+3·6.
        Ступень задаётся диапазоном дат рождения (`birth_date_range`, «сегодня» — параметр);
        пользователи без пола / даты рождения / младше 18 попадают только в «остаток» родителя —
        строки с NULL-полом или NULL-ступенью отбрасываются как невыбираемые."""
        quantile_levels = [0.5, *(p / 100 for p in NEXT_TARGET_PERCENTILES)]
        params: dict[str, object] = {}
        bucket_cases: list[str] = []
        for i, name in enumerate(AGE_BUCKETS):
            b_after, b_upto = birth_date_range(name, today)
            params[f"b{i}_after"], params[f"b{i}_upto"], params[f"b{i}_name"] = b_after, b_upto, name
            bucket_cases.append(
                f"WHEN u.birth_date <= CAST(:b{i}_upto AS date) "
                f"AND (CAST(:b{i}_after AS date) IS NULL OR u.birth_date > CAST(:b{i}_after AS date)) "
                f"THEN CAST(:b{i}_name AS text)"
            )
        bucket_case = f"CASE {' '.join(bucket_cases)} END"
        sql = f"""
            WITH latest AS (
                SELECT DISTINCT ON (r.user_id)
                    CAST(r.value AS float8) AS value, CAST(u.gender AS text) AS gender, {bucket_case} AS bucket
                FROM assessment_results r
                JOIN users u ON u.id = r.user_id
                WHERE r.protocol_id = :protocol_id
                ORDER BY r.user_id, r.performed_at DESC, r.id DESC
            )
            SELECT
                GROUPING(gender, bucket) AS gset, gender, bucket,
                count(*) AS n,
                percentile_cont(CAST(:levels AS float8[])) WITHIN GROUP (ORDER BY value) AS q,
                count(*) FILTER (WHERE value < :own) AS below,
                count(*) FILTER (WHERE value = :own) AS equal
            FROM latest
            GROUP BY GROUPING SETS ((), (gender), (gender, bucket))
            HAVING count(*) >= :min_size
        """
        result = await self._session.execute(
            text(sql),
            {
                "protocol_id": protocol_id, "own": float(own_value), "levels": quantile_levels,
                "min_size": MIN_COHORT_SIZE, **params,
            },
        )
        stats: dict[CohortKey, CohortStats] = {}
        for row in result.all():
            # GROUPING(gender, bucket): 3 — итог (ALL), 1 — по полу, 0 — пол × ступень
            if row.gset == 3:
                key = ALL_COHORT
            elif row.gset == 1 and row.gender is not None:
                key = gender_cohort(row.gender)
            elif row.gset == 0 and row.gender is not None and row.bucket is not None:
                key = cell_cohort(row.gender, row.bucket)
            else:
                continue  # без пола / без ступени — невыбираемый остаток
            if row.q is None:
                continue
            median, *quantiles = (Decimal(str(round(x, 2))) for x in row.q)
            stats[key] = CohortStats(
                key=key, size=row.n, median=median, quantiles=tuple(quantiles), below=row.below, equal=row.equal,
            )
        return stats
