"""Решение владельца 2026-10-17 (PROJECT_SPEC «Подписка и доступ к курсам», app/domain/program_access.py): бесплатна
только программа «Подтягивания»; факультатив, доп./свободные/свои тренировки, другие программы, свои упражнения,
тренировки и планы, добавление их в план и их выполнение — по подписке. Гейт — на сервере (прямые запросы к API без
подписки получают 402 subscription_required и ничего не создают), уже созданные данные остаются (просмотр, история,
удаление — бесплатно), идущая тренировка завершается и сохраняется даже после истечения подписки.

Пользователь без подписки — status NONE (никогда не было триала) или EXPIRED (срок вчера); с подпиской — TRIAL."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.db.models import SubscriptionStatus, User
from app.db.models_program import (
    Complex,
    ComplexItem,
    CustomPlan,
    Exercise,
    PlanItem,
    ProgramInclusion,
    TrainingSession,
)
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.elective_workouts import ElectiveWorkoutRepository
from app.db.repositories.training_plans import TrainingPlanRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.multi_program import MetricType
from app.domain.session import BlockLog
from tests.test_web._v2_client import v2_delete, v2_get, v2_patch, v2_post
from tests.test_web.test_free_program_access import (
    _current_course_items,
    _free_program,
    _run_workout,
)
from tests.test_web.test_v2_live_session import _make_step_program

LIVE = "/api/v2/sessions/live"
REPS = {"type": "reps_sets", "rest_seconds": 30, "prescription": {"source": "static", "sets": 2, "reps": 8}}


async def _set_subscription(session, user: User, status: SubscriptionStatus, expires_in: timedelta | None) -> User:
    expires_at = None if expires_in is None else datetime.now(UTC) + expires_in
    return await UserRepository(session).update_subscription_cache(user.id, status=status, expires_at=expires_at)


async def _no_subscription(session, user: User) -> User:
    return await _set_subscription(session, user, SubscriptionStatus.NONE, None)


async def _expire(session, user: User) -> User:
    return await _set_subscription(session, user, SubscriptionStatus.EXPIRED, timedelta(days=-1))


def _assert_402(response) -> None:
    assert response.status_code == 402, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "subscription_required"
    assert "Подтягивания" in detail["message"]  # объяснение: бесплатная программа остаётся бесплатной
    assert "быстрее" not in detail["message"].lower()  # без обещаний прогресса


async def _system_exercise(session) -> Exercise:
    exercise = Exercise(name="Отжимания (гейт)", metric_type=MetricType.REPS, category="push")
    session.add(exercise)
    await session.flush()
    return exercise


async def _own_workout(session, user: User, exercise: Exercise) -> tuple[Complex, ComplexItem]:
    workout = Complex(name="Моя тренировка", source_type="user", owner_user_id=user.id)
    session.add(workout)
    await session.flush()
    item = ComplexItem(complex_id=workout.id, exercise_id=exercise.id, order_index=0, sets=2, protocol=REPS)
    session.add(item)
    await session.flush()
    return workout, item


async def _count(session, model, **where) -> int:
    query = select(func.count()).select_from(model)
    for column, value in where.items():
        query = query.where(getattr(model, column) == value)
    return (await session.execute(query)).scalar_one()


async def _start_live(session, user: User, *, plan_item_ids=None, workout_id=None, client_session_id=None):
    payload = {"client_session_id": str(client_session_id or uuid.uuid4())}
    if workout_id is not None:
        payload["workout_id"] = workout_id
    else:
        payload["plan_item_ids"] = plan_item_ids
    return await v2_post(session, telegram_id=user.telegram_id, path=LIVE, payload=payload)


async def _backdated_payload(exercise: Exercise) -> dict:
    return {
        "source": "backdated", "performed_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
        "blocks": [{"exercise_id": exercise.id, "sets": [{"set_number": 1, "metric_type": "reps", "value": "8", "unit": "reps"}]}],
    }


# --- 1. Прямые запросы к API без подписки: 402 и ничего не создано -----------------------------------------


@pytest.mark.parametrize("make_unsubscribed", [_no_subscription, _expire])
async def test_unsubscribed_user_cannot_create_own_content_via_api(session, user: User, make_unsubscribed):
    exercise = await _system_exercise(session)
    user = await make_unsubscribed(session, user)
    tg = user.telegram_id

    _assert_402(await v2_post(session, tg, "/api/v2/exercises", {"name": "Своё упражнение"}))
    assert await _count(session, Exercise, owner_user_id=user.id) == 0

    _assert_402(await v2_post(session, tg, "/api/v2/workouts", {"title": "Своя"}))
    assert await _count(session, Complex, owner_user_id=user.id) == 0

    workout, _item = await _own_workout(session, user, exercise)  # создана раньше (при подписке)
    _assert_402(await v2_post(session, tg, "/api/v2/custom-plans", {"display_name": "Мой план", "workout_ids": [workout.id], "weeks": [2]}))
    assert await _count(session, CustomPlan, user_id=user.id) == 0

    _assert_402(await v2_post(session, tg, "/api/v2/plan-items", {"complex_id": workout.id, "count_per_week": 1}))
    _assert_402(await v2_post(session, tg, "/api/v2/plan-items", {"exercise_id": exercise.id, "count_per_week": 1}))
    _assert_402(await v2_post(session, tg, "/api/v2/plan/weeks", {"week_number": 1}))
    assert await _count(session, PlanItem) == 0


async def test_unsubscribed_user_cannot_edit_or_copy_existing_own_workout(session, user: User):
    exercise = await _system_exercise(session)
    workout, item = await _own_workout(session, user, exercise)
    user = await _expire(session, user)
    tg = user.telegram_id
    base = f"/api/v2/workouts/{workout.id}"

    _assert_402(await v2_post(session, tg, f"{base}/items", {"exercise_id": exercise.id, "protocol": REPS}))
    _assert_402(await v2_patch(session, tg, f"{base}/items/{item.id}", {"protocol": REPS}))
    _assert_402(await v2_post(session, tg, f"{base}/items/{item.id}/move", {"direction": "down"}))
    _assert_402(await v2_patch(session, tg, base, {"title": "Новое имя"}))
    _assert_402(await v2_post(session, tg, f"{base}/duplicate", {}))
    _assert_402(await v2_delete(session, tg, f"{base}/items/{item.id}"))
    await session.refresh(workout)
    assert workout.name == "Моя тренировка"
    assert await _count(session, ComplexItem, complex_id=workout.id) == 1
    assert await _count(session, Complex, owner_user_id=user.id) == 1


async def test_unsubscribed_user_cannot_add_other_program_but_can_add_free_pullups(session, user: User):
    premium = await _make_step_program(session)
    free = await _free_program(session)
    user = await _no_subscription(session, user)

    _assert_402(await v2_post(session, user.telegram_id, "/api/v2/program-inclusions", {"program_id": premium.id}))
    assert await _count(session, ProgramInclusion, program_id=premium.id) == 0

    added = await v2_post(
        session, user.telegram_id, "/api/v2/program-inclusions",
        {"program_id": free.id, "program_version": "pullups_legacy_step"},
    )
    assert added.status_code == 200, added.text
    # неизвестная программа — по-прежнему 404, не 402
    assert (await v2_post(session, user.telegram_id, "/api/v2/program-inclusions", {"program_id": 987654321})).status_code == 404


async def test_unsubscribed_user_cannot_start_extra_workouts_live(session, user: User):
    exercise = await _system_exercise(session)
    workout, _ = await _own_workout(session, user, exercise)
    catalog = Complex(name="Готовая (гейт)", source_type="system", owner_user_id=None)
    session.add(catalog)
    await session.flush()
    session.add(ComplexItem(complex_id=catalog.id, exercise_id=exercise.id, order_index=0, sets=2, protocol=REPS))
    plan = await TrainingPlanRepository(session).get_or_create_for_user(user.id)
    manual = PlanItem(training_plan_id=plan.id, exercise_id=exercise.id, complex_id=workout.id, count_per_week=1)
    session.add(manual)
    await session.flush()
    user = await _expire(session, user)

    _assert_402(await _start_live(session, user, workout_id=workout.id))
    _assert_402(await _start_live(session, user, workout_id=catalog.id))
    _assert_402(await _start_live(session, user, plan_item_ids=[manual.id]))
    assert (await v2_get(session, user.telegram_id, f"{LIVE}/active")).json()["session"] is None
    # чужая/несуществующая тренировка — 404 (видимость проверяется раньше подписки)
    assert (await _start_live(session, user, workout_id=987654321)).status_code == 404


async def test_mixed_main_plus_extra_start_is_denied_whole_and_main_alone_works(session, user: User):
    inclusion = await v2_post(
        session, user.telegram_id, "/api/v2/program-inclusions",
        {"program_id": (await _free_program(session)).id, "program_version": "pullups_legacy_step"},
    )
    inclusion = inclusion.json()
    main_ids = await _current_course_items(session, user, inclusion["id"])
    exercise = await _system_exercise(session)
    plan = await TrainingPlanRepository(session).get_for_user(user.id)
    extra = PlanItem(training_plan_id=plan.id, exercise_id=exercise.id, count_per_week=1)
    # строка «Подтягиваний» старой формы (до разворота в занятия, старый клиент) — её можно прислать вместе с доп.
    legacy_main = PlanItem(
        training_plan_id=plan.id, exercise_id=inclusion["snapshot"]["exercises"][0]["exercise_id"], count_per_week=3,
        program_inclusion_id=inclusion["id"],
    )
    session.add_all([extra, legacy_main])
    await session.flush()
    user = await _no_subscription(session, user)

    _assert_402(await _start_live(session, user, plan_item_ids=[legacy_main.id, extra.id]))
    _assert_402(await _start_live(session, user, plan_item_ids=[extra.id, legacy_main.id]))
    # с занятием (#304) смешанный запрос отклоняется целиком ещё до гейта — тоже без сессии
    assert (await _start_live(session, user, plan_item_ids=[*main_ids, extra.id])).status_code in (402, 422)
    assert (await v2_get(session, user.telegram_id, f"{LIVE}/active")).json()["session"] is None
    # основная тренировка «Подтягиваний» одна — бесплатно
    assert await _run_workout(session, user, inclusion, main_ids)


async def test_unsubscribed_user_cannot_record_or_repeat_extra_sessions(session, user: User):
    exercise = await _system_exercise(session)
    workout, _ = await _own_workout(session, user, exercise)
    existing = await v2_post(session, user.telegram_id, "/api/v2/sessions", await _backdated_payload(exercise))
    assert existing.status_code == 200, existing.text  # записано при подписке
    user = await _expire(session, user)
    tg = user.telegram_id
    before = await _count(session, TrainingSession, user_id=user.id)
    now = datetime.now(UTC) - timedelta(hours=1)

    _assert_402(await v2_post(session, tg, "/api/v2/sessions", await _backdated_payload(exercise)))
    _assert_402(await v2_post(session, tg, "/api/v2/sessions", {
        "source": "freeform", "activity_type": "running", "duration_seconds": 1800, "blocks": [],
        "performed_at": now.isoformat(),
    }))
    _assert_402(await v2_post(session, tg, "/api/v2/sessions", {
        "source": "backdated", "workout_definition_id": workout.id, "performed_at": now.isoformat(),
        "blocks": (await _backdated_payload(exercise))["blocks"],
    }))
    _assert_402(await v2_post(session, tg, "/api/v2/sessions", {
        "source": "elective", "performed_at": now.isoformat(), "blocks": [],
    }))
    _assert_402(await v2_post(session, tg, f"/api/v2/sessions/{existing.json()['id']}/clone", {}))
    assert await _count(session, TrainingSession, user_id=user.id) == before


async def _legacy_history(session, user: User) -> None:
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=datetime.now(UTC) - timedelta(days=3),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.BODYWEIGHT, block_b_equipment_value=None,
    )


async def test_unsubscribed_user_sees_elective_and_free_workout_offers_but_cannot_submit(session, user: User):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    await _legacy_history(session, user)
    user = await _expire(session, user)
    tg = user.telegram_id

    elective_plan = await v2_get(session, tg, "/api/elective/plan")
    assert elective_plan.status_code == 200
    assert elective_plan.json()["status"] == "ready" and elective_plan.json()["subscription_required"] is True
    assert elective_plan.json()["available_types"]  # предложение остаётся видимым
    _assert_402(await v2_post(session, tg, "/api/elective/submit", {"elective_type": "volume_target", "total_reps": 50}))
    assert await ElectiveWorkoutRepository(session).count_since(user.id, datetime.now(UTC) - timedelta(days=7)) == 0

    free_plan = await v2_get(session, tg, "/api/free-workout/plan")
    assert free_plan.status_code == 200 and free_plan.json()["subscription_required"] is True
    history_before = len(await WorkoutRepository(session).list_for_user(user.id))
    _assert_402(await v2_post(session, tg, "/api/free-workout/submit", {
        "working_reps": [10, 8], "max_reps": 6, "equipment_type": "bodyweight",
    }))
    assert len(await WorkoutRepository(session).list_for_user(user.id)) == history_before


async def test_subscribed_user_keeps_all_premium_features(session, user: User):
    """Контроль: с подпиской (TRIAL) всё перечисленное работает как раньше."""
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    await _legacy_history(session, user)
    tg = user.telegram_id
    exercise = await _system_exercise(session)

    assert (await v2_post(session, tg, "/api/v2/exercises", {"name": "Своё"})).status_code == 200
    workout = await v2_post(session, tg, "/api/v2/workouts", {"title": "Своя"})
    assert workout.status_code == 200
    workout_id = workout.json()["id"]
    assert (await v2_post(session, tg, f"/api/v2/workouts/{workout_id}/items", {"exercise_id": exercise.id, "protocol": REPS})).status_code == 200
    assert (await v2_post(session, tg, "/api/v2/plan-items", {"complex_id": workout_id, "count_per_week": 1})).status_code == 200
    assert (await v2_post(session, tg, "/api/v2/program-inclusions", {"program_id": (await _make_step_program(session)).id})).status_code == 200
    assert (await v2_post(session, tg, "/api/v2/sessions", await _backdated_payload(exercise))).status_code == 200
    elective_plan = (await v2_get(session, tg, "/api/elective/plan")).json()
    assert elective_plan["subscription_required"] is False
    assert (await v2_post(session, tg, "/api/elective/submit", {"elective_type": "volume_target", "total_reps": 50})).json()["status"] == "ok"
    live = await _start_live(session, user, workout_id=workout_id)
    assert live.status_code == 200, live.text


# --- 2. Уже созданные доп. активности: данные остаются, просмотр/история/удаление — бесплатно ---------------


async def test_existing_extra_activities_stay_viewable_and_removable_after_expiry(session, user: User):
    exercise = await _system_exercise(session)
    tg = user.telegram_id
    workout = (await v2_post(session, tg, "/api/v2/workouts", {"title": "Старая своя"})).json()
    assert (await v2_post(session, tg, f"/api/v2/workouts/{workout['id']}/items", {"exercise_id": exercise.id, "protocol": REPS})).status_code == 200
    plan_item = (await v2_post(session, tg, "/api/v2/plan-items", {"complex_id": workout["id"], "count_per_week": 1})).json()
    custom_plan = (await v2_post(session, tg, "/api/v2/custom-plans", {"display_name": "Мой", "workout_ids": [workout["id"]], "weeks": [1]})).json()
    recorded = (await v2_post(session, tg, "/api/v2/sessions", await _backdated_payload(exercise))).json()
    activity = (await v2_post(session, tg, "/api/v2/sessions", {
        "source": "freeform", "activity_type": "running", "duration_seconds": 1800, "blocks": [],
        "performed_at": (datetime.now(UTC) - timedelta(hours=3)).isoformat(),
    })).json()
    user = await _expire(session, user)

    # просмотр: свои тренировки, деталь, план, Журнал, аналитика
    assert workout["id"] in [w["id"] for w in (await v2_get(session, tg, "/api/v2/workouts")).json()["workouts"]]
    assert (await v2_get(session, tg, f"/api/v2/workouts/{workout['id']}")).status_code == 200
    plan = (await v2_get(session, tg, "/api/v2/plan")).json()["plan"]
    assert any(item["complex_id"] == workout["id"] for item in plan["plan_items"])
    journal = {s["id"] for s in (await v2_get(session, tg, "/api/v2/sessions?status=completed")).json()["sessions"]}
    assert {recorded["id"], activity["id"]} <= journal
    assert (await v2_get(session, tg, "/api/v2/analytics/training")).status_code == 200

    # управление своим: правка записи Журнала, убрать из плана, остановить свой план, удалить — бесплатно
    edited = await v2_patch(session, tg, f"/api/v2/sessions/{recorded['id']}", {"comment": "после истечения"})
    assert edited.status_code == 200, edited.text
    assert (await v2_post(session, tg, f"/api/v2/custom-plans/{custom_plan['id']}/deactivate", {})).status_code == 200
    assert (await v2_delete(session, tg, f"/api/v2/plan-items/{plan_item['id']}")).status_code in (204, 404)
    assert (await v2_delete(session, tg, f"/api/v2/sessions/{activity['id']}")).status_code in (200, 204)
    assert (await v2_delete(session, tg, f"/api/v2/workouts/{workout['id']}")).status_code == 204
    # ничего из истории не удалено гейтом: записанная сессия на месте
    assert await session.get(TrainingSession, recorded["id"]) is not None


# --- 3. Истечение посреди тренировки: начатая завершается и сохраняется -----------------------------------


async def test_extra_workout_started_before_expiry_finishes_and_saves(session, user: User):
    exercise = await _system_exercise(session)
    workout, _ = await _own_workout(session, user, exercise)
    client_session_id = uuid.uuid4()
    started = await _start_live(session, user, workout_id=workout.id, client_session_id=client_session_id)
    assert started.status_code == 200, started.text
    session_id = started.json()["id"]

    user = await _expire(session, user)  # подписка истекла посреди тренировки

    # повтор старта тем же client_session_id (переподключение) — та же сессия, не 402
    replay = await _start_live(session, user, workout_id=workout.id, client_session_id=client_session_id)
    assert replay.status_code == 200 and replay.json()["id"] == session_id
    batch = await v2_post(session, user.telegram_id, f"{LIVE}/{session_id}/sets:batch", {
        "sets": [{"set_index": i, "exercise_id": exercise.id, "value": "8"} for i in range(2)],
    })
    assert batch.status_code == 200, batch.text
    complete = await v2_post(session, user.telegram_id, f"{LIVE}/{session_id}/complete", {"abandoned": False})
    assert complete.status_code == 200, complete.text
    assert complete.json()["status"] == "completed"
    stored = await session.get(TrainingSession, session_id)
    await session.refresh(stored)
    assert stored.completed_at is not None
    # а новая доп. тренировка — уже по подписке
    _assert_402(await _start_live(session, user, workout_id=workout.id))


async def test_manual_record_replay_after_expiry_is_idempotent_not_402(session, user: User):
    """Запись Журнала, отправленная при подписке и досылаемая повтором (тот же client_session_id) после истечения,
    возвращает уже сохранённую сессию: досылка не теряется гейтом."""
    exercise = await _system_exercise(session)
    payload = {**await _backdated_payload(exercise), "client_session_id": str(uuid.uuid4())}
    first = await v2_post(session, user.telegram_id, "/api/v2/sessions", payload)
    assert first.status_code == 200, first.text
    user = await _expire(session, user)
    replay = await v2_post(session, user.telegram_id, "/api/v2/sessions", payload)
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == first.json()["id"]


# --- 4. Бесплатный путь «Подтягиваний» остаётся бесплатным целиком ----------------------------------------


async def test_never_subscribed_user_goes_through_free_pullups_without_any_402(session, user: User):
    """Пользователь, у которого подписки не было никогда (NONE): программа в план, тест на максимум, снаряжение,
    основная тренировка, запись результата, история и прогресс — без единого 402."""
    user = await _no_subscription(session, user)
    tg = user.telegram_id
    free = await _free_program(session)

    assert (await v2_get(session, tg, "/api/v2/programs")).status_code == 200
    assert (await v2_get(session, tg, f"/api/v2/programs/{free.id}/schedule")).status_code == 200
    inclusion = await v2_post(session, tg, "/api/v2/program-inclusions", {"program_id": free.id, "program_version": "pullups_legacy_step"})
    assert inclusion.status_code == 200, inclusion.text
    inclusion = inclusion.json()

    protocols = (await v2_get(session, tg, "/api/v2/assessments")).json()["protocols"]
    assert protocols
    result = await v2_post(session, tg, f"/api/v2/assessments/{protocols[0]['id']}/results", {
        "value": "8", "performed_on": datetime.now(UTC).date().isoformat(),
    })
    assert result.status_code in (200, 201), result.text

    band = await v2_post(session, tg, "/api/equipment/band-items", {"name": "Синяя", "resistance_kg": "15"})
    assert band.status_code in (200, 201), band.text

    session_id = await _run_workout(session, user, inclusion, await _current_course_items(session, user, inclusion["id"]))
    journal = (await v2_get(session, tg, "/api/v2/sessions?status=completed")).json()["sessions"]
    assert session_id in [s["id"] for s in journal]
    assert (await v2_get(session, tg, "/api/v2/analytics/training")).status_code == 200
    assert (await v2_get(session, tg, "/api/v2/plan")).status_code == 200
    # профиль и подписка открыты без оплаты
    assert (await v2_get(session, tg, "/api/profile")).status_code == 200
    subscription = await v2_get(session, tg, "/api/subscription")
    assert subscription.status_code == 200 and subscription.json()["has_access"] is False
