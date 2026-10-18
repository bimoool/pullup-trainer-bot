"""UX-01/UX-02/UX-08/UX-32 (кампания ux-ref-20261018, задача A): доступность занятий курса в `GET /api/v2/plan`.

Контракт CONTRACT_A_B.md: `start_allowed` / `blocked_reason` — один источник «Начать» (то же правило отдыха K1 и
доступа, что проверяет старт); `available_from` верен в текущей и будущих неделях; `session_variant*` /
`session_ordinal`; `ProgramInclusionResponse.schedule`. Календарь (пользователь в UTC): пн 5 окт 2026 — неделя 1
(5–11), неделя 2 — 12–18, неделя 3 — 19–25. Отдых между стартами MAIN = 3 дня (OD-2). Ожидаемые состояния
посчитаны вручную (комментарии у каждого теста), не выведены из тестируемого кода."""


import pytest
from sqlalchemy import select

from app.db.models import User
from app.db.models_program import PlanItem
from app.domain.plan_occurrence import weekly_capacity
from tests.helpers.legacy_inclusion import (
    MON,
    day,
    do_main,
    enrol_legacy_pre_v56,
    ensure_week,
    get_plan,
    make_clock,
    start,
    week_items,
    week_summary,
)


@pytest.fixture
def clock(monkeypatch):
    return make_clock(monkeypatch)


def _facts(items: list[dict]) -> list[tuple]:
    return [(i["state"], i["start_allowed"], i["blocked_reason"], i["available_from"]) for i in items]


# --- UX-01: «Начать» только там, где старт сработает ---------------------------------------------------------


async def test_main_on_monday_next_available_thursday(session, user: User, clock):
    """Пн — основное занятие. Вт: available_from = пн + 3 = чт 8 окт; занятия 2 и 3 too_early, «Начать» нет.
    Чт: занятие 2 доступно (ближайшее) и стартует; занятие 3 (проекция вс 11) тоже не too_early."""
    await enrol_legacy_pre_v56(session, user, clock)
    first = week_items(await get_plan(session, user), 1)[0]
    await do_main(session, user, clock, first["id"], at=MON)

    clock(day(1))
    items = week_items(await get_plan(session, user), 1)
    assert _facts(items) == [
        ("completed", False, "completed", None),
        ("too_early", False, "too_early", "2026-10-08"),
        ("too_early", False, "too_early", "2026-10-08"),
    ]
    rejected = await start(session, user, items[1]["id"])
    assert rejected.status_code == 409 and rejected.json()["detail"]["available_from"] == "2026-10-08"

    clock(day(3))
    items = week_items(await get_plan(session, user), 1)
    assert [(i["state"], i["start_allowed"], i["blocked_reason"]) for i in items[1:]] == [
        ("available", True, None), ("available", True, None),
    ]
    assert (await start(session, user, items[1]["id"])).status_code == 200


async def test_start_allowed_never_disagrees_with_the_start_endpoint(session, user: User, clock):
    """Для каждой строки текущей недели: start_allowed=true ⇒ старт 200; too_early ⇒ 409 (то же правило)."""
    await enrol_legacy_pre_v56(session, user, clock)
    first = week_items(await get_plan(session, user), 1)[0]
    await do_main(session, user, clock, first["id"], at=MON)
    for offset, expected_open in ((2, False), (3, True)):
        clock(day(offset))
        row = week_items(await get_plan(session, user), 1)[1]
        assert row["start_allowed"] is expected_open
        started = await start(session, user, row["id"])
        assert (started.status_code == 200) is expected_open, started.text
        if expected_open:
            break


async def test_infeasible_third_row_is_never_startable(session, user: User, clock):
    """Свежий курс в среду 7 окт: занятия — ср 7, сб 10, (вс 13 > 11) ⇒ третье «не успеть»; «Начать» у него нет."""
    await enrol_legacy_pre_v56(session, user, clock, now=day(2))
    items = week_items(await get_plan(session, user), 1)
    assert [(i["state"], i["start_allowed"], i["blocked_reason"]) for i in items] == [
        ("available", True, None), ("available", True, None), ("infeasible", False, "infeasible"),
    ]


async def test_past_week_rows_are_missed_not_startable(session, user: User, clock):
    await enrol_legacy_pre_v56(session, user, clock)
    clock(day(8))  # пн 13 окт — неделя 1 прошла
    items = week_items(await get_plan(session, user), 1)
    assert _facts(items) == [("missed", False, "missed", None)] * 3
    assert week_summary(await get_plan(session, user), 1)["missed"] == 3


# --- UX-02: будущие недели --------------------------------------------------------------------------------


async def test_future_weeks_carry_correct_available_from_and_become_startable(session, user: User, clock):
    """Пн 5 — основное; вт 6. Недели 2–5 созданы; каждая строка: available_from = чт 8 окт (последний старт + 3),
    пока вт — too_early. В чт 8 строки недели 3 доступны; занятие 1 недели 3 стартует и засчитывает ИМЕННО себя."""
    await enrol_legacy_pre_v56(session, user, clock)
    first = week_items(await get_plan(session, user), 1)[0]
    await do_main(session, user, clock, first["id"], at=MON)
    clock(day(1))
    for number in (2, 3, 4, 5):
        await ensure_week(session, user, number)
    plan = await get_plan(session, user)
    for number in (2, 3, 4, 5):
        rows = week_items(plan, number)
        assert len(rows) == 3
        assert all(r["available_from"] == "2026-10-08" and r["blocked_reason"] == "too_early" for r in rows[:2]), number
        assert not any(r["start_allowed"] for r in rows)

    clock(day(3))
    rows = week_items(await get_plan(session, user), 3)
    assert [r["start_allowed"] for r in rows] == [True, True, True]
    started = await start(session, user, rows[0]["id"])
    assert started.status_code == 200, started.text
    from app.db.models_program import TrainingSession
    credited = (await session.execute(
        select(TrainingSession.plan_item_id).where(TrainingSession.id == started.json()["id"]),
    )).scalar_one()
    assert credited == rows[0]["id"]  # засчитано именно занятие 1 недели 3 (J12)


async def test_main_on_sunday_next_week_first_occurrence_available_wednesday(session, user: User, clock):
    """Вс 11 — основное (неделя 1, занятие 1). Неделя 2 (12–18): available_from = вс + 3 = ср 14 окт.
    Цепочка: занятие 1 — ср 14, 2 — сб 17, 3 — вт 20 > 18 ⇒ infeasible. Сегодня вс ⇒ все блокированы.
    Неделя 1: занятия 2 и 3 — первое возможное ср 14 > 11 ⇒ infeasible, сводка 3/1/2/0."""
    await enrol_legacy_pre_v56(session, user, clock)
    first = week_items(await get_plan(session, user), 1)[0]
    await do_main(session, user, clock, first["id"], at=day(6))
    await ensure_week(session, user, 2)
    plan = await get_plan(session, user)
    assert _facts(week_items(plan, 2)) == [
        ("too_early", False, "too_early", "2026-10-14"),
        ("too_early", False, "too_early", "2026-10-14"),
        ("infeasible", False, "infeasible", "2026-10-14"),
    ]
    assert _facts(week_items(plan, 1))[1:] == [("infeasible", False, "infeasible", "2026-10-14")] * 2
    summary = week_summary(plan, 1)
    assert (summary["planned"], summary["completed"], summary["infeasible"], summary["missed"]) == (3, 1, 2, 0)

    clock(day(9))  # ср 14
    row = week_items(await get_plan(session, user), 2)[0]
    assert (row["state"], row["start_allowed"], row["blocked_reason"]) == ("available", True, None)
    assert (await start(session, user, row["id"])).status_code == 200


async def test_legacy_three_per_week_after_saturday_main(session, user: User, clock):
    """Сб 17 окт (неделя 2: 12–18) — основное занятие 1; на пн 5 окт курс подключён, сегодня сб 17.
    available_from = сб 17 + 3 = вт 20. Неделя 2: занятия 2 и 3 — первое возможное вт 20 > вс 18 ⇒ оба infeasible.
    Неделя 3 (19–25): 1 — вт 20, 2 — пт 23, 3 — пн 26 > 25 ⇒ too_early, too_early, infeasible. Старт 409."""
    await enrol_legacy_pre_v56(session, user, clock)
    clock(day(12))
    first = week_items(await get_plan(session, user), 2)[0]
    await do_main(session, user, clock, first["id"], at=day(12))
    await ensure_week(session, user, 3)
    plan = await get_plan(session, user)
    assert _facts(week_items(plan, 2)) == [
        ("completed", False, "completed", None),
        ("infeasible", False, "infeasible", "2026-10-20"),
        ("infeasible", False, "infeasible", "2026-10-20"),
    ]
    assert _facts(week_items(plan, 3)) == [
        ("too_early", False, "too_early", "2026-10-20"),
        ("too_early", False, "too_early", "2026-10-20"),
        ("infeasible", False, "infeasible", "2026-10-20"),
    ]
    assert (await start(session, user, week_items(plan, 3)[0]["id"])).status_code == 409
    assert (await start(session, user, week_items(plan, 2)[1]["id"])).status_code == 409


# --- UX-32: фактическое расписание старого подключения -------------------------------------------------------


async def test_legacy_inclusion_exposes_three_per_week_as_fact(session, user: User, clock):
    """Форма владельца (CONTRACT §5): снимок без slots/schedule ⇒ частота из каталога, 3 занятия, is_legacy."""
    await enrol_legacy_pre_v56(session, user, clock)
    first = week_items(await get_plan(session, user), 1)[0]
    await do_main(session, user, clock, first["id"], at=MON)
    plan = await get_plan(session, user)
    assert plan["program_inclusions"][0]["schedule"] == {
        "sessions_per_week": 3, "source": "catalogue", "is_legacy": True,
        "min_days_between_starts": 3, "weekly_capacity": 3,
    }
    rows = week_items(plan, 1)
    assert len(rows) == 3 and rows[0]["state"] == "completed"
    assert (week_summary(plan, 1)["planned"], week_summary(plan, 1)["completed"]) == (3, 1)


async def test_legacy_inclusion_with_frozen_slots_is_snapshot_sourced(session, user: User, clock):
    await enrol_legacy_pre_v56(session, user, clock, strip_snapshot=False)
    schedule = (await get_plan(session, user))["program_inclusions"][0]["schedule"]
    assert (schedule["sessions_per_week"], schedule["source"], schedule["is_legacy"]) == (3, "snapshot", True)


def test_weekly_capacity_formula_hand_computed():
    """Пн-старт, шаг d дней, влезает в 7 дней: 1 + (7 - 1) // d. d=1→7, 2→4 (пн ср пт вс), 3→3 (пн чт вс),
    4→2 (пн пт), 6→2 (пн вс), 7→1. Без отдыха (0) — 7."""
    assert [weekly_capacity(d) for d in (0, 1, 2, 3, 4, 6, 7, 10)] == [7, 7, 4, 3, 2, 2, 1, 1]


async def test_week_summaries_match_row_states(session, user: User, clock):
    await enrol_legacy_pre_v56(session, user, clock)
    first = week_items(await get_plan(session, user), 1)[0]
    await do_main(session, user, clock, first["id"], at=day(6))
    for number in (2, 3):
        await ensure_week(session, user, number)
    clock(day(13))  # вт 13 окт... неделя 1 — прошлая
    plan = await get_plan(session, user)
    for week in plan["plan_weeks"]:
        rows = [i for i in plan["plan_items"] if i["plan_week_id"] == week["id"]]
        summary = week_summary(plan, week["week_number"])
        states = [r["state"] for r in rows]
        assert summary["planned"] == len(rows)
        assert (summary["completed"], summary["infeasible"], summary["missed"]) == (
            states.count("completed"), states.count("infeasible"), states.count("missed"),
        )


# --- Регрессия: сходимость идемпотентна, история и прогрессия не тронуты ----------------------------------


@pytest.mark.parametrize("strip_snapshot", [True, False], ids=["owner_shape_no_slots", "frozen_slots"])
async def test_convergence_is_idempotent_and_history_untouched_for_aged_legacy(
    session, user: User, clock, strip_snapshot,
):
    """Состаренные данные: основное в пн 5 и сб 10 окт, прошло три недели, созданы недели 2–4. Повторная сходимость —
    0 изменений; id строк, число занятий (3 в каждой неделе), progression_state и сессии не меняются."""
    from sqlalchemy import func

    from app.db.models_program import ProgramInclusion, TrainingSession
    from app.services.plan_convergence import PlanConvergenceService

    body = await enrol_legacy_pre_v56(session, user, clock, strip_snapshot=strip_snapshot)
    rows = week_items(await get_plan(session, user), 1)
    await do_main(session, user, clock, rows[0]["id"], at=MON)
    await do_main(session, user, clock, rows[1]["id"], at=day(5))
    clock(day(16))  # ср 21 окт, неделя 3
    for number in (3, 4):
        await ensure_week(session, user, number)
    plan = await get_plan(session, user)
    inclusion = await session.get(ProgramInclusion, body["id"])
    state_before = dict(inclusion.progression_state)
    ids = sorted((await session.execute(select(PlanItem.id))).scalars().all())
    sessions_before = (await session.execute(
        select(TrainingSession.id, TrainingSession.performed_at, TrainingSession.plan_item_id).order_by(TrainingSession.id),
    )).all()

    _, again = await PlanConvergenceService(session).converge_user_plan(
        training_plan_id=inclusion.training_plan_id, today=day(16).date(),
    )
    assert again.mutations == 0, again.as_dict()
    assert sorted((await session.execute(select(PlanItem.id))).scalars().all()) == ids
    assert (await session.get(ProgramInclusion, body["id"])).progression_state == state_before
    assert (await session.execute(
        select(TrainingSession.id, TrainingSession.performed_at, TrainingSession.plan_item_id).order_by(TrainingSession.id),
    )).all() == sessions_before
    for number in (1, 3, 4):
        assert len(week_items(plan, number)) == 3, number  # материализация для legacy не изменилась (3 в неделю)
    assert (await session.execute(select(func.count()).select_from(TrainingSession))).scalar_one() == 2


async def test_convergence_is_idempotent_for_v56(session, user: User, clock):
    from app.services.plan_convergence import PlanConvergenceService
    from tests.test_web.test_v2_course_v5 import WEIGHTED_INPUTS, _enrol, _pullups
    clock(MON)
    inclusion = await _enrol(session, user, await _pullups(session), course_inputs=WEIGHTED_INPUTS)
    await ensure_week(session, user, 2)
    plan = await get_plan(session, user)
    assert [len(week_items(plan, n)) for n in (1, 2)] == [2, 2]
    state_before = dict(inclusion.progression_state)
    _, again = await PlanConvergenceService(session).converge_user_plan(
        training_plan_id=inclusion.training_plan_id, today=MON.date(),
    )
    assert again.mutations == 0, again.as_dict()
    assert inclusion.progression_state == state_before
