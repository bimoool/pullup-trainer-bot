"""#304 независимое ревью — снятие занятий без потери кредита (B1), «Остановить план» своего плана (B3),
строки убранного курса не «доступны» (C1). PROGRAM_PLAN_V2 §5 PL8–PL10, §7.

Каждый тест закрывает конкретный дефект ревью и доказан откатом исправления (см. комментарий #304):
* B1 — жёсткое удаление засчитанного занятия обнуляло session.plan_item_id (FK SET NULL), а сходимость
  пересоздавала занятие открытым: «1 из 2» → удалить → «0 из 2»;
* B3 — своего плана нельзя было остановить, сходимость материализовала его вечно;
* C1 — после «Убрать курс» занятия текущей недели отдавались available, а старт — 422.

Часы: «сегодня» плана и «сейчас» старта зафиксированы фикстурой clock (оба авторитетных источника)."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.models import User
from app.db.models_program import CustomPlan, PlanItem, PlanWeek, TrainingPlan, TrainingSession
from app.services import live_session
from app.web import routes_v2
from tests.test_web._v2_client import v2_delete, v2_post
from tests.test_web.test_v2_plan_occurrences import (
    MON,
    TUE,
    _enrol,
    _finish,
    _plan,
    _start,
    _summary,
    _user_workout,
    _week_items,
)


@pytest.fixture
def clock(monkeypatch):
    """Оба авторитетных часа: «сегодня» плана (routes_v2) и «сейчас» старта (live_session)."""
    def _set(now: datetime) -> None:
        monkeypatch.setattr(routes_v2, "_utcnow", lambda: now)
        monkeypatch.setattr(live_session, "_utcnow", lambda: now)
    return _set


async def _custom_setup(session, user: User, clock, *, weeks: list[int], repeat: str = "once") -> tuple[int, int]:
    user.timezone = "UTC"
    session.add(TrainingPlan(user_id=user.id, created_at=MON - timedelta(hours=1)))
    await session.flush()
    clock(MON)
    workout = await _user_workout(session, user)
    created = await v2_post(session, user.telegram_id, "/api/v2/custom-plans", {
        "display_name": "Свой", "workout_ids": [workout.id], "weeks": weeks, "repeat": repeat,
    })
    assert created.status_code == 200, created.text
    return created.json()["id"], workout.id


async def _custom_rows(session, custom_id: int) -> list[tuple]:
    """(неделя-источник, номер занятия, статус) всех строк своего плана в БД — снимок для «ничего не
    пересоздано / ничего не изменилось»."""
    rows = (await session.execute(
        select(PlanWeek.week_number, PlanItem.occurrence_index, PlanItem.status, PlanItem.id)
        .join(PlanWeek, PlanWeek.id == PlanItem.origin_plan_week_id)
        .where(PlanItem.custom_plan_id == custom_id)
        .order_by(PlanWeek.week_number, PlanItem.occurrence_index, PlanItem.id),
    )).all()
    return [tuple(row) for row in rows]


async def _credit_of(session, session_id: int) -> int | None:
    return (await session.execute(
        select(TrainingSession.plan_item_id).where(TrainingSession.id == session_id),
    )).scalar_one()


async def _credit_first_occurrence(session, user: User, week: int = 1) -> tuple[dict, int]:
    occurrence = _week_items(await _plan(session, user), week)[0]
    started = await _start(session, user, [occurrence["id"]])
    assert started.status_code == 200, started.text
    await _finish(session, user, started, performed_at=MON + timedelta(hours=1))
    return occurrence, started.json()["id"]


# --- B1: удаление занятия никогда не стирает кредит ---------------------------------------------


async def test_b1_credited_custom_occurrence_cannot_be_deleted_and_week_stays_1_of_2(session, user: User, clock):
    custom_id, _ = await _custom_setup(session, user, clock, weeks=[2, 2])
    occurrence, session_id = await _credit_first_occurrence(session, user)
    assert (_summary(await _plan(session, user), 1)["completed"], _summary(await _plan(session, user), 1)["planned"]) == (1, 2)
    rows_before = await _custom_rows(session, custom_id)

    response = await v2_delete(session, user.telegram_id, f"/api/v2/plan-items/{occurrence['id']}")

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == {
        "code": "credited_plan_item", "message": "Засчитанную тренировку удалить нельзя",
    }
    assert await _credit_of(session, session_id) == occurrence["id"]
    for _ in range(2):
        plan = await _plan(session, user)
        assert (_summary(plan, 1)["completed"], _summary(plan, 1)["planned"]) == (1, 2)
        assert _week_items(plan, 1)[0]["id"] == occurrence["id"]
        assert _week_items(plan, 1)[0]["state"] == "completed"
    assert await _custom_rows(session, custom_id) == rows_before  # ничего не пересоздано


async def test_b1_open_custom_occurrence_is_soft_removed_and_never_regenerated(session, user: User, clock):
    custom_id, _ = await _custom_setup(session, user, clock, weeks=[2, 2])
    first, second = _week_items(await _plan(session, user), 1)

    response = await v2_delete(session, user.telegram_id, f"/api/v2/plan-items/{second['id']}")

    assert response.status_code == 204, response.text
    after_delete = await _custom_rows(session, custom_id)
    assert (1, 2, "removed", second["id"]) in after_delete  # та же идентичность, мягко снята
    for _ in range(2):
        plan = await _plan(session, user)
        assert [i["id"] for i in _week_items(plan, 1)] == [first["id"]]
        assert _summary(plan, 1)["planned"] == 1
    assert await _custom_rows(session, custom_id) == after_delete  # без замены-«двойника»
    # Снятое занятие не стартуется и повторно не удаляется.
    assert (await _start(session, user, [second["id"]])).status_code == 422
    assert (await v2_delete(session, user.telegram_id, f"/api/v2/plan-items/{second['id']}")).status_code == 404


async def test_b1_delete_workout_keeps_credited_occurrence_and_its_credit(session, user: User, clock):
    custom_id, workout_id = await _custom_setup(session, user, clock, weeks=[2, 2])
    occurrence, session_id = await _credit_first_occurrence(session, user)
    manual = await v2_post(session, user.telegram_id, "/api/v2/plan-items", {"complex_id": workout_id, "count_per_week": 1})
    assert manual.status_code == 200, manual.text
    manual_id = manual.json()["id"]

    response = await v2_delete(session, user.telegram_id, f"/api/v2/workouts/{workout_id}")

    assert response.status_code == 204, response.text
    rows = await _custom_rows(session, custom_id)
    assert (1, 1, "open", occurrence["id"]) in rows  # засчитанная строка — как была
    assert all(status == "removed" for week, _, status, row_id in rows if row_id != occurrence["id"])
    assert await _credit_of(session, session_id) == occurrence["id"]
    assert (await session.execute(select(PlanItem.id).where(PlanItem.id == manual_id))).scalar_one_or_none() is None
    plan = await _plan(session, user)
    assert (_summary(plan, 1)["completed"], _summary(plan, 1)["planned"]) == (1, 1)
    assert await _custom_rows(session, custom_id) == rows


async def test_b1_manual_occurrence_uncredited_deletes_credited_is_protected(session, user: User, clock):
    _, workout_id = await _custom_setup(session, user, clock, weeks=[1])
    ids = []
    for _ in range(2):
        created = await v2_post(session, user.telegram_id, "/api/v2/plan-items", {"complex_id": workout_id, "count_per_week": 1})
        assert created.status_code == 200, created.text
        ids.append(created.json()["id"])
    started = await _start(session, user, [ids[0]])
    assert started.status_code == 200, started.text
    await _finish(session, user, started, performed_at=MON + timedelta(hours=1))

    assert (await v2_delete(session, user.telegram_id, f"/api/v2/plan-items/{ids[0]}")).status_code == 422
    assert await _credit_of(session, started.json()["id"]) == ids[0]
    assert (await v2_delete(session, user.telegram_id, f"/api/v2/plan-items/{ids[1]}")).status_code == 204
    remaining = set((await session.execute(select(PlanItem.id).where(PlanItem.id.in_(ids)))).scalars().all())
    assert remaining == {ids[0]}  # ручная незасчитанная — удалена жёстко (контракт #188 D2)


# --- B3: «Остановить план» ----------------------------------------------------------------------


async def test_b3_deactivate_cycle_plan_soft_removes_open_and_never_regenerates(session, user: User, clock):
    custom_id, _ = await _custom_setup(session, user, clock, weeks=[1, 1], repeat="cycle")
    assert (await v2_post(session, user.telegram_id, "/api/v2/plan/weeks", {"week_number": 3})).status_code == 200
    before = await _custom_rows(session, custom_id)
    assert [(week, status) for week, _, status, _ in before] == [(1, "open"), (2, "open"), (3, "open")]

    response = await v2_post(session, user.telegram_id, f"/api/v2/custom-plans/{custom_id}/deactivate", {})

    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is False
    after = await _custom_rows(session, custom_id)
    assert [(week, status) for week, _, status, _ in after] == [(1, "removed"), (2, "removed"), (3, "removed")]
    assert [row_id for *_, row_id in after] == [row_id for *_, row_id in before]

    # Время идёт: окно доходит до недель 4..8 (cycle продолжался бы вечно) — ничего не воскресает.
    clock(MON + timedelta(weeks=3))
    assert (await v2_post(session, user.telegram_id, "/api/v2/plan/weeks", {"week_number": 8})).status_code == 200
    for _ in range(2):
        plan = await _plan(session, user)
        assert not [i for i in plan["plan_items"] if i["custom_plan_id"] == custom_id]
    assert await _custom_rows(session, custom_id) == after


async def test_b3_deactivate_keeps_completed_occurrence_and_credit(session, user: User, clock):
    custom_id, _ = await _custom_setup(session, user, clock, weeks=[2, 2])
    occurrence, session_id = await _credit_first_occurrence(session, user)

    response = await v2_post(session, user.telegram_id, f"/api/v2/custom-plans/{custom_id}/deactivate", {})

    assert response.status_code == 200, response.text
    rows = await _custom_rows(session, custom_id)
    assert (1, 1, "open", occurrence["id"]) in rows
    assert [status for *_, status, row_id in rows if row_id != occurrence["id"]] == ["removed"] * 3
    assert await _credit_of(session, session_id) == occurrence["id"]
    plan = await _plan(session, user)
    assert [(i["id"], i["state"]) for i in _week_items(plan, 1)] == [(occurrence["id"], "completed")]
    assert (_summary(plan, 1)["completed"], _summary(plan, 1)["planned"]) == (1, 1)


async def test_b3_deactivate_past_week_history_unchanged(session, user: User, clock):
    custom_id, _ = await _custom_setup(session, user, clock, weeks=[1, 1])
    clock(MON + timedelta(weeks=1))
    await _plan(session, user)

    assert (await v2_post(session, user.telegram_id, f"/api/v2/custom-plans/{custom_id}/deactivate", {})).status_code == 200

    statuses = {week: status for week, _, status, _ in await _custom_rows(session, custom_id)}
    assert statuses == {1: "open", 2: "removed"}  # прошлая неделя — история («пропущено»), не трогаем
    assert _week_items(await _plan(session, user), 1)[0]["state"] == "missed"


async def test_b3_other_users_custom_plan_is_404(session, user: User, clock):
    custom_id, _ = await _custom_setup(session, user, clock, weeks=[1])
    other = User(telegram_id=2003, username="other")
    session.add(other)
    await session.flush()
    session.add(TrainingPlan(user_id=other.id, created_at=MON))
    await session.flush()

    for target in (custom_id, custom_id + 1000):
        response = await v2_post(session, other.telegram_id, f"/api/v2/custom-plans/{target}/deactivate", {})
        assert response.status_code == 404
    assert (await session.execute(select(CustomPlan.is_active).where(CustomPlan.id == custom_id))).scalar_one() is True
    assert [status for _, _, status, _ in await _custom_rows(session, custom_id)] == ["open"]


async def test_b3_double_deactivate_has_no_further_side_effects(session, user: User, clock):
    custom_id, _ = await _custom_setup(session, user, clock, weeks=[2])
    first = await v2_post(session, user.telegram_id, f"/api/v2/custom-plans/{custom_id}/deactivate", {})
    rows = await _custom_rows(session, custom_id)

    second = await v2_post(session, user.telegram_id, f"/api/v2/custom-plans/{custom_id}/deactivate", {})

    assert (first.status_code, second.status_code) == (200, 200)
    assert first.json() == second.json()
    assert await _custom_rows(session, custom_id) == rows
    await _plan(session, user)
    assert await _custom_rows(session, custom_id) == rows


# --- C1: строки убранного курса не «доступны» ---------------------------------------------------


async def test_c1_removed_course_current_week_rows_are_not_actionable(session, user: User, clock):
    inclusion = await _enrol(session, user, clock)
    occurrence, _ = await _credit_first_occurrence(session, user)
    clock(TUE)

    removed = await v2_post(session, user.telegram_id, f"/api/v2/program-inclusions/{inclusion['id']}/deactivate", {})
    assert removed.status_code == 200, removed.text

    plan = await _plan(session, user)
    course_rows = [i for i in plan["plan_items"] if i["program_inclusion_id"] == inclusion["id"]]
    # Засчитанное (история) — видно и completed; незасчитанных «Начать»/available нет.
    assert [(i["id"], i["state"]) for i in course_rows] == [(occurrence["id"], "completed")]
    assert (_summary(plan, 1)["completed"], _summary(plan, 1)["planned"]) == (1, 1)
    # Сервер и UI согласны: такую строку и сервер не стартует.
    hidden = (await session.execute(select(PlanItem.id).where(
        PlanItem.program_inclusion_id == inclusion["id"], PlanItem.id != occurrence["id"],
    ))).scalars().all()
    assert hidden  # строки в БД не удалены (повторное «Добавить» вернёт их)
    assert (await _start(session, user, [hidden[0]])).status_code == 422
