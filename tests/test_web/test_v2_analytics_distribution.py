"""CRIMPD #274 → #308 — GET /api/v2/analytics/training: distribution по категориям.

Тренировка атомарна: каждая сессия — ровно в ОДНОЙ категории (primary_category, SESSION §6 A2), все счётчики
целые, Σ по категориям == итог, минуты категорий раздаются наибольшим остатком до итога (A5), подписи только
человеческие (A3): ни pull_ups, ни block_a, ни user, ни произвольный ключ категории в ответе не появляются."""

import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.models_program import Exercise, SessionBlock, SessionStatus, SetLog, TrainingSession
from app.domain.multi_program import MetricType, SessionSource
from app.domain.training_analytics import (
    OTHER_ACTIVITY_CATEGORY,
    UNCATEGORIZED,
    AnalyticsBlock,
    AnalyticsSession,
    AnalyticsSetLog,
    compute_distribution,
)
from tests.test_web._v2_client import v2_get
from tests.test_web.test_v2_mixed_workout import _user

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
UTC_TZ = ZoneInfo("UTC")
RAW_KEYS = ("pull_ups", "block_a", "block_b", "elective_", "manual_custom", "dist274", "user")


async def _exercise(
    session: AsyncSession, name: str, category: str, subcategory: str | None = None, *, owner: User | None = None,
) -> Exercise:
    exercise = Exercise(
        name=name, metric_type=MetricType.REPS, category=category, subcategory=subcategory,
        source_type="user" if owner else "system", owner_user_id=owner.id if owner else None,
    )
    session.add(exercise)
    await session.flush()
    return exercise


async def _session(
    session: AsyncSession, user: User, at: datetime, minutes: float | None, blocks: list[tuple[Exercise, int]],
    *, activity_type: str | None = None,
) -> int:
    """blocks — (упражнение, число выполненных подходов)."""
    row = TrainingSession(
        user_id=user.id, source=SessionSource.FREEFORM if activity_type else SessionSource.PLAN,
        status=SessionStatus.COMPLETED, performed_at=at,
        completed_at=None if minutes is None or activity_type else at + timedelta(minutes=minutes),
        activity_type=activity_type,
        duration_seconds=int(minutes * 60) if activity_type and minutes is not None else None,
    )
    session.add(row)
    await session.flush()
    for index, (exercise, sets) in enumerate(blocks):
        block = SessionBlock(session_id=row.id, order_index=index, exercise_id=exercise.id)
        session.add(block)
        await session.flush()
        for number in range(1, sets + 1):
            session.add(SetLog(
                session_block_id=block.id, set_number=number, is_max_set=False, metric_type=MetricType.REPS,
                value=10, unit="reps",
            ))
    await session.flush()
    return row.id


async def _distribution(session: AsyncSession, user: User, query: str) -> dict:
    response = await v2_get(session, telegram_id=user.telegram_id, path=f"/api/v2/analytics/training{query}")
    assert response.status_code == 200, response.text
    return response.json()["distribution"]


async def test_each_session_lands_in_exactly_one_human_labelled_category(session: AsyncSession):
    user = await _user(session, 960101)
    user.timezone = "UTC"
    pull_a = await _exercise(session, "Подтягивания — объём", "pull_ups", "block_a")
    pull_b = await _exercise(session, "Подтягивания — сила", "pull_ups", "block_b")
    mine = await _exercise(session, "Мой комплекс", "user", owner=user)
    grip = await _exercise(session, "Вис", "Хват")
    odd = await _exercise(session, "Странное", "dist274_odd", "dist274_sub")
    await _exercise(session, "Ноги", "general_fitness")  # в каталоге, без тренировок
    # курс: блок A (3 подхода) + блок Б (5 подходов) — ОДНА тренировка, категория блока с большим числом подходов
    await _session(session, user, datetime(2025, 3, 4, 10, tzinfo=UTC), 40, [(pull_a, 3), (pull_b, 5)])
    # смешанная: подтягивания (1 подход) + хват (2 подхода) -> хват, не 50/50
    await _session(session, user, datetime(2025, 3, 5, 10, tzinfo=UTC), 20, [(pull_a, 1), (grip, 2)])
    await _session(session, user, datetime(2025, 3, 6, 10, tzinfo=UTC), 30, [], activity_type="running")
    await _session(session, user, datetime(2025, 3, 7, 10, tzinfo=UTC), None, [(mine, 4)])  # нет длительности
    await _session(session, user, datetime(2025, 3, 8, 10, tzinfo=UTC), 10, [(odd, 1)])
    await _session(session, user, datetime(2025, 4, 20, 10, tzinfo=UTC), 99, [(grip, 1)])  # вне диапазона
    await session.commit()

    data = await _distribution(session, user, "?from=2025-03-01&to=2025-03-31")
    by_name = {c["name"]: c for c in data["categories"]}

    assert {name: c["workouts"] for name, c in by_name.items() if c["workouts"]} == {
        "Подтягивания": 1, "Хват": 1, OTHER_ACTIVITY_CATEGORY: 1, "Мои упражнения": 1, UNCATEGORIZED: 1,
    }
    assert all(isinstance(c["workouts"], int) and isinstance(c["minutes"], int) for c in data["categories"])
    assert sum(c["workouts"] for c in data["categories"]) == data["total_workouts"] == 5
    assert sum(c["minutes"] for c in data["categories"]) == data["total_minutes"] == 100  # 40+20+30+10, без None
    assert (by_name["Подтягивания"]["minutes"], by_name["Хват"]["minutes"]) == (40, 20)
    assert by_name["Подтягивания"]["subcategories"] == []  # block_a/block_b — служебные, не показываются
    assert by_name["Общая физическая подготовка"]["workouts"] == 0  # ноль каталога показан
    assert [c["name"] for c in data["categories"]][-2:] == [OTHER_ACTIVITY_CATEGORY, UNCATEGORIZED]  # служебные — в конце
    dump = json.dumps(data, ensure_ascii=False)
    assert not [key for key in RAW_KEYS if key in dump], dump


async def test_external_activity_category_has_a_deterministic_display_name(session: AsyncSession):
    user = await _user(session, 960104)
    user.timezone = "UTC"
    await _session(session, user, datetime(2025, 3, 6, 10, tzinfo=UTC), 45, [], activity_type="running")
    await _session(session, user, datetime(2025, 3, 7, 10, tzinfo=UTC), 30, [], activity_type="cycling")
    await session.commit()

    data = await _distribution(session, user, "?from=2025-03-01&to=2025-03-31")
    other = next(c for c in data["categories"] if c["name"] == OTHER_ACTIVITY_CATEGORY)
    assert (other["workouts"], other["minutes"]) == (2, 75)
    assert {(s["name"], s["workouts"], s["minutes"]) for s in other["subcategories"]} == {
        ("Бег", 1, 45), ("Велосипед", 1, 30),
    }


async def test_distribution_is_scoped_to_user_library_and_range(session: AsyncSession):
    user = await _user(session, 960102)
    user.timezone = "UTC"
    other = await _user(session, 960103)
    await _exercise(session, "Моё", "user", owner=user)
    await _exercise(session, "Чужое", "Хват", owner=other)
    await session.commit()

    data = await _distribution(session, user, "?from=2025-03-01&to=2025-03-31")
    names = {c["name"] for c in data["categories"]}
    assert "Мои упражнения" in names
    assert "Хват" not in names  # категория чужого каталога не видна
    assert data["total_workouts"] == 0 and data["total_minutes"] == 0


def _block(category, sub=None, sets=1):
    return AnalyticsBlock(
        exercise_id=1, exercise_name="x", protocol_type="reps_sets", category=category, subcategory=sub,
        set_logs=[AnalyticsSetLog(value=10, unit="reps")] * sets,
    )


def test_domain_distribution_is_integer_sums_and_future_excluded():
    def at(days: int, minutes: float | None, blocks) -> AnalyticsSession:
        when = NOW - timedelta(days=days)
        return AnalyticsSession(
            performed_at=when, completed_at=None if minutes is None else when + timedelta(minutes=minutes), blocks=blocks,
        )

    sessions = [
        at(2, 30, [_block("pull_ups", "block_a", 1), _block("Хват", None, 1), _block("general_fitness", None, 1)]),
        AnalyticsSession(performed_at=NOW + timedelta(days=1), blocks=[_block("pull_ups")]),  # будущее
        at(1, None, [AnalyticsBlock(None, None, None)]),
    ]
    result = compute_distribution(sessions, [("grip", None)], (NOW - timedelta(days=30)).date(), NOW.date(), NOW, UTC_TZ)
    by_name = {c.name: c for c in result.categories}
    # ничья по подходам (1:1:1) -> ПЕРВЫЙ блок: вся сессия в «Подтягиваниях», никаких долей 0.33
    assert by_name["Подтягивания"].workouts == 1 and by_name["Подтягивания"].minutes == 30
    assert by_name["Хват"].workouts == 0 and "Общая физическая подготовка" not in by_name  # нулевая строка — из каталога
    assert by_name[UNCATEGORIZED].workouts == 1  # блок без упражнения
    assert result.total_workouts == 2 and result.total_minutes == 30
    assert all(isinstance(c.workouts, int) for c in result.categories)


def test_domain_minutes_are_allocated_by_largest_remainder_to_the_total():
    def session(at_days: int, seconds: int, category: str) -> AnalyticsSession:
        return AnalyticsSession(
            performed_at=NOW - timedelta(days=at_days), duration_seconds=seconds, blocks=[_block(category)],
        )

    # 3 × 30 с: каждая категория по отдельности округлилась бы до 0 или 1; итог — round(90 / 60) = 2
    sessions = [session(1, 30, "Хват"), session(2, 30, "pull_ups"), session(3, 30, "general_fitness")]
    result = compute_distribution(sessions, [], (NOW - timedelta(days=30)).date(), NOW.date(), NOW, UTC_TZ)
    assert result.total_minutes == 2
    assert sum(c.minutes for c in result.categories) == 2
