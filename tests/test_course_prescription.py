"""issue #305 (W1c): механизм версий прескрипции курса — app/domain/course_prescription.py.

Текущая программа — V5.6 (pullups_v5_6, домен и золотые тесты — tests/test_pullups_v5.py). Здесь —
реестр правил стартовой прескрипции, ворота замера и машинерия УСТАРЕВШЕЙ версии (pullups_legacy_step:
нормализация block_b.work_sets, резолвер «рабочие + максимум» бот-эпохи). Прежнее решение «прогрессию
двигает только подход на максимум» заменено решением владельца V5.6 и здесь не проверяется."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.db.repositories.training_sessions import SetLogInput
from app.domain.constants import STRENGTH_BLOCK
from app.domain.course_prescription import (
    CURRENT_INITIAL_PRESCRIPTION_RULE,
    LEGACY_INITIAL_PRESCRIPTION_RULE,
    AssessmentInput,
    AssessmentRequirement,
    AssessmentSource,
    InclusionAssessmentState,
    InvalidProgressionStateError,
    PrescriptionOverrides,
    get_initial_prescription_rule,
    initial_assessment_state,
    latest_valid_assessment,
    normalize_progression_state,
    prescription_provenance,
    progression_state_needs_normalization,
    resolve_progression_block,
    rule_key_from_provenance,
)
from app.domain.multi_program import MetricType
from app.domain.progression import recalculate_target
from app.domain.pullups_v5 import EntryInputs, is_v5_state
from app.services.session_log import _apply_step_progression

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


# --- УСТАРЕВШАЯ версия программы (pullups_legacy_step): формула бот-эпохи, не V5.6 -----------------

LEGACY_STATE = {
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


def _sets(working: list[int], max_reps: int) -> list[SetLogInput]:
    logs = [
        SetLogInput(set_number=i + 1, metric_type=MetricType.REPS, value=Decimal(r), unit="reps")
        for i, r in enumerate(working)
    ]
    logs.append(SetLogInput(
        set_number=len(working) + 1, metric_type=MetricType.REPS, value=Decimal(max_reps), unit="reps", is_max_set=True,
    ))
    return logs


def test_legacy_version_keeps_bot_era_formula_not_v5():
    """Инклюзии УСТАРЕВШЕЙ версии (без program_version) прогрессируют прежней формулой бот-эпохи —
    рабочие подходы + подход на максимум (``recalculate_target``), как до #305. Это не правило V5.6 и
    не «MAX-only»: J4 «3·3·3·3 + max 6» — вектор только устаревшей версии."""
    assert not is_v5_state(LEGACY_STATE)
    new_state, result = _apply_step_progression(
        LEGACY_STATE, performed_at=datetime(2026, 10, 9, tzinfo=UTC),
        block_a_sets=_sets([10, 10, 10], 12), block_b_sets=_sets([3, 3, 3, 3], 6),
    )
    # Объём блока бот-эпохи = рабочие + максимум: 3·4 + 6 = 18 (прошлый — 12).
    expected_b = recalculate_target(STRENGTH_BLOCK, 3, (3, 3, 3, 3), 6, 18, 12, consecutive_weak_before=0)
    assert result.block_b.target_after == expected_b.new_target
    assert new_state["block_b"]["target"] == expected_b.new_target
    assert new_state["block_b"]["volume"] == 18  # объём (рабочие + максимум) — вход прежней формулы
    assert "program_version" not in new_state


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


# --- InitialPrescriptionRule: реестр версий --------------------------------------------------------


def test_current_rule_is_v5_6_and_decided():
    rule = get_initial_prescription_rule()
    assert CURRENT_INITIAL_PRESCRIPTION_RULE == f"{rule.rule_id}@{rule.version}" == "pullups_v5_6@1"
    assert rule.decided is True and rule.program_version == "pullups_v5_6"


def test_v5_rule_takes_fresh_max_from_assessment():
    state = get_initial_prescription_rule().prescribe({}, _assessment(0), PrescriptionOverrides())
    assert is_v5_state(state) and state["level"] == "assisted"  # M = 8 < 10
    assert state["inputs"]["fresh_max"] == 8
    explicit = get_initial_prescription_rule().prescribe({}, _assessment(0), PrescriptionOverrides(), EntryInputs(fresh_max=25))
    assert explicit["level"] == "weighted"  # явный ввод сильнее замера


def test_legacy_rule_stays_registered_with_canonical_shape():
    rule = get_initial_prescription_rule(LEGACY_INITIAL_PRESCRIPTION_RULE)
    assert rule.decided is False and rule.program_version == "pullups_legacy_step"
    state = rule.prescribe(
        {"block_a": {"base_target": 10, "work_sets": 3}, "block_b": {"base_target": 3}}, None, PrescriptionOverrides(),
    )
    assert state["block_b"]["work_sets"] == STRENGTH_BLOCK.work_sets
    assert normalize_progression_state(state) == state
    for role in ("block_a", "block_b"):
        assert resolve_progression_block(role, state)


def test_rule_key_from_provenance_reads_old_and_new_records():
    assert rule_key_from_provenance(None) == LEGACY_INITIAL_PRESCRIPTION_RULE
    assert rule_key_from_provenance({"rule_id": "program_config_default", "rule_version": 0}) == "program_config_default@0"
    assert rule_key_from_provenance({"rule_id": "pullups_v5_6", "rule_version": 1}) == "pullups_v5_6@1"


def test_provenance_records_rule_version_inputs_and_assessment():
    rule = get_initial_prescription_rule()
    assessment = _assessment(2, AssessmentSource.ASSESSMENT_RESULT, 42)
    provenance = prescription_provenance(
        rule, assessment=assessment, overrides=PrescriptionOverrides(),
        state=InclusionAssessmentState.ACTIVE, computed_at=datetime(2026, 10, 9, tzinfo=UTC),
        inputs=EntryInputs(volume_capacity=10),
    )
    assert provenance["rule_id"] == "pullups_v5_6" and provenance["rule_version"] == 1
    assert provenance["rule_decided"] is True and provenance["program_version"] == "pullups_v5_6"
    assert provenance["inputs"]["volume_capacity"] == 10
    assert provenance["assessment"] == {
        "source": "assessment_result", "id": 42, "max_reps": 8, "performed_on": "2026-10-07",
    }
    assert provenance["explicit_targets"] is None
    assert provenance["assessment_state"] == "active"
