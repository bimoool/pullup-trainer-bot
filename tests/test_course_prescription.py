"""issue #305 (W1c): чистые правила прескрипции курса — app/domain/course_prescription.py.

OD-3 решён владельцем (подход на максимум включается), прогрессию двигает только подход на максимум
(решение владельца) — оба правила проверяются здесь. Числа стартовой прескрипции (OD-1) открыты и не
проверяются."""

from datetime import UTC, date, datetime

import pytest

from app.domain.constants import STRENGTH_BLOCK
from app.domain.course_prescription import (
    CURRENT_INITIAL_PRESCRIPTION_RULE,
    AssessmentInput,
    AssessmentRequirement,
    AssessmentSource,
    InclusionAssessmentState,
    InvalidProgressionStateError,
    PrescriptionOverrides,
    advance_step_progression,
    get_initial_prescription_rule,
    initial_assessment_state,
    latest_valid_assessment,
    normalize_progression_state,
    prescription_provenance,
    progression_state_needs_normalization,
    resolve_progression_block,
)

AGED_BLOCK_B = {
    "target": 6, "volume": 30, "weak_streak": 2, "equipment_type": "band", "equipment_value": "25",
    "equipment_item_id": 17, "needs_new_equipment": False, "is_heavy_next": False,
    "heavy_equipment_value_next": None,
}


def _state(block_a: dict | None = None, block_b: dict | None = None) -> dict:
    return {
        "schema_version": 1, "strategy_type": "step",
        "block_a": block_a or {"target": 10, "work_sets": 3, "equipment_type": "bodyweight"},
        "block_b": block_b if block_b is not None else {"target": 3, "work_sets": 4},
        "workouts_completed_in_set": 5,
    }


# --- B / C / K: каноническая форма состояния ---------------------------------------------------


def test_b_aged_block_b_without_work_sets_gets_canonical_value_and_keeps_target_and_equipment():
    aged = _state(block_b=dict(AGED_BLOCK_B))
    normalized = normalize_progression_state(aged)
    assert normalized["block_b"] == {**AGED_BLOCK_B, "work_sets": STRENGTH_BLOCK.work_sets}
    assert STRENGTH_BLOCK.work_sets == 4
    assert normalized["block_a"] == aged["block_a"]
    assert {k: v for k, v in normalized.items() if k != "block_b"} == {k: v for k, v in aged.items() if k != "block_b"}
    assert "work_sets" not in aged["block_b"]  # вход не мутирован


def test_b_null_work_sets_is_treated_as_missing():
    assert normalize_progression_state(_state(block_b={"target": 3, "work_sets": None}))["block_b"]["work_sets"] == 4


@pytest.mark.parametrize("value", [1, 4, 6])
def test_c_existing_work_sets_is_never_overwritten(value):
    state = _state(block_b={**AGED_BLOCK_B, "work_sets": value})
    assert normalize_progression_state(state) == state
    assert not progression_state_needs_normalization(state)


def test_k_normalization_is_idempotent_and_ignores_non_step_state():
    once = normalize_progression_state(_state(block_b=dict(AGED_BLOCK_B)))
    assert normalize_progression_state(once) == once
    assert not progression_state_needs_normalization(once)
    assert normalize_progression_state({}) == {}


# --- D / E: резолвер ------------------------------------------------------------------------


def _shape(sets) -> list[tuple[int, int, bool]]:
    return [(s.set_number, s.target_reps, s.is_max_set) for s in sets]


def test_d_resolver_reads_work_sets_for_both_roles_and_appends_one_max_set():
    state = _state(block_a={"target": 12, "work_sets": 5}, block_b={"target": 2, "work_sets": 6})
    a = resolve_progression_block("block_a", state)
    b = resolve_progression_block("block_b", state)
    assert _shape(a) == [(n, 12, False) for n in range(1, 6)] + [(6, 0, True)]
    assert _shape(b) == [(n, 2, False) for n in range(1, 7)] + [(7, 0, True)]


def test_e_block_b_with_work_sets_4_resolves_four_working_sets_never_one():
    state = normalize_progression_state(_state(block_b={"target": 3}))
    working = [s for s in resolve_progression_block("block_b", state) if not s.is_max_set]
    assert len(working) == 4 and {s.target_reps for s in working} == {3}


def test_e_missing_work_sets_is_an_error_not_a_silent_single_set():
    with pytest.raises(InvalidProgressionStateError):
        resolve_progression_block("block_b", _state(block_b={"target": 3}))
    with pytest.raises(InvalidProgressionStateError):
        resolve_progression_block("block_b", _state(block_b={"target": 3, "work_sets": 0}))


def test_a_od3_max_set_is_included_last_exactly_once():
    """OD-3 решён: «4 × 3» = 4 рабочих + ОДИН явный подход на максимум последним, без цели (target 0)."""
    included = resolve_progression_block("block_b", _state())
    assert _shape(included) == [(1, 3, False), (2, 3, False), (3, 3, False), (4, 3, False), (5, 0, True)]
    assert sum(s.is_max_set for s in included) == 1


# --- C / D / E / F: прогрессию двигает только подход на максимум, только вперёд ----------------

STEP_STATE = {
    "schema_version": 1, "strategy_type": "step",
    "block_a": {
        "target": 10, "volume": 30, "work_sets": 3, "work_sets_growth_reason": None, "weak_streak": 0,
        "stall_streak": 0, "equipment_type": "bodyweight", "equipment_value": None, "equipment_item_id": None,
        "needs_new_equipment": False,
    },
    "block_b": {
        "target": 3, "volume": 12, "work_sets": 4, "weak_streak": 0, "equipment_type": "bodyweight",
        "equipment_value": None, "equipment_item_id": None, "needs_new_equipment": False,
        "is_heavy_next": False, "heavy_equipment_value_next": None,
    },
    "workouts_completed_in_set": 2,
}


def test_c_state_carries_no_working_set_input():
    """Сигнатура шага прогрессии принимает только замеры (max_a/max_b): рабочие подходы физически не
    могут попасть в расчёт. Одинаковый замер → байт в байт одинаковое следующее состояние."""
    import inspect

    assert set(inspect.signature(advance_step_progression).parameters) == {"progression_state", "max_a", "max_b"}
    first, *_ = advance_step_progression(STEP_STATE, max_a=12, max_b=5)
    second, *_ = advance_step_progression(STEP_STATE, max_a=12, max_b=5)
    assert first == second
    assert first["block_a"]["volume"] == 30 and first["block_b"]["volume"] == 12  # объём — не вход и не пишется


@pytest.mark.parametrize(("max_b", "expected_target_b"), [(5, 4), (3, 3), (2, 3)])
def test_d_max_drives_next_target(max_b, expected_target_b):
    """J4: цель 3, max 6/5 > 3 → 3 + max(1, ceil(3·0.05)) = 4; max = цель → держим; max < цели — держим
    (первый промах, откат только после 3 подряд)."""
    state, _a, advance_b = advance_step_progression(STEP_STATE, max_a=None, max_b=max_b)
    assert state["block_b"]["target"] == expected_target_b
    assert (advance_b.target_before, advance_b.target_after, advance_b.measured) == (3, expected_target_b, True)


def test_d_block_a_grows_only_from_its_max():
    state, advance_a, _b = advance_step_progression(STEP_STATE, max_a=12, max_b=None)
    assert state["block_a"]["target"] == 11  # 10 + max(1, ceil(10·0.05))
    assert advance_a.measured and advance_a.target_after == 11
    assert state["block_b"] == STEP_STATE["block_b"]  # без замера Б не двигается


def test_e_no_max_measurement_changes_no_role():
    """Рабочие подходы без подхода на максимум (или подход не выполнен) — прогрессии нет."""
    state, advance_a, advance_b = advance_step_progression(STEP_STATE, max_a=None, max_b=None)
    assert state["block_a"] == STEP_STATE["block_a"] and state["block_b"] == STEP_STATE["block_b"]
    assert not advance_a.measured and not advance_b.measured


def test_e_weak_streak_counts_max_misses_not_volume():
    """weak_streak — подряд идущие промахи ЗАМЕРА; откат −1 на третьем. Объём рабочих подходов не участвует."""
    state = STEP_STATE
    targets = []
    for _ in range(3):
        state, _a, _b = advance_step_progression(state, max_a=None, max_b=2)
        targets.append((state["block_b"]["target"], state["block_b"]["weak_streak"]))
    assert targets == [(3, 1), (3, 2), (2, 3)]
    reset, *_ = advance_step_progression(state, max_a=None, max_b=2)  # max = новая цель 2 → не промах
    assert reset["block_b"]["weak_streak"] == 0


def test_f_forward_only_input_state_is_not_mutated():
    snapshot = repr(STEP_STATE)
    advance_step_progression(STEP_STATE, max_a=40, max_b=9)
    assert repr(STEP_STATE) == snapshot


# --- I / J: ворота замера ---------------------------------------------------------------------

REQUIRED = AssessmentRequirement(protocol_id=7, required_before_first_session=True, validity_days=35)
TODAY = date(2026, 10, 9)


def _assessment(days_ago: int, source=AssessmentSource.BASELINE, id_=1) -> AssessmentInput:
    return AssessmentInput(source=source, id=id_, max_reps=8, performed_on=date.fromordinal(TODAY.toordinal() - days_ago))


def test_i_fresh_user_without_assessment_awaits_assessment():
    assert initial_assessment_state(REQUIRED, assessment=None, has_main_history=False) == (
        InclusionAssessmentState.AWAITING_ASSESSMENT
    )


def test_j_user_with_main_history_is_never_sent_to_assessment():
    assert initial_assessment_state(REQUIRED, assessment=None, has_main_history=True) == InclusionAssessmentState.ACTIVE


def test_valid_assessment_or_no_requirement_is_active():
    assert initial_assessment_state(REQUIRED, assessment=_assessment(0), has_main_history=False) == (
        InclusionAssessmentState.ACTIVE
    )
    assert initial_assessment_state(None, assessment=None, has_main_history=False) == InclusionAssessmentState.ACTIVE
    optional = AssessmentRequirement(protocol_id=7, required_before_first_session=False, validity_days=35)
    assert initial_assessment_state(optional, assessment=None, has_main_history=False) == InclusionAssessmentState.ACTIVE


def test_latest_valid_assessment_respects_validity_window_and_is_deterministic():
    old = _assessment(36, id_=1)
    edge = _assessment(35, id_=2)
    assert latest_valid_assessment([old], today=TODAY, validity_days=35) is None
    assert latest_valid_assessment([old, edge], today=TODAY, validity_days=35) == edge
    same_day = [_assessment(0, AssessmentSource.BASELINE, 9), _assessment(0, AssessmentSource.ASSESSMENT_RESULT, 3)]
    assert latest_valid_assessment(same_day, today=TODAY, validity_days=35).source == AssessmentSource.ASSESSMENT_RESULT
    assert latest_valid_assessment([old], today=TODAY, validity_days=None) == old


# --- InitialPrescriptionRule: оболочка (числа — OD-1) --------------------------------------------


def test_current_rule_is_versioned_and_marked_undecided_pending_od1():
    rule = get_initial_prescription_rule()
    assert CURRENT_INITIAL_PRESCRIPTION_RULE == f"{rule.rule_id}@{rule.version}"
    assert rule.decided is False  # OD-1 (#310) не решён — правило не утверждено владельцем


def test_rule_output_has_canonical_shape_with_work_sets_for_both_roles():
    state = get_initial_prescription_rule().prescribe(
        {"block_a": {"base_target": 10, "work_sets": 3}, "block_b": {"base_target": 3}}, None, PrescriptionOverrides(),
    )
    assert state["block_b"]["work_sets"] == STRENGTH_BLOCK.work_sets
    assert normalize_progression_state(state) == state
    for role in ("block_a", "block_b"):
        assert resolve_progression_block(role, state)


def test_provenance_records_rule_version_and_assessment_input():
    rule = get_initial_prescription_rule()
    assessment = _assessment(2, AssessmentSource.ASSESSMENT_RESULT, 42)
    provenance = prescription_provenance(
        rule, assessment=assessment, overrides=PrescriptionOverrides(target_b=5),
        state=InclusionAssessmentState.ACTIVE, computed_at=datetime(2026, 10, 9, tzinfo=UTC),
    )
    assert provenance["rule_id"] == rule.rule_id and provenance["rule_version"] == rule.version
    assert provenance["rule_decided"] is False
    assert provenance["assessment"] == {
        "source": "assessment_result", "id": 42, "max_reps": 8, "performed_on": "2026-10-07",
    }
    assert provenance["explicit_targets"] == {"target_b": 5}
    assert provenance["assessment_state"] == "active"
