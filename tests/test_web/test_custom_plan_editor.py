"""UX-EDITOR: редактор своего плана и расписание недели. Ожидаемые числа посчитаны вручную по
checkpoints/UX-EDITOR-contract.md §4 (примеры a–e), а не выведены из кода.

Время: план создан в понедельник MON (неделя 1 — текущая), поэтому неделям плана W1..W4 соответствуют
календарные недели 1..4, окно планирования — недели 1..5. Пользователь в поясе UTC."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.models import User
from app.db.models_program import PlanItem, PlanWeek, TrainingPlan, TrainingSession
from app.services import live_session
from app.web import routes_v2
from tests.test_web._v2_client import v2_delete, v2_get, v2_patch, v2_post
from tests.test_web.test_v2_plan_occurrences import _finish, _start, _user_workout

MON = datetime(2026, 10, 5, 10, tzinfo=UTC)
THU = MON + timedelta(days=3)
BASE = "/api/v2/custom-plans"


@pytest.fixture
def clock(monkeypatch):
    def _set(now: datetime) -> None:
        monkeypatch.setattr(routes_v2, "_utcnow", lambda: now)
        monkeypatch.setattr(live_session, "_utcnow", lambda: now)
    return _set


async def _setup(session, user: User, clock):
    user.timezone = "UTC"
    session.add(TrainingPlan(user_id=user.id, created_at=MON - timedelta(hours=1)))
    await session.flush()
    clock(MON)
    a = await _user_workout(session, user)
    b = await _user_workout(session, user)
    c = await _user_workout(session, user)
    return a, b, c


async def _create_matrix(session, user, a, b):
    response = await v2_post(session, user.telegram_id, BASE, {
        "display_name": "Матрица", "workout_ids": [a.id, b.id], "weeks": [1],
        "quantities": [[2, 2, 0, 1], [1, 1, 1, 1]],
    })
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _rows(session, plan_id: int):
    """[(id, origin_week, placed_week, workout, day, status, index)] всех занятий плана, включая снятые."""
    weeks = {w.id: w.week_number for w in (await session.execute(select(PlanWeek))).scalars()}
    items = (await session.execute(
        select(PlanItem).where(PlanItem.custom_plan_id == plan_id).order_by(PlanItem.id)
        .execution_options(populate_existing=True),
    )).scalars().all()
    return [
        (i.id, weeks[i.origin_plan_week_id], weeks[i.plan_week_id], i.workout_definition_id, i.day_of_week,
         i.status, i.occurrence_index) for i in items
    ]


def _per_week(rows, *, placed=False):
    counts: dict[int, int] = {}
    for row in rows:
        if row[5] != "removed":
            week = row[2] if placed else row[1]
            counts[week] = counts.get(week, 0) + 1
    return counts


async def _editor(session, user, plan_id):
    response = await v2_get(session, user.telegram_id, f"{BASE}/{plan_id}/editor")
    assert response.status_code == 200, response.text
    return response.json()


async def _credit(session, user, row_id: int, *, performed_at=MON):
    started = await _start(session, user, [row_id])
    assert started.status_code == 200, started.text
    await _finish(session, user, started, performed_at=performed_at)
    return started.json()["id"]


# --- (a) количества и итоги ---------------------------------------------------------------------


async def test_totals_per_week_example_a(session, user: User, clock):
    a, b, _ = await _setup(session, user, clock)
    plan_id = await _create_matrix(session, user, a, b)
    editor = await _editor(session, user, plan_id)
    assert [w["total"] for w in editor["weeks"]] == [3, 3, 1, 2]
    assert editor["weeks"][0]["quantities"] == {str(a.id): 2, str(b.id): 1}
    assert editor["weeks"][0]["state"] == "current" and editor["weeks"][1]["state"] == "future"
    assert editor["converted"] is True
    listed = (await v2_get(session, user.telegram_id, BASE)).json()["items"][0]
    assert listed["weeks"] == [3, 3, 1, 2]  # weeks = недельные суммы
    rows = await _rows(session, plan_id)
    assert _per_week(rows) == {1: 3, 2: 3, 3: 1, 4: 2} and len(rows) == 9
    assert all(r[4] is None for r in rows)  # дни не назначены
    assert sorted(r[6] for r in rows if r[1] == 1) == [1, 2, 3]


# --- (b) старые планы конвертируются без изменений ----------------------------------------------


async def test_legacy_conversion_is_lossless(session, user: User, clock):
    a, b, _ = await _setup(session, user, clock)
    created = await v2_post(session, user.telegram_id, BASE, {
        "display_name": "Старый", "workout_ids": [a.id, b.id], "weeks": [2, 2, 0, 2],
    })
    plan_id = created.json()["id"]
    before = await _rows(session, plan_id)
    editor = await _editor(session, user, plan_id)
    assert editor["converted"] is False
    assert [w["quantities"] for w in editor["weeks"]] == [
        {str(a.id): 1, str(b.id): 1}, {str(a.id): 1, str(b.id): 1}, {str(a.id): 0, str(b.id): 0},
        {str(a.id): 1, str(b.id): 1},
    ]
    assert [w["total"] for w in editor["weeks"]] == [2, 2, 0, 2]
    assert await _rows(session, plan_id) == before  # чтение редактора ничего не меняет

    # Первая правка (те же значения) записывает spec — занятия не меняются: 0 созданных / 0 снятых.
    patched = await v2_patch(session, user.telegram_id, f"{BASE}/{plan_id}/weeks/1/quantities", {
        "quantities": {str(a.id): 1, str(b.id): 1},
    })
    assert patched.status_code == 200, patched.text
    assert patched.json()["converted"] is True
    assert await _rows(session, plan_id) == before
    assert _per_week(before) == {1: 2, 2: 2, 4: 2}


async def test_legacy_conversion_odd_rotation_is_lossless(session, user: User, clock):
    a, b, c = await _setup(session, user, clock)
    created = await v2_post(session, user.telegram_id, BASE, {
        "display_name": "Три", "workout_ids": [a.id, b.id, c.id], "weeks": [2, 2, 2],
    })
    plan_id = created.json()["id"]
    before = await _rows(session, plan_id)
    editor = await _editor(session, user, plan_id)
    got = [[w["quantities"][str(x.id)] for x in (a, b, c)] for w in editor["weeks"]]
    assert got == [[1, 1, 0], [1, 0, 1], [0, 1, 1]]  # A=[1,1,0] B=[1,0,1] C=[0,1,1] по неделям
    await v2_patch(session, user.telegram_id, f"{BASE}/{plan_id}/weeks/3/quantities", {
        "quantities": {str(b.id): 1, str(c.id): 1},
    })
    assert await _rows(session, plan_id) == before


# --- (c) вставка недели ------------------------------------------------------------------------


async def test_insert_week_shifts_open_rows_keeps_ids_days_and_done(session, user: User, clock):
    a, b, _ = await _setup(session, user, clock)
    plan_id = await _create_matrix(session, user, a, b)
    rows = await _rows(session, plan_id)
    a_week1 = next(r for r in rows if r[1] == 1 and r[3] == a.id)
    credited_session = await _credit(session, user, a_week1[0])
    # B недели 3 поставлен на среду — должен сохранить день при сдвиге.
    b_week3 = next(r for r in rows if r[1] == 3)
    placed = await v2_post(session, user.telegram_id, f"{BASE}/{plan_id}/weeks/3/place", {
        "workout_id": b.id, "day_of_week": 2,
    })
    assert placed.status_code == 200, placed.text
    rows_before = await _rows(session, plan_id)

    response = await v2_post(session, user.telegram_id, f"{BASE}/{plan_id}/weeks", {"after_index": 2})
    assert response.status_code == 200, response.text
    editor = response.json()
    assert [w["total"] for w in editor["weeks"]] == [3, 3, 0, 1, 2]
    assert [w["quantities"][str(a.id)] for w in editor["weeks"]] == [2, 2, 0, 0, 1]
    assert [w["quantities"][str(b.id)] for w in editor["weeks"]] == [1, 1, 0, 1, 1]
    rows_after = await _rows(session, plan_id)
    assert _per_week(rows_after, placed=True) == {1: 3, 2: 3, 4: 1, 5: 2} and len(
        [r for r in rows_after if r[5] != "removed"]) == 9
    assert not [r for r in rows_after if r[5] == "removed"]
    # те же id строк: B недели 3 → неделя 4, день 2 сохранён; засчитанный A недели 1 на месте
    moved = next(r for r in rows_after if r[0] == b_week3[0])
    assert (moved[1], moved[2], moved[4]) == (4, 4, 2)
    assert next(r for r in rows_after if r[0] == a_week1[0])[1:3] == (1, 1)
    assert {r[0] for r in rows_before} == {r[0] for r in rows_after}
    credit = (await session.execute(
        select(TrainingSession.plan_item_id).where(TrainingSession.id == credited_session),
    )).scalar_one()
    assert credit == a_week1[0]


async def test_insert_week_refusals_leave_state_unchanged(session, user: User, clock):
    a, b, _ = await _setup(session, user, clock)
    plan_id = await _create_matrix(session, user, a, b)
    before = await _rows(session, plan_id)
    refused = await v2_post(session, user.telegram_id, f"{BASE}/{plan_id}/weeks", {"after_index": 0})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "week_not_editable"
    assert refused.json()["detail"]["reason"] == "current"

    week3_row = next(r for r in before if r[1] == 3)
    await _credit(session, user, week3_row[0], performed_at=MON)
    before = await _rows(session, plan_id)
    done = await v2_post(session, user.telegram_id, f"{BASE}/{plan_id}/weeks", {"after_index": 2})
    assert done.status_code == 422 and done.json()["detail"]["code"] == "week_has_done_sessions"
    assert await _rows(session, plan_id) == before
    assert [w["total"] for w in (await _editor(session, user, plan_id))["weeks"]] == [3, 3, 1, 2]


# --- (d) удаление недели -----------------------------------------------------------------------


async def test_delete_future_week_retires_and_shifts(session, user: User, clock):
    a, b, _ = await _setup(session, user, clock)
    plan_id = await _create_matrix(session, user, a, b)
    before = await _rows(session, plan_id)
    response = await v2_delete(session, user.telegram_id, f"{BASE}/{plan_id}/weeks/3")
    assert response.status_code == 200, response.text
    editor = response.json()
    assert [w["quantities"][str(a.id)] for w in editor["weeks"]] == [2, 2, 1]
    assert [w["quantities"][str(b.id)] for w in editor["weeks"]] == [1, 1, 1]
    assert [w["total"] for w in editor["weeks"]] == [3, 3, 2]
    assert editor["removed_sessions"] == 1
    rows = await _rows(session, plan_id)
    assert _per_week(rows) == {1: 3, 2: 3, 3: 2}  # 8 = 9 − 1
    assert [r for r in rows if r[5] == "removed"] == [r for r in rows if r[0] == next(x for x in before if x[1] == 3)[0]]
    # строки старой недели 4 сохранили id и переехали на неделю 3
    old_week4_ids = {r[0] for r in before if r[1] == 4}
    assert {r[0] for r in rows if r[1] == 3 and r[5] != "removed"} == old_week4_ids


async def test_delete_week_with_done_refused_and_quantity_floor(session, user: User, clock):
    a, b, _ = await _setup(session, user, clock)
    plan_id = await _create_matrix(session, user, a, b)
    rows = await _rows(session, plan_id)
    a_week2 = next(r for r in rows if r[1] == 2 and r[3] == a.id)
    await _credit(session, user, a_week2[0], performed_at=MON)
    before = await _rows(session, plan_id)

    refused = await v2_delete(session, user.telegram_id, f"{BASE}/{plan_id}/weeks/2")
    assert refused.status_code == 422
    detail = refused.json()["detail"]
    assert (detail["code"], detail["done"], detail["open"]) == ("week_has_done_sessions", 1, 2)  # A: 1 done + 1 open, B: 1 open
    assert await _rows(session, plan_id) == before

    below = await v2_patch(session, user.telegram_id, f"{BASE}/{plan_id}/weeks/2/quantities", {
        "quantities": {str(a.id): 0},
    })
    assert below.status_code == 422 and below.json()["detail"]["code"] == "below_done"
    assert below.json()["detail"]["min"] == 1

    lowered = await v2_patch(session, user.telegram_id, f"{BASE}/{plan_id}/weeks/2/quantities", {
        "quantities": {str(a.id): 1},
    })
    assert lowered.status_code == 200
    assert [w["quantities"][str(a.id)] for w in lowered.json()["weeks"]] == [2, 1, 0, 1]
    assert [w["total"] for w in lowered.json()["weeks"]] == [3, 2, 1, 2]
    after = await _rows(session, plan_id)
    assert next(r for r in after if r[0] == a_week2[0])[5] != "removed"  # засчитанный остался
    assert len([r for r in after if r[1] == 2 and r[5] != "removed"]) == 2  # A(done) + B

    current = await v2_delete(session, user.telegram_id, f"{BASE}/{plan_id}/weeks/1")
    assert current.status_code == 422 and current.json()["detail"]["code"] == "week_not_editable"


# --- (e) размещение по дням ---------------------------------------------------------------------


async def test_place_same_day_twice_and_quota(session, user: User, clock):
    a, b, _ = await _setup(session, user, clock)
    plan_id = await _create_matrix(session, user, a, b)
    url = f"{BASE}/{plan_id}/weeks/1"
    first = await v2_post(session, user.telegram_id, f"{url}/place", {"workout_id": a.id, "day_of_week": 1})
    assert first.status_code == 200, first.text
    wa = next(w for w in first.json()["workouts"] if w["workout_id"] == a.id)
    assert (wa["quantity"], wa["remaining"], wa["placed_by_day"][1]) == (2, 1, 1)
    second = await v2_post(session, user.telegram_id, f"{url}/place", {"workout_id": a.id, "day_of_week": 1})
    wa = next(w for w in second.json()["workouts"] if w["workout_id"] == a.id)
    assert (wa["remaining"], wa["placed_by_day"]) == (0, [0, 2, 0, 0, 0, 0, 0])
    assert second.json()["days"][1]["total"] == 2
    third = await v2_post(session, user.telegram_id, f"{url}/place", {"workout_id": a.id, "day_of_week": 3})
    assert third.status_code == 422 and third.json()["detail"]["code"] == "quota_exhausted"
    rows = [r for r in await _rows(session, plan_id) if r[1] == 1 and r[3] == a.id]
    assert sorted((r[4], r[6]) for r in rows) == [(1, 1), (1, 2)]

    await v2_post(session, user.telegram_id, f"{url}/place", {"workout_id": b.id, "day_of_week": 3})
    shown = (await v2_get(session, user.telegram_id, f"{url}/schedule")).json()
    assert [d["total"] for d in shown["days"]] == [0, 2, 0, 1, 0, 0, 0]
    # переносим одно занятие A со вторника на четверг: вт 1, чт 2 (A1 + B1)
    await v2_post(session, user.telegram_id, f"{url}/unplace", {"workout_id": a.id, "day_of_week": 1})
    moved = await v2_post(session, user.telegram_id, f"{url}/place", {"workout_id": a.id, "day_of_week": 3})
    assert [d["total"] for d in moved.json()["days"]] == [0, 1, 0, 2, 0, 0, 0]


async def test_place_and_move_into_past_day_refused(session, user: User, clock):
    a, b, _ = await _setup(session, user, clock)
    plan_id = await _create_matrix(session, user, a, b)
    clock(THU)  # сегодня четверг: пн..ср прошли
    url = f"{BASE}/{plan_id}/weeks/1"
    refused = await v2_post(session, user.telegram_id, f"{url}/place", {"workout_id": a.id, "day_of_week": 1})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "past_day"
    ok = await v2_post(session, user.telegram_id, f"{url}/place", {"workout_id": a.id, "day_of_week": 3})
    assert ok.status_code == 200
    shown = ok.json()
    assert [d["state"] for d in shown["days"]][:5] == ["past", "past", "past", "today", "future"]
    # PATCH существующего эндпоинта тоже не пускает в прошедший день (UX-31)
    item = next(r for r in await _rows(session, plan_id) if r[1] == 1 and r[4] is None)
    patched = await v2_patch(session, user.telegram_id, f"/api/v2/plan-items/{item[0]}", {"day_of_week": 0})
    assert patched.status_code == 422


async def test_missed_flag_for_placed_row_on_past_day(session, user: User, clock):
    a, b, _ = await _setup(session, user, clock)
    plan_id = await _create_matrix(session, user, a, b)
    url = f"{BASE}/{plan_id}/weeks/1"
    await v2_post(session, user.telegram_id, f"{url}/place", {"workout_id": b.id, "day_of_week": 1})
    clock(THU)
    shown = (await v2_get(session, user.telegram_id, f"{url}/schedule")).json()
    wb = next(w for w in shown["workouts"] if w["workout_id"] == b.id)
    assert [(i["day"], i["missed"], i["done"]) for i in wb["items"]] == [(1, True, False)]


# --- Прочее --------------------------------------------------------------------------------------


async def test_phase_add_remove_workout_and_foreign_plan(session, user: User, clock):
    a, b, c = await _setup(session, user, clock)
    plan_id = await _create_matrix(session, user, a, b)
    phased = await v2_patch(session, user.telegram_id, f"{BASE}/{plan_id}/weeks/3", {"phase": "rest"})
    assert [w["phase"] for w in phased.json()["weeks"]] == ["base", "base", "rest", "base"]
    added = await v2_post(session, user.telegram_id, f"{BASE}/{plan_id}/workouts", {"workout_id": c.id})
    assert added.status_code == 200 and [w["workout_id"] for w in added.json()["workouts"]] == [a.id, b.id, c.id]
    assert [w["total"] for w in added.json()["weeks"]] == [3, 3, 1, 2]
    removed = await v2_delete(session, user.telegram_id, f"{BASE}/{plan_id}/workouts/{b.id}")
    assert removed.status_code == 200
    assert removed.json()["removed_sessions"] == 4  # B: по одному открытому занятию в каждой из 4 недель
    assert [w["total"] for w in removed.json()["weeks"]] == [2, 2, 0, 1]
    assert _per_week(await _rows(session, plan_id)) == {1: 2, 2: 2, 4: 1}
    other = User(telegram_id=4040, username="other")
    session.add(other)
    await session.flush()
    assert (await v2_get(session, other.telegram_id, f"{BASE}/{plan_id}/editor")).status_code == 404


async def test_history_untouched_after_edit_sequence(session, user: User, clock):
    a, b, _ = await _setup(session, user, clock)
    plan_id = await _create_matrix(session, user, a, b)
    rows = await _rows(session, plan_id)
    a_week1 = next(r for r in rows if r[1] == 1 and r[3] == a.id)
    session_id = await _credit(session, user, a_week1[0])
    for step in (
        lambda: v2_post(session, user.telegram_id, f"{BASE}/{plan_id}/weeks", {"after_index": 3}),
        lambda: v2_patch(session, user.telegram_id, f"{BASE}/{plan_id}/weeks/2/quantities", {"quantities": {str(b.id): 0}}),
        lambda: v2_delete(session, user.telegram_id, f"{BASE}/{plan_id}/weeks/2"),
    ):
        assert (await step()).status_code == 200
    row = next(r for r in await _rows(session, plan_id) if r[0] == a_week1[0])
    assert row[1:3] == (1, 1) and row[5] != "removed"
    credit, status = (await session.execute(
        select(TrainingSession.plan_item_id, TrainingSession.status).where(TrainingSession.id == session_id),
    )).one()
    assert credit == a_week1[0] and status.value == "completed"
