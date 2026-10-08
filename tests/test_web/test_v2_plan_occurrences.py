"""DOMAIN-V2 Wave 1b (issue #304): одна строка PlanItem = одно занятие, явный кредит сессии, отдых
между стартами MAIN (OD-2: два полных дня отдыха, Пн → Чт), будущие недели стартуемы, свой план с
объёмом по неделям. Journeys J6, J7, J11, J12 (docs/domain/ACCEPTANCE_JOURNEYS_V2.md) + clone.

Время: «сегодня» плана — routes_v2._utcnow, «сейчас» проверки отдыха на старте — live_session._utcnow,
legacy-путь и бот получают now явно. Пользователь — в поясе UTC (даты = календарные даты UTC)."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select, update

from app.bot.handlers.workout import resolve_rest_day_notice
from app.db.models import User
from app.db.models_program import (
    Complex,
    ComplexItem,
    Exercise,
    PlanItem,
    PlanWeek,
    Program,
    ProgramItem,
    ProgressionStrategyProfile,
    SessionPlanItem,
    TrainingPlan,
    TrainingSession,
)
from app.db.repositories.training_sessions import TrainingSessionRepository
from app.domain.multi_program import MetricType, ProgramStructureType, WeekPhase
from app.domain.progression_strategy import ProgressionStrategyType
from app.services import live_session
from app.web import routes_v2
from app.web.routes import _resolve_plan_context
from tests.test_web._v2_client import v2_get, v2_patch, v2_post

MON = datetime(2026, 10, 5, 10, tzinfo=UTC)  # понедельник недели плана
TUE, WED, THU, FRI = (MON + timedelta(days=n) for n in (1, 2, 3, 4))
NEXT_MON = MON + timedelta(days=7)


@pytest.fixture
def clock(monkeypatch):
    def _set(now: datetime) -> None:
        monkeypatch.setattr(routes_v2, "_utcnow", lambda: now)
        monkeypatch.setattr(live_session, "_utcnow", lambda: now)
    return _set


async def _pullups_program(session, *, constraints=True) -> Program:
    """Как каталожные «Подтягивания»: STEP, роли block_a/block_b, 2 элемента × 3 в неделю, OD-2 = 3."""
    profile = ProgressionStrategyProfile(strategy_type=ProgressionStrategyType.STEP, name="Step 304", config={})
    session.add(profile)
    await session.flush()
    program = Program(
        name="Подтягивания", goal="test", structure_type=ProgramStructureType.RECURRING, category="pull_ups",
        progression_strategy_id=profile.id, access_level="free",
        config={"block_a": {"base_target": 10, "work_sets": 3}, "block_b": {"base_target": 3}},
        constraints=[{"spacing_group": "main", "min_days_between_starts": 3}] if constraints else None,
        frequency={"sessions_per_week": 3, "per_slot": {}},
    )
    session.add(program)
    await session.flush()
    for name, role in (("Подтягивания — объём", "block_a"), ("Подтягивания — сила", "block_b")):
        exercise = Exercise(name=name, metric_type=MetricType.REPS, category="pull_ups", subcategory=role)
        session.add(exercise)
        await session.flush()
        session.add(ProgramItem(
            program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=exercise.id, count_per_week=3, day_of_week=None,
        ))
    await session.flush()
    return program


async def _enrol(session, user: User, clock, now: datetime = MON) -> dict:
    user.timezone = "UTC"
    session.add(TrainingPlan(user_id=user.id, created_at=MON - timedelta(hours=1)))
    await session.flush()
    clock(now)
    program = await _pullups_program(session)
    response = await v2_post(session, user.telegram_id, "/api/v2/program-inclusions", {"program_id": program.id})
    assert response.status_code == 200
    return response.json()


async def _plan(session, user: User) -> dict:
    response = await v2_get(session, user.telegram_id, "/api/v2/plan")
    assert response.status_code == 200
    return response.json()["plan"]


def _week_items(plan: dict, week_number: int) -> list[dict]:
    week_id = next(w["id"] for w in plan["plan_weeks"] if w["week_number"] == week_number)
    return sorted(
        (i for i in plan["plan_items"] if i["plan_week_id"] == week_id),
        key=lambda i: (i["program_slot_key"] or "", i["occurrence_index"] or 0, i["id"]),
    )


def _summary(plan: dict, week_number: int) -> dict:
    week_id = next(w["id"] for w in plan["plan_weeks"] if w["week_number"] == week_number)
    return next(s for s in plan["week_summaries"] if s["plan_week_id"] == week_id)


async def _start(session, user: User, plan_item_ids: list[int] | None = None, workout_id: int | None = None):
    payload: dict = {"client_session_id": str(uuid.uuid4())}
    if workout_id is not None:
        payload["workout_id"] = workout_id
    else:
        payload["plan_item_ids"] = plan_item_ids
    return await v2_post(session, user.telegram_id, "/api/v2/sessions/live", payload)


async def _finish(session, user: User, started, *, performed_at: datetime) -> None:
    """Подход в первом блоке (иначе пустая брошенная сессия) → завершение → дата старта = performed_at."""
    session_id = started.json()["id"]
    exercise_id = started.json()["blocks"][0]["exercise_id"]
    batch = await v2_post(
        session, user.telegram_id, f"/api/v2/sessions/live/{session_id}/sets:batch",
        {"sets": [{"set_index": 0, "exercise_id": exercise_id, "value": 10, "block_index": 0}]},
    )
    assert batch.status_code == 200, batch.text
    done = await v2_post(session, user.telegram_id, f"/api/v2/sessions/live/{session_id}/complete", {"abandoned": False})
    assert done.status_code == 200, done.text
    await session.execute(update(TrainingSession).where(TrainingSession.id == session_id).values(performed_at=performed_at))
    await session.flush()


# --- Одно занятие = одна строка -----------------------------------------------------------------


async def test_course_week_has_three_main_occurrences_counted_as_three(session, user: User, clock):
    await _enrol(session, user, clock)
    plan = await _plan(session, user)
    items = _week_items(plan, 1)

    assert [(i["program_slot_key"], i["occurrence_index"], i["count_per_week"]) for i in items] == [
        ("main", 1, 1), ("main", 2, 1), ("main", 3, 1),
    ]
    summary = _summary(plan, 1)
    assert (summary["planned"], summary["completed"]) == (3, 0)  # «0 из 3», без скрытого множителя
    assert plan["spacing"] == [{
        "spacing_group": "main", "min_days_between_starts": 3, "last_start_date": None, "available_from": None,
    }]
    rows = (await session.execute(select(func.count()).select_from(PlanItem))).scalar_one()
    assert rows == 3  # ни одной агрегатной строки


async def test_get_plan_twice_creates_nothing_new(session, user: User, clock):
    await _enrol(session, user, clock)
    first = await _plan(session, user)
    second = await _plan(session, user)
    assert [i["id"] for i in first["plan_items"]] == [i["id"] for i in second["plan_items"]]


# --- J11: два полных дня отдыха -----------------------------------------------------------------


async def test_j11_monday_main_wednesday_rejected_thursday_allowed(session, user: User, clock):
    await _enrol(session, user, clock)
    occurrences = _week_items(await _plan(session, user), 1)

    clock(MON)
    started = await _start(session, user, [occurrences[0]["id"]])
    assert started.status_code == 200, started.text
    await _finish(session, user, started, performed_at=MON)

    clock(WED)
    plan = await _plan(session, user)
    states = {i["occurrence_index"]: i for i in _week_items(plan, 1)}
    assert states[1]["state"] == "completed" and states[1]["credited_session_id"] == started.json()["id"]
    assert states[2]["state"] == "too_early" and states[2]["available_from"] == "2026-10-08"
    assert (states[2]["projected_date"], states[3]["projected_date"]) == ("2026-10-08", "2026-10-11")
    assert (_summary(plan, 1)["planned"], _summary(plan, 1)["completed"], _summary(plan, 1)["infeasible"]) == (3, 1, 0)

    rejected = await _start(session, user, [states[2]["id"]])
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "too_early"
    assert rejected.json()["detail"]["available_from"] == "2026-10-08"

    # legacy /api/workout/plan и бот — тот же отказ (по v2-истории)
    context = await _resolve_plan_context(session, user.telegram_id, now=WED)
    assert (context.status, context.available_from) == ("too_early", date(2026, 10, 8))
    assert await resolve_rest_day_notice(session, telegram_id=user.telegram_id, now=WED) is not None

    clock(THU)
    allowed = await _start(session, user, [states[2]["id"]])
    assert allowed.status_code == 200, allowed.text
    credited = (await session.execute(
        select(TrainingSession.plan_item_id).where(TrainingSession.id == allowed.json()["id"]),
    )).scalar_one()
    assert credited == states[2]["id"]
    assert await resolve_rest_day_notice(session, telegram_id=user.telegram_id, now=THU) is None


async def test_k2_fresh_wednesday_third_main_is_infeasible(session, user: User, clock):
    await _enrol(session, user, clock, now=WED)
    clock(WED)
    plan = await _plan(session, user)
    states = [i["state"] for i in _week_items(plan, 1)]
    assert states == ["available", "available", "infeasible"]  # Ср, Сб, «не успеть на этой неделе»
    assert _summary(plan, 1)["infeasible"] == 1


async def test_admin_bypasses_rest(session, user: User, clock, monkeypatch):
    await _enrol(session, user, clock)
    occurrences = _week_items(await _plan(session, user), 1)
    started = await _start(session, user, [occurrences[0]["id"]])
    await _finish(session, user, started, performed_at=MON)
    monkeypatch.setattr(routes_v2.settings, "admin_ids", str(user.telegram_id))
    clock(TUE)
    assert (await _start(session, user, [occurrences[1]["id"]])).status_code == 200


# --- J12: будущие недели видимы и стартуемы ----------------------------------------------------


async def test_j12_future_week_occurrence_starts_and_credits_itself(session, user: User, clock):
    await _enrol(session, user, clock)
    assert (await v2_post(session, user.telegram_id, "/api/v2/plan/weeks", {"week_number": 2})).status_code == 200
    plan = await _plan(session, user)
    future = _week_items(plan, 2)
    assert [i["state"] for i in future][:1] == ["available"]

    started = await _start(session, user, [future[0]["id"]])
    assert started.status_code == 200, started.text  # раньше 422 «неделя ещё не началась» (D8)
    await _finish(session, user, started, performed_at=MON)

    plan = await _plan(session, user)
    assert _week_items(plan, 2)[0]["state"] == "completed"
    assert _summary(plan, 2)["completed"] == 1
    assert _summary(plan, 1)["completed"] == 0  # текущая неделя не засчитана по дате


# --- Кредит: прямой старт, копия, чужое занятие -------------------------------------------------


async def _user_workout(session, user: User) -> Complex:
    exercise = Exercise(name="Отжимания 304", metric_type=MetricType.REPS, category="Общая")
    session.add(exercise)
    await session.flush()
    workout = Complex(name="Моя силовая 304", source_type="user", owner_user_id=user.id)
    session.add(workout)
    await session.flush()
    session.add(ComplexItem(complex_id=workout.id, exercise_id=exercise.id, order_index=0, sets=3, target_value=10))
    await session.flush()
    return workout


async def test_j7_direct_start_credits_nothing(session, user: User, clock):
    await _enrol(session, user, clock)
    workout = await _user_workout(session, user)
    created = await v2_post(session, user.telegram_id, "/api/v2/custom-plans", {
        "display_name": "Свой", "workout_ids": [workout.id], "weeks": [1],
    })
    assert created.status_code == 200, created.text

    direct = await _start(session, user, workout_id=workout.id)
    assert direct.status_code == 200, direct.text
    await v2_post(session, user.telegram_id, f"/api/v2/sessions/live/{direct.json()['id']}/complete", {"abandoned": False})

    row = (await session.execute(
        select(TrainingSession.plan_item_id).where(TrainingSession.id == direct.json()["id"]),
    )).scalar_one()
    assert row is None
    plan = await _plan(session, user)
    assert _summary(plan, 1)["completed"] == 0  # «0 из N» — прямой старт план не засчитывает


async def test_clone_never_credits_a_plan_item(session, user: User, clock):
    await _enrol(session, user, clock)
    occurrences = _week_items(await _plan(session, user), 1)
    started = await _start(session, user, [occurrences[0]["id"]])
    await _finish(session, user, started, performed_at=MON)

    # Копия — единственный писатель «Повторить» (SessionEditingService.clone → repository.clone_session).
    clone_id = (await TrainingSessionRepository(session).clone_session(
        started.json()["id"], user_id=user.id, performed_at=TUE,
    )).id
    credit = (await session.execute(select(TrainingSession.plan_item_id).where(TrainingSession.id == clone_id))).scalar_one()
    links = (await session.execute(select(func.count()).select_from(SessionPlanItem).where(
        SessionPlanItem.session_id == clone_id,
    ))).scalar_one()
    assert (credit, links) == (None, 0)
    assert _summary(await _plan(session, user), 1)["completed"] == 1  # не «2 из 3»


async def test_cannot_credit_another_users_occurrence(session, user: User, clock):
    await _enrol(session, user, clock)
    occurrences = _week_items(await _plan(session, user), 1)
    other = User(telegram_id=2002, username="other")
    session.add(other)
    await session.flush()
    session.add(TrainingPlan(user_id=other.id, created_at=MON))
    await session.flush()

    response = await _start(session, other, [occurrences[0]["id"]])
    assert response.status_code == 404
    assert (await session.execute(select(func.count()).select_from(TrainingSession))).scalar_one() == 0


async def test_one_session_credits_at_most_one_occurrence(session, user: User, clock):
    await _enrol(session, user, clock)
    occurrences = _week_items(await _plan(session, user), 1)
    response = await _start(session, user, [occurrences[0]["id"], occurrences[1]["id"]])
    assert response.status_code == 422


async def test_repeat_of_credited_occurrence_does_not_credit_again(session, user: User, clock):
    await _enrol(session, user, clock)
    occurrences = _week_items(await _plan(session, user), 1)
    first = await _start(session, user, [occurrences[0]["id"]])
    await _finish(session, user, first, performed_at=MON - timedelta(days=4))
    again = await _start(session, user, [occurrences[0]["id"]])
    assert again.status_code == 200
    credit = (await session.execute(
        select(TrainingSession.plan_item_id).where(TrainingSession.id == again.json()["id"]),
    )).scalar_one()
    assert credit is None


# --- J6: свой план с объёмом по неделям --------------------------------------------------------


async def test_j6_custom_plan_2_2_0_2_2_0_exact_occurrence_counts(session, user: User, clock):
    user.timezone = "UTC"
    session.add(TrainingPlan(user_id=user.id, created_at=MON - timedelta(hours=1)))
    await session.flush()
    clock(MON)
    workout = await _user_workout(session, user)
    created = await v2_post(session, user.telegram_id, "/api/v2/custom-plans", {
        "display_name": "2/2/0/2/2/0", "workout_ids": [workout.id], "weeks": [2, 2, 0, 2, 2, 0],
        "preferred_weekdays": [1, 3, 5],
    })
    assert created.status_code == 200, created.text
    custom_id = created.json()["id"]

    # Неделя 6 вне окна «текущая .. +4» — материализуется, когда окно до неё дойдёт.
    clock(MON + timedelta(weeks=1))
    assert (await v2_post(session, user.telegram_id, "/api/v2/plan/weeks", {"week_number": 6})).status_code == 200

    counts = {}
    for number in range(1, 7):
        rows = (await session.execute(
            select(PlanItem).join(TrainingPlan).where(
                PlanItem.custom_plan_id == custom_id,
                PlanItem.origin_plan_week_id == select(PlanWeek.id).where(
                    PlanWeek.training_plan_id == TrainingPlan.id, PlanWeek.week_number == number,
                ).scalar_subquery(),
            ),
        )).scalars().all()
        counts[number] = len(rows)
        assert all(row.count_per_week == 1 for row in rows)
        assert [row.day_of_week for row in sorted(rows, key=lambda r: r.occurrence_index)] == [1, 3][: len(rows)]
    assert counts == {1: 2, 2: 2, 3: 0, 4: 2, 5: 2, 6: 0}

    plan = await _plan(session, user)
    assert [_summary(plan, n)["planned"] for n in (2, 3, 4)] == [2, 0, 2]

    # J6: старт одного занятия засчитывает именно его («1 из 2»), запись Журнала — с именем тренировки.
    week2 = _week_items(plan, 2)
    started = await _start(session, user, [week2[0]["id"]])
    assert started.status_code == 200, started.text
    done = await v2_post(session, user.telegram_id, f"/api/v2/sessions/live/{started.json()['id']}/complete", {})
    assert done.status_code == 200
    plan = await _plan(session, user)
    assert (_summary(plan, 2)["completed"], _summary(plan, 2)["planned"]) == (1, 2)
    assert [i["state"] for i in _week_items(plan, 2)][0] == "completed"
    journal = (await v2_get(session, user.telegram_id, "/api/v2/sessions?status=completed")).json()["sessions"]
    entry = next(e for e in journal if e["id"] == started.json()["id"])
    assert (entry["title"], entry["plan_item_id"]) == ("Моя силовая 304", week2[0]["id"])


async def test_custom_plan_weekday_hint_does_not_change_volume(session, user: User, clock):
    user.timezone = "UTC"
    session.add(TrainingPlan(user_id=user.id, created_at=MON - timedelta(hours=1)))
    await session.flush()
    clock(MON)
    workout = await _user_workout(session, user)
    for hint in (None, [6]):
        response = await v2_post(session, user.telegram_id, "/api/v2/custom-plans", {
            "display_name": f"hint {hint}", "workout_ids": [workout.id], "weeks": [3], "preferred_weekdays": hint,
        })
        assert response.status_code == 200
    rows = (await session.execute(select(PlanItem.custom_plan_id, func.count()).where(
        PlanItem.custom_plan_id.is_not(None)).group_by(PlanItem.custom_plan_id))).all()
    assert sorted(count for _, count in rows) == [3, 3]


async def test_custom_plan_rejects_foreign_workout_and_bad_vector(session, user: User, clock):
    user.timezone = "UTC"
    session.add(TrainingPlan(user_id=user.id, created_at=MON - timedelta(hours=1)))
    await session.flush()
    clock(MON)
    other = User(telegram_id=3003, username="other")
    session.add(other)
    await session.flush()
    foreign = await _user_workout(session, other)
    mine = await _user_workout(session, user)

    assert (await v2_post(session, user.telegram_id, "/api/v2/custom-plans", {
        "display_name": "x", "workout_ids": [foreign.id], "weeks": [1],
    })).status_code == 404
    assert (await v2_post(session, user.telegram_id, "/api/v2/custom-plans", {
        "display_name": "x", "workout_ids": [mine.id], "weeks": [0, 0],
    })).status_code == 422
    assert (await v2_post(session, user.telegram_id, "/api/v2/custom-plans", {
        "display_name": "x", "workout_ids": [mine.id], "weeks": [15],
    })).status_code == 422


# --- Перенос занятия (PL6) ------------------------------------------------------------------------


async def test_reschedule_course_occurrence_keeps_identity_and_completed_does_not_move(session, user: User, clock):
    await _enrol(session, user, clock)
    await v2_post(session, user.telegram_id, "/api/v2/plan/weeks", {"week_number": 2})
    plan = await _plan(session, user)
    occurrences = _week_items(plan, 1)
    week2_id = next(w["id"] for w in plan["plan_weeks"] if w["week_number"] == 2)

    moved = await v2_patch(
        session, user.telegram_id, f"/api/v2/plan-items/{occurrences[2]['id']}",
        {"day_of_week": 4, "plan_week_id": week2_id},
    )
    assert moved.status_code == 200, moved.text
    body = moved.json()
    assert (body["plan_week_id"], body["day_of_week"], body["scheduled_date"]) == (week2_id, 4, "2026-10-16")
    assert (body["origin_plan_week_id"], body["occurrence_index"], body["status"]) == (
        occurrences[2]["plan_week_id"], 3, "rescheduled",
    )
    # converge не досоздаёт «пропавшее» занятие недели 1 — идентичность занятия сохранена
    plan = await _plan(session, user)
    assert len(_week_items(plan, 1)) == 2 and len(_week_items(plan, 2)) == 4

    started = await _start(session, user, [occurrences[0]["id"]])
    await _finish(session, user, started, performed_at=MON)
    refused = await v2_patch(
        session, user.telegram_id, f"/api/v2/plan-items/{occurrences[0]['id']}", {"day_of_week": 2},
    )
    assert refused.status_code == 422
    performed = (await session.execute(
        select(TrainingSession.performed_at).where(TrainingSession.id == started.json()["id"]),
    )).scalar_one()
    assert performed == MON  # историческая сессия не двигается
