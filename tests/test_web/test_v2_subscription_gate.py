"""#300 / PROJECT_SPEC §5 «Подписка и доступ к курсам» (решение владельца D6): старт курсовой тренировки
(plan item с program_inclusion_id) требует действующей подписки, считанной СЕРВЕРОМ из
subscription_expires_at; свободные/свои тренировки и факультатив — без подписки."""

import uuid
from datetime import UTC, datetime, timedelta

from app.db.models import SubscriptionStatus, User
from app.db.models_program import Complex, ComplexItem, Exercise, PlanItem
from app.db.repositories.training_plans import TrainingPlanRepository
from app.db.repositories.users import UserRepository
from app.domain.multi_program import MetricType
from app.services.subscription import SubscriptionService
from tests.test_web._v2_client import v2_get, v2_post
from tests.test_web.test_v2_live_session import _setup_step_session

LIVE = "/api/v2/sessions/live"
REPS = {"type": "reps_sets", "rest_seconds": 30, "prescription": {"source": "static", "sets": 2, "reps": 8}}


async def _set_subscription(session, user: User, status: SubscriptionStatus, expires_in: timedelta | None) -> None:
    expires_at = None if expires_in is None else datetime.now(UTC) + expires_in
    await UserRepository(session).update_subscription_cache(user.id, status=status, expires_at=expires_at)


async def _start(session, user: User, plan_item_ids: list[int]):
    return await v2_post(
        session, telegram_id=user.telegram_id, path=LIVE,
        payload={"client_session_id": str(uuid.uuid4()), "plan_item_ids": plan_item_ids},
    )


async def _course_ids(session, user: User) -> list[int]:
    _, _, plan_item_ids = await _setup_step_session(session, user)
    return [plan_item_ids["block_a"], plan_item_ids["block_b"]]


async def _manual_item(session, user: User) -> int:
    exercise = Exercise(name="Планка", metric_type=MetricType.REPS, category="core")
    session.add(exercise)
    await session.flush()
    plan = await TrainingPlanRepository(session).get_for_user(user.id)
    item = PlanItem(training_plan_id=plan.id, exercise_id=exercise.id, count_per_week=2)
    session.add(item)
    await session.flush()
    return item.id


def _assert_subscription_required(response) -> None:
    assert response.status_code == 402
    assert response.json()["detail"]["code"] == "subscription_required"


async def test_expired_user_cannot_start_course_session(session, user: User):
    ids = await _course_ids(session, user)
    await _set_subscription(session, user, SubscriptionStatus.EXPIRED, timedelta(days=-1))

    _assert_subscription_required(await _start(session, user, ids))


async def test_stale_trial_cache_with_past_expiry_is_denied(session, user: User):
    """Кэш статуса `trial`, но срок прошёл (ничто не переводит в EXPIRED само) — доступ считается по сроку."""
    ids = await _course_ids(session, user)
    await _set_subscription(session, user, SubscriptionStatus.TRIAL, timedelta(days=-1))

    _assert_subscription_required(await _start(session, user, ids))


async def test_user_without_subscription_cannot_start_course_session(session, user: User):
    ids = await _course_ids(session, user)
    await _set_subscription(session, user, SubscriptionStatus.NONE, None)

    _assert_subscription_required(await _start(session, user, ids))


async def test_trial_and_active_users_can_start_course_session(session, user: User):
    ids = await _course_ids(session, user)

    await _set_subscription(session, user, SubscriptionStatus.TRIAL, timedelta(days=3))
    response = await _start(session, user, ids)
    assert response.status_code == 200
    # завершим, чтобы не упереться в «одна активная сессия»
    complete = await v2_post(
        session, telegram_id=user.telegram_id, path=f"{LIVE}/{response.json()['id']}/complete",
        payload={"abandoned": True},
    )
    assert complete.status_code == 200

    await _set_subscription(session, user, SubscriptionStatus.ACTIVE, timedelta(days=30))
    assert (await _start(session, user, ids)).status_code == 200


async def test_denied_start_creates_no_session(session, user: User):
    ids = await _course_ids(session, user)
    await _set_subscription(session, user, SubscriptionStatus.EXPIRED, timedelta(days=-1))
    _assert_subscription_required(await _start(session, user, ids))

    active = await v2_get(session, telegram_id=user.telegram_id, path=f"{LIVE}/active")
    assert active.json()["session"] is None


async def test_expired_user_can_start_own_workout_and_manual_plan_item(session, user: User):
    await _set_subscription(session, user, SubscriptionStatus.EXPIRED, timedelta(days=-1))
    workout = Complex(name="Моя", source_type="user", owner_user_id=user.id)
    session.add(workout)
    await session.flush()
    exercise = Exercise(name="Подтягивания", metric_type=MetricType.REPS, category="pull")
    session.add(exercise)
    await session.flush()
    session.add(ComplexItem(complex_id=workout.id, exercise_id=exercise.id, order_index=0, sets=2, protocol=REPS))
    await session.flush()
    await TrainingPlanRepository(session).get_or_create_for_user(user.id)
    manual_id = await _manual_item(session, user)

    own = await v2_post(
        session, telegram_id=user.telegram_id, path=LIVE,
        payload={"client_session_id": str(uuid.uuid4()), "workout_id": workout.id},
    )
    assert own.status_code == 200
    await v2_post(
        session, telegram_id=user.telegram_id, path=f"{LIVE}/{own.json()['id']}/complete", payload={"abandoned": True},
    )
    assert (await _start(session, user, [manual_id])).status_code == 200


async def test_mixed_course_and_own_items_are_denied_for_expired_user(session, user: User):
    course = await _course_ids(session, user)
    manual_id = await _manual_item(session, user)
    await _set_subscription(session, user, SubscriptionStatus.EXPIRED, timedelta(days=-1))

    _assert_subscription_required(await _start(session, user, [manual_id, *course]))


async def test_admin_grant_restores_course_start_without_rebuilding_plan(session, user: User):
    ids = await _course_ids(session, user)
    await _set_subscription(session, user, SubscriptionStatus.EXPIRED, timedelta(days=-1))
    _assert_subscription_required(await _start(session, user, ids))

    await SubscriptionService(session).grant_by_admin(user.id, now=datetime.now(UTC), days=30)

    response = await _start(session, user, ids)  # те же plan_item_ids: план не пересобирали
    assert response.status_code == 200


async def test_retry_of_already_started_session_is_not_blocked_after_expiry(session, user: User):
    ids = await _course_ids(session, user)
    await _set_subscription(session, user, SubscriptionStatus.TRIAL, timedelta(days=3))
    client_session_id = str(uuid.uuid4())
    payload = {"client_session_id": client_session_id, "plan_item_ids": ids}
    first = await v2_post(session, telegram_id=user.telegram_id, path=LIVE, payload=payload)
    assert first.status_code == 200

    await _set_subscription(session, user, SubscriptionStatus.TRIAL, timedelta(days=-1))
    retry = await v2_post(session, telegram_id=user.telegram_id, path=LIVE, payload=payload)
    assert retry.status_code == 200
    assert retry.json()["id"] == first.json()["id"]


async def test_post_sessions_course_plan_record_requires_subscription(session, user: User):
    await _course_ids(session, user)
    inclusion_id = (await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/plan")).json()["plan"][
        "program_inclusions"
    ][0]["id"]
    await _set_subscription(session, user, SubscriptionStatus.EXPIRED, timedelta(days=-1))

    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions",
        payload={
            "source": "plan", "program_inclusion_id": inclusion_id, "performed_at": datetime.now(UTC).isoformat(),
            "blocks": [],
        },
    )
    _assert_subscription_required(response)


async def test_subscription_endpoint_reports_expired_not_stale_trial(session, user: User):
    """FD-11: кэш `trial` после истечения — Mini App видит «истекла» и has_access=False."""
    await _set_subscription(session, user, SubscriptionStatus.TRIAL, timedelta(days=-1))
    from tests.test_web.test_subscription import _get_subscription

    body = await _get_subscription(session, user.telegram_id)

    assert body["status"] == "expired"
    assert body["has_access"] is False
    assert "истекла" in body["status_label"]
