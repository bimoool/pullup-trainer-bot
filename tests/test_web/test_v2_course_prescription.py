"""DOMAIN-V2 Wave 1c (issue #305): прескрипция курса «Подтягивания» на реальном Postgres через API.

Покрывает механизм, не зависящий от решений владельца OD-1/OD-3 (#310):
  A/E  свежая инклюзия: block_b.work_sets = 4, Live блока Б — 4 рабочих подхода (D2), не 1;
  F/G/H цель с is_max_set → подход → SetLog.is_max_set → вход прогрессии (D3) → РЕАЛЬНАЯ
       recalculate_target (J4: цель 3, 3·3·3·3, max 6). Подход на максимум в Live включается здесь
       ЯВНО (monkeypatch точки решения OD-3) — это тест механизма, не ответ на OD-3;
  I/J  awaiting_assessment: свежий без замера ждёт замера и не стартует main; записанный замер
       переводит в active; пользователь с историей основных тренировок — никогда на замер;
  K/L  повторный converge = 0 изменений; подписка/доступ не меняются.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.models import Baseline, User, Workout, WorkoutStatus
from app.db.models_program import (
    AssessmentProtocol,
    AssessmentResult,
    Exercise,
    Program,
    ProgramInclusion,
    ProgramItem,
    ProgressionStrategyProfile,
    SessionBlock,
    SetLog,
    SetTarget,
    TrainingPlan,
)
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.domain.constants import STRENGTH_BLOCK
from app.domain.course_prescription import TrailingMaxSetRule
from app.domain.multi_program import MetricType, ProgramStructureType, WeekPhase
from app.domain.progression import recalculate_target
from app.domain.progression_strategy import ProgressionStrategyType
from app.domain.session import BlockLog
from app.services import live_session
from app.services.plan_convergence import PlanConvergenceService
from app.web import routes_v2
from tests.test_web._v2_client import v2_get, v2_post

MON = datetime(2026, 10, 5, 10, tzinfo=UTC)


@pytest.fixture
def clock(monkeypatch):
    def _set(now: datetime) -> None:
        monkeypatch.setattr(routes_v2, "_utcnow", lambda: now)
        monkeypatch.setattr(live_session, "_utcnow", lambda: now)
    _set(MON)
    return _set


async def _pullups(session, *, assessment_required: bool = False) -> Program:
    """Как каталожные «Подтягивания» (#304 seed): STEP, block_b.config без work_sets; опционально —
    обязательный замер до первой тренировки (programs.assessment, как засеяно d8a3c6f1e2b4)."""
    profile = ProgressionStrategyProfile(strategy_type=ProgressionStrategyType.STEP, name="Step 305", config={})
    session.add(profile)
    await session.flush()
    assessment = None
    if assessment_required:
        protocol = AssessmentProtocol(name="Максимум 305", metric_type=MetricType.REPS, description="t")
        session.add(protocol)
        await session.flush()
        assessment = {"protocol_id": protocol.id, "required_before_first_session": True, "validity_days": 35}
    program = Program(
        name="Подтягивания", goal="test", structure_type=ProgramStructureType.RECURRING, category="pull_ups",
        progression_strategy_id=profile.id, access_level="free",
        config={"block_a": {"base_target": 10, "work_sets": 3}, "block_b": {"base_target": 3}},
        constraints=[{"spacing_group": "main", "min_days_between_starts": 3}],
        frequency={"sessions_per_week": 3, "per_slot": {}}, assessment=assessment,
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


async def _enrol(session, user: User, program: Program) -> ProgramInclusion:
    user.timezone = "UTC"
    session.add(TrainingPlan(user_id=user.id, created_at=MON - timedelta(hours=1)))
    await session.flush()
    response = await v2_post(session, user.telegram_id, "/api/v2/program-inclusions", {"program_id": program.id})
    assert response.status_code == 200, response.text
    return await session.get(ProgramInclusion, response.json()["id"])


async def _main_occurrences(session, user: User) -> list[dict]:
    response = await v2_get(session, user.telegram_id, "/api/v2/plan")
    assert response.status_code == 200, response.text
    plan = response.json()["plan"]
    week_id = next(w["id"] for w in plan["plan_weeks"] if w["week_number"] == 1)
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


async def _block_rows(session, model, session_id: int, order_index: int) -> list:
    block_id = (await session.execute(
        select(SessionBlock.id).where(SessionBlock.session_id == session_id, SessionBlock.order_index == order_index),
    )).scalar_one()
    return list((await session.execute(
        select(model).where(model.session_block_id == block_id).order_by(model.set_number, model.id),
    )).scalars())


# --- A / E: Block B work_sets ----------------------------------------------------------------------


async def test_a_fresh_inclusion_block_b_has_four_work_sets_and_records_provenance(session, user: User, clock):
    inclusion = await _enrol(session, user, await _pullups(session))

    assert inclusion.progression_state["block_b"]["work_sets"] == STRENGTH_BLOCK.work_sets == 4
    assert inclusion.status == "active"
    assert inclusion.prescription_provenance["rule_id"] == "program_config_default"
    assert inclusion.prescription_provenance["rule_decided"] is False  # OD-1 открыт


async def test_e_live_block_b_executes_and_persists_four_working_sets_not_one(session, user: User, clock):
    await _enrol(session, user, await _pullups(session))
    occurrence = (await _main_occurrences(session, user))[0]

    started = await _start(session, user, occurrence["id"])
    assert started.status_code == 200, started.text
    body = started.json()
    targets = body["blocks"][1]["targets"]
    assert len(targets) == 4  # было 1 (D2 / FD-09)
    assert all(Decimal(str(t["value"])) == 3 and not t["is_max_set"] for t in targets)

    await _log(session, user, body, [[10, 10, 10], [3, 3, 3, 3]])
    rows = await _block_rows(session, SetLog, body["id"], 1)
    assert [int(r.value) for r in rows] == [3, 3, 3, 3]


async def test_e_aged_inclusion_without_block_b_work_sets_still_runs_four_sets(session, user: User, clock):
    """Инклюзия старой формы (миграция ещё не прошла / записана старым кодом): Live нормализует в памяти."""
    inclusion = await _enrol(session, user, await _pullups(session))
    state = dict(inclusion.progression_state)
    state["block_b"] = {k: v for k, v in state["block_b"].items() if k != "work_sets"} | {"target": 5}
    inclusion.progression_state = state
    await session.flush()

    started = await _start(session, user, (await _main_occurrences(session, user))[0]["id"])
    assert started.status_code == 200, started.text
    targets = started.json()["blocks"][1]["targets"]
    assert len(targets) == 4 and all(Decimal(str(t["value"])) == 5 for t in targets)


# --- F / G / H: is_max_set от цели до прогрессии ------------------------------------------------------


async def test_f_g_h_max_target_persists_as_max_and_feeds_real_recalculate_target(
    session, user: User, clock, monkeypatch,
):
    """J4 — механизм. Подход на максимум в Live включён ЯВНО (OD-3 открыт; см. модульный докстринг)."""
    monkeypatch.setattr(live_session, "COURSE_TRAILING_MAX_SET_RULE", TrailingMaxSetRule.INCLUDE)
    inclusion = await _enrol(session, user, await _pullups(session))
    before_b = dict(inclusion.progression_state["block_b"])
    assert before_b["target"] == 3

    started = await _start(session, user, (await _main_occurrences(session, user))[0]["id"])
    assert started.status_code == 200, started.text
    body = started.json()
    assert [t["is_max_set"] for t in body["blocks"][1]["targets"]] == [False, False, False, False, True]

    await _log(session, user, body, [[10, 10, 10, 12], [3, 3, 3, 3, 6]])

    # F: SetLog наследует is_max_set от SetTarget (раньше — жёсткий False).
    targets = await _block_rows(session, SetTarget, body["id"], 1)
    logs = await _block_rows(session, SetLog, body["id"], 1)
    assert [(t.set_number, t.is_max_set) for t in targets] == [(1, False), (2, False), (3, False), (4, False), (5, True)]
    assert [(int(r.value), r.is_max_set) for r in logs] == [(3, False), (3, False), (3, False), (3, False), (6, True)]

    done = await v2_post(session, user.telegram_id, f"/api/v2/sessions/live/{body['id']}/complete", {"abandoned": False})
    assert done.status_code == 200, done.text

    # G/H: прогрессия получила max = 6; ожидание — из РЕАЛЬНОЙ recalculate_target, формула не дублируется.
    log = BlockLog(working_reps=(3, 3, 3, 3), max_reps=6)
    expected = recalculate_target(
        STRENGTH_BLOCK, before_b["target"], log.working_reps, log.max_reps, log.volume, before_b["volume"],
        consecutive_weak_before=before_b["weak_streak"],
    ).new_target
    await session.refresh(inclusion)
    assert inclusion.progression_state["block_b"]["target"] == expected
    assert expected == 4  # J4 (ACCEPTANCE_JOURNEYS_V2): round(3) + max(1, ceil(3·0.05))
    assert inclusion.progression_state["block_b"]["work_sets"] == 4  # прогрессия форму не теряет


async def test_f_extra_set_before_max_does_not_steal_or_shift_max_identity(session, user: User, clock, monkeypatch):
    monkeypatch.setattr(live_session, "COURSE_TRAILING_MAX_SET_RULE", TrailingMaxSetRule.INCLUDE)
    await _enrol(session, user, await _pullups(session))
    body = (await _start(session, user, (await _main_occurrences(session, user))[0]["id"])).json()
    b = body["blocks"][1]
    sets = [
        {"set_index": i, "exercise_id": b["exercise_id"], "value": v, "block_index": 1, "is_extra": extra}
        for i, (v, extra) in enumerate([(3, False), (3, False), (3, False), (2, True), (3, False), (7, False)])
    ]
    response = await v2_post(session, user.telegram_id, f"/api/v2/sessions/live/{body['id']}/sets:batch", {"sets": sets})
    assert response.status_code == 200, response.text
    logs = await _block_rows(session, SetLog, body["id"], 1)
    flagged = [(int(r.value), r.is_extra) for r in logs if r.is_max_set]
    assert flagged == [(7, False)]  # ровно один max, у планового пятого подхода


async def test_od3_undecided_live_has_no_max_target_so_block_b_target_cannot_grow(session, user: User, clock):
    """Граница решения OD-3: пока OD-3 не решён, Live не добавляет подход на максимум (прежнее поведение);
    тогда формула получает max = 0 и цель Б не растёт. Это ожидаемо-заблокированный J4, не регрессия."""
    inclusion = await _enrol(session, user, await _pullups(session))
    body = (await _start(session, user, (await _main_occurrences(session, user))[0]["id"])).json()
    assert not any(t["is_max_set"] for block in body["blocks"] for t in block["targets"])
    await _log(session, user, body, [[10, 10, 10], [3, 3, 3, 3]])
    done = await v2_post(session, user.telegram_id, f"/api/v2/sessions/live/{body['id']}/complete", {"abandoned": False})
    assert done.status_code == 200, done.text
    await session.refresh(inclusion)
    assert inclusion.progression_state["block_b"]["target"] == 3


# --- I / J: awaiting_assessment --------------------------------------------------------------------


async def test_i_fresh_user_without_assessment_awaits_and_cannot_start_main(session, user: User, clock):
    program = await _pullups(session, assessment_required=True)
    inclusion = await _enrol(session, user, program)
    assert inclusion.status == "awaiting_assessment"
    assert inclusion.prescription_provenance["assessment_state"] == "awaiting_assessment"

    occurrences = await _main_occurrences(session, user)
    assert {o["state"] for o in occurrences} == {"awaiting_assessment"}

    response = await _start(session, user, occurrences[0]["id"])
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "assessment_required"
    assert response.json()["detail"]["protocol_id"] == program.assessment["protocol_id"]


async def test_i_logged_assessment_promotes_to_active_and_main_starts(session, user: User, clock):
    program = await _pullups(session, assessment_required=True)
    inclusion = await _enrol(session, user, program)
    assert inclusion.status == "awaiting_assessment"
    result = AssessmentResult(
        user_id=user.id, protocol_id=program.assessment["protocol_id"], performed_at=MON, value=Decimal(8), unit="reps",
    )
    session.add(result)
    await session.flush()

    started = await _start(session, user, (await _main_occurrences(session, user))[0]["id"])
    assert started.status_code == 200, started.text
    await session.refresh(inclusion)
    assert inclusion.status == "active"
    assert inclusion.baseline_assessment_result_id == result.id
    assert inclusion.prescription_provenance["assessment"]["id"] == result.id
    assert inclusion.prescription_provenance["assessment"]["max_reps"] == 8
    assert len(started.json()["blocks"][1]["targets"]) == 4


async def test_i_onboarding_baseline_counts_as_valid_assessment(session, user: User, clock):
    session.add(Baseline(user_id=user.id, performed_at=MON - timedelta(days=3), reps=8))
    await session.flush()
    inclusion = await _enrol(session, user, await _pullups(session, assessment_required=True))
    assert inclusion.status == "active"
    assert inclusion.prescription_provenance["assessment"]["source"] == "baseline"


async def test_i_expired_assessment_is_not_valid(session, user: User, clock):
    session.add(Baseline(user_id=user.id, performed_at=MON - timedelta(days=60), reps=8))
    await session.flush()
    inclusion = await _enrol(session, user, await _pullups(session, assessment_required=True))
    assert inclusion.status == "awaiting_assessment"


async def test_j_user_with_completed_main_history_is_not_sent_to_assessment(session, user: User, clock):
    """Aged-пользователь (история основных тренировок в legacy workouts), без замера в окне валидности."""
    old = Baseline(user_id=user.id, performed_at=MON - timedelta(days=120), reps=8)  # вне окна валидности
    session.add(old)
    await session.flush()
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=old.id)
    session.add(Workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=MON - timedelta(days=90),
        status=WorkoutStatus.COMPLETED,
    ))
    await session.flush()
    inclusion = await _enrol(session, user, await _pullups(session, assessment_required=True))
    assert inclusion.status == "active"
    started = await _start(session, user, (await _main_occurrences(session, user))[0]["id"])
    assert started.status_code == 200, started.text


async def test_j_k_convergence_never_demotes_active_and_is_idempotent(session, user: User, clock):
    program = await _pullups(session, assessment_required=True)
    awaiting = await _enrol(session, user, program)
    plan_id = awaiting.training_plan_id
    service = PlanConvergenceService(session)

    await service.converge_user_plan(training_plan_id=plan_id, today=MON.date())
    _, second = await service.converge_user_plan(training_plan_id=plan_id, today=MON.date())
    assert second.mutations == 0, second.as_dict()  # K: awaiting без замера — 0 изменений
    await session.refresh(awaiting)
    assert awaiting.status == "awaiting_assessment"

    # Активная инклюзия без замера и без истории (создана до #305) convergence НЕ уводит на замер.
    awaiting.status = "active"
    await session.flush()
    _, third = await service.converge_user_plan(training_plan_id=plan_id, today=MON.date())
    await session.refresh(awaiting)
    assert awaiting.status == "active" and third.assessments_promoted == 0

    # Замер записан → один переход, повтор — 0.
    awaiting.status = "awaiting_assessment"
    session.add(Baseline(user_id=user.id, performed_at=MON, reps=8))
    await session.flush()
    _, promoted = await service.converge_user_plan(training_plan_id=plan_id, today=MON.date())
    assert promoted.assessments_promoted == 1
    _, again = await service.converge_user_plan(training_plan_id=plan_id, today=MON.date())
    assert again.mutations == 0, again.as_dict()
    await session.refresh(awaiting)
    assert awaiting.status == "active"


async def test_l_enrolment_and_promotion_do_not_touch_subscription_or_access(session, user: User, clock):
    user.subscription_status = "trial"
    user.subscription_expires_at = MON + timedelta(days=7)
    program = await _pullups(session, assessment_required=True)
    await session.flush()
    before = (user.subscription_status, user.subscription_expires_at, program.access_level)

    inclusion = await _enrol(session, user, program)
    session.add(Baseline(user_id=user.id, performed_at=MON, reps=8))
    await session.flush()
    await PlanConvergenceService(session).converge_user_plan(training_plan_id=inclusion.training_plan_id, today=MON.date())

    await session.refresh(user)
    await session.refresh(program)
    assert (user.subscription_status, user.subscription_expires_at, program.access_level) == before
