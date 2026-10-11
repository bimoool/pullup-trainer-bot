"""Программа «Подтягивания» V5.6 (issue #305) через API на реальном Postgres.

Сквозной путь: подключение (правило pullups_v5_6@1, провенанс) → недостающие входы (409
course_setup_required, PUT /course/inputs) → живой старт занятия A/B (SetTarget + рецепт в снимке
сессии: роль, уровень, отдых 240/30 → 900 → 180, маркеры) → завершение с подтверждениями техники/отдыха
→ типизированная прогрессия по блокам → следующее занятие. Плюс: только вперёд (правка истории и
снимки не меняются, каскад неприменим), повторное завершение без второй прогрессии, копия сессии без
кредита, устаревшая версия программы читается и исполняется прежним кодом, тест 1RM."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, update

from app.db.models import Baseline, EquipmentItem, User
from app.db.models_program import (
    Exercise,
    Program,
    ProgramInclusion,
    ProgramItem,
    ProgressionStrategyProfile,
    SessionBlock,
    SetTarget,
    TrainingPlan,
    TrainingSession,
)
from app.domain.multi_program import MetricType, ProgramStructureType, WeekPhase
from app.domain.progression_strategy import ProgressionStrategyType
from app.services import live_session
from app.web import routes_v2
from tests.test_web._v2_client import v2_get, v2_patch, v2_post, v2_put

MON = datetime(2026, 10, 5, 10, tzinfo=UTC)


@pytest.fixture
def clock(monkeypatch):
    def _set(now: datetime) -> None:
        monkeypatch.setattr(routes_v2, "_utcnow", lambda: now)
        monkeypatch.setattr(live_session, "_utcnow", lambda: now)
    _set(MON)
    return _set


async def _pullups(session) -> Program:
    profile = ProgressionStrategyProfile(strategy_type=ProgressionStrategyType.STEP, name="Step V5.6", config={})
    session.add(profile)
    await session.flush()
    program = Program(
        name="Подтягивания", goal="test", structure_type=ProgramStructureType.RECURRING, category="pull_ups",
        progression_strategy_id=profile.id, access_level="free",
        config={"block_a": {"base_target": 10, "work_sets": 3}, "block_b": {"base_target": 3}},
        constraints=[{"spacing_group": "main", "min_days_between_starts": 3}],
        frequency={"sessions_per_week": 3, "per_slot": {}},  # каталог: 3 — как у поставляемой программы
    )
    session.add(program)
    await session.flush()
    for name, role in (("Подтягивания — объём", "block_a"), ("Подтягивания — сила", "block_b")):
        exercise = Exercise(name=name, metric_type=MetricType.REPS, category="pull_ups", subcategory=role)
        session.add(exercise)
        await session.flush()
        session.add(ProgramItem(
            program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=exercise.id, count_per_week=2, day_of_week=None,
        ))
    await session.flush()
    return program


async def _enrol(session, user: User, program: Program, *, fresh_max: int | None = 25, weight="70", **payload):
    user.timezone = "UTC"
    user.weight_kg = Decimal(weight) if weight is not None else None
    session.add(TrainingPlan(user_id=user.id, created_at=MON - timedelta(hours=1)))
    if fresh_max is not None:
        session.add(Baseline(user_id=user.id, performed_at=MON - timedelta(days=1), reps=fresh_max))
    await session.flush()
    response = await v2_post(session, user.telegram_id, "/api/v2/program-inclusions", {"program_id": program.id, **payload})
    assert response.status_code == 200, response.text
    return await session.get(ProgramInclusion, response.json()["id"])


async def _main_occurrences(session, user: User, week_number: int = 1) -> list[dict]:
    if week_number > 1:
        created = await v2_post(session, user.telegram_id, "/api/v2/plan/weeks", {"week_number": week_number})
        assert created.status_code == 200, created.text
    response = await v2_get(session, user.telegram_id, "/api/v2/plan")
    assert response.status_code == 200, response.text
    plan = response.json()["plan"]
    week_id = next(w["id"] for w in plan["plan_weeks"] if w["week_number"] == week_number)
    return sorted(
        (i for i in plan["plan_items"] if i["plan_week_id"] == week_id and i["program_slot_key"] == "main"),
        key=lambda i: i["occurrence_index"],
    )


async def _start(session, user: User, plan_item_id: int):
    return await v2_post(session, user.telegram_id, "/api/v2/sessions/live", {
        "client_session_id": str(uuid.uuid4()), "plan_item_ids": [plan_item_id],
    })


async def _log(session, user: User, started: dict, reps_by_block: list[list[int]]) -> None:
    sets, index = [], 0
    for block_index, reps in enumerate(reps_by_block):
        exercise_id = started["blocks"][block_index]["exercise_id"]
        for value in reps:
            sets.append({"set_index": index, "exercise_id": exercise_id, "value": value, "block_index": block_index})
            index += 1
    response = await v2_post(session, user.telegram_id, f"/api/v2/sessions/live/{started['id']}/sets:batch", {"sets": sets})
    assert response.status_code == 200, response.text


CONFIRMED = [
    {"block_index": 0, "technique_valid": True, "rest_within_limit": True},
    {"block_index": 1, "technique_valid": True, "rest_within_limit": True},
]


async def _complete(session, user: User, session_id: int, checks: list | None = CONFIRMED) -> dict:
    payload = {"abandoned": False}
    if checks is not None:
        payload["block_checks"] = checks
    done = await v2_post(session, user.telegram_id, f"/api/v2/sessions/live/{session_id}/complete", payload)
    assert done.status_code == 200, done.text
    return done.json()


async def _cycle(session, user: User, clock, index: int, reps_by_block: list[list[int]], checks=CONFIRMED) -> tuple[dict, dict]:
    """Одно основное занятие (через 3 дня после предыдущего — отдых MAIN): старт, подходы, завершение."""
    at = MON + timedelta(days=3 * index)
    clock(at)
    # V5.6 §1: две основные тренировки в неделю — занятие index живёт в неделе 1 + index // 2.
    occurrences = await _main_occurrences(session, user, week_number=1 + index // 2)
    started = await _start(session, user, occurrences[index % 2]["id"])
    assert started.status_code == 200, started.text
    body = started.json()
    await _log(session, user, body, reps_by_block)
    done = await _complete(session, user, body["id"], checks)
    await session.execute(update(TrainingSession).where(TrainingSession.id == body["id"]).values(
        performed_at=at, started_at=at, completed_at=at + timedelta(minutes=50), ended_at=at + timedelta(minutes=50),
    ))
    await session.flush()
    return body, done


async def _setup_weighted(session, user: User, program: Program) -> ProgramInclusion:
    inclusion = await _enrol(
        session, user, program, course_inputs={"e1rm_kg": "30", "load_step_kg": "0.5"},
    )
    return inclusion


# --- Подключение и входы ---------------------------------------------------------------------------


async def test_new_inclusion_uses_v5_6_rule_and_records_provenance(session, user: User, clock):
    inclusion = await _setup_weighted(session, user, await _pullups(session))
    state = inclusion.progression_state
    assert state["program_version"] == "pullups_v5_6" and state["level"] == "weighted"
    assert state["inputs"]["fresh_max"] == 25 and state["inputs"]["body_mass_kg"] == "70"
    assert (state["strength_a"]["load_kg"], state["strength_b"]["load_kg"]) == ("5", "10")
    provenance = inclusion.prescription_provenance
    assert (provenance["rule_id"], provenance["rule_version"], provenance["rule_decided"]) == ("pullups_v5_6", 1, True)
    assert provenance["program_version"] == "pullups_v5_6" and provenance["inputs"]["e1rm_kg"] == "30"
    assert provenance["assessment"]["max_reps"] == 25


async def test_missing_inputs_block_start_with_explicit_list_then_inputs_unblock(session, user: User, clock):
    program = await _pullups(session)
    inclusion = await _enrol(session, user, program, fresh_max=3, weight=None)
    occurrence = (await _main_occurrences(session, user))[0]
    blocked = await _start(session, user, occurrence["id"])
    assert blocked.status_code == 409, blocked.text
    detail = blocked.json()["detail"]
    assert detail["code"] == "course_setup_required"
    assert set(detail["missing"]) == {"volume_capacity", "volume_assistance", "strength_assistance"}

    dashboard = await v2_get(session, user.telegram_id, "/api/v2/dashboard/status")
    assert dashboard.json()["status"] == "course_setup_required"
    assert set(dashboard.json()["course_pending_inputs"]) == set(detail["missing"])

    band = {"kind": "band", "name": "Синяя", "colour": "синяя", "attachment": "петля", "body_position": "стопа"}
    incomplete = await v2_put(session, user.telegram_id, f"/api/v2/program-inclusions/{inclusion.id}/course/inputs", {
        "volume_capacity": 10, "volume_assistance": {"kind": "band", "name": "Синяя"},
    })
    assert incomplete.status_code == 200 and "volume_assistance" in incomplete.json()["pending_inputs"]  # не готова
    put = await v2_put(session, user.telegram_id, f"/api/v2/program-inclusions/{inclusion.id}/course/inputs", {
        "volume_capacity": 10, "volume_assistance": band, "strength_assistance": {"kind": "bodyweight"},
    })
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["pending_inputs"] == [] and body["level"] == "assisted"
    assert body["next_workout"]["blocks"][0]["display"] == "7/7/7/7+"
    assert body["next_workout"]["blocks"][1]["display"] == "5/5/5/5/5–8"

    started = await _start(session, user, occurrence["id"])
    assert started.status_code == 200, started.text


async def test_legacy_targets_or_version_create_legacy_inclusion(session, user: User, clock):
    program = await _pullups(session)
    inclusion = await _enrol(session, user, program, program_version="pullups_legacy_step")
    assert "program_version" not in inclusion.progression_state
    assert inclusion.progression_state["block_b"]["work_sets"] == 4
    assert inclusion.prescription_provenance["program_version"] == "pullups_legacy_step"
    bad = await v2_post(session, user.telegram_id, "/api/v2/program-inclusions", {
        "program_id": program.id, "program_version": "pullups_v5_6", "initial_target_a": 12, "restart": True,
    })
    assert bad.status_code == 422


# --- Расписание: две основные тренировки в неделю только у V5.6 -------------------------------------


async def test_v5_enrolment_freezes_two_main_sessions_per_week(session, user: User, clock):
    program = await _pullups(session)
    inclusion = await _setup_weighted(session, user, program)
    main = next(slot for slot in inclusion.snapshot["slots"] if slot["key"] == "main")
    assert main["sessions_per_week"] == 2
    assert inclusion.snapshot["schedule"] == {"program_version": "pullups_v5_6", "main_sessions_per_week": 2}
    assert len(await _main_occurrences(session, user)) == 2
    await session.refresh(program)
    assert program.frequency["sessions_per_week"] == 3  # каталог не изменён
    # Повторная инициализация (convergence) объём не меняет.
    from app.services.plan_convergence import PlanConvergenceService
    _, again = await PlanConvergenceService(session).converge_user_plan(
        training_plan_id=inclusion.training_plan_id, today=MON.date(),
    )
    assert again.mutations == 0, again.as_dict()
    assert len(await _main_occurrences(session, user)) == 2


async def test_legacy_enrolment_keeps_catalog_frequency(session, user: User, clock):
    inclusion = await _enrol(session, user, await _pullups(session), program_version="pullups_legacy_step")
    main = next(slot for slot in inclusion.snapshot["slots"] if slot["key"] == "main")
    assert main["sessions_per_week"] == 3 and "schedule" not in inclusion.snapshot
    assert len(await _main_occurrences(session, user)) == 3


async def test_aged_legacy_snapshot_without_frozen_slots_is_not_rescheduled(session, user: User, clock):
    """Инклюзия до #304 (снимок без slots) читает частоту из каталога, как раньше; V5.6 её не трогает."""
    inclusion = await _enrol(session, user, await _pullups(session), program_version="pullups_legacy_step")
    snapshot = {k: v for k, v in inclusion.snapshot.items() if k != "slots"}
    inclusion.snapshot = snapshot
    await session.flush()
    assert len(await _main_occurrences(session, user)) == 3
    await session.refresh(inclusion)
    assert "schedule" not in inclusion.snapshot and "program_version" not in inclusion.progression_state


# --- Живой старт: SetTarget и снимок рецепта ----------------------------------------------------------


async def test_a_start_writes_targets_and_full_prescription_snapshot(session, user: User, clock):
    inclusion = await _setup_weighted(session, user, await _pullups(session))
    started = await _start(session, user, (await _main_occurrences(session, user))[0]["id"])
    assert started.status_code == 200, started.text
    body = started.json()
    volume, strength = body["blocks"]
    assert [Decimal(t["value"]) for t in volume["targets"]] == [17, 17, 17, 17]
    assert [t["marker"] for t in volume["targets"]] == ["working", "working", "working", "amrap"]
    assert [t["is_max_set"] for t in volume["targets"]] == [False, False, False, True]
    assert [Decimal(t["value"]) for t in strength["targets"]] == [5] * 5
    assert {t["is_max_set"] for t in strength["targets"]} == {False}  # силовой 5×5 — без максимума
    assert volume["course_block"]["rest_seconds"] == 240 and strength["course_block"]["rest_seconds"] == 180
    assert strength["course_block"]["external_load_kg"] == "5"
    assert body["course_program"]["workout_role"] == "A" and body["course_program"]["inter_block_rest_seconds"] == 900

    row = await session.get(TrainingSession, body["id"])
    snapshot = row.prescription_snapshot
    course = snapshot["provenance"]["course_program"]
    assert course["program_version"] == "pullups_v5_6" and course["level"] == "weighted"
    assert [b["block_role"] for b in course["blocks"]] == ["a_volume", "a_weighted_strength"]
    assert course["source_inputs"]["fresh_max"] == 25 and course["source_inputs"]["e1rm_kg"] == "30"
    assert snapshot["provenance"]["strategy"] == "pullups_v5_6"
    assert snapshot["provenance"]["progression_state_rev"] == inclusion.progression_state_rev
    assert snapshot["blocks"][0]["rest_after_block_seconds"] == 900
    assert [s["rest_after_seconds"] for s in snapshot["blocks"][0]["sets"]] == [240, 240, 240, None]
    assert [s["rest_after_seconds"] for s in snapshot["blocks"][1]["sets"]] == [180, 180, 180, 180, None]


async def test_v5_role_block_cannot_start_alone(session, user: User, clock):
    inclusion = await _setup_weighted(session, user, await _pullups(session))
    exercise_id = inclusion.snapshot["exercises"][0]["exercise_id"]
    from app.db.models_program import PlanItem
    item = PlanItem(training_plan_id=inclusion.training_plan_id, exercise_id=exercise_id, count_per_week=1, program_inclusion_id=inclusion.id)
    session.add(item)
    await session.flush()
    response = await _start(session, user, item.id)
    assert response.status_code == 422


async def test_dashboard_ready_describes_next_v5_workout(session, user: User, clock):
    await _setup_weighted(session, user, await _pullups(session))
    response = await v2_get(session, user.telegram_id, "/api/v2/dashboard/status")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ready" and body["program_version"] == "pullups_v5_6"
    assert body["block_a"]["display"] == "17/17/17/17+" and body["block_a"]["block_role"] == "a_volume"
    assert body["block_b"]["display"] == "5×5 +5 кг" and body["block_b"]["equipment"]["type"] == "weight"
    assert body["course"]["workout_role"] == "A"


async def test_v5_main_start_respects_main_spacing(session, user: User, clock):
    await _setup_weighted(session, user, await _pullups(session))
    await _cycle(session, user, clock, 0, [[17, 17, 17, 19], [5, 5, 5, 5, 5]])
    clock(MON + timedelta(days=1))
    too_early = await _start(session, user, (await _main_occurrences(session, user))[1]["id"])
    assert too_early.status_code == 409 and too_early.json()["detail"]["code"] == "too_early"


# --- Завершение: типизированная прогрессия --------------------------------------------------------------


async def test_a_then_b_sequence_progresses_each_block_by_its_own_signal(session, user: User, clock):
    inclusion = await _setup_weighted(session, user, await _pullups(session))
    rev = inclusion.progression_state_rev

    _a, done_a = await _cycle(session, user, clock, 0, [[17, 17, 17, 19], [5, 5, 5, 5, 5]])
    assert done_a["progression_result"] is None
    course = done_a["course_progression"]
    assert course["workout_role"] == "A" and course["next_workout_role"] == "B"
    volume, strength = course["blocks"]
    assert (volume["block_role"], volume["decision"], volume["fact_volume"]) == ("a_volume", "add_mandatory_rep", 70)
    assert (strength["block_role"], strength["decision"]) == ("a_weighted_strength", "increase_load")
    assert strength["details"]["delta_kg"] == "1.5"
    await session.refresh(inclusion)
    assert inclusion.progression_state_rev == rev + 1
    assert inclusion.progression_state["volume_a"]["targets"] == [18, 17, 17, 17]
    assert inclusion.progression_state["strength_a"]["load_kg"] == "6.5"

    b, done_b = await _cycle(session, user, clock, 1, [[5] * 13 + [2], [3, 3, 3, 3, 3]])
    assert [Decimal(t["value"]) for t in b["blocks"][0]["targets"]] == [5] * 15  # V_ref 70 → 15×5
    assert {t["marker"] for t in b["blocks"][0]["targets"]} == {"dynamic"}
    assert b["course_program"]["blocks"][0]["rest_seconds"] == 30
    assert b["blocks"][1]["course_block"]["external_load_kg"] == "10"
    volume, strength = done_b["course_progression"]["blocks"]
    assert (volume["block_role"], volume["decision"], volume["fact_volume"]) == ("b_volume", "hold", 67)
    assert volume["details"]["stop_reason"] == "low_reps"
    assert (strength["block_role"], strength["decision"]) == ("b_weighted_strength", "increase_load")
    await session.refresh(inclusion)
    assert inclusion.progression_state["strength_b"]["load_kg"] == "11.5"
    assert inclusion.progression_state["strength_a"]["load_kg"] == "6.5"  # A и B независимы

    a2, _ = await _cycle(session, user, clock, 2, [[18, 17, 17, 17], [5, 5, 5, 5, 4]])
    assert [Decimal(t["value"]) for t in a2["blocks"][0]["targets"]] == [18, 17, 17, 17]
    assert a2["blocks"][1]["course_block"]["display"] == "5×5 +6.5 кг"
    clock(MON + timedelta(days=9))
    b2 = await _start(session, user, (await _main_occurrences(session, user, week_number=2))[1]["id"])
    assert b2.status_code == 200, b2.text
    assert b2.json()["blocks"][0]["course_block"]["intermediate_goal"] == 68  # прошлый факт 67 + 1


async def test_unconfirmed_technique_never_counts_as_valid(session, user: User, clock):
    inclusion = await _setup_weighted(session, user, await _pullups(session))
    _a, done = await _cycle(session, user, clock, 0, [[17, 17, 17, 25], [5, 5, 5, 5, 5]], checks=None)
    volume, strength = done["course_progression"]["blocks"]
    assert (volume["decision"], volume["reason"]) == ("repeat", "unconfirmed")
    assert (strength["decision"], strength["reason"]) == ("hold", "standard_unconfirmed")
    await session.refresh(inclusion)
    assert inclusion.progression_state["volume_a"]["targets"] == [17, 17, 17, 17]
    assert inclusion.progression_state["strength_a"]["load_kg"] == "5"


def _band(item: EquipmentItem, colour: str) -> dict:
    return {
        "kind": "band", "equipment_item_id": item.id, "name": item.name, "colour": colour,
        "attachment": "петля на перекладине", "body_position": "стопа",
    }


async def test_assisted_strength_band_step_waits_for_full_setup_confirmation(session, user: User, clock):
    """Следующая ступень помощи — по ЛИЧНОМУ порядку резин, но порядок не подтверждает цвет, крепление и
    положение стопы/колена: блок хранит прежнюю подтверждённую помощь, намерение ждёт, старт этой роли
    заблокирован до подтверждения полной записи; неполная запись — 422."""
    program = await _pullups(session)
    session.add_all([
        EquipmentItem(user_id=user.id, name="Красная", position=0),
        EquipmentItem(user_id=user.id, name="Синяя", position=1),
        EquipmentItem(user_id=user.id, name="Жёлтая", position=2),
    ])
    await session.flush()
    items = list((await session.execute(select(EquipmentItem).where(EquipmentItem.user_id == user.id).order_by(EquipmentItem.position))).scalars())
    inclusion = await _enrol(session, user, program, fresh_max=4, course_inputs={
        "volume_capacity": 10, "volume_assistance": _band(items[0], "красная"),
        "strength_assistance": _band(items[1], "синяя"),
    })
    started, done = await _cycle(session, user, clock, 0, [[7, 7, 7, 9], [5, 5, 5, 5, 8]])
    assert [t["marker"] for t in started["blocks"][1]["targets"]] == ["working"] * 4 + ["control"]
    assert started["blocks"][1]["targets"][-1]["cap_reps"] == 8
    strength = done["course_progression"]["blocks"][1]
    assert (strength["block_role"], strength["assistance_intent"]) == ("assisted_strength", "decrease_assistance")
    assert strength["reason"] == "assistance_confirmation_required"
    await session.refresh(inclusion)
    state = inclusion.progression_state
    assert state["strength_a"]["assistance"] == _band(items[1], "синяя")  # прежняя, подтверждённая
    assert state["assistance_pending"] == [{
        "block": "strength_a", "intent": "decrease_assistance",
        "proposed": {"kind": "band", "equipment_item_id": items[2].id, "name": "Жёлтая", "colour": None,
                     "attachment": None, "body_position": None},
    }]
    assert state["strength_b"]["assistance"] == _band(items[1], "синяя")

    # B не затронута; следующая A — только после подтверждения.
    await _cycle(session, user, clock, 1, [[5] * 10, [5, 5, 5, 5, 6]])
    clock(MON + timedelta(days=6))
    blocked = await _start(session, user, (await _main_occurrences(session, user, week_number=2))[0]["id"])
    assert blocked.status_code == 409 and blocked.json()["detail"]["missing"] == ["assistance_confirmation"]

    path = f"/api/v2/program-inclusions/{inclusion.id}/course/inputs"
    partial = await v2_put(session, user.telegram_id, path, {"assistance_confirmations": [
        {"block": "strength_a", "setup": {"kind": "band", "equipment_item_id": items[2].id, "name": "Жёлтая"}},
    ]})
    assert partial.status_code == 422
    confirmed = await v2_put(session, user.telegram_id, path, {"assistance_confirmations": [
        {"block": "strength_a", "setup": _band(items[2], "жёлтая")},
    ]})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["assistance_pending"] == [] and confirmed.json()["pending_inputs"] == []
    started = await _start(session, user, (await _main_occurrences(session, user, week_number=2))[0]["id"])
    assert started.status_code == 200, started.text
    assert started.json()["blocks"][1]["course_block"]["assistance"] == _band(items[2], "жёлтая")


# --- Только вперёд, идемпотентность, копия ---------------------------------------------------------


async def test_history_edit_rewrites_neither_state_nor_snapshot_nor_targets(session, user: User, clock):
    inclusion = await _setup_weighted(session, user, await _pullups(session))
    body, _ = await _cycle(session, user, clock, 0, [[17, 17, 17, 19], [5, 5, 5, 5, 5]])
    await session.refresh(inclusion)
    state, rev = dict(inclusion.progression_state), inclusion.progression_state_rev
    row = await session.get(TrainingSession, body["id"])
    snapshot_before = dict(row.prescription_snapshot)
    targets_before = [(t.set_number, t.value) for t in (await session.execute(
        select(SetTarget).join(SessionBlock).where(SessionBlock.session_id == body["id"]).order_by(SetTarget.id),
    )).scalars()]

    edited = await v2_patch(session, user.telegram_id, f"/api/v2/sessions/{body['id']}", {
        "sets": [{"block_index": 0, "set_number": 4, "value": "15"}],
    })
    assert edited.status_code == 200, edited.text
    await session.refresh(inclusion)
    await session.refresh(row)
    assert inclusion.progression_state == state and inclusion.progression_state_rev == rev
    assert row.prescription_snapshot == snapshot_before
    assert [(t.set_number, t.value) for t in (await session.execute(
        select(SetTarget).join(SessionBlock).where(SessionBlock.session_id == body["id"]).order_by(SetTarget.id),
    )).scalars()] == targets_before
    cascade = await v2_post(session, user.telegram_id, f"/api/v2/program-inclusions/{inclusion.id}/progression/preview", {
        "edited_session_id": body["id"],
    })
    assert cascade.status_code == 422  # V5.6 — только вперёд, реплея истории нет


async def test_repeat_complete_and_clone_do_not_progress_twice(session, user: User, clock):
    inclusion = await _setup_weighted(session, user, await _pullups(session))
    body, _ = await _cycle(session, user, clock, 0, [[17, 17, 17, 19], [5, 5, 5, 5, 5]])
    await session.refresh(inclusion)
    state, rev = dict(inclusion.progression_state), inclusion.progression_state_rev

    again = await _complete(session, user, body["id"])
    assert again["progression_skipped_reason"] == "already_completed" and again["course_progression"] is None
    clone = await v2_post(session, user.telegram_id, f"/api/v2/sessions/{body['id']}/clone", {})
    assert clone.status_code == 201, clone.text
    await session.refresh(inclusion)
    assert inclusion.progression_state == state and inclusion.progression_state_rev == rev
    cloned = await session.get(TrainingSession, clone.json()["id"])
    assert cloned.plan_item_id is None


async def test_whole_session_record_does_not_progress_v5(session, user: User, clock):
    inclusion = await _setup_weighted(session, user, await _pullups(session))
    roles = {e["role"]: e["exercise_id"] for e in inclusion.snapshot["exercises"]}
    response = await v2_post(session, user.telegram_id, "/api/v2/sessions", {
        "source": "plan", "performed_at": MON.isoformat(), "program_inclusion_id": inclusion.id,
        "blocks": [
            {"exercise_id": roles["block_a"], "sets": [
                {"set_number": i + 1, "metric_type": "reps", "value": "17", "unit": "reps"} for i in range(4)
            ]},
            {"exercise_id": roles["block_b"], "sets": [
                {"set_number": i + 1, "metric_type": "reps", "value": "5", "unit": "reps"} for i in range(5)
            ]},
        ],
    })
    assert response.status_code == 200, response.text
    assert response.json()["progression_skipped_reason"] == "v5_requires_prescribed_session"


# --- Устаревшая версия программы ---------------------------------------------------------------------


async def test_legacy_inclusion_keeps_legacy_blocks_and_formula(session, user: User, clock):
    inclusion = await _enrol(session, user, await _pullups(session), program_version="pullups_legacy_step")
    body, done = await _cycle(session, user, clock, 0, [[10, 10, 10, 12], [3, 3, 3, 3, 6]])
    assert [t["is_max_set"] for t in body["blocks"][1]["targets"]] == [False] * 4 + [True]
    assert body["course_program"] is None
    assert done["course_progression"] is None and done["progression_result"] is not None
    await session.refresh(inclusion)
    assert "program_version" not in inclusion.progression_state  # не переведена в V5.6


# --- Тест 1RM ------------------------------------------------------------------------------------------


async def test_one_rep_max_ladder_and_48h_rule(session, user: User, clock):
    program = await _pullups(session)
    inclusion = await _enrol(session, user, program, fresh_max=12, weight="80", course_inputs={"load_step_kg": "1.25"})
    state = await v2_get(session, user.telegram_id, f"/api/v2/program-inclusions/{inclusion.id}/course")
    assert state.json()["level"] == "transition" and state.json()["pending_inputs"] == ["one_rep_max"]

    path = f"/api/v2/program-inclusions/{inclusion.id}/course/one-rep-max"
    first = await v2_post(session, user.telegram_id, f"{path}/next-set", {"attempts": []})
    assert first.json() == {"next_set": {"set_number": 1, "load_kg": "0", "reps": 5}, "rest_seconds": 180}
    third = await v2_post(session, user.telegram_id, f"{path}/next-set", {"attempts": [
        {"load_kg": "0", "reps": 5, "success": True}, {"load_kg": "7.5", "reps": 3, "success": True},
    ]})
    assert third.json()["next_set"] == {"set_number": 3, "load_kg": "15", "reps": 1}

    recorded = await v2_post(session, user.telegram_id, path, {"attempts": [
        {"load_kg": "0", "reps": 5, "success": True}, {"load_kg": "7.5", "reps": 3, "success": True},
        {"load_kg": "15", "reps": 1, "success": True, "speed": "normal"}, {"load_kg": "18.75", "reps": 1, "success": False},
    ]})
    assert recorded.status_code == 200, recorded.text
    body = recorded.json()
    assert body["one_rep_max"]["e1rm_kg"] == "15"
    # T1RM = 80 + 15 = 95: A 0,75·95 − 80 = −8,75 → масса тела; B 0,80·95 − 80 = −4 → масса тела.
    assert body["pending_inputs"] == [] and body["next_workout"]["blocks"][1]["display"] == "5×5 масса тела"
    assert body["next_workout"]["blocks"][0]["display"] == "5/5/5/5+"

    # Сразу после основной тренировки тест запрещён (48 ч).
    await _cycle(session, user, clock, 0, [[5, 5, 5, 7], [5, 5, 5, 5, 5]])
    await session.execute(update(TrainingSession).values(performed_at=datetime.now(UTC) - timedelta(hours=10)))
    await session.flush()
    too_soon = await v2_post(session, user.telegram_id, path, {"attempts": [{"load_kg": "0", "reps": 5, "success": True}]})
    assert too_soon.status_code == 409 and too_soon.json()["detail"]["code"] == "one_rep_max_too_soon"
    # Начало лестницы проверяет тот же день/48 ч заранее (пользователь не проходит тест ради отказа в конце);
    # следующий подход уже начатого теста — без повторной проверки.
    ladder_start = await v2_post(session, user.telegram_id, f"{path}/next-set", {"attempts": []})
    assert ladder_start.status_code == 409 and ladder_start.json()["detail"]["code"] == "one_rep_max_too_soon"
    ladder_next = await v2_post(session, user.telegram_id, f"{path}/next-set", {"attempts": [
        {"load_kg": "0", "reps": 5, "success": True},
    ]})
    assert ladder_next.status_code == 200 and ladder_next.json()["next_set"]["set_number"] == 2


async def test_course_endpoints_404_for_legacy_inclusion(session, user: User, clock):
    inclusion = await _enrol(session, user, await _pullups(session), program_version="pullups_legacy_step")
    response = await v2_get(session, user.telegram_id, f"/api/v2/program-inclusions/{inclusion.id}/course")
    assert response.status_code == 404
