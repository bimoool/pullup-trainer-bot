"""POST /api/v2/sessions/live с workout_id — «Начать» на Workout Detail:
свободная (freeform) сессия из замороженного снимка своей тренировки без
PlanItem. Видимость §5 (чужая -> 404), идемпотентность client_session_id,
конфликт с уже активной сессией (409), прогрессия/счётчики плана не затронуты."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SubscriptionStatus, User
from app.db.models_program import Complex, ComplexItem, Exercise, SessionPlanItem, TrainingSession
from app.db.repositories.users import UserRepository
from app.domain.multi_program import MetricType
from tests.test_web._v2_client import v2_get, v2_post

REPS = {"type": "reps_sets", "rest_seconds": 30, "prescription": {"source": "static", "sets": 2, "reps": 8}}
LIVE = "/api/v2/sessions/live"


async def _user(session: AsyncSession, telegram_id: int) -> User:
    users = UserRepository(session)
    user = await users.create(telegram_id=telegram_id, username=f"u{telegram_id}")
    await users.complete_onboarding(user.id, datetime.now(UTC))
    # действующий триал: старт курсовой строки плана требует подписки (#300)
    await users.update_subscription_cache(
        user.id, status=SubscriptionStatus.TRIAL, expires_at=datetime.now(UTC) + timedelta(days=14),
    )
    return user


async def _workout(session: AsyncSession, owner: User, *, with_items: bool = True) -> Complex:
    workout = Complex(name="Моя тренировка", source_type="user", owner_user_id=owner.id)
    session.add(workout)
    await session.flush()
    if with_items:
        exercise = Exercise(name="Подтягивания", metric_type=MetricType.REPS, category="pull")
        session.add(exercise)
        await session.flush()
        session.add(ComplexItem(complex_id=workout.id, exercise_id=exercise.id, order_index=0, sets=9, protocol=REPS))
        await session.flush()
    return workout


async def _start(session, user: User, payload: dict):
    return await v2_post(session, telegram_id=user.telegram_id, path=LIVE, payload=payload)


async def test_start_by_workout_creates_freeform_session_without_plan_items(session: AsyncSession):
    user = await _user(session, 930001)
    workout = await _workout(session, user)

    response = await _start(session, user, {"client_session_id": str(uuid.uuid4()), "workout_id": workout.id})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "started"
    assert body["title"] == "Моя тренировка"
    assert len(body["blocks"][0]["targets"]) == 2  # из протокола, не из ComplexItem.sets=9
    persisted = await session.get(TrainingSession, body["id"])
    assert persisted.source == "freeform"
    assert persisted.workout_snapshot["workout_id"] == workout.id
    plan_links = await session.scalar(
        select(func.count()).select_from(SessionPlanItem).where(SessionPlanItem.session_id == body["id"]),
    )
    assert plan_links == 0


async def test_start_by_workout_is_idempotent_by_client_session_id(session: AsyncSession):
    user = await _user(session, 930002)
    workout = await _workout(session, user)
    payload = {"client_session_id": str(uuid.uuid4()), "workout_id": workout.id}

    first = await _start(session, user, payload)
    second = await _start(session, user, payload)

    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


async def test_start_by_foreign_or_missing_workout_is_404(session: AsyncSession):
    owner = await _user(session, 930003)
    stranger = await _user(session, 930004)
    workout = await _workout(session, owner)

    foreign = await _start(session, stranger, {"client_session_id": str(uuid.uuid4()), "workout_id": workout.id})
    missing = await _start(session, stranger, {"client_session_id": str(uuid.uuid4()), "workout_id": 999999})

    assert foreign.status_code == 404
    assert missing.status_code == 404


async def test_start_by_workout_conflicts_with_active_session(session: AsyncSession):
    user = await _user(session, 930005)
    workout = await _workout(session, user)
    first = await _start(session, user, {"client_session_id": str(uuid.uuid4()), "workout_id": workout.id})

    second = await _start(session, user, {"client_session_id": str(uuid.uuid4()), "workout_id": workout.id})

    assert second.status_code == 409
    assert second.json()["detail"] == {"code": "active_session_exists", "active_session_id": first.json()["id"]}
    active = await v2_get(session, telegram_id=user.telegram_id, path=f"{LIVE}/active")
    assert active.json()["session"]["id"] == first.json()["id"]


async def test_start_by_empty_workout_is_422(session: AsyncSession):
    user = await _user(session, 930006)
    workout = await _workout(session, user, with_items=False)

    response = await _start(session, user, {"client_session_id": str(uuid.uuid4()), "workout_id": workout.id})

    assert response.status_code == 422


async def test_workout_id_and_plan_item_ids_are_mutually_exclusive(session: AsyncSession):
    user = await _user(session, 930007)
    workout = await _workout(session, user)

    response = await _start(
        session, user,
        {"client_session_id": str(uuid.uuid4()), "workout_id": workout.id, "plan_item_ids": [1]},
    )

    assert response.status_code == 422


async def test_completed_workout_session_skips_progression_and_shows_in_history(session: AsyncSession):
    user = await _user(session, 930008)
    workout = await _workout(session, user)
    started = await _start(session, user, {"client_session_id": str(uuid.uuid4()), "workout_id": workout.id})
    session_id = started.json()["id"]

    done = await v2_post(
        session, telegram_id=user.telegram_id, path=f"{LIVE}/{session_id}/complete", payload={"abandoned": False},
    )

    assert done.status_code == 200
    assert done.json()["progression_skipped_reason"] == "not_plan_session"
    history = await v2_get(session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout.id}/sessions")
    assert [row["id"] for row in history.json()["sessions"]] == [session_id]


# --- R-4 (#289): plan-путь старта тоже уважает «одна активная сессия» -------------------------------

async def _plan_item_ids(session: AsyncSession, user: User) -> list[int]:
    from tests.test_web.test_v2_live_session import _setup_step_session

    _inclusion, _roles, plan_item_ids = await _setup_step_session(session, user)
    return [plan_item_ids["block_a"], plan_item_ids["block_b"]]


async def test_plan_start_conflicts_with_active_session_but_same_client_id_is_idempotent(session: AsyncSession):
    user = await _user(session, 930011)
    workout = await _workout(session, user)
    active = await _start(session, user, {"client_session_id": str(uuid.uuid4()), "workout_id": workout.id})
    plan_item_ids = await _plan_item_ids(session, user)

    blocked = await _start(session, user, {"client_session_id": str(uuid.uuid4()), "plan_item_ids": plan_item_ids})

    assert blocked.status_code == 409
    assert blocked.json()["detail"] == {"code": "active_session_exists", "active_session_id": active.json()["id"]}
    started = await session.scalar(select(func.count()).select_from(TrainingSession).where(TrainingSession.user_id == user.id))
    assert started == 1


async def test_plan_start_retry_with_same_client_id_returns_existing_session(session: AsyncSession):
    user = await _user(session, 930012)
    plan_item_ids = await _plan_item_ids(session, user)
    payload = {"client_session_id": str(uuid.uuid4()), "plan_item_ids": plan_item_ids}

    first = await _start(session, user, payload)
    retry = await _start(session, user, payload)  # сессия уже STARTED, но тот же id — не 409
    other = await _start(session, user, {"client_session_id": str(uuid.uuid4()), "plan_item_ids": plan_item_ids})

    assert first.status_code == retry.status_code == 200
    assert first.json()["id"] == retry.json()["id"]
    assert other.status_code == 409
    assert other.json()["detail"]["active_session_id"] == first.json()["id"]
