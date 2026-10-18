"""UX-08 / UX-32 на подключении V5.6 + обход отдыха админом + чистая логика причин блокировки.

Календарь и допущения — как в test_v2_plan_availability.py. V5.6: 2 основных занятия в неделю (замороженный
slots/schedule), роль занятия А/Б — по последовательности (`next_role`, чередуется после завершённого занятия)."""

import pytest

from app.db.models import User
from app.db.models_program import PlanItem
from app.domain.plan_occurrence import OccurrenceState, OccurrenceStateResult
from app.services.plan_view import _start_availability
from app.web import routes_v2_live
from tests.helpers.legacy_inclusion import (
    MON,
    day,
    ensure_week,
    get_plan,
    make_clock,
    start,
    week_items,
)
from tests.test_web.test_v2_course_v5 import WEIGHTED_INPUTS, _cycle, _enrol, _pullups

CONFIRMED_REPS = [[17, 17, 17, 19], [5, 5, 5, 5, 5]]


@pytest.fixture
def clock(monkeypatch):
    setter = make_clock(monkeypatch)
    setter(MON)
    return setter


async def test_v56_variants_actual_for_next_projected_after_and_actual_for_done(session, user: User, clock):
    """Старт: next_role = А. Неделя 1: занятие 1 — А (actual, №1), занятие 2 — Б (projected, №2); неделя 2
    продолжает чередование: А, Б (projected, №1, №2). После завершённого занятия 1 (А): оно остаётся А (actual по
    рецепту сессии), следующее открытое занятие 2 — Б (actual: next_role стал Б), неделя 2: А, Б (projected)."""
    inclusion = await _enrol(session, user, await _pullups(session), course_inputs=WEIGHTED_INPUTS)
    assert inclusion.progression_state["next_role"] == "A"
    await ensure_week(session, user, 2)
    plan = await get_plan(session, user)

    def variants(number: int):
        return [(r["session_variant"], r["session_variant_basis"], r["session_ordinal"]) for r in week_items(plan, number)]

    assert variants(1) == [("A", "actual", 1), ("B", "projected", 2)]
    assert variants(2) == [("A", "projected", 1), ("B", "projected", 2)]

    await _cycle(session, user, clock, 0, CONFIRMED_REPS)
    clock(day(1))
    plan = await get_plan(session, user)
    assert variants(1) == [("A", "actual", 1), ("B", "actual", 2)]
    assert variants(2) == [("A", "projected", 1), ("B", "projected", 2)]


async def test_v56_schedule_is_two_per_week_and_not_legacy(session, user: User, clock):
    await _enrol(session, user, await _pullups(session), course_inputs=WEIGHTED_INPUTS)
    schedule = (await get_plan(session, user))["program_inclusions"][0]["schedule"]
    assert schedule == {
        "sessions_per_week": 2, "source": "snapshot", "is_legacy": False,
        "min_days_between_starts": 3, "weekly_capacity": 3,
    }


async def test_legacy_inclusion_has_no_variant(session, user: User, clock):
    from tests.helpers.legacy_inclusion import enrol_legacy_pre_v56
    await enrol_legacy_pre_v56(session, user, clock)
    rows = week_items(await get_plan(session, user), 1)
    assert [(r["session_variant"], r["session_variant_basis"], r["session_ordinal"]) for r in rows] == [
        (None, None, 1), (None, None, 2), (None, None, 3),
    ]


async def test_admin_bypasses_rest_in_start_allowed_but_infeasible_stays_blocked(session, user: User, clock, monkeypatch):
    """Админ обходит K1 на старте (test_admin_bypasses_rest) ⇒ too_early-строки для него start_allowed; infeasible — нет."""
    from tests.helpers.legacy_inclusion import do_main, enrol_legacy_pre_v56
    await enrol_legacy_pre_v56(session, user, clock)
    first = week_items(await get_plan(session, user), 1)[0]
    await do_main(session, user, clock, first["id"], at=day(6))  # вс 11 окт
    await ensure_week(session, user, 2)
    monkeypatch.setattr(routes_v2_live.settings, "admin_ids", str(user.telegram_id))
    rows = week_items(await get_plan(session, user), 2)
    assert [(r["state"], r["start_allowed"]) for r in rows] == [
        ("too_early", True), ("too_early", True), ("infeasible", False),
    ]
    assert (await start(session, user, rows[0]["id"])).status_code == 200


def test_start_availability_reasons_and_precedence():
    item = PlanItem(id=1, exercise_id=1, count_per_week=1, legacy_aggregate=False)
    aggregate = PlanItem(id=2, exercise_id=1, count_per_week=3, legacy_aggregate=True)

    def state(value, **kw):
        return OccurrenceStateResult(value, **kw)

    allowed = {"access_allowed": True, "bypass_spacing": False}
    assert _start_availability(item, state(OccurrenceState.AVAILABLE), **allowed) == (True, None)
    assert _start_availability(item, None, **allowed) == (True, None)
    assert _start_availability(item, state(OccurrenceState.COMPLETED), **allowed) == (False, "completed")
    assert _start_availability(item, state(OccurrenceState.MISSED), **allowed) == (False, "missed")
    assert _start_availability(item, state(OccurrenceState.INFEASIBLE), **allowed) == (False, "infeasible")
    assert _start_availability(item, state(OccurrenceState.TOO_EARLY), **allowed) == (False, "too_early")
    assert _start_availability(item, state(OccurrenceState.AWAITING_ASSESSMENT), **allowed) == (
        False, "awaiting_assessment",
    )
    # нет подписки: причина доступа приоритетнее отдыха (старт сначала проверяет доступ)
    assert _start_availability(item, state(OccurrenceState.TOO_EARLY), access_allowed=False, bypass_spacing=False) == (
        False, "no_access",
    )
    assert _start_availability(item, state(OccurrenceState.TOO_EARLY), access_allowed=True, bypass_spacing=True) == (
        True, None,
    )
    assert _start_availability(aggregate, state(OccurrenceState.AVAILABLE), **allowed) == (False, "missed")

