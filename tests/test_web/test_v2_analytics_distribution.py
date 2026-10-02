"""CRIMPD #274 — GET /api/v2/analytics/training: distribution по категориям.
Смешанная сессия делится по долям блоков, свободная активность — «Другая
активность», категории каталога присутствуют с нулями."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.models_program import Exercise, SessionBlock, SessionStatus, TrainingSession
from app.domain.multi_program import MetricType, SessionSource
from app.domain.training_analytics import (
    OTHER_ACTIVITY_CATEGORY,
    AnalyticsBlock,
    AnalyticsSession,
    compute_distribution,
)
from tests.test_web._v2_client import v2_get
from tests.test_web.test_v2_mixed_workout import _user

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
UTC_TZ = ZoneInfo("UTC")


async def _exercise(session: AsyncSession, name: str, category: str, subcategory: str | None = None) -> Exercise:
    exercise = Exercise(name=name, metric_type=MetricType.REPS, category=category, subcategory=subcategory)
    session.add(exercise)
    await session.flush()
    return exercise


async def _session(
    session: AsyncSession, user: User, at: datetime, minutes: float | None, exercises: list[Exercise],
    *, activity_type: str | None = None,
) -> None:
    row = TrainingSession(
        user_id=user.id, source=SessionSource.FREEFORM if activity_type else SessionSource.PLAN,
        status=SessionStatus.COMPLETED, performed_at=at,
        completed_at=None if minutes is None or activity_type else at + timedelta(minutes=minutes),
        activity_type=activity_type,
        duration_seconds=int(minutes * 60) if activity_type and minutes is not None else None,
    )
    session.add(row)
    await session.flush()
    for index, exercise in enumerate(exercises):
        session.add(SessionBlock(session_id=row.id, order_index=index, exercise_id=exercise.id))


async def _distribution(session: AsyncSession, user: User, query: str) -> dict:
    response = await v2_get(session, telegram_id=user.telegram_id, path=f"/api/v2/analytics/training{query}")
    assert response.status_code == 200, response.text
    return response.json()["distribution"]


async def test_distribution_splits_mixed_sessions_adds_free_activity_and_zero_rows(session: AsyncSession):
    user = await _user(session, 960101)
    user.timezone = "UTC"
    pull_a = await _exercise(session, "Тяга A", "dist274_pull", "dist274_vertical")
    pull_b = await _exercise(session, "Тяга B", "dist274_pull", "dist274_horizontal")
    core = await _exercise(session, "Пресс", "dist274_core")
    await _exercise(session, "Ноги", "dist274_legs", "dist274_squat")  # в каталоге, но без тренировок
    await _session(session, user, datetime(2025, 3, 4, 10, tzinfo=UTC), 40, [pull_a])
    await _session(session, user, datetime(2025, 3, 5, 10, tzinfo=UTC), 20, [pull_b, core])  # 50/50
    await _session(session, user, datetime(2025, 3, 6, 10, tzinfo=UTC), 30, [], activity_type="running")
    await _session(session, user, datetime(2025, 3, 7, 10, tzinfo=UTC), None, [core])  # нет длительности
    await _session(session, user, datetime(2025, 4, 20, 10, tzinfo=UTC), 99, [core])  # вне диапазона
    await session.commit()

    data = await _distribution(session, user, "?from=2025-03-01&to=2025-03-31")
    by_name = {c["name"]: c for c in data["categories"]}

    pull = by_name["dist274_pull"]
    assert (pull["workouts"], pull["minutes"]) == (1.5, 50.0)  # 1 + 0.5 ; 40 + 10
    assert {s["name"]: (s["workouts"], s["minutes"]) for s in pull["subcategories"]} == {
        "dist274_vertical": (1.0, 40.0), "dist274_horizontal": (0.5, 10.0),
    }
    core_row = by_name["dist274_core"]
    assert (core_row["workouts"], core_row["minutes"]) == (1.5, 10.0)
    assert core_row["subcategories"] == []
    legs = by_name["dist274_legs"]
    assert (legs["workouts"], legs["minutes"]) == (0, 0)  # ноль показан
    assert [(s["name"], s["workouts"]) for s in legs["subcategories"]] == [("dist274_squat", 0)]
    other = by_name[OTHER_ACTIVITY_CATEGORY]
    assert (other["workouts"], other["minutes"]) == (1.0, 30.0)
    assert data["categories"][-1]["name"] == OTHER_ACTIVITY_CATEGORY  # служебная — в конце

    # Итог тренировок = число тренировок диапазона (доли одной сессии суммируются в 1).
    assert data["total_workouts"] >= 4.0
    own = ("dist274_pull", "dist274_core", "dist274_legs", OTHER_ACTIVITY_CATEGORY)
    assert sum(by_name[n]["workouts"] for n in own) == 4.0
    assert sum(by_name[n]["minutes"] for n in own) == 90.0


async def test_distribution_is_scoped_to_user_library_and_range(session: AsyncSession):
    user = await _user(session, 960102)
    user.timezone = "UTC"
    other = await _user(session, 960103)
    own = await _exercise(session, "Моё", "dist274_own")
    own.source_type, own.owner_user_id = "user", user.id
    foreign = await _exercise(session, "Чужое", "dist274_foreign")
    foreign.source_type, foreign.owner_user_id = "user", other.id
    await session.commit()

    data = await _distribution(session, user, "?from=2025-03-01&to=2025-03-31")
    names = {c["name"] for c in data["categories"]}
    assert "dist274_own" in names
    assert "dist274_foreign" not in names  # чужой каталог не виден
    assert data["total_workouts"] == 0


def test_domain_distribution_shares_sum_to_one_and_future_excluded():
    def block(cat, sub=None):
        return AnalyticsBlock(
            exercise_id=1, exercise_name="x", protocol_type="reps_sets", category=cat, subcategory=sub,
        )

    sessions = [
        AnalyticsSession(
            performed_at=NOW - timedelta(days=2), completed_at=NOW - timedelta(days=2) + timedelta(minutes=30),
            blocks=[block("a"), block("a", "s"), block("b")],
        ),
        AnalyticsSession(performed_at=NOW + timedelta(days=1), blocks=[block("a")]),  # будущее
        AnalyticsSession(performed_at=NOW - timedelta(days=1), blocks=[AnalyticsBlock(None, None, None)]),
    ]
    result = compute_distribution(
        sessions, [("z", None)], (NOW - timedelta(days=30)).date(), NOW.date(), NOW, UTC_TZ,
    )
    by_name = {c.name: c for c in result.categories}
    assert by_name["a"].workouts == 0.67
    assert by_name["b"].workouts == 0.33
    assert by_name["a"].minutes == 20.0 and by_name["b"].minutes == 10.0
    assert [s.name for s in by_name["a"].subcategories] == ["s"]
    assert by_name["z"].workouts == 0
    assert by_name["Без категории"].workouts == 1.0  # блок без упражнения
    assert result.total_workouts == 2.0
