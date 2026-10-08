"""#301 targeted aged-state repair (scripts/repair_plan_convergence.py): the operator tool runs the SAME runtime
convergence (PlanWeekService.ensure_current_plan_week -> converge_inclusion_snapshot) for ONE identity.
Owner acceptance (2026-10-06): dry-run shows the exact mutation and writes nothing; apply touches only that
identity and only the missing snapshot data + required materialisation; idempotent; guards abort otherwise.

The aged state is built by the real paths (POST /program-inclusions, GET /plan with a back-dated clock), plus the
one historical-shape mutation the staging snapshot proved (inclusion snapshot without "program_items")."""

import copy
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.db.models_program import (
    Exercise,
    PlanItem,
    PlanWeek,
    Program,
    ProgramInclusion,
    ProgramItem,
    TrainingPlan,
)
from app.db.repositories.users import UserRepository
from app.domain.multi_program import MetricType, ProgramStructureType, WeekPhase
from app.web import routes_v2
from scripts.repair_plan_convergence import (
    EXIT_GUARD,
    EXIT_NO_PLAN,
    EXIT_NO_USER,
    EXIT_OK,
    _diff,
    _State,
    run_repair,
)
from tests.test_web._v2_client import v2_get, v2_post

PLAN_CREATED = datetime(2026, 9, 14, 10, tzinfo=UTC)  # week 1; 2026-10-06 is week 4
OPENED_IN_WEEK_1 = datetime(2026, 9, 16, 11, tzinfo=UTC)
TODAY = date(2026, 10, 6)
OWNER_TG, BYSTANDER_TG = 7000000005, 7000000099
PROGRESSED = {"schema_version": 1, "strategy_type": "step", "block_a": {"target": 11}, "block_b": {"target": 4}}


@pytest.fixture
def clock(monkeypatch):
    def _set(now: datetime) -> None:
        monkeypatch.setattr(routes_v2, "_utcnow", lambda: now)
    return _set


async def _program(session) -> Program:
    program = Program(
        name="Подтягивания", goal="test", structure_type=ProgramStructureType.RECURRING, category="pull_ups", config={},
    )
    session.add(program)
    await session.flush()
    for subcategory in ("block_a", "block_b"):
        exercise = Exercise(
            name=f"Подтягивания {subcategory}", metric_type=MetricType.REPS, category="pull_ups", subcategory=subcategory,
        )
        session.add(exercise)
        await session.flush()
        session.add(ProgramItem(program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=exercise.id, count_per_week=3))
    await session.commit()
    return program


async def _aged_legacy_user(session, clock, program: Program, telegram_id: int) -> ProgramInclusion:
    user = await UserRepository(session).create(telegram_id=telegram_id, username=None)
    session.add(TrainingPlan(user_id=user.id, created_at=PLAN_CREATED))
    await session.commit()
    clock(PLAN_CREATED)
    response = await v2_post(session, telegram_id, "/api/v2/program-inclusions", {"program_id": program.id})
    assert response.status_code == 200, response.text
    await session.commit()
    clock(OPENED_IN_WEEK_1)
    assert (await v2_get(session, telegram_id, "/api/v2/plan")).status_code == 200
    await session.commit()
    inclusion = await session.get(ProgramInclusion, response.json()["id"])
    inclusion.snapshot = {k: v for k, v in inclusion.snapshot.items() if k != "program_items"}
    inclusion.progression_state = PROGRESSED
    await session.commit()
    return inclusion


async def _current_week_items(session, training_plan_id: int) -> int:
    week = (await session.execute(
        select(PlanWeek).where(PlanWeek.training_plan_id == training_plan_id, PlanWeek.week_number == 4),
    )).scalar_one_or_none()
    if week is None:
        return 0
    return len((await session.execute(select(PlanItem).where(PlanItem.plan_week_id == week.id))).scalars().all())


async def _fresh(session, inclusion_id: int) -> ProgramInclusion:
    session.expire_all()
    return await session.get(ProgramInclusion, inclusion_id)


async def test_dry_run_reports_the_exact_mutation_and_writes_nothing(session, clock):
    program = await _program(session)
    owner = await _aged_legacy_user(session, clock, program, OWNER_TG)
    owner_id, owner_plan = owner.id, owner.training_plan_id

    code, report = await run_repair(session, telegram_id=OWNER_TG, apply=False, today=TODAY)

    assert code == EXIT_OK
    assert report["result"] == "dry-run: rolled back, nothing written"
    assert report["current_week_number"] == 4
    assert report["before"]["current_week_plan_items"] == 0
    assert report["after"]["current_week_plan_items"] == 3  # #304: 3 занятия main (A + Б в каждом)
    repairs = report["mutation"]["snapshot_repairs"]
    assert [(r["inclusion_id"], r["reason"], r["program_items_before"]) for r in repairs] == [
        (owner_id, "missing_program_items_key", "<missing key>"),
    ]
    assert len(repairs[0]["program_items_after"]) == 2  # снимок — по-прежнему 2 элемента программы
    assert {i["week_number"] for i in report["mutation"]["plan_items_created"]} == {4}
    assert report["guard_violations"] == []
    # nothing persisted
    assert "program_items" not in (await _fresh(session, owner_id)).snapshot
    assert await _current_week_items(session, owner_plan) == 0


async def test_apply_repairs_only_the_target_identity_preserves_state_and_is_idempotent(session, clock):
    program = await _program(session)
    owner = await _aged_legacy_user(session, clock, program, OWNER_TG)
    bystander = await _aged_legacy_user(session, clock, program, BYSTANDER_TG)
    owner_id, owner_plan, owner_started_at = owner.id, owner.training_plan_id, owner.started_at
    bystander_id, bystander_plan = bystander.id, bystander.training_plan_id

    code, report = await run_repair(session, telegram_id=OWNER_TG, apply=True, today=TODAY)

    assert (code, report["result"]) == (EXIT_OK, "applied")
    owner = await _fresh(session, owner_id)
    assert len(owner.snapshot["program_items"]) == 2
    assert owner.progression_state == PROGRESSED
    assert owner.started_at == owner_started_at
    assert owner.is_active
    assert await _current_week_items(session, owner_plan) == 3  # #304: занятия, не агрегатные строки
    # the other aged user is NOT auto-repaired by the targeted tool
    assert "program_items" not in (await _fresh(session, bystander_id)).snapshot
    assert await _current_week_items(session, bystander_plan) == 0

    code, again = await run_repair(session, telegram_id=OWNER_TG, apply=True, today=TODAY)
    assert (code, again["result"]) == (EXIT_OK, "nothing to do")
    assert await _current_week_items(session, owner_plan) == 3


async def test_unknown_identity_and_identity_without_plan_are_refused(session):
    assert (await run_repair(session, telegram_id=123, apply=True, today=TODAY))[0] == EXIT_NO_USER
    await UserRepository(session).create(telegram_id=124, username=None)
    await session.commit()
    assert (await run_repair(session, telegram_id=124, apply=True, today=TODAY))[0] == EXIT_NO_PLAN


def _state_with(snapshot: dict, progression: dict, items: dict | None = None) -> _State:
    state = _State()
    state.inclusions[1] = {
        "program_id": 1, "is_active": True, "started_at": PLAN_CREATED, "expires_at": None,
        "snapshot": snapshot, "progression_state": progression, "initial_progression_state": {},
    }
    state.weeks = {10: {"week_number": 1, "start_date": date(2026, 9, 14)}, 40: {"week_number": 4, "start_date": TODAY}}
    state.items = items or {}
    return state


def test_guard_rejects_rewriting_a_non_empty_historical_snapshot():
    before = _state_with({"program_items": [{"id": 1}]}, PROGRESSED)
    after = copy.deepcopy(before)
    after.inclusions[1]["snapshot"] = {"program_items": [{"id": 1}, {"id": 2}]}
    _, violations = _diff(before, after, current_week_number=4)
    assert any("non-empty historical" in v for v in violations)


def test_guard_rejects_progression_change_other_snapshot_keys_and_past_week_rows():
    before = _state_with({"program_name": "Подтягивания"}, PROGRESSED)
    after = copy.deepcopy(before)
    after.inclusions[1]["snapshot"] = {"program_name": "другое", "program_items": [{"id": 1}]}
    after.inclusions[1]["progression_state"] = {"block_a": {"target": 1}}
    after.items[99] = {"plan_week_id": 10, "program_inclusion_id": 1, "exercise_id": 1, "complex_id": None,
                       "count_per_week": 3, "day_of_week": None, "week_phase": "base"}
    _, violations = _diff(before, after, current_week_number=4)
    assert any("progression_state changed" in v for v in violations)
    assert any("other than program_items" in v for v in violations)
    assert any("outside current/future weeks" in v for v in violations)


def test_guard_accepts_exactly_the_allowed_repair():
    before = _state_with({"program_name": "Подтягивания"}, PROGRESSED)
    after = copy.deepcopy(before)
    after.inclusions[1]["snapshot"] = {"program_name": "Подтягивания", "program_items": [{"id": 1}]}
    after.items[99] = {"plan_week_id": 40, "program_inclusion_id": 1, "exercise_id": 1, "complex_id": None,
                       "count_per_week": 3, "day_of_week": None, "week_phase": "base"}
    mutation, violations = _diff(before, after, current_week_number=4)
    assert violations == []
    assert mutation["snapshot_repairs"][0]["reason"] == "missing_program_items_key"
    assert EXIT_GUARD == 4
