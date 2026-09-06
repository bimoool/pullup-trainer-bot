from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.leaderboard import LeaderboardEntry, LeaderboardMetric

# max по элементам JSONB-массива working_reps (jsonb_array_elements_text) и
# RANK() OVER по всем пользователям разом не выражаются штатным ORM
# select() без raw-фрагментов — единственное место в проекте на
# sqlalchemy.text() вместо ORM select(), см. CLAUDE.md ("Google Sheets"/
# репозитории обычно грузят полные ORM-объекты и агрегируют в Python, но
# здесь это означало бы тянуть блоки ВСЕХ пользователей в память при каждом
# открытии лидерборда).
_METRIC_EXPR: dict[LeaderboardMetric, str] = {
    LeaderboardMetric.MAX_REPS: (
        "MAX(GREATEST(b.max_reps, COALESCE("
        "(SELECT MAX(elem::int) FROM jsonb_array_elements_text(b.working_reps) AS elem), 0)))"
    ),
    LeaderboardMetric.MAX_WEIGHT: "MAX(b.equipment_value)",
    LeaderboardMetric.TOTAL_VOLUME: (
        "SUM(b.max_reps + COALESCE("
        "(SELECT SUM(elem::int) FROM jsonb_array_elements_text(b.working_reps) AS elem), 0))"
    ),
}

# Зеркало app.domain.leaderboard.age_bucket в SQL (issue #67) — возраст
# считается на лету через встроенную age(), не хранится нигде отдельно.
_AGE_BUCKET_CASE = """
    CASE
        WHEN u.birth_date IS NULL THEN NULL
        WHEN date_part('year', age(CURRENT_DATE, u.birth_date)) < 18 THEN NULL
        WHEN date_part('year', age(CURRENT_DATE, u.birth_date)) <= 29 THEN '18_29'
        WHEN date_part('year', age(CURRENT_DATE, u.birth_date)) <= 39 THEN '30_39'
        WHEN date_part('year', age(CURRENT_DATE, u.birth_date)) <= 49 THEN '40_49'
        WHEN date_part('year', age(CURRENT_DATE, u.birth_date)) <= 59 THEN '50_59'
        WHEN date_part('year', age(CURRENT_DATE, u.birth_date)) <= 69 THEN '60_69'
        ELSE '70_plus'
    END
"""


class LeaderboardRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def top(
        self,
        *,
        metric: LeaderboardMetric,
        gender: str | None,
        age_bucket: str | None,
        requesting_user_id: int | None,
        limit: int = 20,
    ) -> list[LeaderboardEntry]:
        """Топ-N по метрике плюс строка самого запрашивающего пользователя,
        даже если он вне топа (одним проходом — своя строка либо уже внутри
        LIMIT, либо добавляется тем же условием в финальном WHERE, см.
        план issue #67). gender/age_bucket=None — без фильтра ("все"),
        gender сравнивается как обычная строка (::text), не как enum-тип
        Postgres — параметр приходит с веб-слоя plain-строкой.

        Фильтрация по WHERE применяется к строкам blocks ДО GROUP BY — это
        эквивалентно фильтрации по пользователям, потому что gender/
        age_bucket зависят только от u, не от конкретного блока: либо все
        блоки пользователя проходят фильтр, либо ни одного (тогда
        пользователь просто не появляется в agg через INNER JOIN)."""
        metric_expr = _METRIC_EXPR[metric]
        # equipment_type сравнивается с литералом 'weight' в тексте самого
        # SQL (не bind-параметром) — Postgres сам приводит строковый литерал
        # к enum-типу колонки, в отличие от параметра, приходящего от
        # asyncpg без информации о типе.
        equipment_filter = "AND b.equipment_type = 'weight'" if metric == LeaderboardMetric.MAX_WEIGHT else ""

        sql = f"""
            WITH agg AS (
                SELECT
                    u.id AS user_id,
                    u.leaderboard_display_name AS display_name,
                    {metric_expr} AS value
                FROM users u
                JOIN workouts w ON w.user_id = u.id
                JOIN blocks b ON b.workout_id = w.id
                WHERE (CAST(:gender AS text) IS NULL OR u.gender::text = CAST(:gender AS text))
                  AND (
                    CAST(:age_bucket AS text) IS NULL
                    OR ({_AGE_BUCKET_CASE}) = CAST(:age_bucket AS text)
                  )
                  {equipment_filter}
                GROUP BY u.id, u.leaderboard_display_name
            ),
            ranked AS (
                SELECT user_id, display_name, value,
                       RANK() OVER (ORDER BY value DESC) AS rnk
                FROM agg
                WHERE value IS NOT NULL
            )
            SELECT user_id, display_name, value, rnk
            FROM ranked
            WHERE rnk <= CAST(:limit AS integer)
               OR (
                 CAST(:requesting_user_id AS bigint) IS NOT NULL
                 AND user_id = CAST(:requesting_user_id AS bigint)
               )
            ORDER BY rnk ASC
        """
        # asyncpg готовит запрос как prepared statement и не может сам
        # угадать тип параметра, если единственное употребление в запросе —
        # "IS NULL"/"IS NOT NULL" (нет соседнего типизированного операнда,
        # который дал бы вывести тип) — явные CAST(... AS ...) выше на
        # каждом параметре нужны именно поэтому, не для документирования.
        result = await self._session.execute(
            text(sql),
            {
                "gender": gender,
                "age_bucket": age_bucket,
                "limit": limit,
                "requesting_user_id": requesting_user_id,
            },
        )
        return [
            LeaderboardEntry(
                user_id=row.user_id,
                display_name=row.display_name,
                value=row.value,
                rank=row.rnk,
                is_current_user=row.user_id == requesting_user_id,
            )
            for row in result.all()
        ]
