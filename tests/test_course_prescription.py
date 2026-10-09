"""issue #305 (W1c): чистые правила прескрипции курса — app/domain/course_prescription.py.

Только механизм, не зависящий от решений владельца OD-1 (числа стартовой прескрипции) и OD-3
(хвостовой подход на максимум): правило OD-3 передаётся резолверу явно, числа OD-1 не проверяются."""

from datetime import UTC, date, datetime

import pytest

from app.domain.constants import STRENGTH_BLOCK
from app.domain.course_prescription import (
    COURSE_TRAILING_MAX_SET_RULE,
    CURRENT_INITIAL_PRESCRIPTION_RULE,
    AssessmentInput,
    AssessmentRequirement,
    AssessmentSource,
    InclusionAssessmentState,
    InvalidProgressionStateError,
    PrescriptionOverrides,
    TrailingMaxSetRule,
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


@pytest.mark.parametrize("rule", [TrailingMaxSetRule.OMIT, TrailingMaxSetRule.UNDECIDED])
def test_d_resolver_reads_work_sets_for_both_roles(rule):
    state = _state(block_a={"target": 12, "work_sets": 5}, block_b={"target": 2, "work_sets": 6})
    a = resolve_progression_block("block_a", state, trailing_max_set=rule)
    b = resolve_progression_block("block_b", state, trailing_max_set=rule)
    assert [(s.set_number, s.target_reps, s.is_max_set) for s in a] == [(n, 12, False) for n in range(1, 6)]
    assert [(s.set_number, s.target_reps, s.is_max_set) for s in b] == [(n, 2, False) for n in range(1, 7)]


def test_e_block_b_with_work_sets_4_resolves_four_working_sets_never_one():
    state = normalize_progression_state(_state(block_b={"target": 3}))
    working = [s for s in resolve_progression_block("block_b", state, trailing_max_set=COURSE_TRAILING_MAX_SET_RULE)
               if not s.is_max_set]
    assert len(working) == 4 and {s.target_reps for s in working} == {3}


def test_e_missing_work_sets_is_an_error_not_a_silent_single_set():
    with pytest.raises(InvalidProgressionStateError):
        resolve_progression_block("block_b", _state(block_b={"target": 3}), trailing_max_set=TrailingMaxSetRule.OMIT)
    with pytest.raises(InvalidProgressionStateError):
        resolve_progression_block("block_b", _state(block_b={"target": 3, "work_sets": 0}),
                                  trailing_max_set=TrailingMaxSetRule.OMIT)


def test_trailing_max_set_is_appended_last_only_when_rule_includes_it():
    """Механизм для любого ответа OD-3: INCLUDE → work_sets рабочих + один max последним; иначе — без max."""
    state = _state()
    included = resolve_progression_block("block_b", state, trailing_max_set=TrailingMaxSetRule.INCLUDE)
    assert [(s.set_number, s.is_max_set) for s in included] == [(1, False), (2, False), (3, False), (4, False), (5, True)]
    assert included[-1].target_reps == 0  # у подхода на максимум цели нет
    assert sum(s.is_max_set for s in included) == 1
    assert not any(s.is_max_set for s in resolve_progression_block("block_b", state, trailing_max_set=TrailingMaxSetRule.OMIT))


def test_od3_is_recorded_as_undecided_not_silently_answered():
    """OD-3 (#310) открыт: единственная точка решения в коде помечена как нерешённая. Тест меняется вместе
    с записанным решением владельца, не раньше."""
    assert COURSE_TRAILING_MAX_SET_RULE == TrailingMaxSetRule.UNDECIDED


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
        assert resolve_progression_block(role, state, trailing_max_set=TrailingMaxSetRule.OMIT)


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
