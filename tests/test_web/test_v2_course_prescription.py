"""DOMAIN-V2 Wave 1c (issue #305): прескрипция курса «Подтягивания» на реальном Postgres через API.

OD-3 решён (подход на максимум включается), прогрессию двигает ТОЛЬКО подход на максимум, только вперёд
(решения владельца); числа стартовой прескрипции (OD-1) открыты и здесь не проверяются:
  A/E  свежая инклюзия: block_b.work_sets = 4, Live блока Б — 4 рабочих подхода (D2), не 1, + max;
  B    цель с is_max_set → SetLog.is_max_set → чтение TrainingSession V2 (исходы) → вход прогрессии (D3);
  C/D/E одинаковый max + разные рабочие → одинаковое следующее состояние; одинаковые рабочие + разный
       max → разное; провалы рабочих подходов сами по себе ничего не меняют (J4: цель 3, max 6 → 4);
  F    правка истории (обычный подход и max) не переписывает ни состояния, ни плана, ни рецептов, а
       следующий рецепт строится из замера на момент завершения;
  I/J  awaiting_assessment: свежий без замера ждёт замера и не стартует main; записанный замер
       переводит в active; пользователь с историей основных тренировок — никогда на замер;
  K/L  повторный converge = 0 изменений; подписка/доступ не меняются.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, update

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
    TrainingSession,
)
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.domain.constants import STRENGTH_BLOCK
from app.domain.multi_program import MetricType, ProgramStructureType, WeekPhase
from app.domain.progression_strategy import ProgressionStrategyType
from app.services import live_session
from app.services.plan_convergence import PlanConvergenceService
from app.web import routes_v2
from tests.test_web._v2_client import v2_get, v2_patch, v2_post

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
    working = [t for t in targets if not t["is_max_set"]]
    assert len(working) == 4  # было 1 (D2 / FD-09)
    assert all(Decimal(str(t["value"])) == 3 for t in working)

    await _log(session, user, body, [[10, 10, 10, 12], [3, 3, 3, 3, 6]])
    rows = await _block_rows(session, SetLog, body["id"], 1)
    assert [int(r.value) for r in rows] == [3, 3, 3, 3, 6]


async def test_e_aged_inclusion_without_block_b_work_sets_still_runs_four_sets(session, user: User, clock):
    """Инклюзия старой формы (миграция ещё не прошла / записана старым кодом): Live нормализует в памяти."""
    inclusion = await _enrol(session, user, await _pullups(session))
    state = dict(inclusion.progression_state)
    state["block_b"] = {k: v for k, v in state["block_b"].items() if k != "work_sets"} | {"target": 5}
    inclusion.progression_state = state
    await session.flush()

    started = await _start(session, user, (await _main_occurrences(session, user))[0]["id"])
    assert started.status_code == 200, started.text
    working = [t for t in started.json()["blocks"][1]["targets"] if not t["is_max_set"]]
    assert len(working) == 4 and all(Decimal(str(t["value"])) == 5 for t in working)


# --- A / B: подход на максимум в рецепте и до чтения TrainingSession V2 ------------------------------


async def _complete(session, user: User, session_id: int) -> dict:
    done = await v2_post(session, user.telegram_id, f"/api/v2/sessions/live/{session_id}/complete", {"abandoned": False})
    assert done.status_code == 200, done.text
    return done.json()


async def _course_cycle(session, user: User, clock, occurrence_index: int, reps_by_block: list[list[int]]) -> dict:
    """Один цикл курса: старт main-занятия (через 3 дня после предыдущего — отдых MAIN), подходы, завершение."""
    clock(MON + timedelta(days=3 * occurrence_index))
    occurrence = (await _main_occurrences(session, user))[occurrence_index]
    started = await _start(session, user, occurrence["id"])
    assert started.status_code == 200, started.text
    body = started.json()
    await _log(session, user, body, reps_by_block)
    await _complete(session, user, body["id"])
    # Завершение ставит реальное «сейчас»; цикл переносится на часы теста, чтобы отдых MAIN считался от них.
    at = MON + timedelta(days=3 * occurrence_index)
    await session.execute(update(TrainingSession).where(TrainingSession.id == body["id"]).values(
        performed_at=at, started_at=at, completed_at=at + timedelta(minutes=30), ended_at=at + timedelta(minutes=30),
    ))
    await session.flush()
    return body


async def test_a_b_prescription_has_working_sets_plus_one_max_and_flag_survives_to_session_v2(
    session, user: User, clock,
):
    """A: рецепт = рабочие подходы + ОДИН явный max последним (OD-3). B: is_max_set цели → SetTarget → Live →
    SetLog → TrainingSession V2 (set_targets / set_logs / исходы, #307) — ровно у последнего планового подхода."""
    await _enrol(session, user, await _pullups(session))
    started = await _start(session, user, (await _main_occurrences(session, user))[0]["id"])
    assert started.status_code == 200, started.text
    body = started.json()
    for index, working in ((0, 3), (1, 4)):
        targets = body["blocks"][index]["targets"]
        assert [t["is_max_set"] for t in targets] == [False] * working + [True]
        assert Decimal(str(targets[-1]["value"])) == 0  # у замера цели нет

    await _log(session, user, body, [[10, 10, 10, 12], [3, 3, 3, 3, 6]])
    targets = await _block_rows(session, SetTarget, body["id"], 1)
    logs = await _block_rows(session, SetLog, body["id"], 1)
    assert [(t.set_number, t.is_max_set) for t in targets] == [(1, False), (2, False), (3, False), (4, False), (5, True)]
    assert [(int(r.value), r.is_max_set) for r in logs] == [(3, False), (3, False), (3, False), (3, False), (6, True)]
    await _complete(session, user, body["id"])

    listed = await v2_get(session, user.telegram_id, "/api/v2/sessions?status=completed")
    assert listed.status_code == 200, listed.text
    block_b = next(card for card in listed.json()["sessions"] if card["id"] == body["id"])["blocks"][1]
    assert [t["is_max_set"] for t in block_b["set_targets"]] == [False] * 4 + [True]
    assert [log["is_max_set"] for log in block_b["set_logs"]] == [False] * 4 + [True]
    assert [(o["is_max_set"], o["actual"]) for o in block_b["outcomes"]][-1] == (True, "6.00")
    assert sum(o["is_max_set"] for o in block_b["outcomes"]) == 1


async def test_b_extra_set_before_max_does_not_steal_or_shift_max_identity(session, user: User, clock):
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


# --- C / D / E: прогрессию двигает только подход на максимум -----------------------------------------


def _without_counter(state: dict) -> dict:
    return {k: v for k, v in state.items() if k != "workouts_completed_in_set"}


async def _next_state_after(session, user: User, clock, inclusion: ProgramInclusion, initial: dict,
                            reps_by_block: list[list[int]], occurrence_index: int) -> dict:
    """Следующее состояние после одного цикла от ОДНОГО И ТОГО ЖЕ стартового состояния."""
    inclusion.progression_state = initial
    await session.flush()
    await _course_cycle(session, user, clock, occurrence_index, reps_by_block)
    await session.refresh(inclusion)
    return dict(inclusion.progression_state)


async def test_c_same_max_different_working_sets_gives_same_next_progression(session, user: User, clock):
    inclusion = await _enrol(session, user, await _pullups(session))
    initial = dict(inclusion.progression_state)

    on_plan = await _next_state_after(session, user, clock, inclusion, initial, [[10, 10, 10, 12], [3, 3, 3, 3, 6]], 0)
    off_plan = await _next_state_after(session, user, clock, inclusion, initial, [[25, 1, 0, 12], [0, 9, 1, 2, 6]], 1)

    assert on_plan == off_plan  # байт в байт: рабочие подходы — не вход
    assert on_plan["block_a"]["target"] == 11 and on_plan["block_b"]["target"] == 4  # J4: 3 → 4 по max 6

    # Следующий рецепт одинаков: тот же резолвер от того же состояния.
    clock(MON + timedelta(days=6))
    started = await _start(session, user, (await _main_occurrences(session, user))[2]["id"])
    assert [Decimal(str(t["value"])) for t in started.json()["blocks"][1]["targets"]] == [4, 4, 4, 4, 0]


async def test_d_same_working_sets_different_max_gives_different_next_prescription(session, user: User, clock):
    inclusion = await _enrol(session, user, await _pullups(session))
    initial = dict(inclusion.progression_state)
    working_a, working_b = [10, 10, 10], [3, 3, 3, 3]

    held = await _next_state_after(session, user, clock, inclusion, initial, [[*working_a, 10], [*working_b, 3]], 0)
    grown = await _next_state_after(session, user, clock, inclusion, initial, [[*working_a, 15], [*working_b, 6]], 1)

    assert (held["block_a"]["target"], held["block_b"]["target"]) == (10, 3)  # max = цель → держим
    assert (grown["block_a"]["target"], grown["block_b"]["target"]) == (11, 4)  # max > цели → +шаг


async def test_e_working_set_failures_alone_do_not_mutate_progression(session, user: User, clock):
    """Провалы рабочих подходов (0 повторений, объём ниже прошлого) при том же max: следующее состояние —
    то же, что при выполнении по плану; трижды подряд — ни отката цели, ни weak_streak (раньше откат по
    «слабому объёму» срабатывал на третьей)."""
    inclusion = await _enrol(session, user, await _pullups(session))
    initial = dict(inclusion.progression_state)
    on_plan = await _next_state_after(session, user, clock, inclusion, initial, [[10, 10, 10, 10], [3, 3, 3, 3, 3]], 0)
    failed = await _next_state_after(session, user, clock, inclusion, initial, [[0, 0, 0, 10], [0, 0, 0, 0, 3]], 1)
    assert failed == on_plan


async def test_e_three_failed_working_cycles_in_a_row_do_not_roll_back(session, user: User, clock):
    inclusion = await _enrol(session, user, await _pullups(session))
    state = dict(inclusion.progression_state)
    # Прошлый объём велик — по старому правилу каждый из трёх циклов был бы «слабым» (объём < прошлого).
    state["block_a"] = {**state["block_a"], "volume": 1000}
    state["block_b"] = {**state["block_b"], "volume": 1000}
    for index in (0, 1, 2):
        state = await _next_state_after(session, user, clock, inclusion, state, [[0, 0, 0, 10], [0, 0, 0, 0, 3]], index)
        assert (state["block_a"]["target"], state["block_b"]["target"]) == (10, 3)
        assert state["block_a"]["weak_streak"] == state["block_b"]["weak_streak"] == 0


async def test_e_missing_max_measurement_does_not_move_progression(session, user: User, clock):
    """Подход на максимум не выполнен (рабочие подходы есть) — замера нет, роль не двигается."""
    inclusion = await _enrol(session, user, await _pullups(session))
    initial = dict(inclusion.progression_state)
    state = await _next_state_after(session, user, clock, inclusion, initial, [[30, 30, 30], [9, 9, 9, 9]], 0)
    assert _without_counter(state) == _without_counter(initial)


# --- F: только вперёд — правка истории ничего не пересчитывает ------------------------------------


async def test_f_historical_edits_do_not_rewrite_progression_and_next_prescription_uses_completion_time_max(
    session, user: User, clock,
):
    inclusion = await _enrol(session, user, await _pullups(session))
    body = await _course_cycle(session, user, clock, 0, [[10, 10, 10, 12], [3, 3, 3, 3, 6]])
    await session.refresh(inclusion)
    state_after, rev_after = dict(inclusion.progression_state), inclusion.progression_state_rev
    targets_before = [(t.set_number, t.value, t.is_max_set) for t in await _block_rows(session, SetTarget, body["id"], 1)]
    plan_before = await _main_occurrences(session, user)

    path = f"/api/v2/sessions/{body['id']}"
    ordinary = await v2_patch(session, user.telegram_id, path, {"sets": [{"block_index": 1, "set_number": 1, "value": "0"}]})
    assert ordinary.status_code == 200, ordinary.text
    corrected = await v2_patch(session, user.telegram_id, path, {"sets": [{"block_index": 1, "set_number": 5, "value": "1"}]})
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["blocks"][1]["outcomes"][-1]["actual"] == "1.00"  # история исправлена

    await session.refresh(inclusion)
    assert inclusion.progression_state == state_after and inclusion.progression_state_rev == rev_after
    assert [(t.set_number, t.value, t.is_max_set) for t in await _block_rows(session, SetTarget, body["id"], 1)] == targets_before
    assert await _main_occurrences(session, user) == plan_before

    # Следующий рецепт — от состояния, рассчитанного на границе завершения (max 6 → цель 4), не от
    # поправленного задним числом max 1.
    clock(MON + timedelta(days=3))
    started = await _start(session, user, (await _main_occurrences(session, user))[1]["id"])
    assert [Decimal(str(t["value"])) for t in started.json()["blocks"][1]["targets"]] == [4, 4, 4, 4, 0]


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
    assert [t["is_max_set"] for t in started.json()["blocks"][1]["targets"]] == [False] * 4 + [True]


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
