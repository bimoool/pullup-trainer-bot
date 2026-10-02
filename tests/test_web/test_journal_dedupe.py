"""#282 — Журнал не показывает legacy Workout второй раз, если backfill (#163) уже перенёс её
в v2 TrainingSession. Display-only: данные не меняются, правило — app.domain.journal_dedupe.

Backfill-копии создаются НАСТОЯЩИМИ функциями scripts/backfill_multi_program.py, чтобы тест
ломался, если отпечаток backfill-сессии разойдётся с тем, что backfill реально пишет."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Workout
from app.db.models_program import (
    Exercise,
    PlanItem,
    SessionPlanItem,
    SessionStatus,
    TrainingPlan,
    TrainingSession,
)
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.training_sessions import (
    SessionBlockInput,
    SetLogInput,
    TrainingSessionRepository,
)
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.journal_dedupe import LegacyWorkoutKey, find_backfilled_duplicates
from app.domain.multi_program import MetricType, SessionSource
from app.domain.session import BlockLog
from scripts.backfill_multi_program import (
    _EXERCISE_BLOCK_A_NAME,
    _EXERCISE_BLOCK_B_NAME,
    _create_training_session_for_workout,
    _get_or_create_exercise,
)
from tests.test_web._v2_client import v2_get

BASE = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
FROM_TO = "date_from=2026-10-01&date_to=2026-10-31"


async def _legacy_user(session: AsyncSession, telegram_id: int):
    user = await UserRepository(session).create(telegram_id=telegram_id, username=f"u{telegram_id}")
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=BASE - timedelta(days=30), reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    return user, workout_set


def _kwargs(user, workout_set, at: datetime, max_a: int):
    return {
        "user_id": user.id, "workout_set_id": workout_set.id, "performed_at": at,
        "block_a_reps": BlockLog(working_reps=(10, 10, 10), max_reps=max_a),
        "block_b_reps": BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        "block_a_equipment_type": EquipmentType.BAND, "block_a_equipment_value": Decimal("15.0"),
        "block_b_equipment_type": EquipmentType.BAND, "block_b_equipment_value": Decimal("15.0"),
    }


async def _free_workout(session, user, workout_set, at: datetime, max_a: int) -> Workout:
    return await WorkoutRepository(session).record_free_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=at,
        block_a_reps=BlockLog(working_reps=(10, 10, 10), max_reps=max_a),
        equipment_type=EquipmentType.BAND, equipment_value=Decimal("15.0"),
    )


async def _backfill(session: AsyncSession, workouts: list[Workout]) -> None:
    """То же, что backfill_all делает с историей пользователя (минус общий каталог программ)."""
    exercise_a = await _get_or_create_exercise(session, name=_EXERCISE_BLOCK_A_NAME, subcategory="block_a")
    exercise_b = await _get_or_create_exercise(session, name=_EXERCISE_BLOCK_B_NAME, subcategory="block_b")
    for workout in workouts:
        await _create_training_session_for_workout(
            session, workout, exercise_a_id=exercise_a.id, exercise_b_id=exercise_b.id,
        )
    await session.flush()


async def _history(session, telegram_id: int, *, exclude: bool = True) -> list[dict]:
    flag = "&exclude_migrated=true" if exclude else ""
    response = await v2_get(session, telegram_id=telegram_id, path=f"/api/history?{FROM_TO}{flag}")
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _maxes(items: list[dict]) -> list[str]:
    return [item["result_a"] for item in items]


async def _migrated_user(session: AsyncSession, telegram_id: int):
    """Каскадная (макс. 11) + задним числом (12) + свободная (13), все перенесены; затем
    пост-миграционная legacy-запись (14), v2-копии у неё нет."""
    user, workout_set = await _legacy_user(session, telegram_id)
    repo = WorkoutRepository(session)
    await repo.record_workout(**_kwargs(user, workout_set, BASE, 11))
    await repo.record_backdated_workout(**_kwargs(user, workout_set, BASE + timedelta(hours=1), 12))
    await _free_workout(session, user, workout_set, BASE + timedelta(hours=2), 13)
    await _backfill(session, await repo.list_for_user(user.id))
    post = await repo.record_workout(**_kwargs(user, workout_set, BASE + timedelta(hours=3), 14))
    return user, workout_set, post


async def test_migrated_workouts_hidden_post_migration_workout_kept(session: AsyncSession):
    user, _workout_set, post = await _migrated_user(session, 982001)

    items = await _history(session, user.telegram_id)
    assert [item["workout_id"] for item in items] == [post.id]
    assert "максимум 14" in items[0]["result_a"]
    assert items[0]["target_a"] is not None  # цель следующей тренировки осталась на самой свежей записи


async def test_without_flag_history_is_unchanged(session: AsyncSession):
    user, _workout_set, _post = await _migrated_user(session, 982002)

    assert len(await _history(session, user.telegram_id, exclude=False)) == 4
    # скрытие — только отображение: ни одна запись не изменена и не удалена
    assert await session.scalar(select(func.count()).select_from(Workout).where(Workout.user_id == user.id)) == 4
    assert await session.scalar(
        select(func.count()).select_from(TrainingSession).where(TrainingSession.user_id == user.id),
    ) == 3


async def test_hidden_latest_does_not_move_target_to_older_card(session: AsyncSession):
    """Если самая свежая legacy-запись перенесена (скрыта), цель не «переезжает» на более старую."""
    user, workout_set = await _legacy_user(session, 982003)
    repo = WorkoutRepository(session)
    await repo.record_backdated_workout(**_kwargs(user, workout_set, BASE, 11))  # НЕ перенесена
    latest = await repo.record_workout(**_kwargs(user, workout_set, BASE + timedelta(hours=1), 12))
    await _backfill(session, [latest])

    items = await _history(session, user.telegram_id)
    assert len(items) == 1
    assert items[0]["target_a"] is None and items[0]["target_b"] is None


async def test_unmigrated_user_sees_everything(session: AsyncSession):
    user, workout_set = await _legacy_user(session, 982004)
    repo = WorkoutRepository(session)
    await repo.record_workout(**_kwargs(user, workout_set, BASE, 11))
    await repo.record_backdated_workout(**_kwargs(user, workout_set, BASE + timedelta(hours=1), 12))

    assert len(await _history(session, user.telegram_id)) == 2


async def test_near_miss_different_timestamp_is_not_hidden(session: AsyncSession):
    user, workout_set = await _legacy_user(session, 982005)
    workout = await WorkoutRepository(session).record_workout(**_kwargs(user, workout_set, BASE, 11))
    await _backfill(session, [workout])
    await session.execute(
        TrainingSession.__table__.update().where(TrainingSession.user_id == user.id)
        .values(performed_at=BASE + timedelta(microseconds=1)),
    )

    assert [item["workout_id"] for item in await _history(session, user.telegram_id)] == [workout.id]


async def test_near_miss_source_mismatch_is_not_hidden(session: AsyncSession):
    """Каскадная legacy ↔ сессия source=backdated на тот же момент — не её копия."""
    user, workout_set = await _legacy_user(session, 982006)
    workout = await WorkoutRepository(session).record_workout(**_kwargs(user, workout_set, BASE, 11))
    await _backfill(session, [workout])
    await session.execute(
        TrainingSession.__table__.update().where(TrainingSession.user_id == user.id)
        .values(source=SessionSource.BACKDATED),
    )

    assert [item["workout_id"] for item in await _history(session, user.telegram_id)] == [workout.id]


async def test_other_users_backfilled_session_does_not_hide(session: AsyncSession):
    user, workout_set = await _legacy_user(session, 982007)
    other, other_set = await _legacy_user(session, 982008)
    mine = await WorkoutRepository(session).record_workout(**_kwargs(user, workout_set, BASE, 11))
    theirs = await WorkoutRepository(session).record_workout(**_kwargs(other, other_set, BASE, 11))
    await _backfill(session, [theirs])  # копия есть только у другого пользователя на тот же момент

    assert [item["workout_id"] for item in await _history(session, user.telegram_id)] == [mine.id]
    assert await _history(session, other.telegram_id) == []


async def _live_flow_session(session: AsyncSession, user, *, exercise_id: int, **overrides) -> TrainingSession:
    """v2-сессия живого потока Mini App на тот же момент, что у legacy-записи."""
    repo = TrainingSessionRepository(session)
    created = await repo.create_session(
        user_id=user.id, source=SessionSource.PLAN, performed_at=BASE, effort=None, comment=None,
        blocks=[SessionBlockInput(exercise_id=exercise_id, sets=[
            SetLogInput(set_number=1, metric_type=MetricType.REPS, value=Decimal(10), unit="reps"),
        ])],
    )
    for field, value in overrides.items():
        setattr(created, field, value)
    await session.flush()
    return created


async def test_live_flow_sessions_at_identical_timestamp_do_not_hide(session: AsyncSession):
    """Живая сессия Mini App на тот же момент (другое упражнение / client_session_id / снимок / PlanItem)
    — не backfill-копия: legacy-запись остаётся видна."""
    user, workout_set = await _legacy_user(session, 982009)
    workout = await WorkoutRepository(session).record_workout(**_kwargs(user, workout_set, BASE, 11))
    block_a = await _get_or_create_exercise(session, name=_EXERCISE_BLOCK_A_NAME, subcategory="block_a")
    custom = Exercise(
        name="Свои подтягивания", metric_type=MetricType.REPS, category="pull_ups", subcategory="block_a",
        source_type="user", owner_user_id=user.id,
    )
    session.add(custom)
    await session.flush()

    # 1) другое (не backfill-овское) упражнение
    await _live_flow_session(session, user, exercise_id=custom.id)
    assert [item["workout_id"] for item in await _history(session, user.telegram_id)] == [workout.id]

    # 2) то же упражнение блока A, но с client_session_id (живой старт)
    await _live_flow_session(session, user, exercise_id=block_a.id, client_session_id=uuid.uuid4())
    # 3) со снимком Builder-тренировки
    await _live_flow_session(session, user, exercise_id=block_a.id, workout_snapshot={"schema_version": 1})
    # 4) связанная с PlanItem (запуск из плана)
    linked = await _live_flow_session(session, user, exercise_id=block_a.id)
    plan = TrainingPlan(user_id=user.id)
    session.add(plan)
    await session.flush()
    plan_item = PlanItem(training_plan_id=plan.id, exercise_id=block_a.id, count_per_week=1)
    session.add(plan_item)
    await session.flush()
    session.add(SessionPlanItem(session_id=linked.id, plan_item_id=plan_item.id))
    # 5) незавершённая сессия
    await _live_flow_session(session, user, exercise_id=block_a.id, status=SessionStatus.STARTED)
    await session.flush()

    assert [item["workout_id"] for item in await _history(session, user.telegram_id)] == [workout.id]


async def test_journal_days_do_not_double_count_migrated_workouts(session: AsyncSession):
    user, _workout_set, _post = await _migrated_user(session, 982010)

    body = (await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/journal/days?month=2026-10")).json()
    # 3 перенесённые (как v2-сессии) + 1 пост-миграционная legacy = 4 тренировки за день, не 7
    assert body["days"] == [{"date": "2026-10-02", "count": 4}]


def _key(workout_id: int, at: datetime, source: SessionSource = SessionSource.PLAN) -> LegacyWorkoutKey:
    return LegacyWorkoutKey(workout_id=workout_id, performed_at=at, source=source)


def test_matching_is_one_to_one():
    """Две legacy-записи на один момент и одна v2-копия: скрывается ровно одна (детерминированно —
    с меньшим id), вторая остаётся видна — лучше дубль, чем потеря записи."""
    workouts = [_key(2, BASE), _key(1, BASE)]
    assert find_backfilled_duplicates(workouts, [(BASE, SessionSource.PLAN)]) == [_key(1, BASE)]
    assert find_backfilled_duplicates(workouts, [(BASE, SessionSource.PLAN)] * 2) == [_key(1, BASE), _key(2, BASE)]
    assert find_backfilled_duplicates(workouts, []) == []
    assert find_backfilled_duplicates(workouts, [(BASE, SessionSource.FREEFORM)]) == []
