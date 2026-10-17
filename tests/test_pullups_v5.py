"""Программа V5.6 (issue #305): чистый домен ``app/domain/pullups_v5.py``.

Каждый пример — из документа владельца «Подтягивания V5.6» (docs/domain/PULLUPS_V5_6.md) или из
постановки #305; ожидаемые значения — точные числа, а не пересчёт той же формулой."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.domain.pullups_v5 import (
    BODYWEIGHT,
    PROGRAM_VERSION,
    AssistanceIntent,
    AssistanceSetup,
    AttemptSpeed,
    BlockResult,
    BlockRole,
    BStopReason,
    BVolumeStage,
    EntryInputs,
    OneRmAttempt,
    OneRmOutcome,
    OneRmTestError,
    PendingInput,
    PrescriptionPending,
    ProgramLevel,
    SessionPrescription,
    SessionResult,
    StrengthState,
    V5State,
    WorkoutRole,
    a_start_target,
    add_one_mandatory_rep,
    advance_session,
    apply_inputs,
    b_start,
    b_volume_fact,
    clear_recovery_check,
    confirm_assistance,
    initial_state,
    initial_weighted_loads,
    is_v5_state,
    latest_one_rm_test_at,
    load_increment,
    next_one_rm_set,
    one_rm_missing_inputs,
    one_rm_rest_ok,
    one_rm_result,
    pending_inputs,
    prescribe_session,
    program_version_of,
    record_one_rm_test,
    step_assistance,
    validate_one_rm_attempts,
)

D = Decimal
# Личный упорядоченный список резин (EquipmentItem.position: 0 — больше всего помощи): в нём только id и
# название — крепление, цвет и положение стопы/колена он НЕ подтверждает.
BAND_HEAVY = AssistanceSetup(kind="band", equipment_item_id=1, name="Красная")
BAND_MID = AssistanceSetup(kind="band", equipment_item_id=2, name="Синяя")
BAND_LIGHT = AssistanceSetup(kind="band", equipment_item_id=3, name="Жёлтая")
LADDER = (BAND_HEAVY, BAND_MID, BAND_LIGHT)


def _full(band: AssistanceSetup, colour: str) -> AssistanceSetup:
    """Полностью подтверждённая пользователем запись резины (§8.2)."""
    return AssistanceSetup(
        kind="band", equipment_item_id=band.equipment_item_id, name=band.name, colour=colour,
        attachment="петля на перекладине", body_position="стопа",
    )


MID_FULL = _full(BAND_MID, "синяя")
LIGHT_FULL = _full(BAND_LIGHT, "жёлтая")
VOLUME_BAND = _full(BAND_MID, "синяя")


def _session(state: V5State, role: WorkoutRole | None = None) -> SessionPrescription:
    prescription = prescribe_session(state, role)
    assert isinstance(prescription, SessionPrescription), prescription
    return prescription


def _run(
    state: V5State, volume: tuple, strength: tuple, *, tech: bool | None = True, rest: bool | None = True,
    body_mass: Decimal | None = D("70"), ladder=LADDER,
):
    prescription = _session(state).to_dict()
    return advance_session(
        state, prescription,
        SessionResult(
            volume=BlockResult(reps=volume, technique_valid=tech, rest_within_limit=rest),
            strength=BlockResult(reps=strength, technique_valid=tech, rest_within_limit=rest),
        ),
        body_mass=body_mass, ladder=ladder,
    )


def _weighted(m: int = 25, **kwargs) -> V5State:
    return initial_state(EntryInputs(
        fresh_max=m, body_mass_kg=D("70"), e1rm_kg=D("30"), load_step_kg=D("0.5"), **kwargs,
    ))


def _assisted(**kwargs) -> V5State:
    return initial_state(EntryInputs(
        fresh_max=0, volume_capacity=10, volume_assistance=VOLUME_BAND, strength_assistance=MID_FULL, **kwargs,
    ))


# --- Версия и состояние ----------------------------------------------------------------------------


def test_state_carries_explicit_program_version_and_roundtrips():
    state = _weighted()
    data = state.to_dict()
    assert data["program_version"] == PROGRAM_VERSION == "pullups_v5_6"
    assert data["strategy_type"] == "step"
    assert is_v5_state(data) and program_version_of(data) == "pullups_v5_6"
    assert V5State.from_dict(data) == state


def test_legacy_state_is_reported_as_legacy_version():
    legacy = {"schema_version": 1, "strategy_type": "step", "block_a": {"target": 10}, "block_b": {"target": 3}}
    assert not is_v5_state(legacy)
    assert program_version_of(legacy) == "pullups_legacy_step"


# --- Уровни и стартовые примеры (§7, §13) ---------------------------------------------------------


def test_m0_assisted_example():
    """M=0, объёмная резина R≈10: A 7/7/7/7+, факт 7/7/7/9=30; сила 5/5/5/5/5–8; B 10×5 с резиной."""
    state = _assisted()
    assert state.level is ProgramLevel.ASSISTED
    a = _session(state)
    assert a.role is WorkoutRole.A
    assert [s.target_reps for s in a.volume.sets] == [7, 7, 7, 7]
    assert [s.marker.value for s in a.volume.sets] == ["working", "working", "working", "amrap"]
    assert a.volume.display == "7/7/7/7+"
    assert a.volume.assistance == VOLUME_BAND
    assert a.volume.rest_seconds == 240 and a.inter_block_rest_seconds == 900
    assert a.strength.block_role is BlockRole.ASSISTED_STRENGTH
    assert [s.target_reps for s in a.strength.sets] == [5, 5, 5, 5, 5]
    assert [s.cap_reps for s in a.strength.sets] == [None, None, None, None, 8]
    assert a.strength.sets[-1].marker.value == "control"
    assert a.strength.rest_seconds == 180 and a.strength.display == "5/5/5/5/5–8"

    after_a = _run(state, (7, 7, 7, 9), (5, 5, 5, 5, 6)).state
    assert after_a.volume_a.last_volume == 30
    b = _session(after_a)
    assert b.role is WorkoutRole.B
    assert (len(b.volume.sets), b.volume.sets[0].target_reps) == (10, 5)
    assert b.volume.display == "10×5" and b.volume.rest_seconds == 60
    assert b.volume.assistance == VOLUME_BAND
    assert b.strength.display == "5/5/5/5/5–8"  # до допуска силовые дни одинаковы


def test_m10_qualifies_immediately_with_transition_volume():
    state = _weighted(m=10)
    assert state.level is ProgramLevel.TRANSITION
    assert state.qualification == {"signal": "fresh_max", "fresh_max": 10}
    a = _session(state)
    assert a.volume.display == "5/5/5/5+" and a.volume.assistance == BODYWEIGHT
    assert a.strength.block_role is BlockRole.A_WEIGHTED_STRENGTH and a.strength.display.startswith("5×5")
    b = _session(_run(state, (5, 5, 5, 7), (5, 5, 5, 5, 5)).state)
    assert b.volume.display == "10×3" and b.volume.stage == "transition"
    assert b.strength.block_role is BlockRole.B_WEIGHTED_STRENGTH and b.strength.display.startswith("5×3")


def test_m10_e1rm_not_derived_from_m():
    """M=10 — только допуск к тесту 1RM: без E1RM сила ждёт ввода, а не выводится из M."""
    state = initial_state(EntryInputs(fresh_max=10, body_mass_kg=D("70"), load_step_kg=D("0.5")))
    pending = prescribe_session(state)
    assert isinstance(pending, PrescriptionPending)
    assert pending.missing == (PendingInput.ONE_REP_MAX,)


def test_m25_example():
    state = _weighted(m=25)
    assert state.level is ProgramLevel.WEIGHTED
    assert _session(state).volume.display == "17/17/17/17+"
    after = _run(state, (17, 17, 17, 19), (5, 5, 5, 5, 5)).state
    assert after.volume_a.last_volume == 70
    b = _session(after)
    assert b.volume.display == "15×5"


def test_m50_start_cap_only():
    state = _weighted(m=50)
    assert _session(state).volume.display == "20/20/20/20+"
    after = _run(state, (20, 20, 20, 22), (5, 5, 5, 5, 5)).state
    assert after.volume_a.last_volume == 82
    assert _session(after).volume.display == "17×5"


def test_m15_needs_no_transition_week():
    state = _weighted(m=15)
    assert state.level is ProgramLevel.WEIGHTED
    assert _session(state).volume.display == "10/10/10/10+"


def test_m6_stays_assisted():
    """M=6 ещё не открывает уровень с весом."""
    state = initial_state(EntryInputs(fresh_max=6, volume_capacity=10, volume_assistance=VOLUME_BAND, strength_assistance=LIGHT_FULL))
    assert state.level is ProgramLevel.ASSISTED
    assert _session(state).strength.block_role is BlockRole.ASSISTED_STRENGTH


def test_unknown_m_is_not_classified():
    state = initial_state(EntryInputs())
    assert state.level is None
    assert prescribe_session(state).missing == (PendingInput.FRESH_MAX,)


def test_assisted_without_r_or_band_waits_for_input():
    state = initial_state(EntryInputs(fresh_max=3))
    pending = prescribe_session(state)
    assert set(pending.missing) == {
        PendingInput.VOLUME_CAPACITY, PendingInput.VOLUME_ASSISTANCE, PendingInput.STRENGTH_ASSISTANCE,
    }


# --- A: длинный объём (§4) ------------------------------------------------------------------------


@pytest.mark.parametrize(("r", "a"), [(10, 7), (25, 17), (26, 18), (50, 20), (100, 20), (4, 3), (0, 3), (12, 8)])
def test_a_initial_formula_and_start_cap(r, a):
    assert a_start_target(r) == a


def test_known_a_block_replaces_formula():
    state = initial_state(EntryInputs(
        fresh_max=25, known_a_targets=(18, 18, 18, 18), body_mass_kg=D("70"), e1rm_kg=D("30"), load_step_kg=D("1"),
    ))
    assert _session(state).volume.display == "18/18/18/18+"


def test_earliest_lowest_distribution_sequence():
    targets = (18, 18, 18, 18)
    seen = []
    for _ in range(4):
        targets, _index = add_one_mandatory_rep(targets)
        seen.append(targets)
    assert seen == [(19, 18, 18, 18), (19, 19, 18, 18), (19, 19, 19, 18), (19, 19, 19, 19)]


def _a_cycle(state: V5State, volume: tuple, tech: bool | None = True) -> V5State:
    """A, затем B без изменений A (B закрывается нейтрально), чтобы вернуться к следующей A."""
    after_a = _run(state, volume, (5, 5, 5, 5, 5), tech=tech)
    b = _session(after_a.state)
    neutral_b = (b.volume.sets[0].target_reps,) * (len(b.volume.sets) - 1) + (1,)
    # Сила B «по плану»: 5/5/5/5/5 у силы с помощью (контроль 5 — та же помощь), 3/3/3/3/3 у 5×3.
    neutral_strength = tuple(s.target_reps for s in b.strength.sets)
    return after_a, _run(after_a.state, neutral_b, neutral_strength).state


def test_a_green_adds_one_mandatory_rep_total():
    state = initial_state(EntryInputs(
        fresh_max=26, body_mass_kg=D("70"), e1rm_kg=D("30"), load_step_kg=D("0.5"),
    ))
    assert _session(state).volume.display == "18/18/18/18+"
    displays = []
    for _ in range(4):
        outcome, state = _a_cycle(state, tuple(_session(state).volume.sets[i].target_reps for i in range(3)) + (30,))
        assert outcome.volume.block_role is BlockRole.A_VOLUME
        assert outcome.volume.decision == "add_mandatory_rep"
        displays.append(_session(state).volume.display)
    assert displays == ["19/18/18/18+", "19/19/18/18+", "19/19/19/18+", "19/19/19/19+"]


def test_a_green_requires_margin_two():
    state = _weighted(m=25)  # 17/17/17/17+
    outcome, nxt = _a_cycle(state, (17, 17, 17, 19))
    assert outcome.volume.decision == "add_mandatory_rep"
    assert _session(nxt).volume.display == "18/17/17/17+"


@pytest.mark.parametrize("last", [17, 18])
def test_a_yellow_repeats_plan(last):
    state = _weighted(m=25)
    outcome, nxt = _a_cycle(state, (17, 17, 17, last))
    assert outcome.volume.decision == "repeat" and outcome.volume.reason == "yellow"
    assert _session(nxt).volume.display == "17/17/17/17+"


def test_a_red_repeats_plan_and_two_reds_roll_back_last_addition():
    state = _weighted(m=25)
    _, state = _a_cycle(state, (17, 17, 17, 19))  # зелёный → 18/17/17/17+
    _, state = _a_cycle(state, (18, 17, 17, 20))  # зелёный → 18/18/17/17+
    assert _session(state).volume.display == "18/18/17/17+"
    first_red, state = _a_cycle(state, (18, 16, 17, 20))
    assert first_red.volume.decision == "repeat" and first_red.volume.reason == "red"
    assert _session(state).volume.display == "18/18/17/17+"
    second_red, state = _a_cycle(state, (18, 18, 17, 16))
    assert second_red.volume.decision == "rollback_last_addition"
    assert second_red.volume.details["set_index"] == 1
    assert _session(state).volume.display == "18/17/17/17+"


def test_a_red_streak_is_interrupted_by_non_red():
    state = _weighted(m=25)
    _, state = _a_cycle(state, (17, 17, 17, 19))
    _, state = _a_cycle(state, (17, 17, 17, 17))  # красный 1
    _, state = _a_cycle(state, (18, 17, 17, 17))  # жёлтый — серия прервана
    outcome, state = _a_cycle(state, (18, 17, 16, 17))  # снова красный 1
    assert outcome.volume.decision == "repeat"
    assert _session(state).volume.display == "18/17/17/17+"


def test_a_two_reds_without_additions_emit_assistance_intent_not_guess():
    state = _assisted()
    _, state = _a_cycle(state, (7, 6, 7, 7))
    outcome, state = _a_cycle(state, (7, 7, 5, 7))
    assert outcome.volume.decision == "increase_assistance"
    assert outcome.volume.assistance_intent is AssistanceIntent.INCREASE
    # Резина по порядку списка предложена, но не подтверждена: блок хранит прежнюю, намерение ждёт.
    assert state.volume_a.assistance == VOLUME_BAND
    assert state.assistance_pending == ({"block": "volume_a", "intent": "increase_assistance", "proposed": BAND_HEAVY.to_dict()},)
    assert PendingInput.ASSISTANCE_CONFIRMATION in prescribe_session(state, WorkoutRole.A).missing


def test_a_green_without_confirmed_technique_does_not_progress():
    state = _weighted(m=25)
    outcome, nxt = _a_cycle(state, (17, 17, 17, 25), tech=None)
    assert outcome.volume.decision == "repeat" and outcome.volume.reason == "unconfirmed"
    assert _session(nxt).volume.display == "17/17/17/17+"


def test_a_last_amrap_is_not_fresh_max():
    state = _weighted(m=25)
    after = _run(state, (17, 17, 17, 30), (5, 5, 5, 5, 5)).state
    assert after.inputs.fresh_max == 25  # 30 в AMRAP после трёх подходов — не свежий M
    assert after.volume_a.last_fact == (17, 17, 17, 30)


# --- B: короткий объём (§5, §6) -------------------------------------------------------------------


@pytest.mark.parametrize(("v_ref", "plan"), [(30, (10, 5)), (70, (15, 5)), (74, (15, 5)), (82, (17, 5)), (100, (20, 6)), (99, (20, 5)), (140, (20, 8))])
def test_b_start(v_ref, plan):
    assert b_start(v_ref) == plan


def test_b_stop_rule_three_continues_two_stops_and_counts():
    fact, stop = b_volume_fact(13, BlockResult(reps=(5,) * 10 + (4, 3, 2)))
    assert fact == (5,) * 10 + (4, 3, 2) and sum(fact) == 59
    assert stop is BStopReason.LOW_REPS
    fact, stop = b_volume_fact(13, BlockResult(reps=(5, 3, 1, 5)))
    assert fact == (5, 3, 1) and stop is BStopReason.LOW_REPS  # подход после стопа не учитывается
    fact, stop = b_volume_fact(13, BlockResult(reps=(5, 3, 3, None)))
    assert stop is BStopReason.ENDED_EARLY


def _b_state(sets: int, reps: int, stage=BVolumeStage.STANDARD) -> V5State:
    state = _weighted(m=25)
    return V5State(**{**state.__dict__, "next_role": WorkoutRole.B, "volume_b": state.volume_b.__class__(
        stage=stage, sets=sets, reps=reps, assistance=BODYWEIGHT, reference_volume=60,
    )})


def test_b_full_completion_advances_and_partial_holds_with_intermediate_goal():
    state = _b_state(13, 5)
    partial = _run(state, (5,) * 10 + (4, 3, 2), (3, 3, 3, 3, 3))
    assert partial.volume.block_role is BlockRole.B_VOLUME
    assert partial.volume.decision == "hold" and partial.volume.fact_volume == 59
    held = V5State(**{**partial.state.__dict__, "next_role": WorkoutRole.B})
    b = _session(held)
    assert b.volume.display == "13×5"
    assert b.volume.intermediate_goal == 60  # промежуточная цель — только отображение
    # Факт выше промежуточной цели, но план не закрыт — ступень не открывается.
    again = _run(held, (5,) * 12 + (2,), (3, 3, 3, 3, 3))
    assert again.volume.decision == "hold"
    held = V5State(**{**again.state.__dict__, "next_role": WorkoutRole.B})
    assert _session(held).volume.display == "13×5"
    closed = _run(held, (5,) * 13, (3, 3, 3, 3, 3))
    assert closed.volume.decision == "advance"
    assert _session(V5State(**{**closed.state.__dict__, "next_role": WorkoutRole.B})).volume.display == "14×5"


def test_b_ladder_20x5_to_20x6_to_20x7():
    state = _b_state(19, 5)
    plans = []
    for _ in range(3):
        b = _session(state)
        state = _run(state, (b.volume.sets[0].target_reps,) * len(b.volume.sets), (3, 3, 3, 3, 3)).state
        state = V5State(**{**state.__dict__, "next_role": WorkoutRole.B})
        plans.append(_session(state).volume.display)
    assert plans == ["20×5", "20×6", "20×7"]


def test_b_has_no_max_set():
    b = _session(_b_state(15, 5))
    assert {s.marker.value for s in b.volume.sets} == {"dynamic"}
    assert b.volume.stop_rule["stop_at_or_below"] == 2


def test_b_closed_but_unconfirmed_rest_holds():
    outcome = _run(_b_state(10, 5), (5,) * 10, (3, 3, 3, 3, 3), rest=None)
    assert outcome.volume.decision == "hold" and outcome.volume.reason == "standard_unconfirmed"


def test_b_transition_ladder_then_normal_ladder():
    state = _weighted(m=12)
    state = V5State(**{**state.__dict__, "next_role": WorkoutRole.B})
    plans = []
    for _ in range(4):
        b = _session(state)
        state = _run(state, (b.volume.sets[0].target_reps,) * len(b.volume.sets), (3, 3, 3, 3, 3)).state
        state = V5State(**{**state.__dict__, "next_role": WorkoutRole.B})
        plans.append((_session(state).volume.display, state.level))
    assert plans == [
        ("10×4", ProgramLevel.TRANSITION), ("10×5", ProgramLevel.TRANSITION),
        ("11×5", ProgramLevel.WEIGHTED), ("12×5", ProgramLevel.WEIGHTED),
    ]


def test_b_known_volume_replaces_first_a_fact():
    state = initial_state(EntryInputs(
        fresh_max=25, known_volume=70, body_mass_kg=D("70"), e1rm_kg=D("30"), load_step_kg=D("0.5"),
    ))
    assert _session(state, WorkoutRole.B).volume.display == "15×5"


# --- Сила уровня 1 (§8.2) -------------------------------------------------------------------------


def test_assisted_strength_eight_decreases_assistance_one_step_after_confirmation():
    outcome = _run(_assisted(), (7, 7, 7, 8), (5, 5, 5, 5, 8))
    assert outcome.strength.block_role is BlockRole.ASSISTED_STRENGTH
    assert outcome.strength.assistance_intent is AssistanceIntent.DECREASE
    assert outcome.strength.reason == "assistance_confirmation_required"
    # Следующая ступень по личному порядку — «Жёлтая», но её крепление/положение не подтверждены:
    # блок хранит прежнюю подтверждённую помощь, намерение и предложение ждут пользователя.
    state = outcome.state
    assert state.strength_a.assistance == MID_FULL
    assert state.assistance_pending == ({"block": "strength_a", "intent": "decrease_assistance", "proposed": BAND_LIGHT.to_dict()},)
    assert state.strength_b.assistance == MID_FULL  # A и B — независимо
    assert prescribe_session(state, WorkoutRole.A).missing == (PendingInput.ASSISTANCE_CONFIRMATION,)
    with pytest.raises(ValueError):
        confirm_assistance(state, "strength_a", BAND_LIGHT)  # неполная запись не принимается
    confirmed = confirm_assistance(state, "strength_a", LIGHT_FULL)
    assert confirmed.assistance_pending == () and confirmed.strength_a.assistance == LIGHT_FULL


@pytest.mark.parametrize("control", [5, 6, 7])
def test_assisted_strength_five_to_seven_keeps(control):
    outcome = _run(_assisted(), (7, 7, 7, 8), (5, 5, 5, 5, control))
    assert outcome.strength.assistance_intent is AssistanceIntent.KEEP
    assert outcome.state.strength_a.assistance == MID_FULL and outcome.state.assistance_pending == ()


@pytest.mark.parametrize("strength", [(5, 4, 5, 5, 8), (5, 5, 5, 5, 4), (5, 5, 5, 5, None)])
def test_assisted_strength_miss_increases_assistance(strength):
    outcome = _run(_assisted(), (7, 7, 7, 8), strength)
    assert outcome.strength.assistance_intent is AssistanceIntent.INCREASE
    assert outcome.state.strength_a.assistance == MID_FULL  # до подтверждения — прежняя
    assert outcome.state.assistance_pending[0]["proposed"] == BAND_HEAVY.to_dict()


def test_assisted_strength_lightest_band_steps_to_bodyweight():
    state = initial_state(EntryInputs(fresh_max=4, volume_capacity=10, volume_assistance=VOLUME_BAND, strength_assistance=LIGHT_FULL))
    outcome = _run(state, (7, 7, 7, 8), (5, 5, 5, 5, 8))
    assert outcome.state.strength_a.assistance == BODYWEIGHT


def test_assisted_strength_unknown_ladder_requires_selection_and_keeps_setup():
    outcome = _run(_assisted(), (7, 7, 7, 8), (5, 5, 5, 5, 8), ladder=())
    assert outcome.strength.reason == "assistance_confirmation_required"
    assert outcome.state.strength_a.assistance == MID_FULL
    assert outcome.state.assistance_pending == ({"block": "strength_a", "intent": "decrease_assistance", "proposed": None},)
    assert PendingInput.ASSISTANCE_CONFIRMATION in prescribe_session(outcome.state, WorkoutRole.A).missing


def test_incomplete_band_setup_is_never_ready():
    state = initial_state(EntryInputs(fresh_max=4, volume_capacity=10, volume_assistance=BAND_MID, strength_assistance=BAND_LIGHT))
    assert set(prescribe_session(state).missing) == {PendingInput.VOLUME_ASSISTANCE, PendingInput.STRENGTH_ASSISTANCE}
    assert not BAND_MID.is_complete and MID_FULL.is_complete and BODYWEIGHT.is_complete


def test_bodyweight_5_5_5_5_8_qualifies_for_weighted_level():
    state = initial_state(EntryInputs(
        fresh_max=8, volume_capacity=10, volume_assistance=VOLUME_BAND, strength_assistance=BODYWEIGHT,
        body_mass_kg=D("70"), load_step_kg=D("0.5"),
    ))
    outcome = _run(state, (7, 7, 7, 8), (5, 5, 5, 5, 8))
    assert outcome.qualified is True and outcome.strength.decision == "qualify"
    nxt = outcome.state
    assert nxt.level is ProgramLevel.TRANSITION
    assert nxt.qualification["signal"] == "in_program"
    assert nxt.volume_a.targets == (5, 5, 5, 5) and nxt.volume_a.assistance == BODYWEIGHT
    assert (nxt.volume_b.sets, nxt.volume_b.reps, nxt.volume_b.stage) == (10, 3, BVolumeStage.TRANSITION)
    # Резина убрана; сила ждёт отдельного теста 1RM.
    assert prescribe_session(nxt).missing == (PendingInput.ONE_REP_MAX,)
    after_1rm = apply_inputs(nxt, EntryInputs(e1rm_kg=D("20")))
    # T1RM = 70 + 20 = 90: A 0,75·90 − 70 = −2,5 → масса тела; B 0,80·90 − 70 = 2.
    assert _session(after_1rm, WorkoutRole.A).strength.display == "5×5 масса тела"
    assert _session(after_1rm, WorkoutRole.B).strength.display == "5×3 +2 кг"


def test_bodyweight_eight_without_confirmed_rest_does_not_qualify():
    state = initial_state(EntryInputs(fresh_max=8, volume_capacity=10, volume_assistance=VOLUME_BAND, strength_assistance=BODYWEIGHT))
    outcome = _run(state, (7, 7, 7, 8), (5, 5, 5, 5, 8), rest=None)
    assert outcome.qualified is False and outcome.strength.reason == "rest_unconfirmed"


def test_control_set_over_cap_counts_as_eight():
    outcome = _run(_assisted(), (7, 7, 7, 8), (5, 5, 5, 5, 11))
    assert outcome.strength.assistance_intent is AssistanceIntent.DECREASE


# --- Сила уровня 2 (§8.3–§8.6) --------------------------------------------------------------------


def test_initial_weighted_loads_from_total_mass():
    """T1RM = BW + E1RM = 100; A: 0,75·100 − 70 = 5 → 5; B: 0,80·100 − 70 = 10 → 10."""
    assert initial_weighted_loads(body_mass=D("70"), e1rm=D("30"), load_step=D("1.25")) == (D("5"), D("10"))
    # 0,75·(80+27) − 80 = 0,25 → вниз до 0,5 = 0; 0,80·107 − 80 = 5,6 → 5,5.
    assert initial_weighted_loads(body_mass=D("80"), e1rm=D("27"), load_step=D("0.5")) == (D("0"), D("5.5"))
    # Округление вниз до шага 2,5: 0,75·(75+45) − 75 = 15 → 15; 0,80·120 − 75 = 21 → 20.
    assert initial_weighted_loads(body_mass=D("75"), e1rm=D("45"), load_step=D("2.5")) == (D("15"), D("20"))


def test_zero_or_negative_load_means_bodyweight():
    a, b = initial_weighted_loads(body_mass=D("90"), e1rm=D("5"), load_step=D("0.5"))
    assert (a, b) == (D("0"), D("0"))
    state = initial_state(EntryInputs(fresh_max=12, body_mass_kg=D("90"), e1rm_kg=D("5"), load_step_kg=D("0.5")))
    assert _session(state).strength.display == "5×5 масса тела"


@pytest.mark.parametrize(
    ("bw", "load", "step", "delta"),
    [
        ("70", "10", "0.5", "1.5"),  # 1,6 → 1,5
        ("80", "40", "0.5", "2.5"),  # 2,4 → 2,5
        ("95", "60", "0.5", "2.5"),  # 3,1 → ограничитель 2,5
        ("60", "0", "0.5", "1"),  # 1,2 → 1,0
        ("50", "0", "0.25", "1"),  # 1,0 → 1,0
        ("40", "0", "0.25", "0.75"),  # 0,8 → 0,75
        ("25", "0", "0.25", "0.5"),  # 0,5 → минимум 0,5
        ("62.5", "0", "0.5", "1"),  # 1,25: равное расстояние 1,0/1,5 → меньший
        ("70", "10", "1.25", "1.25"),  # 1,6 → ближайший доступный 1,25
        ("70", "10", "2", "2"),  # единственный доступный шаг ≤ 2,5
    ],
)
def test_load_increment(bw, load, step, delta):
    assert load_increment(body_mass=D(bw), working_load=D(load), load_step=D(step)) == D(delta)


def test_load_increment_unavailable_when_equipment_step_exceeds_cap():
    assert load_increment(body_mass=D("70"), working_load=D("10"), load_step=D("5")) is None


def _weighted_cycle(state: V5State, a_strength: tuple, b_strength: tuple = (3, 3, 3, 3, 3), **kwargs):
    a = _session(state)
    after_a = _run(state, tuple(s.target_reps for s in a.volume.sets[:3]) + (a.volume.sets[3].target_reps,), a_strength, **kwargs)
    b = _session(after_a.state)
    after_b = _run(after_a.state, (b.volume.sets[0].target_reps,) * (len(b.volume.sets) - 1) + (1,), b_strength, **kwargs)
    return after_a, after_b


def test_a_and_b_loads_progress_independently():
    state = _weighted()  # BW 70, E1RM 30, шаг 0,5 → A 5 кг, B 10 кг
    assert (state.strength_a.load_kg, state.strength_b.load_kg) == (D("5"), D("10"))
    after_a, after_b = _weighted_cycle(state, (5, 5, 5, 5, 5), (3, 3, 2, 3, 3))
    assert after_a.strength.block_role is BlockRole.A_WEIGHTED_STRENGTH
    assert after_a.strength.decision == "increase_load"
    assert after_a.strength.details["delta_kg"] == "1.5"  # 2% от 75 = 1,5
    assert after_b.strength.block_role is BlockRole.B_WEIGHTED_STRENGTH
    assert after_b.strength.decision == "hold"
    assert (after_b.state.strength_a.load_kg, after_b.state.strength_b.load_kg) == (D("6.5"), D("10"))


def test_b_5x3_complete_gets_own_delta():
    state = _weighted()
    _, after_b = _weighted_cycle(state, (5, 5, 5, 5, 4), (3, 3, 3, 3, 3))
    assert after_b.strength.decision == "increase_load"
    assert after_b.strength.details["delta_kg"] == "1.5"  # 2% от 80 = 1,6 → 1,5
    assert after_b.state.strength_b.load_kg == D("11.5")
    assert after_b.state.strength_a.load_kg == D("5")


def test_extra_reps_do_not_accelerate_and_unconfirmed_technique_holds():
    state = _weighted()
    after_a, _ = _weighted_cycle(state, (7, 7, 7, 7, 7), tech=None)
    assert after_a.strength.decision == "hold" and after_a.strength.reason == "standard_unconfirmed"
    after_a, _ = _weighted_cycle(state, (7, 7, 7, 7, 7))
    assert after_a.state.strength_a.load_kg == D("6.5")  # +1,5, а не больше


def _a_strength_only(state: V5State, totals: list[tuple]) -> list:
    outcomes = []
    for reps in totals:
        after_a, after_b = _weighted_cycle(state, reps)
        outcomes.append(after_a.strength)
        state = after_b.state
    return outcomes, state


def test_plateau_three_equal_incomplete_triggers_calibration_undoing_last_increase():
    state = _weighted()
    (_inc,), state = _a_strength_only(state, [(5, 5, 5, 5, 5)])
    assert state.strength_a.load_kg == D("6.5")
    outcomes, state = _a_strength_only(state, [(5, 5, 5, 4, 3), (5, 5, 5, 4, 3), (5, 5, 5, 4, 3)])
    assert [o.decision for o in outcomes] == ["hold", "hold", "calibrate_undo_last_increase"]
    assert outcomes[-1].reason == "no_improvement"
    assert state.strength_a.load_kg == D("5")


def test_plateau_improving_total_keeps_waiting():
    state = _weighted()
    (_inc,), state = _a_strength_only(state, [(5, 5, 5, 5, 5)])
    outcomes, state = _a_strength_only(state, [(5, 5, 4, 3, 3), (5, 5, 5, 3, 3), (5, 5, 5, 4, 3), (5, 5, 5, 5, 3)])
    assert [o.decision for o in outcomes] == ["hold"] * 4
    assert state.strength_a.load_kg == D("6.5")


def test_plateau_two_consecutive_deteriorations_trigger_calibration():
    state = _weighted()
    (_inc,), state = _a_strength_only(state, [(5, 5, 5, 5, 5)])
    outcomes, state = _a_strength_only(state, [(5, 5, 5, 5, 3), (5, 5, 5, 4, 3), (5, 5, 5, 3, 3)])
    assert outcomes[-1].decision == "calibrate_undo_last_increase"
    assert outcomes[-1].details["deteriorations"] == 2


def test_calibration_undoes_only_last_increase_then_offers_1rm():
    state = _weighted()
    _, state = _a_strength_only(state, [(5, 5, 5, 5, 5), (5, 5, 5, 5, 5)])
    assert state.strength_a.load_kg == D("8")  # 5 → 6,5 → 8 (2% от 76,5 = 1,53 → 1,5)
    outcomes, state = _a_strength_only(state, [(5, 5, 5, 4, 3)] * 3)
    assert outcomes[-1].decision == "calibrate_undo_last_increase"
    assert state.strength_a.load_kg == D("6.5")  # отменена только последняя прибавка
    outcomes, state = _a_strength_only(state, [(5, 5, 5, 4, 3)] * 3)
    assert outcomes[-1].decision == "offer_fresh_1rm_or_recalibrate"
    assert state.strength_a.load_kg == D("6.5")  # новый 1RM не обязателен, вес сам не меняется
    assert state.strength_a.recalibration_offered is True


def test_weighted_strength_without_load_step_cannot_increase():
    state = initial_state(EntryInputs(fresh_max=25, body_mass_kg=D("70"), known_strength_a_kg=D("10"), known_strength_b_kg=D("12")))
    after_a = _run(state, (17, 17, 17, 17), (5, 5, 5, 5, 5))
    assert after_a.strength.decision == "hold" and after_a.strength.reason == "load_increment_unavailable"


def test_known_strength_results_outrank_1rm_formula():
    state = initial_state(EntryInputs(
        fresh_max=25, body_mass_kg=D("70"), e1rm_kg=D("30"), load_step_kg=D("0.5"), known_strength_a_kg=D("12.5"),
    ))
    assert (state.strength_a.load_kg, state.strength_b.load_kg) == (D("12.5"), D("10"))


# --- 1RM (§8.3) -------------------------------------------------------------------------------------


def test_one_rm_ramp_protocol():
    bw, step = D("80"), D("1.25")
    attempts: list[OneRmAttempt] = []
    plan = []
    speeds = [AttemptSpeed.NORMAL, AttemptSpeed.NORMAL, AttemptSpeed.FAST, AttemptSpeed.NORMAL, AttemptSpeed.SLOW]
    for speed in speeds:
        nxt = next_one_rm_set(attempts, body_mass=bw, load_step=step)
        plan.append((nxt.load_kg, nxt.reps))
        attempts.append(OneRmAttempt(nxt.load_kg, nxt.reps, True, speed))
    # BW×5; +10% BW = 8 → 7,5 × 3; +20% BW = 16 → 15 × 1; после быстрого +8 → 7,5; после обычного +4 → 3,75.
    assert plan == [(D("0"), 5), (D("7.5"), 3), (D("15"), 1), (D("22.5"), 1), (D("26.25"), 1)]
    failed = next_one_rm_set(attempts, body_mass=bw, load_step=step)
    assert failed.load_kg == D("27.5")  # после медленного +2 → 1,25 (вниз до шага)
    attempts.append(OneRmAttempt(failed.load_kg, 1, False))
    assert next_one_rm_set(attempts, body_mass=bw, load_step=step) is None  # стоп после неудачи
    assert one_rm_result(attempts).e1rm_kg == D("26.25")


def test_one_rm_eight_sets_max_and_conservative_eighth():
    attempts = [OneRmAttempt(D(i), 1, True, AttemptSpeed.FAST) for i in range(8)]
    assert next_one_rm_set(attempts, body_mass=D("70"), load_step=D("1")) is None  # девятого нет
    result = one_rm_result(attempts)
    assert result.e1rm_kg == D("7") and result.conservative is True


# --- Тест 1RM: серверная проверка лестницы (review #305) -------------------------------------------------

BW80, STEP125 = D("80"), D("1.25")


def _ok(load: str, reps: int, speed: AttemptSpeed | None = None) -> OneRmAttempt:
    return OneRmAttempt(D(load), reps, True, speed)


def _fail(load: str, reps: int) -> OneRmAttempt:
    return OneRmAttempt(D(load), reps, False)


# BW 80, шаг 1,25: BW×5 → +7,5×3 → +15×1 → после обычного +3,75 (5% BW = 4 → вниз до шага).
VALID_TERMINAL_FAILURE = [
    _ok("0", 5), _ok("7.5", 3), _ok("15", 1, AttemptSpeed.NORMAL), _fail("18.75", 1),
]


def _transition_80() -> V5State:
    return initial_state(EntryInputs(fresh_max=12, body_mass_kg=BW80, load_step_kg=STEP125))


def test_one_rm_validation_accepts_exact_ladder_with_terminal_failure_or_eighth_set():
    validate_one_rm_attempts(VALID_TERMINAL_FAILURE, body_mass=BW80, load_step=STEP125, outcome=OneRmOutcome.COMPLETED)
    # Восемь подходов: после быстрого — +7,5 (10% BW = 8 → вниз до шага); восьмой успешный быстрый — консервативно.
    eight = [_ok("0", 5), _ok("7.5", 3)] + [_ok(str(15 + 7.5 * i), 1, AttemptSpeed.FAST) for i in range(6)]
    validate_one_rm_attempts(eight, body_mass=BW80, load_step=STEP125, outcome=OneRmOutcome.COMPLETED)
    state, result = record_one_rm_test(_transition_80(), eight, performed_at="2026-10-10T10:00:00+00:00")
    assert (result.e1rm_kg, result.conservative, result.sets_used) == (D("52.5"), True, 8)
    assert result.outcome is OneRmOutcome.COMPLETED and result.confirmed is True
    assert state.inputs.e1rm_kg == D("52.5") and len(state.one_rm_tests) == 1
    assert state.one_rm_tests[0]["outcome"] == "completed" and state.one_rm_tests[0]["standardized"] is True
    assert state.one_rm_tests[0]["body_mass_kg"] == "80" and state.one_rm_tests[0]["load_step_kg"] == "1.25"
    # Неудача на первом подходе — оконченный тест без результата.
    state, result = record_one_rm_test(_transition_80(), [_fail("0", 5)], performed_at="2026-10-10T10:00:00+00:00")
    assert result.e1rm_kg is None and state.inputs.e1rm_kg is None and len(state.one_rm_tests) == 1


@pytest.mark.parametrize("attempts", [
    pytest.param([_ok("0", 5), _ok("7.5", 3), _ok("40", 1, AttemptSpeed.FAST), _fail("47.5", 1)], id="off-ladder-load"),
    pytest.param([_ok("0", 5), _ok("7.5", 5), _ok("15", 1, AttemptSpeed.NORMAL), _fail("18.75", 1)], id="wrong-reps"),
    pytest.param([_ok("0", 5), _fail("7.5", 3), _ok("15", 1, AttemptSpeed.FAST)], id="success-after-failure"),
    pytest.param([*VALID_TERMINAL_FAILURE, _ok("18.75", 1, AttemptSpeed.SLOW)], id="attempt-after-terminal-failure"),
    pytest.param([_ok("50", 1, AttemptSpeed.FAST)], id="single-arbitrary-success"),
    pytest.param([_ok("0", 5)], id="single-valid-success-not-finished"),
    pytest.param([_ok("0", 5), _ok("7.5", 3), _ok("15", 1, AttemptSpeed.FAST)], id="stopped-mid-ladder"),
    pytest.param([_ok("0", 5), _ok("7.5", 3), _ok("15", 1), _fail("17.5", 1)], id="single-success-without-speed"),
    pytest.param([], id="empty"),
])
def test_one_rm_record_rejects_whole_invalid_test_without_state_change(attempts):
    state = _transition_80()
    with pytest.raises(OneRmTestError):
        record_one_rm_test(state, attempts, performed_at="2026-10-10T10:00:00+00:00")
    assert state.one_rm_tests == () and state.inputs.e1rm_kg is None  # чистая функция: ничего не записано


def test_one_rm_record_requires_weighted_strength_and_ladder_inputs():
    with pytest.raises(OneRmTestError):  # уровень 1 — силе с весом нечего применять
        record_one_rm_test(_assisted(body_mass_kg=BW80, load_step_kg=STEP125), VALID_TERMINAL_FAILURE, performed_at="x")
    no_step = initial_state(EntryInputs(fresh_max=12, body_mass_kg=BW80))
    assert one_rm_missing_inputs(no_step) == (PendingInput.LOAD_STEP,)
    with pytest.raises(OneRmTestError):
        record_one_rm_test(no_step, VALID_TERMINAL_FAILURE, performed_at="x")


def test_completed_test_without_successful_single_assigns_no_e1rm():
    """E1RM — вес на ОДНО повторение: успешные ×5/×3 его не дают. Неудача на третьем подходе (+15 × 1) —
    оконченный тест, записан как факт, но E1RM не назначается (раньше брался +7,5 из подхода ×3)."""
    attempts = [_ok("0", 5), _ok("7.5", 3), _fail("15", 1)]
    state, result = record_one_rm_test(_transition_80(), attempts, performed_at="2026-10-10T10:00:00+00:00")
    assert (result.e1rm_kg, result.last_successful_single_kg, result.confirmed) == (None, None, False)
    assert state.inputs.e1rm_kg is None and pending_inputs(state) == (PendingInput.ONE_REP_MAX,)
    assert state.one_rm_tests[0]["outcome"] == "completed" and state.one_rm_tests[0]["e1rm_kg"] is None


# --- Тест 1RM: явная добровольная остановка (review #318) -----------------------------------------------


@pytest.mark.parametrize(("attempts", "last_single"), [
    # BW 80, шаг 1,25: остановился после +15 × 1 (обычный) — до неудачи и до восьмого подхода.
    pytest.param([_ok("0", 5), _ok("7.5", 3), _ok("15", 1, AttemptSpeed.NORMAL)], D("15"), id="after-first-single"),
    # +15 быстрый → +22,5 (10% BW = 8 → 7,5) обычный → +26,25 (5% = 4 → 3,75) медленный — остановка.
    pytest.param([
        _ok("0", 5), _ok("7.5", 3), _ok("15", 1, AttemptSpeed.FAST), _ok("22.5", 1, AttemptSpeed.NORMAL),
        _ok("26.25", 1, AttemptSpeed.SLOW),
    ], D("26.25"), id="after-five-sets"),
    # Остановка после разминочных ×5/×3: одиночного успешного нет — сохраняется только факт попыток.
    pytest.param([_ok("0", 5)], None, id="after-bw-x5"),
    pytest.param([_ok("0", 5), _ok("7.5", 3)], None, id="after-x3"),
])
def test_voluntary_stop_keeps_attempts_and_last_single_but_assigns_no_e1rm(attempts, last_single):
    state, result = record_one_rm_test(
        _transition_80(), attempts, performed_at="2026-10-10T10:00:00+00:00", outcome=OneRmOutcome.STOPPED,
    )
    assert result.outcome is OneRmOutcome.STOPPED and result.confirmed is False and result.e1rm_kg is None
    assert result.last_successful_single_kg == last_single and result.sets_used == len(attempts)
    assert result.conservative is False
    # Не подтверждённый 1RM: E1RM не назначен, веса силы не посчитаны — курс по-прежнему ждёт тест.
    assert state.inputs.e1rm_kg is None and pending_inputs(state) == (PendingInput.ONE_REP_MAX,)
    assert state.strength_a.load_kg is None and state.strength_b.load_kg is None
    (record,) = state.one_rm_tests
    assert record["outcome"] == "stopped" and record["standardized"] is False and record["e1rm_kg"] is None
    assert record["last_successful_single_kg"] == (str(last_single) if last_single is not None else None)
    assert len(record["attempts"]) == len(attempts) and all(a["success"] for a in record["attempts"])


@pytest.mark.parametrize("attempts", [
    pytest.param([], id="nothing-to-record"),
    pytest.param([_ok("0", 5), _ok("10", 3)], id="off-ladder"),
    pytest.param([_ok("0", 5), _ok("7.5", 3), _ok("15", 1)], id="single-without-speed"),
    pytest.param(VALID_TERMINAL_FAILURE, id="ladder-already-ended-by-failure"),
    pytest.param(
        [_ok("0", 5), _ok("7.5", 3)] + [_ok(str(15 + 7.5 * i), 1, AttemptSpeed.FAST) for i in range(6)],
        id="ladder-already-ended-by-eighth-set",
    ),
])
def test_voluntary_stop_keeps_server_ladder_validation(attempts):
    state = _transition_80()
    with pytest.raises(OneRmTestError):
        record_one_rm_test(state, attempts, performed_at="2026-10-10T10:00:00+00:00", outcome=OneRmOutcome.STOPPED)
    assert state.one_rm_tests == ()


def test_latest_one_rm_test_at_uses_saved_server_timestamps():
    assert latest_one_rm_test_at(()) is None
    tests = [
        {"performed_at": "2026-10-10T10:00:00+00:00", "outcome": "completed"},
        {"performed_at": "2026-10-12T09:30:00+00:00", "outcome": "stopped"},
        {"performed_at": "2026-10-11T08:00:00+00:00"},  # запись до review #318 — без outcome
    ]
    assert latest_one_rm_test_at(tests) == datetime(2026, 10, 12, 9, 30, tzinfo=UTC)


def test_one_rm_preconditions():
    assert one_rm_rest_ok(hours_since_heavy_pulling=47) is False
    assert one_rm_rest_ok(hours_since_heavy_pulling=48) is True


# --- §9: одновременное ухудшение обоих блоков ------------------------------------------------------


def test_two_sessions_with_both_blocks_worse_pause_increases_until_recovery_check():
    state = _weighted()
    _, state = _a_cycle(state, (17, 17, 17, 18))  # A 17×4 + 18
    after_b = None
    a1 = _run(state, (17, 17, 17, 17), (5, 5, 5, 5, 4))  # A: 68 < 69, сила 24 — нет прошлого сопоставимого
    state = a1.state
    b = _session(state)
    after_b = _run(state, (b.volume.sets[0].target_reps,) * (len(b.volume.sets) - 1) + (1,), (3, 3, 3, 3, 2))
    state = after_b.state
    a2 = _run(state, (17, 17, 17, 16), (5, 5, 5, 4, 4))  # A хуже (67 < 68) и сила хуже (23 < 24)
    assert a2.state.both_deteriorated_streak == 1
    state = a2.state
    b = _session(state)
    b2 = _run(state, (b.volume.sets[0].target_reps,) * (len(b.volume.sets) - 2) + (1,), (3, 3, 3, 2, 2))
    assert b2.state.recovery_check_required is True
    # Пауза — не вход: занятие назначается с удержанной нагрузкой (старт не блокируется).
    paused = b2.state
    held = _session(paused)
    assert pending_inputs(paused) == ()
    assert [s.target_reps for s in held.volume.sets] == list(paused.volume_a.targets)
    assert held.strength.external_load_kg == paused.strength_a.load_kg

    # Полностью закрытое занятие во время паузы: прибавки не назначаются, нагрузка удерживается.
    perfect_volume = tuple(s.target_reps for s in held.volume.sets[:-1]) + (held.volume.sets[-1].target_reps + 2,)
    during = _run(paused, perfect_volume, (5, 5, 5, 5, 5))
    assert during.volume.reason == "recovery_check_required" and during.strength.reason == "recovery_check_required"
    assert during.state.volume_a.targets == paused.volume_a.targets
    assert during.state.strength_a.load_kg == paused.strength_a.load_kg
    assert during.state.recovery_check_required is True

    # Подтверждение проверки снимает паузу: то же закрытое занятие снова даёт прибавки.
    cleared = clear_recovery_check(paused)
    assert cleared.recovery_check_required is False and cleared.both_deteriorated_streak == 0
    after = _run(cleared, perfect_volume, (5, 5, 5, 5, 5))
    assert after.strength.decision == "increase_load"
    assert after.state.strength_a.load_kg > paused.strength_a.load_kg
    assert sum(after.state.volume_a.targets) == sum(paused.volume_a.targets) + 1


# --- Только вперёд ------------------------------------------------------------------------------------


def test_advance_reads_prescription_not_regenerated_state():
    """Рецепт занятия берётся из его снимка: состояние, изменённое после выдачи, не переписывает
    смысл уже выданного рецепта (и его прогрессия не применяется к другому весу)."""
    state = _weighted()
    issued = _session(state).to_dict()
    moved = apply_inputs(state, EntryInputs(known_strength_a_kg=D("20")))  # 0 сессий: пересчёт старта
    assert moved.strength_a.load_kg == D("20")
    outcome = advance_session(
        moved, issued,
        SessionResult(BlockResult((17, 17, 17, 19), True, True), BlockResult((5,) * 5, True, True)),
        body_mass=D("70"),
    )
    assert outcome.strength.decision == "hold" and outcome.strength.reason == "load_changed_since_prescription"
    assert issued["blocks"][1]["external_load_kg"] == "5"  # выданный рецепт не изменился


def test_session_advance_flips_role_and_counts():
    state = _weighted()
    outcome = _run(state, (17, 17, 17, 17), (5, 5, 5, 5, 5))
    assert outcome.state.next_role is WorkoutRole.B and outcome.state.sessions_completed == 1


def test_prescription_snapshot_contents():
    data = _session(_assisted()).to_dict()
    assert data["program_version"] == "pullups_v5_6" and data["workout_role"] == "A" and data["level"] == "assisted"
    assert data["inter_block_rest_seconds"] == 900
    assert data["structure"] == ["warm_up", "volume", "inter_block_rest", "strength_ramp_up", "strength"]
    # Разминка и подводка в источнике названы, но не описаны — явно «не предписаны», без выдуманного содержания.
    assert data["warm_up"]["prescribed"] is False and "content" in data["warm_up"]["missing"]
    assert data["strength_ramp_up"]["prescribed"] is False
    assert data["strength_ramp_up"]["counts_as_working_sets"] is False
    volume, strength = data["blocks"]
    assert volume["block_role"] == "a_volume" and volume["rest_seconds"] == 240
    assert volume["assistance"]["attachment"] == "петля на перекладине" and volume["assistance"]["body_position"] == "стопа"
    assert [s["rest_after_seconds"] for s in volume["sets"]] == [240, 240, 240, None]
    assert strength["block_role"] == "assisted_strength" and strength["sets"][-1]["cap_reps"] == 8
    assert data["source_inputs"]["volume_capacity"] == 10 and data["source_inputs"]["fresh_max"] == 0


def test_step_assistance_without_ladder_never_guesses():
    step = step_assistance(BAND_MID, AssistanceIntent.DECREASE, ())
    assert step.selection_required is True and step.setup == BAND_MID
    step = step_assistance(BAND_HEAVY, AssistanceIntent.INCREASE, LADDER)
    assert step.selection_required is True and step.setup == BAND_HEAVY  # тяжелее нет


def test_strength_state_rejects_unknown_mode():
    with pytest.raises(ValueError):
        StrengthState.from_dict({"mode": "max_only"})


# --- Отдых объёма B: 60 с (решение владельца 17.10.2026) -------------------------------------------


def _rests(block) -> list[int | None]:
    return [s.rest_after_seconds for s in block.sets]


@pytest.mark.parametrize(
    ("label", "state"),
    [
        ("assisted", _run(_assisted(), (7, 7, 7, 9), (5, 5, 5, 5, 6)).state),
        ("transition", _run(_weighted(m=10), (5, 5, 5, 7), (5, 5, 5, 5, 5)).state),
        ("weighted", _run(_weighted(m=25), (17, 17, 17, 19), (5, 5, 5, 5, 5)).state),
        ("weighted_standard", _b_state(13, 5)),
    ],
)
def test_b_volume_rest_is_60_seconds_at_every_level(label, state):
    """Решение владельца 17.10.2026: отдых между подходами объёма B — 60 с (было 30) на всех уровнях."""
    b = _session(state)
    assert b.role is WorkoutRole.B and b.volume.block_role is BlockRole.B_VOLUME, label
    assert b.volume.rest_seconds == 60
    assert _rests(b.volume) == [60] * (len(b.volume.sets) - 1) + [None]
    data = b.to_dict()["blocks"][0]
    assert data["rest_seconds"] == 60 and {s["rest_after_seconds"] for s in data["sets"][:-1]} == {60}
    # Остальные интервалы не меняются: сила 180, объём → сила 900.
    assert _rests(b.strength) == [180] * (len(b.strength.sets) - 1) + [None]
    assert b.strength.rest_seconds == 180 and b.inter_block_rest_seconds == 900


@pytest.mark.parametrize("state", [_assisted(), _weighted(m=10), _weighted(m=25)])
def test_other_v5_intervals_unchanged_by_b_rest_change(state):
    a = _session(state)
    assert a.role is WorkoutRole.A
    assert a.volume.rest_seconds == 240 and _rests(a.volume) == [240, 240, 240, None]
    assert a.strength.rest_seconds == 180 and _rests(a.strength) == [180] * 4 + [None]
    assert a.inter_block_rest_seconds == 900


def test_b_progression_does_not_depend_on_the_rest_seconds_value():
    """Прогрессия B читает подтверждение «отдых в пределах» (да/нет/не знаю), а не число секунд: снимок
    старого занятия с 30 с и новый с 60 с при одинаковом факте дают одно и то же решение."""
    state = _b_state(13, 5)
    new = _session(state).to_dict()
    old = {**new, "blocks": [
        {**new["blocks"][0], "rest_seconds": 30, "sets": [
            {**s, "rest_after_seconds": 30 if s["rest_after_seconds"] is not None else None} for s in new["blocks"][0]["sets"]
        ]},
        new["blocks"][1],
    ]}
    result = SessionResult(
        volume=BlockResult(reps=(5,) * 13, technique_valid=True, rest_within_limit=True),
        strength=BlockResult(reps=(3,) * 5, technique_valid=True, rest_within_limit=True),
    )
    after_new = advance_session(state, new, result, body_mass=D("70"), ladder=LADDER)
    after_old = advance_session(state, old, result, body_mass=D("70"), ladder=LADDER)
    assert after_new.state.volume_b == after_old.state.volume_b
    assert (after_new.state.volume_b.sets, after_new.state.volume_b.reps) == (14, 5)
