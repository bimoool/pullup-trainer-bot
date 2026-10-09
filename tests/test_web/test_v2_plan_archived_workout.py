"""#304 второе независимое ревью, блокер F — повторяющийся свой план не материализует удалённую
(архивную) тренировку. PROGRAM_PLAN_V2 §7, PROJECT_SPEC (решения владельца):

* удалённая тренировка не даёт новых занятий; её открытые занятия текущей/будущих недель — removed
  (та же идентичность), засчитанные и прошлые недели — история, не меняются;
* ротация НЕ пересчитывается: оставшиеся тренировки остаются на своих позициях и объём удалённой не
  забирают, occurrence_index не перенумеровывается (дыры допустимы);
* свой план без живых тренировок останавливается (is_active = false);
* страховка: старт строки с архивной тренировкой — 422 «план обновился», в GET /plan она не available.

Часы: «сегодня» плана и «сейчас» старта зафиксированы фикстурой clock."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.db.models import User
from app.db.models_program import (
    Complex,
    ComplexItem,
    CustomPlan,
    Exercise,
    PlanItem,
    PlanWeek,
    TrainingPlan,
)
from app.domain.multi_program import MetricType
from app.domain.plan_occurrence import CustomPlanRepeat, custom_week_occurrences
from app.services import live_session
from app.services.live_session import STALE_PLAN_ITEM_MESSAGE
from app.web import routes_v2
from tests.test_web._v2_client import v2_delete, v2_get, v2_post
from tests.test_web.test_v2_plan_occurrences import (
    MON,
    _finish,
    _plan,
    _start,
    _summary,
    _week_items,
)
from tests.test_web.test_v2_plan_removal import _credit_of


@pytest.fixture
def clock(monkeypatch):
    def _set(now: datetime) -> None:
        monkeypatch.setattr(routes_v2, "_utcnow", lambda: now)
        monkeypatch.setattr(live_session, "_utcnow", lambda: now)
    return _set


async def _workout(session, user: User, name: str) -> int:
    exercise = Exercise(name=f"Упражнение {name}", metric_type=MetricType.REPS, category="Общая")
    session.add(exercise)
    await session.flush()
    workout = Complex(name=name, source_type="user", owner_user_id=user.id)
    session.add(workout)
    await session.flush()
    session.add(ComplexItem(complex_id=workout.id, exercise_id=exercise.id, order_index=0, sets=3, target_value=10))
    await session.flush()
    return workout.id


async def _setup(session, user: User, clock, *, names: list[str], weeks: list[int], repeat: str = "cycle"):
    user.timezone = "UTC"
    session.add(TrainingPlan(user_id=user.id, created_at=MON - timedelta(hours=1)))
    await session.flush()
    clock(MON)
    workout_ids = [await _workout(session, user, name) for name in names]
    created = await v2_post(session, user.telegram_id, "/api/v2/custom-plans", {
        "display_name": "F", "workout_ids": workout_ids, "weeks": weeks, "repeat": repeat,
    })
    assert created.status_code == 200, created.text
    return created.json()["id"], workout_ids


async def _rows(session, custom_id: int) -> list[tuple]:
    """(неделя-источник, номер занятия, тренировка, статус, id) — снимок всех строк своего плана в БД."""
    rows = (await session.execute(
        select(PlanWeek.week_number, PlanItem.occurrence_index, PlanItem.workout_definition_id, PlanItem.status, PlanItem.id)
        .join(PlanWeek, PlanWeek.id == PlanItem.origin_plan_week_id)
        .where(PlanItem.custom_plan_id == custom_id)
        .order_by(PlanWeek.week_number, PlanItem.occurrence_index, PlanItem.id),
    )).all()
    return [tuple(row) for row in rows]


def _rotation(workout_ids: list[int], weeks: list[int], week_number: int) -> list[tuple[int, int]]:
    """(occurrence_index, тренировка) недели по ПОЛНОЙ сохранённой ротации — эталон позиций."""
    return [
        (spec.occurrence_index, spec.workout_definition_id)
        for spec in custom_week_occurrences(
            workout_ids=workout_ids, weeks=weeks, repeat=CustomPlanRepeat.CYCLE, week_offset=week_number - 1,
            preferred_weekdays=None,
        )
    ]


async def _archive_directly(session, workout_id: int) -> None:
    """Архив в обход DELETE-пути (другой путь / гонка): строки плана остаются как были — проверяется
    именно сходимость / старт / GET /plan, а не снятие при удалении."""
    await session.execute(update(Complex).where(Complex.id == workout_id).values(archived_at=datetime.now(UTC)))
    await session.flush()


async def _is_active(session, custom_id: int) -> bool:
    return (await session.execute(select(CustomPlan.is_active).where(CustomPlan.id == custom_id))).scalar_one()


# --- TEST 1 / 6: многотренировочный повторяющийся план -----------------------------------------


async def test_f_deleted_workout_never_rematerializes_and_w2_keeps_its_positions(session, user: User, clock):
    weeks = [3]
    custom_id, (w1, w2) = await _setup(session, user, clock, names=["W1", "W2"], weeks=weeks)
    assert (await v2_post(session, user.telegram_id, "/api/v2/plan/weeks", {"week_number": 3})).status_code == 200
    before = await _rows(session, custom_id)
    assert [(week, index, workout) for week, index, workout, _, _ in before] == [
        (n, index, workout) for n in (1, 2, 3) for index, workout in _rotation([w1, w2], weeks, n)
    ]
    w1_before = {(week, index): row_id for week, index, workout, _, row_id in before if workout == w1}
    w2_before = [row for row in before if row[2] == w2]

    assert (await v2_delete(session, user.telegram_id, f"/api/v2/workouts/{w1}")).status_code == 204

    after_delete = await _rows(session, custom_id)
    # Открытые W1 текущей/будущих недель — removed, та же идентичность; W2 — без изменений.
    assert {(week, index): row_id for week, index, workout, status, row_id in after_delete if workout == w1} == w1_before
    assert all(status == "removed" for _, _, workout, status, _ in after_delete if workout == w1)
    assert [row for row in after_delete if row[2] == w2] == w2_before
    assert await _is_active(session, custom_id) is True  # W2 жива — план идёт

    # Время идёт на 3 недели, окно планирования — до недели 8.
    clock(MON + timedelta(weeks=3))
    assert (await v2_post(session, user.telegram_id, "/api/v2/plan/weeks", {"week_number": 8})).status_code == 200
    plans = [await _plan(session, user), await _plan(session, user)]
    rows = await _rows(session, custom_id)

    # Нет новых W1: строки W1 — ровно те же removed-строки, что были.
    assert {(week, index): row_id for week, index, workout, _, row_id in rows if workout == w1} == w1_before
    assert all(status == "removed" for _, _, workout, status, _ in rows if workout == w1)
    # W2 — только на своих позициях полной ротации, объём W1 не забирает, номера не перенумерованы.
    for number in range(1, 9):
        expected = [index for index, workout in _rotation([w1, w2], weeks, number) if workout == w2]
        actual = [index for week, index, workout, _, _ in rows if week == number and workout == w2]
        assert actual == expected, (number, actual, expected)
        assert len(actual) < weeks[0]  # меньше объёма недели: дыры W1 не заполнены
    # Без дублей идентичности занятия.
    assert len({(week, index) for week, index, *_ in rows}) == len(rows)
    # GET /plan не отдаёт W1 вовсе; повторная сходимость ничего не меняет.
    for plan in plans:
        assert not [i for i in plan["plan_items"] if i["complex_id"] == w1]
    assert plans[0]["plan_items"] == plans[1]["plan_items"]
    assert await _rows(session, custom_id) == rows


async def test_f_no_rerotation_when_workout_archived_outside_delete_path(session, user: User, clock):
    """Сходимость сама (без DELETE-пути) не материализует архивную тренировку и не сдвигает ротацию."""
    weeks = [2, 3]
    custom_id, (w1, w2, w3) = await _setup(session, user, clock, names=["W1", "W2", "W3"], weeks=weeks)
    await _plan(session, user)
    w1_before = {row[4] for row in await _rows(session, custom_id) if row[2] == w1}
    await _archive_directly(session, w1)

    clock(MON + timedelta(weeks=1))
    assert (await v2_post(session, user.telegram_id, "/api/v2/plan/weeks", {"week_number": 6})).status_code == 200
    await _plan(session, user)
    rows = await _rows(session, custom_id)

    for number in range(2, 7):
        rotation = [
            (spec.occurrence_index, spec.workout_definition_id)
            for spec in custom_week_occurrences(
                workout_ids=[w1, w2, w3], weeks=weeks, repeat=CustomPlanRepeat.CYCLE,
                week_offset=number - 1, preferred_weekdays=None,
            )
        ]
        live = [(index, workout) for index, workout in rotation if workout != w1]
        actual = [(index, workout) for week, index, workout, status, _ in rows if week == number and status == "open"]
        assert actual == live, (number, actual, live)
        # Ни одной открытой W1; уже бывшие (созданные до архива) — сняты, новых нет.
        assert all(status == "removed" for week, _, workout, status, _ in rows if week == number and workout == w1)
    assert {row[4] for row in rows if row[2] == w1} == w1_before
    # Неделя 1 (прошлая): её открытая W1 — история («пропущено»), не снята.
    assert [status for week, _, workout, status, _ in rows if week == 1 and workout == w1] == ["open"]
    assert await _is_active(session, custom_id) is True


# --- TEST 2: старт устаревшего занятия -----------------------------------------------------------


async def test_f_stale_occurrence_of_archived_workout_cannot_start(session, user: User, clock):
    _custom_id, (w1, w2) = await _setup(session, user, clock, names=["W1", "W2"], weeks=[2])
    stale = next(i for i in _week_items(await _plan(session, user), 1) if i["complex_id"] == w1)

    await _archive_directly(session, w1)  # строка ещё open в БД — проверяется страховка старта

    response = await _start(session, user, [stale["id"]])
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == STALE_PLAN_ITEM_MESSAGE
    # GET /plan: строка снята сходимостью и не available; W2 — как была.
    plan = await _plan(session, user)
    assert [i["complex_id"] for i in _week_items(plan, 1)] == [w2]
    assert (await _start(session, user, [stale["id"]])).status_code == 422


async def test_f_stale_occurrence_after_workout_delete_is_422(session, user: User, clock):
    _, (w1, _) = await _setup(session, user, clock, names=["W1", "W2"], weeks=[2])
    stale = next(i for i in _week_items(await _plan(session, user), 1) if i["complex_id"] == w1)
    assert (await v2_delete(session, user.telegram_id, f"/api/v2/workouts/{w1}")).status_code == 204

    response = await _start(session, user, [stale["id"]])

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == STALE_PLAN_ITEM_MESSAGE


async def test_f_plan_view_never_offers_archived_workout_row(session, user: User, clock):
    """UI и сервер согласны: даже не снятая в БД строка архивной тренировки не отдаётся как available."""
    custom_id, (w1, _w2) = await _setup(session, user, clock, names=["W1", "W2"], weeks=[2])
    await _plan(session, user)
    await _archive_directly(session, w1)
    stale_id = next(row_id for _, _, workout, _, row_id in await _rows(session, custom_id) if workout == w1)

    from app.db.repositories.training_plans import TrainingPlanRepository
    from app.db.repositories.users import UserRepository
    from app.services.plan_view import PlanViewService

    plan_row = (await session.execute(select(TrainingPlan).where(TrainingPlan.user_id == user.id))).scalar_one()
    repo = TrainingPlanRepository(session)
    items = (await session.execute(select(PlanItem).where(PlanItem.training_plan_id == plan_row.id))).scalars().all()
    view = await PlanViewService(session).build(
        plan=plan_row, user=await UserRepository(session).get_by_id(user.id), today=MON.date(),
        plan_weeks=await repo.list_plan_weeks(plan_row.id), plan_items=list(items), inclusions=[],
    )
    assert stale_id not in {entry.item.id for entry in view.items}
    assert (await _start(session, user, [stale_id])).status_code == 422


# --- TEST 3: план из одной тренировки -----------------------------------------------------------


async def test_f_single_workout_plan_auto_stops_on_delete(session, user: User, clock):
    custom_id, (w1,) = await _setup(session, user, clock, names=["W1"], weeks=[1])
    assert (await v2_post(session, user.telegram_id, "/api/v2/plan/weeks", {"week_number": 2})).status_code == 200

    assert (await v2_delete(session, user.telegram_id, f"/api/v2/workouts/{w1}")).status_code == 204

    assert await _is_active(session, custom_id) is False
    listed = (await v2_get(session, user.telegram_id, "/api/v2/custom-plans")).json()
    assert [(p["id"], p["is_active"]) for p in listed["items"]] == [(custom_id, False)]
    rows = await _rows(session, custom_id)
    assert [(week, status) for week, _, _, status, _ in rows] == [(1, "removed"), (2, "removed")]

    clock(MON + timedelta(weeks=3))
    assert (await v2_post(session, user.telegram_id, "/api/v2/plan/weeks", {"week_number": 8})).status_code == 200
    for _ in range(3):
        plan = await _plan(session, user)
        assert not [i for i in plan["plan_items"] if i["custom_plan_id"] == custom_id]
    assert await _rows(session, custom_id) == rows
    assert await _is_active(session, custom_id) is False


async def test_f_single_workout_plan_auto_stops_on_convergence(session, user: User, clock):
    """Архив в обход DELETE-пути: сходимость сама останавливает план, история сохраняется."""
    custom_id, (w1,) = await _setup(session, user, clock, names=["W1"], weeks=[1])
    clock(MON + timedelta(weeks=1))
    await _plan(session, user)  # неделя 1 стала прошлой («пропущено»), неделя 2 — текущая
    await _archive_directly(session, w1)

    await _plan(session, user)  # сходимость текущей недели 2 видит архив
    assert await _is_active(session, custom_id) is False
    rows = await _rows(session, custom_id)
    assert [(week, status) for week, _, _, status, _ in rows] == [(1, "open"), (2, "removed")]

    clock(MON + timedelta(weeks=4))
    for _ in range(2):
        items = [i for i in (await _plan(session, user))["plan_items"] if i["custom_plan_id"] == custom_id]
        assert [(i["id"], i["state"]) for i in items] == [(rows[0][4], "missed")]  # только история недели 1
    assert await _rows(session, custom_id) == rows
    assert await _is_active(session, custom_id) is False


# --- TEST 4: история прошлых недель ---------------------------------------------------------------


async def test_f_delete_workout_keeps_past_week_completed_and_missed_rows(session, user: User, clock):
    custom_id, (w1, _w2) = await _setup(session, user, clock, names=["W1", "W2"], weeks=[4])
    week1 = _week_items(await _plan(session, user), 1)
    w1_rows = [i for i in week1 if i["complex_id"] == w1]
    assert len(w1_rows) == 2
    started = await _start(session, user, [w1_rows[0]["id"]])
    assert started.status_code == 200, started.text
    await _finish(session, user, started, performed_at=MON + timedelta(hours=1))

    clock(MON + timedelta(weeks=1))
    await _plan(session, user)
    before = await _rows(session, custom_id)

    assert (await v2_delete(session, user.telegram_id, f"/api/v2/workouts/{w1}")).status_code == 204

    after = await _rows(session, custom_id)
    assert [row for row in after if row[0] == 1] == [row for row in before if row[0] == 1]  # прошлая — как была
    assert await _credit_of(session, started.json()["id"]) == w1_rows[0]["id"]
    assert all(status == "removed" for week, _, workout, status, _ in after if week >= 2 and workout == w1)
    plan = await _plan(session, user)
    states = {i["id"]: i["state"] for i in _week_items(plan, 1)}
    assert (states[w1_rows[0]["id"]], states[w1_rows[1]["id"]]) == ("completed", "missed")
    assert _summary(plan, 1)["planned"] == 4


# --- TEST 5: текущая/будущая открытая строка -------------------------------------------------------


async def test_f_current_open_occurrence_soft_removed_same_id_no_replacement(session, user: User, clock):
    custom_id, (w1, _w2) = await _setup(session, user, clock, names=["W1", "W2"], weeks=[2])
    current = next(i for i in _week_items(await _plan(session, user), 1) if i["complex_id"] == w1)

    assert (await v2_delete(session, user.telegram_id, f"/api/v2/workouts/{w1}")).status_code == 204
    for _ in range(2):
        await _plan(session, user)

    rows = await _rows(session, custom_id)
    week1 = [(index, workout, status, row_id) for week, index, workout, status, row_id in rows if week == 1]
    assert (current["occurrence_index"], w1, "removed", current["id"]) in week1
    assert [r for r in week1 if r[0] == current["occurrence_index"]] == [
        (current["occurrence_index"], w1, "removed", current["id"]),
    ]
