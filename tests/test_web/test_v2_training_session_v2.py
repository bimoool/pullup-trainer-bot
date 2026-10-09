"""TrainingSession v2 (issue #307, docs/domain/TRAINING_SESSION_V2.md) — сценарии J1–J15 задачи на
реальном Postgres через API. Нумерация J* — из постановки #307 (не путать с J1–J12
ACCEPTANCE_JOURNEYS_V2: там J7/J8/J9/J10 — клон без кредита / post-factum / активность / правка)."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.models_program import (
    Complex,
    ComplexItem,
    Exercise,
    PlanItem,
    ProgramInclusion,
    SessionBlock,
    SessionPlanItem,
    SessionStatus,
    SetLog,
    SetTarget,
    TrainingPlan,
    TrainingSession,
)
from app.db.repositories.training_sessions import TrainingSessionRepository
from app.domain.multi_program import MetricType, SessionSource
from tests.test_web._v2_client import v2_delete, v2_get, v2_patch, v2_post
from tests.test_web.test_v2_live_session import _setup_step_session
from tests.test_web.test_v2_live_session_workout_start import _user
from tests.test_web.test_v2_mixed_workout import _advance, _log_set

LIVE = "/api/v2/sessions/live"
REPS_4x6 = {"type": "reps_sets", "rest_seconds": 60, "prescription": {"source": "static", "sets": 4, "reps": 6}}
REPS_2x8 = {"type": "reps_sets", "rest_seconds": 30, "prescription": {"source": "static", "sets": 2, "reps": 8}}
MAX_2 = {"type": "max_effort", "rest_seconds": 0, "prescription": {"source": "static", "attempts": 2}}


def _past(days: int = 2) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).replace(microsecond=0).isoformat()


async def _workout(
    session: AsyncSession, owner: User, protocols: list[dict], *, title: str = "Моя тренировка",
) -> tuple[Complex, list[Exercise]]:
    workout = Complex(name=title, source_type="user", owner_user_id=owner.id)
    session.add(workout)
    await session.flush()
    exercises = []
    for index, protocol in enumerate(protocols):
        exercise = Exercise(name=f"Упражнение {index + 1}", metric_type=MetricType.REPS, category="ts-v2")
        session.add(exercise)
        await session.flush()
        session.add(ComplexItem(
            complex_id=workout.id, exercise_id=exercise.id, order_index=index, sets=9, protocol=protocol,
        ))
        exercises.append(exercise)
    await session.flush()
    return workout, exercises


async def _plan_item(session: AsyncSession, user: User, workout: Complex, exercise: Exercise) -> int:
    plan = await session.scalar(select(TrainingPlan).where(TrainingPlan.user_id == user.id))
    if plan is None:
        plan = TrainingPlan(user_id=user.id)
        session.add(plan)
        await session.flush()
    item = PlanItem(
        training_plan_id=plan.id, exercise_id=exercise.id, complex_id=workout.id, count_per_week=1, day_of_week=1,
    )
    session.add(item)
    await session.flush()
    return item.id


def _sets(*values: str) -> list[dict]:
    return [{"set_number": i + 1, "metric_type": "reps", "value": v, "unit": "reps"} for i, v in enumerate(values)]


async def _manual(session, user: User, workout: Complex, blocks: list[list[str]], **extra):
    exercise_ids = [
        row[0] for row in await session.execute(
            select(ComplexItem.exercise_id).where(ComplexItem.complex_id == workout.id).order_by(ComplexItem.order_index),
        )
    ]
    payload = {
        "source": "backdated", "performed_at": _past(), "workout_definition_id": workout.id,
        "blocks": [{"exercise_id": e, "sets": _sets(*values)} for e, values in zip(exercise_ids, blocks, strict=True)],
    }
    payload.update(extra)
    return await v2_post(session, user.telegram_id, "/api/v2/sessions", payload)


async def _start(session, user: User, payload: dict) -> dict:
    response = await v2_post(session, user.telegram_id, LIVE, {"client_session_id": str(uuid.uuid4()), **payload})
    assert response.status_code == 200, response.text
    return response.json()


async def _complete(session, user: User, session_id: int, **body) -> dict:
    response = await v2_post(session, user.telegram_id, f"{LIVE}/{session_id}/complete", {"abandoned": False, **body})
    assert response.status_code == 200, response.text
    return response.json()


async def _listed(session, user: User) -> list[dict]:
    response = await v2_get(session, user.telegram_id, "/api/v2/sessions?status=completed")
    assert response.status_code == 200, response.text
    return response.json()["sessions"]


async def _card(session, user: User, session_id: int) -> dict:
    return next(card for card in await _listed(session, user) if card["id"] == session_id)


async def _backdate_start(session: AsyncSession, session_id: int, minutes: int) -> None:
    started = datetime.now(UTC) - timedelta(minutes=minutes)
    await session.execute(
        update(TrainingSession).where(TrainingSession.id == session_id).values(performed_at=started, started_at=started),
    )
    await session.commit()


# --- J1: тренировка программы / своего плана → одна сессия, верный кредит ------------------------


async def test_j1_planned_workout_completion_one_session_with_credit_and_snapshot(session: AsyncSession):
    user = await _user(session, 307001)
    workout, [exercise] = await _workout(session, user, [REPS_2x8])
    plan_item_id = await _plan_item(session, user, workout, exercise)
    started = await _start(session, user, {"plan_item_ids": [plan_item_id]})
    await _backdate_start(session, started["id"], 25)
    done = await _complete(session, user, started["id"])

    assert done["status"] == "completed"
    assert await session.scalar(select(func.count()).select_from(TrainingSession)) == 1
    card = await _card(session, user, started["id"])
    assert card["plan_item_id"] == plan_item_id
    assert card["source_v2"] == "planned_live" and card["kind"] == "strength" and card["origin"] == "native"
    assert card["workout_definition_id"] == workout.id
    assert card["duration_source"] == "measured" and 25 * 60 - 5 <= card["duration_seconds"] <= 25 * 60 + 60
    snapshot = card["prescription_snapshot"]
    assert snapshot["title"] == "Моя тренировка" and snapshot["workout_definition_id"] == workout.id
    assert [len(b["sets"]) for b in snapshot["blocks"]] == [2]
    assert card["title"] == "Моя тренировка"


async def test_j1_course_main_session_is_fully_editable_and_cloneable(session: AsyncSession, user: User):
    inclusion, _roles, plan_item_ids = await _setup_step_session(session, user)
    started = await _start(session, user, {"plan_item_ids": [plan_item_ids["block_a"], plan_item_ids["block_b"]]})
    await _complete(session, user, started["id"])

    card = await _card(session, user, started["id"])
    assert card["source_v2"] == "planned_live"
    assert card["plan_item_id"] == plan_item_ids["block_a"]
    row = await session.get(TrainingSession, started["id"])
    assert row.program_inclusion_id == inclusion["id"]
    assert card["prescription_snapshot"]["provenance"]["kind"] == "progression"
    # ED1 (решение владельца, B1): сессия курса правится целиком и копируется — прогрессию двигает
    # только подход на максимум и только вперёд (#305). Удаление — прежний строгий предикат: нет.
    assert {"set_actuals", "comment", "date", "duration"} <= set(card["editable_fields"])
    assert card["can_edit"] is True and card["can_clone"] is True and card["can_delete"] is False


# --- J2: прямой старт → сессия без случайного кредита -----------------------------------------


async def test_j2_direct_start_never_credits_existing_occurrence(session: AsyncSession):
    user = await _user(session, 307002)
    workout, [exercise] = await _workout(session, user, [REPS_2x8])
    plan_item_id = await _plan_item(session, user, workout, exercise)  # то же занятие стоит в плане
    started = await _start(session, user, {"workout_id": workout.id})
    await _complete(session, user, started["id"])

    card = await _card(session, user, started["id"])
    assert card["source_v2"] == "direct_live" and card["plan_item_id"] is None
    assert card["workout_definition_id"] == workout.id
    assert await TrainingSessionRepository(session).credited_plan_item_ids([plan_item_id]) == set()


# --- J3: копия → новая сессия без унаследованного кредита ------------------------------------


async def test_j3_clone_of_planned_session_has_no_credit_and_keeps_identity(session: AsyncSession):
    user = await _user(session, 307003)
    workout, [exercise] = await _workout(session, user, [REPS_2x8])
    plan_item_id = await _plan_item(session, user, workout, exercise)
    started = await _start(session, user, {"plan_item_ids": [plan_item_id]})
    await _complete(session, user, started["id"])

    response = await v2_post(session, user.telegram_id, f"/api/v2/sessions/{started['id']}/clone", {})
    assert response.status_code == 201, response.text
    clone = response.json()
    assert clone["id"] != started["id"]
    assert clone["plan_item_id"] is None and clone["source_v2"] == "manual_existing_workout"
    assert clone["workout_definition_id"] == workout.id
    assert clone["prescription_snapshot"] == (await _card(session, user, started["id"]))["prescription_snapshot"]
    assert clone["duration_source"] == "unknown"  # копия не измерялась — не выдумываем
    credits = await TrainingSessionRepository(session).credits_for_plan_items([plan_item_id])
    assert [c[1] for c in credits] == [started["id"]]  # «N из M» не изменилось


async def test_j3_clone_of_external_activity_keeps_type_and_duration(session: AsyncSession, user: User):
    """Регрессия: копия активности раньше выходила пустой силовой записью."""
    created = await v2_post(session, user.telegram_id, "/api/v2/sessions", {
        "source": "freeform", "performed_at": _past(), "blocks": [], "activity_type": "running",
        "duration_seconds": 2700,
    })
    clone = await v2_post(session, user.telegram_id, f"/api/v2/sessions/{created.json()['id']}/clone", {})
    body = clone.json()
    assert (body["activity_type"], body["duration_seconds"], body["kind"]) == ("running", 2700, "external_activity")
    assert body["title"] == "Бег"


# --- J4/J5/J6: факт против рецепта ------------------------------------------------------------


async def test_j4_manual_existing_workout_preserves_actual_against_prescription(session: AsyncSession):
    user = await _user(session, 307004)
    workout, _ = await _workout(session, user, [REPS_4x6])
    response = await _manual(session, user, workout, [["6", "6", "5", "4"]])
    assert response.status_code == 200, response.text
    body = response.json()

    [block] = body["blocks"]
    assert [t["value"] for t in block["set_targets"]] == ["6.00"] * 4
    assert [log["value"] for log in block["set_logs"]] == ["6.00", "6.00", "5.00", "4.00"]
    assert [(o["target"], o["actual"]) for o in block["outcomes"]] == [
        ("6.00", "6.00"), ("6.00", "6.00"), ("6.00", "5.00"), ("6.00", "4.00"),
    ]
    stored = [row[0] for row in await session.execute(
        select(SetLog.value).join(SessionBlock).where(SessionBlock.session_id == body["id"]).order_by(SetLog.set_number),
    )]
    assert [str(v) for v in stored] == ["6.00", "6.00", "5.00", "4.00"]


async def test_j5_skipped_and_extra_sets_in_live_session(session: AsyncSession):
    user = await _user(session, 307005)
    workout, _ = await _workout(session, user, [REPS_4x6])
    body = await _start(session, user, {"workout_id": workout.id})
    body = await _advance(session, user, body)  # get_ready -> go
    await _log_set(session, user, body, set_index=0, value="6")
    extra = await v2_post(session, user.telegram_id, f"{LIVE}/{body['id']}/sets:batch", {"sets": [{
        "set_index": 1, "exercise_id": body["blocks"][0]["exercise_id"], "value": "3", "block_index": 0,
        "is_extra": True,
    }]})
    assert extra.status_code == 200, extra.text
    await _complete(session, user, body["id"], abandoned=True)  # раннее завершение

    card = await _card(session, user, body["id"])
    outcomes = card["blocks"][0]["outcomes"]
    assert [(o["status"], o["is_extra"]) for o in outcomes] == [
        ("performed", False), ("not_performed", False), ("not_performed", False), ("not_performed", False),
        ("performed", True),
    ]
    assert outcomes[1]["actual"] is None and outcomes[4]["actual"] == "3.00"
    assert card["status"] == "completed"


async def test_j5_manual_unfilled_exercise_is_not_performed_not_dropped(session: AsyncSession):
    user = await _user(session, 307015)
    workout, _ = await _workout(session, user, [REPS_2x8, REPS_2x8])
    body = (await _manual(session, user, workout, [["8", "8", "4"], []])).json()
    first, second = body["blocks"]
    assert [o["is_extra"] for o in first["outcomes"]] == [False, False, True]
    assert [o["status"] for o in second["outcomes"]] == ["not_performed", "not_performed"]


async def test_j6_max_set_marker_survives_persistence_and_readback(session: AsyncSession):
    user = await _user(session, 307006)
    workout, _ = await _workout(session, user, [MAX_2])
    body = (await _manual(session, user, workout, [["12", "10"]])).json()

    [block] = body["blocks"]
    assert [t["is_max_set"] for t in block["set_targets"]] == [True, True]
    assert [log["is_max_set"] for log in block["set_logs"]] == [True, True]
    assert [o["is_max_set"] for o in block["outcomes"]] == [True, True]
    flags = [row[0] for row in await session.execute(
        select(SetLog.is_max_set).join(SessionBlock).where(SessionBlock.session_id == body["id"]),
    )]
    assert flags == [True, True]
    assert [s["kind"] for s in body["prescription_snapshot"]["blocks"][0]["sets"]] == ["max_reps", "max_reps"]


# --- J7/J11: повтор и гонка — ни второй сессии, ни второго кредита ---------------------------


async def test_j7_retried_completion_and_manual_record_are_idempotent(session: AsyncSession):
    user = await _user(session, 307007)
    workout, [exercise] = await _workout(session, user, [REPS_2x8])
    plan_item_id = await _plan_item(session, user, workout, exercise)
    started = await _start(session, user, {"plan_item_ids": [plan_item_id]})
    await _backdate_start(session, started["id"], 30)
    first = await _complete(session, user, started["id"])
    duration = (await _card(session, user, started["id"]))["duration_seconds"]
    second = await _complete(session, user, started["id"], active_elapsed_ms=1)
    assert second["progression_skipped_reason"] == "already_completed" and first["id"] == second["id"]
    assert (await _card(session, user, started["id"]))["duration_seconds"] == duration  # повтор её не трогает
    assert len(await TrainingSessionRepository(session).credits_for_plan_items([plan_item_id])) == 1

    key = str(uuid.uuid4())
    one = await _manual(session, user, workout, [["8", "8"]], client_session_id=key)
    two = await _manual(session, user, workout, [["8", "8"]], client_session_id=key)
    assert one.status_code == two.status_code == 200 and one.json()["id"] == two.json()["id"]
    assert await session.scalar(select(func.count()).select_from(TrainingSession)) == 2


async def test_j7_engine_active_time_is_the_duration(session: AsyncSession):
    user = await _user(session, 307017)
    workout, _ = await _workout(session, user, [REPS_2x8])
    started = await _start(session, user, {"workout_id": workout.id})
    await _backdate_start(session, started["id"], 60)
    await _complete(session, user, started["id"], active_elapsed_ms=50 * 60 * 1000)  # 10 минут паузы
    card = await _card(session, user, started["id"])
    assert (card["duration_seconds"], card["duration_source"]) == (3000, "measured")


# --- J8: тренировка удалена/переименована после выполнения — история читается ----------------


async def test_j8_post_factum_existing_workout_keeps_identity_and_is_editable(session: AsyncSession):
    """D9 (ACCEPTANCE J8): заголовок = имя тренировки, «Изменить»/«Повторить»/«Открыть тренировку»,
    правка сохраняется, сессия — в истории тренировки и в панели упражнения Аналитики."""
    user = await _user(session, 307008)
    workout, [exercise] = await _workout(session, user, [REPS_2x8], title="Турник утром")
    created = await _manual(session, user, workout, [["8", "7"]])
    assert created.status_code == 200, created.text
    card = await _card(session, user, created.json()["id"])

    assert card["title"] == "Турник утром"
    assert card["source_v2"] == "manual_existing_workout" and card["workout_definition_id"] == workout.id
    assert card["can_edit"] is True and card["can_clone"] is True and card["can_delete"] is True
    assert card["workout_id"] == workout.id
    assert card["duration_source"] == "unknown" and card["duration_seconds"] is None  # D13: не «0 минут»

    edited = await v2_patch(session, user.telegram_id, f"/api/v2/sessions/{card['id']}", {
        "sets": [{"block_index": 0, "set_number": 2, "value": "8"}],
    })
    assert edited.status_code == 200, edited.text
    assert edited.json()["blocks"][0]["set_logs"][1]["value"] == "8.00" and edited.json()["revision"] == 1

    history = await v2_get(session, user.telegram_id, f"/api/v2/workouts/{workout.id}/sessions")
    assert [row["id"] for row in history.json()["sessions"]] == [card["id"]]
    analytics = (await v2_get(session, user.telegram_id, "/api/v2/analytics/training")).json()
    panel_ids = {entry["exercise_id"] for entry in analytics["exercises"]}
    assert exercise.id in panel_ids


async def test_j8_history_survives_rename_and_archive(session: AsyncSession):
    user = await _user(session, 307018)
    workout, [exercise] = await _workout(session, user, [REPS_2x8], title="Старое имя")
    plan_item_id = await _plan_item(session, user, workout, exercise)
    started = await _start(session, user, {"plan_item_ids": [plan_item_id]})
    await _complete(session, user, started["id"])
    before = await _card(session, user, started["id"])

    renamed = await v2_patch(session, user.telegram_id, f"/api/v2/workouts/{workout.id}", {"title": "Новое имя"})
    assert renamed.status_code == 200, renamed.text
    archived = await v2_delete(session, user.telegram_id, f"/api/v2/workouts/{workout.id}")
    assert archived.status_code == 204, archived.text

    after = await _card(session, user, started["id"])
    assert after["title"] == "Старое имя"  # S2: из снимка, а не из изменённого определения
    assert after["prescription_snapshot"] == before["prescription_snapshot"]
    assert after["blocks"] == before["blocks"]
    assert after["workout_id"] is None  # архивную тренировку не открыть — не мёртвая кнопка
    assert after["plan_item_id"] == plan_item_id
    assert await TrainingSessionRepository(session).credited_plan_item_ids([plan_item_id]) == {plan_item_id}


async def test_j8_manual_mismatched_composition_is_rejected(session: AsyncSession):
    user = await _user(session, 307028)
    workout, _ = await _workout(session, user, [REPS_2x8, REPS_2x8])
    bad = await v2_post(session, user.telegram_id, "/api/v2/sessions", {
        "source": "backdated", "performed_at": _past(), "workout_definition_id": workout.id,
        "blocks": [{"exercise_id": (await session.scalar(select(ComplexItem.exercise_id).where(
            ComplexItem.complex_id == workout.id, ComplexItem.order_index == 0,
        ))), "sets": _sets("8")}],
    })
    assert bad.status_code == 422
    assert await session.scalar(select(func.count()).select_from(TrainingSession)) == 0


# --- J9 (ACCEPTANCE): внешняя активность правится ----------------------------------------------


async def test_external_activity_edit_duration_type_and_date_keeps_duration(session: AsyncSession, user: User):
    created = (await v2_post(session, user.telegram_id, "/api/v2/sessions", {
        "source": "freeform", "performed_at": _past(), "blocks": [], "activity_type": "running",
        "duration_seconds": 2700,
    })).json()
    assert created["source_v2"] == "external_activity" and created["duration_source"] == "entered"
    path = f"/api/v2/sessions/{created['id']}"

    edited = await v2_patch(session, user.telegram_id, path, {"duration_seconds": 3600, "activity_type": "cycling"})
    assert edited.status_code == 200, edited.text
    assert (edited.json()["duration_seconds"], edited.json()["title"]) == (3600, "Велосипед")

    moved_day = (datetime.now(UTC) - timedelta(days=9)).date().isoformat()
    moved = await v2_patch(session, user.telegram_id, path, {"performed_on": moved_day})
    assert moved.json()["duration_seconds"] == 3600 and moved.json()["revision"] == 2  # R4

    assert (await v2_patch(session, user.telegram_id, path, {"duration_seconds": 30})).status_code == 422
    assert (await v2_patch(session, user.telegram_id, path, {"activity_type": "parkour"})).status_code == 422


async def test_date_edit_of_live_session_keeps_measured_duration(session: AsyncSession):
    """D13 / R4: раньше completed_at «подтягивался» к новой дате и длительность пропадала."""
    user = await _user(session, 307019)
    workout, _ = await _workout(session, user, [REPS_2x8])
    started = await _start(session, user, {"workout_id": workout.id})
    await _backdate_start(session, started["id"], 40)
    await _complete(session, user, started["id"])
    duration = (await _card(session, user, started["id"]))["duration_seconds"]

    day = (datetime.now(UTC) - timedelta(days=7)).date().isoformat()
    edited = await v2_patch(session, user.telegram_id, f"/api/v2/sessions/{started['id']}", {"performed_on": day})
    assert edited.status_code == 200, edited.text
    row = await session.get(TrainingSession, started["id"], populate_existing=True)
    assert row.duration_seconds == duration
    assert row.completed_at - row.performed_at == row.ended_at - row.started_at
    analytics = (await v2_get(session, user.telegram_id, "/api/v2/analytics/training")).json()
    assert analytics["metrics"]["total_minutes"] == duration // 60


async def _progression_fingerprint(session: AsyncSession, user: User) -> dict[str, list[str]]:
    """Всё, что прогрессия/план считают состоянием курса, — построчно текстом (байт в байт): инклюзии
    (progression_state, progression_state_rev, снимки, счётчики), занятия плана и цели подходов
    (уже выданные рецепты). Правка исторической сессии не должна менять ни одной строки."""
    uid = user.id

    async def rows(sql: str) -> list[str]:
        return [row[0] for row in await session.execute(text(sql), {"uid": uid})]

    return {
        "inclusions": await rows(
            "SELECT row_to_json(x)::text FROM program_inclusions x WHERE training_plan_id IN "
            "(SELECT id FROM training_plans WHERE user_id = :uid) ORDER BY id",
        ),
        "plan_items": await rows(
            "SELECT row_to_json(x)::text FROM plan_items x WHERE training_plan_id IN "
            "(SELECT id FROM training_plans WHERE user_id = :uid) ORDER BY id",
        ),
        "set_targets": await rows(
            "SELECT row_to_json(x)::text FROM set_targets x JOIN session_blocks b ON b.id = x.session_block_id "
            "JOIN training_sessions s ON s.id = b.session_id WHERE s.user_id = :uid ORDER BY x.id",
        ),
        "snapshots": await rows(
            "SELECT coalesce(prescription_snapshot::text, '-') FROM training_sessions WHERE user_id = :uid ORDER BY id",
        ),
    }


async def _completed_course_session(session: AsyncSession, user: User) -> tuple[dict, dict, int]:
    inclusion, _roles, plan_item_ids = await _setup_step_session(session, user)
    body = await _start(session, user, {"plan_item_ids": [plan_item_ids["block_a"], plan_item_ids["block_b"]]})
    body = await _advance(session, user, body)
    await _log_set(session, user, body, set_index=0, value="10")
    await _complete(session, user, body["id"])
    return inclusion, plan_item_ids, body["id"]


async def test_course_session_ordinary_set_edit_persists_without_touching_progression(session: AsyncSession, user: User):
    """B1 / решение владельца: обычный (не MAX) подход сессии курса правится; прогрессия, её ревизия,
    занятия плана и выданные рецепты не меняются (ретро-пересчёта нет)."""
    inclusion, _plan_item_ids, session_id = await _completed_course_session(session, user)
    before = await _progression_fingerprint(session, user)
    state_before = (await session.get(ProgramInclusion, inclusion["id"], populate_existing=True)).progression_state_rev
    revision = (await session.get(TrainingSession, session_id, populate_existing=True)).revision

    path = f"/api/v2/sessions/{session_id}"
    changed = await v2_patch(session, user.telegram_id, path, {"sets": [{"block_index": 0, "set_number": 1, "value": "12"}]})
    assert changed.status_code == 200, changed.text
    assert changed.json()["blocks"][0]["set_logs"][0]["value"] == "12.00"
    row = await session.get(TrainingSession, session_id, populate_existing=True)
    assert row.revision == revision + 1
    log = await session.scalar(
        select(SetLog).join(SessionBlock).where(SessionBlock.session_id == session_id, SetLog.set_number == 1)
        .execution_options(populate_existing=True),
    )
    assert log.value == 12

    assert await _progression_fingerprint(session, user) == before
    incl = await session.get(ProgramInclusion, inclusion["id"], populate_existing=True)
    assert incl.progression_state_rev == state_before


async def test_non_max_edit_does_not_drive_progression_byte_for_byte(session: AsyncSession, user: User):
    """Сколько бы раз и как бы ни правили рабочие подходы (вверх, вниз, метаданные вместе с ними) —
    состояние прогрессии, будущий план и рецепты остаются байт в байт прежними."""
    _inclusion, plan_item_ids, session_id = await _completed_course_session(session, user)
    before = await _progression_fingerprint(session, user)
    credits_before = await TrainingSessionRepository(session).credits_for_plan_items(list(plan_item_ids.values()))
    path = f"/api/v2/sessions/{session_id}"
    for value in ("30", "1", "11"):
        edited = await v2_patch(session, user.telegram_id, path, {
            "comment": f"правка {value}", "sets": [{"block_index": 0, "set_number": 1, "value": value}],
        })
        assert edited.status_code == 200, edited.text
    assert await _progression_fingerprint(session, user) == before
    assert await TrainingSessionRepository(session).credits_for_plan_items(list(plan_item_ids.values())) == credits_before


async def test_max_set_edit_corrects_history_only(session: AsyncSession, user: User):
    """Подход на максимум: исправленный исторический факт сохраняется, revision + 1; уже выданные
    рецепты/план/прогрессия задним числом не меняются. Как поправленный MAX попадёт в СЛЕДУЮЩИЙ рецепт —
    прямая граница прогрессии (#305), не здесь."""
    await _setup_step_session(session, user)  # у пользователя есть курс с прогрессией
    workout, [exercise] = await _workout(session, user, [MAX_2])
    plan_item_id = await _plan_item(session, user, workout, exercise)
    body = await _start(session, user, {"plan_item_ids": [plan_item_id]})
    body = await _advance(session, user, body)
    await _log_set(session, user, body, set_index=0, value="14")
    await _complete(session, user, body["id"])
    card = await _card(session, user, body["id"])
    # R2: «на максимум» — свойство цели (живая сессия пишет SetLog без флага), исход его наследует
    assert card["source_v2"] == "planned_live" and card["blocks"][0]["set_targets"][0]["is_max_set"] is True
    assert card["blocks"][0]["outcomes"][0]["is_max_set"] is True
    before = await _progression_fingerprint(session, user)
    revision = (await session.get(TrainingSession, body["id"], populate_existing=True)).revision

    edited = await v2_patch(session, user.telegram_id, f"/api/v2/sessions/{body['id']}", {
        "sets": [{"block_index": 0, "set_number": 1, "value": "16"}],
    })
    assert edited.status_code == 200, edited.text
    block = edited.json()["blocks"][0]
    assert block["set_logs"][0]["value"] == "16.00"
    assert block["outcomes"][0]["is_max_set"] is True and block["outcomes"][0]["actual"] == "16.00"
    assert (await session.get(TrainingSession, body["id"], populate_existing=True)).revision == revision + 1
    assert await _progression_fingerprint(session, user) == before
    assert [c[1] for c in await TrainingSessionRepository(session).credits_for_plan_items([plan_item_id])] == [body["id"]]


async def test_course_session_clone_has_no_credit_and_does_not_touch_progression(session: AsyncSession, user: User):
    """Копия сессии курса — по общему правилу копии: новая сессия без plan_item_id и инклюзии; кредиты
    занятий и прогрессия не меняются."""
    _inclusion, plan_item_ids, session_id = await _completed_course_session(session, user)
    before = await _progression_fingerprint(session, user)
    credits_before = await TrainingSessionRepository(session).credits_for_plan_items(list(plan_item_ids.values()))

    response = await v2_post(session, user.telegram_id, f"/api/v2/sessions/{session_id}/clone", {})
    assert response.status_code == 201, response.text
    clone = response.json()
    assert clone["id"] != session_id and clone["plan_item_id"] is None
    assert clone["source_v2"] in ("manual_existing_workout", "manual_custom")
    clone_row = await session.get(TrainingSession, clone["id"], populate_existing=True)
    assert clone_row.program_inclusion_id is None

    after = await _progression_fingerprint(session, user)
    assert after["inclusions"] == before["inclusions"] and after["plan_items"] == before["plan_items"]
    assert after["set_targets"][: len(before["set_targets"])] == before["set_targets"]  # у копии — свои цели
    assert await TrainingSessionRepository(session).credits_for_plan_items(list(plan_item_ids.values())) == credits_before


# --- J9/J10/J14 (#307): история, старые кредиты, повторный backfill — tests/test_scripts --------
# --- J12: контракт чтения — без двойного счёта ---------------------------------------------


async def test_j12_read_contract_counts_each_session_once(session: AsyncSession):
    user = await _user(session, 307012)
    workout, [exercise] = await _workout(session, user, [REPS_2x8])
    plan_item_id = await _plan_item(session, user, workout, exercise)
    live = await _start(session, user, {"plan_item_ids": [plan_item_id]})
    await _backdate_start(session, live["id"], 20)
    await _complete(session, user, live["id"])
    manual = (await _manual(session, user, workout, [["8", "8"]])).json()
    clone = (await v2_post(session, user.telegram_id, f"/api/v2/sessions/{manual['id']}/clone", {})).json()
    activity = (await v2_post(session, user.telegram_id, "/api/v2/sessions", {
        "source": "freeform", "performed_at": _past(), "blocks": [], "activity_type": "running",
        "duration_seconds": 1800,
    })).json()

    listed = await _listed(session, user)
    assert sorted(card["id"] for card in listed) == sorted({live["id"], manual["id"], clone["id"], activity["id"]})
    metrics = (await v2_get(session, user.telegram_id, "/api/v2/analytics/training")).json()["metrics"]
    assert metrics["total_workouts"] == 4
    assert metrics["without_duration"] == 2  # ручная и копия — длительность неизвестна, не 0
    history = (await v2_get(session, user.telegram_id, f"/api/v2/workouts/{workout.id}/sessions")).json()["sessions"]
    assert sorted(row["id"] for row in history) == sorted([live["id"], manual["id"], clone["id"]])


# --- J13: прерванная сессия — ни ложного завершения, ни потери сделанного ----------------------


async def test_j13_interrupted_live_session_is_not_counted_and_keeps_work(session: AsyncSession):
    user = await _user(session, 307013)
    workout, _ = await _workout(session, user, [REPS_2x8])
    body = await _start(session, user, {"workout_id": workout.id})
    body = await _advance(session, user, body)
    await _log_set(session, user, body, set_index=0, value="7")

    assert await _listed(session, user) == []  # STARTED не в истории
    metrics = (await v2_get(session, user.telegram_id, "/api/v2/analytics/training")).json()["metrics"]
    assert metrics["total_workouts"] == 0
    active = (await v2_get(session, user.telegram_id, f"{LIVE}/active")).json()["session"]
    assert active["id"] == body["id"] and active["blocks"][0]["set_logs"][0]["value"] == "7.00"
    row = await session.get(TrainingSession, body["id"])
    assert row.ended_at is None and row.duration_source is None  # длительность не выдумана заранее

    # восстановление: дозаписали и завершили — сделанное на месте
    await _complete(session, user, body["id"], abandoned=True)
    card = await _card(session, user, body["id"])
    assert [o["status"] for o in card["blocks"][0]["outcomes"]] == ["performed", "not_performed"]


# --- J15: чужая сессия ----------------------------------------------------------------------


async def test_j15_cross_user_access_is_404_and_foreign_key_is_rejected(session: AsyncSession):
    owner = await _user(session, 3070151)
    stranger = await _user(session, 3070152)
    workout, _ = await _workout(session, owner, [REPS_2x8])
    key = str(uuid.uuid4())
    created = (await _manual(session, owner, workout, [["8"]], client_session_id=key)).json()
    path = f"/api/v2/sessions/{created['id']}"

    assert (await v2_patch(session, stranger.telegram_id, path, {"comment": "x"})).status_code == 404
    assert (await v2_post(session, stranger.telegram_id, f"{path}/clone", {})).status_code == 404
    assert (await v2_delete(session, stranger.telegram_id, path)).status_code == 404
    assert await _listed(session, stranger) == []
    # чужая тренировка как определение — 404, чужой ключ идемпотентности — 422 без раскрытия
    foreign_workout = await v2_post(session, stranger.telegram_id, "/api/v2/sessions", {
        "source": "backdated", "performed_at": _past(), "workout_definition_id": workout.id,
        "blocks": [{"exercise_id": created["blocks"][0]["exercise_id"], "sets": _sets("8")}],
    })
    assert foreign_workout.status_code == 404
    own_workout, _ = await _workout(session, stranger, [REPS_2x8])
    reused = await _manual(session, stranger, own_workout, [["8"]], client_session_id=key)
    assert reused.status_code == 422
    assert await session.scalar(select(func.count()).select_from(TrainingSession)) == 1


async def test_legacy_m2m_credit_stays_readable(session: AsyncSession):
    """#304 B1 не регрессирует: старая M2M-связь — по-прежнему кредит."""
    user = await _user(session, 307010)
    workout, [exercise] = await _workout(session, user, [REPS_2x8])
    plan_item_id = await _plan_item(session, user, workout, exercise)
    legacy = TrainingSession(
        user_id=user.id, source=SessionSource.PLAN, status=SessionStatus.COMPLETED, performed_at=datetime.now(UTC) - timedelta(days=3),
        completed_at=datetime.now(UTC) - timedelta(days=3),
    )
    session.add(legacy)
    await session.flush()
    session.add(SessionPlanItem(session_id=legacy.id, plan_item_id=plan_item_id))
    await session.commit()
    repo = TrainingSessionRepository(session)
    assert await repo.credited_plan_item_ids([plan_item_id]) == {plan_item_id}
    card = await _card(session, user, legacy.id)
    assert card["source_v2"] == "planned_live"  # строка старого кода без v2-полей читается выведенным источником
    assert await session.scalar(select(func.count()).select_from(SetTarget)) == 0


async def test_absent_snapshots_are_sql_null_not_json_null(session: AsyncSession, user: User):
    """Регрессия (найдено E2E-сидом): явный None в JSONB-колонке пишется JSON-значением 'null', и
    предикаты «… IS NULL» (отпечаток backfill-копий, история тренировки, backfill-скрипт) ломаются."""
    pull = Exercise(name="Подтягивания", metric_type=MetricType.REPS, category="ts-v2")
    session.add(pull)
    await session.flush()
    manual = await v2_post(session, user.telegram_id, "/api/v2/sessions", {
        "source": "backdated", "performed_at": _past(), "blocks": [{"exercise_id": pull.id, "sets": _sets("8")}],
    })
    activity = await v2_post(session, user.telegram_id, "/api/v2/sessions", {
        "source": "freeform", "performed_at": _past(), "blocks": [], "activity_type": "running",
        "duration_seconds": 1800,
    })
    assert manual.status_code == activity.status_code == 200
    ids = [manual.json()["id"], activity.json()["id"]]
    assert await session.scalar(select(func.count()).select_from(TrainingSession).where(
        TrainingSession.id.in_(ids), TrainingSession.workout_snapshot.is_(None),
    )) == 2
    assert await session.scalar(select(func.count()).select_from(TrainingSession).where(
        TrainingSession.id == ids[1], TrainingSession.prescription_snapshot.is_(None),
    )) == 1


async def test_planned_session_without_proof_is_fully_editable_and_cloneable(session: AsyncSession, user: User):
    """B1 / решение владельца: плановая сессия (старая строка source=plan без связей и снимка) не
    становится «только метаданные» из-за происхождения из плана — правятся и метаданные, и значения
    подходов, копия разрешена. Удаление — прежний строгий предикат (недоказанная — нет)."""
    pull = Exercise(name="Подтягивания", metric_type=MetricType.REPS, category="ts-v2")
    session.add(pull)
    await session.flush()
    orphan = TrainingSession(
        user_id=user.id, source=SessionSource.PLAN, status=SessionStatus.COMPLETED,
        performed_at=datetime.now(UTC) - timedelta(days=1), completed_at=datetime.now(UTC) - timedelta(days=1),
    )
    session.add(orphan)
    await session.flush()
    block = SessionBlock(session_id=orphan.id, order_index=0, exercise_id=pull.id)
    session.add(block)
    await session.flush()
    session.add(SetLog(session_block_id=block.id, set_number=1, metric_type=MetricType.REPS, value=8, unit="reps"))
    await session.commit()

    card = await _card(session, user, orphan.id)
    assert card["source_v2"] == "planned_live"
    assert card["can_edit"] is True and card["can_clone"] is True and card["can_delete"] is False
    assert {"comment", "set_actuals"} <= set(card["editable_fields"])
    path = f"/api/v2/sessions/{orphan.id}"
    assert (await v2_patch(session, user.telegram_id, path, {"comment": "ок"})).status_code == 200
    changed = await v2_patch(session, user.telegram_id, path, {"sets": [{"block_index": 0, "set_number": 1, "value": "9"}]})
    assert changed.status_code == 200, changed.text
    assert changed.json()["blocks"][0]["set_logs"][0]["value"] == "9.00"
    cloned = await v2_post(session, user.telegram_id, f"{path}/clone", {})
    assert cloned.status_code == 201, cloned.text
    assert cloned.json()["plan_item_id"] is None
