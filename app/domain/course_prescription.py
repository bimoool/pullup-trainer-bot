"""Прескрипция курса «Подтягивания» (issue #305, W1c; WORKOUT_DOMAIN_V2 §6, PROGRAM_PLAN_V2 §3,
MIGRATION_V2 §3/§5). Чистая логика: без aiogram/sqlalchemy, «сегодня» приходит параметром.

**Текущая программа — V5.6** (``pullups_v5_6``, решение владельца от 11.10.2026, заменяет прежнее
решение OD-3 «прогрессию двигает только подход на максимум»): её домен — ``app/domain/pullups_v5.py``,
контракт — ``docs/domain/PULLUPS_V5_6.md``. Здесь — общий механизм версий:

1. ``InitialPrescriptionRule`` — чистое версионированное правило стартового состояния (реестр
   ``rule_id@version``, провенанс на инклюзии). Текущее — ``pullups_v5_6@1`` (``decided = True``).
   ``program_config_default@0`` остаётся в реестре: им созданы инклюзии УСТАРЕВШЕЙ версии программы
   (``pullups_legacy_step``), их провенанс должен оставаться читаемым. Плюс ворота ``awaiting_assessment``.
2. УСТАРЕВШАЯ версия (``pullups_legacy_step``) — состояние ``block_a``/``block_b`` бот-эпохи:
   ``normalize_progression_state`` (у ``block_b`` старых инклюзий нет ``work_sets`` — D2, дописывается
   ``STRENGTH_BLOCK.work_sets``, как у миграции ``e3b9c5d7a2f1``) и ``resolve_progression_block``
   (``work_sets`` рабочих подходов + подход на максимум — структура тренировки бот-эпохи, вход прежней
   формулы ``recalculate_target``). V5.6 их не использует и старые инклюзии в V5.6 не переводит.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol

from app.domain.constants import STRENGTH_BLOCK, VOLUME_BLOCK, EquipmentType
from app.domain.pullups_v5 import EntryInputs, initial_state

ROLE_BLOCK_A = "block_a"
ROLE_BLOCK_B = "block_b"
PROGRESSION_ROLES = (ROLE_BLOCK_A, ROLE_BLOCK_B)


class InvalidProgressionStateError(ValueError):
    """Состояние роли без валидного ``work_sets`` (после нормализации такого быть не должно)."""


# --- 1. Каноническая форма состояния ---------------------------------------------------------


def _missing(value: object) -> bool:
    return value is None


def normalize_progression_state(progression_state: Mapping) -> dict:
    """Копия состояния, где у ``block_b`` есть ``work_sets`` (MIGRATION_V2 §3: absent → 4, present →
    untouched). Остальные поля (цель, снаряд, счётчики) и ``block_a`` не меняются. Идемпотентно;
    не STEP-состояние (нет объекта ``block_b``) возвращается копией без изменений."""
    state = dict(progression_state)
    block_b = state.get(ROLE_BLOCK_B)
    if isinstance(block_b, Mapping) and _missing(block_b.get("work_sets")):
        state[ROLE_BLOCK_B] = {**block_b, "work_sets": STRENGTH_BLOCK.work_sets}
    return state


def progression_state_needs_normalization(progression_state: Mapping) -> bool:
    return normalize_progression_state(progression_state) != dict(progression_state)


def role_work_sets(role: str, progression_state: Mapping) -> int:
    """Число рабочих подходов роли из состояния. Без значения по умолчанию: отсутствие — дефект
    состояния (нормализация его закрывает), а не повод тихо выполнить один подход (D2)."""
    role_state = progression_state.get(role)
    if not isinstance(role_state, Mapping):
        raise InvalidProgressionStateError(f"progression_state has no {role!r}")
    work_sets = role_state.get("work_sets")
    if isinstance(work_sets, bool) or not isinstance(work_sets, int) or work_sets < 1:
        raise InvalidProgressionStateError(f"{role}.work_sets must be a positive int, got {work_sets!r}")
    return work_sets


# --- 2. Резолвер блока курса -----------------------------------------------------------------


@dataclass(frozen=True)
class ProgressionSetPrescription:
    """Один подход блока курса. ``is_max_set`` — свойство цели (TRAINING_SESSION R2), его сохраняет
    запись подхода. У подхода на максимум цели нет (``target_reps = 0``), как у max_effort Builder."""

    set_number: int
    target_reps: int
    is_max_set: bool = False


def resolve_progression_block(role: str, progression_state: Mapping) -> tuple[ProgressionSetPrescription, ...]:
    """УСТАРЕВШАЯ версия программы (``pullups_legacy_step``): подходы блока роли ``block_a`` / ``block_b``
    — ровно ``work_sets`` рабочих подходов (для обеих ролей, без тихого «1», D2) на ``target`` роли и
    ПОСЛЕДНИМ — подход на максимум (``is_max_set``, ``target_reps = 0``): так устроена тренировка
    бот-эпохи, и подход на максимум — вход её формулы (``recalculate_target``: рабочие подходы + максимум).
    Для V5.6 не используется (там у каждого блока свой сигнал). Состояние должно быть нормализовано."""
    if role not in PROGRESSION_ROLES:
        raise InvalidProgressionStateError(f"unknown progression role {role!r}")
    work_sets = role_work_sets(role, progression_state)
    target = int(progression_state[role]["target"])
    sets = [ProgressionSetPrescription(set_number=i + 1, target_reps=target) for i in range(work_sets)]
    sets.append(ProgressionSetPrescription(set_number=work_sets + 1, target_reps=0, is_max_set=True))
    return tuple(sets)


# --- 3. Стартовая прескрипция и ворота замера --------------------------------------------------


class InclusionAssessmentState(StrEnum):
    ACTIVE = "active"
    AWAITING_ASSESSMENT = "awaiting_assessment"


@dataclass(frozen=True)
class AssessmentRequirement:
    """``programs.assessment`` (#304): {protocol_id, required_before_first_session, validity_days}."""

    protocol_id: int | None
    required_before_first_session: bool
    validity_days: int | None

    @classmethod
    def from_config(cls, config: Mapping | None) -> "AssessmentRequirement | None":
        if not config:
            return None
        return cls(
            protocol_id=config.get("protocol_id"),
            required_before_first_session=bool(config.get("required_before_first_session")),
            validity_days=config.get("validity_days"),
        )


class AssessmentSource(StrEnum):
    ASSESSMENT_RESULT = "assessment_result"  # assessment_results (протокол программы)
    BASELINE = "baseline"  # замер онбординга (baselines) — тот же «максимум подтягиваний»


@dataclass(frozen=True)
class AssessmentInput:
    source: AssessmentSource
    id: int
    max_reps: int
    performed_on: date

    def provenance(self) -> dict:
        return {
            "source": self.source.value, "id": self.id, "max_reps": self.max_reps,
            "performed_on": self.performed_on.isoformat(),
        }


def latest_valid_assessment(
    candidates: list[AssessmentInput], *, today: date, validity_days: int | None,
) -> AssessmentInput | None:
    """Самый свежий замер не старше ``validity_days`` (None — без срока). При равной дате —
    приоритет assessment_results, затем больший id (детерминированно)."""
    valid = [
        c for c in candidates
        if c.performed_on <= today and (validity_days is None or (today - c.performed_on).days <= validity_days)
    ]
    if not valid:
        return None
    return max(valid, key=lambda c: (c.performed_on, c.source == AssessmentSource.ASSESSMENT_RESULT, c.id))


def initial_assessment_state(
    requirement: AssessmentRequirement | None, *, assessment: AssessmentInput | None, has_main_history: bool,
) -> InclusionAssessmentState:
    """PROGRAM_PLAN_V2 §3 + MIGRATION_V2 §5.4: ``awaiting_assessment`` — только если программа требует
    замер до первой тренировки, валидного замера нет И у пользователя нет завершённых основных
    тренировок. Пользователь с историей никогда не отправляется обратно на замер."""
    if requirement is None or not requirement.required_before_first_session:
        return InclusionAssessmentState.ACTIVE
    if has_main_history or assessment is not None:
        return InclusionAssessmentState.ACTIVE
    return InclusionAssessmentState.AWAITING_ASSESSMENT


@dataclass(frozen=True)
class PrescriptionOverrides:
    """Явно переданные цели запроса подключения (API ``initial_target_a/b``, прежний контракт)."""

    target_a: int | None = None
    target_b: int | None = None
    volume_a: int = 0
    volume_b: int = 0


class InitialPrescriptionRule(Protocol):
    rule_id: str
    version: int
    # False — правило не утверждено владельцем (сохранённый статус-кво устаревшей версии).
    decided: bool
    program_version: str

    def prescribe(
        self, program_config: Mapping, assessment: AssessmentInput | None, overrides: PrescriptionOverrides,
        inputs: EntryInputs | None = None,
    ) -> dict: ...


def _step_state(*, target_a: int, target_b: int, work_sets_a: int, work_sets_b: int, volume_a: int, volume_b: int) -> dict:
    """Каноническая форма STEP-состояния (та же, что NextBlockState / backfill_multi_program), обе
    роли с ``work_sets``."""
    return {
        "schema_version": 1,
        "strategy_type": "step",
        ROLE_BLOCK_A: {
            "target": target_a,
            "volume": volume_a,
            "work_sets": work_sets_a,
            "work_sets_growth_reason": None,
            "weak_streak": 0,
            "stall_streak": 0,
            "equipment_type": EquipmentType.BODYWEIGHT.value,
            "equipment_value": None,
            "equipment_item_id": None,
            "needs_new_equipment": False,
        },
        ROLE_BLOCK_B: {
            "target": target_b,
            "volume": volume_b,
            "work_sets": work_sets_b,
            "weak_streak": 0,
            "equipment_type": EquipmentType.BODYWEIGHT.value,
            "equipment_value": None,
            "equipment_item_id": None,
            "needs_new_equipment": False,
            "is_heavy_next": False,
            "heavy_equipment_value_next": None,
        },
        "workouts_completed_in_set": 0,
    }


@dataclass(frozen=True)
class ProgramConfigDefaultRule:
    """УСТАРЕВШАЯ версия программы (``pullups_legacy_step``) — прежнее (до #305) поведение Mini App:
    цели — ``config.block_a/b.base_target`` (иначе ``VOLUME_BLOCK``/``STRENGTH_BLOCK``), снаряд —
    собственный вес, замер не читается. Новые инклюзии получают её только явным запросом устаревшей
    версии (``program_version`` или прежние поля ``initial_target_a/b``); по умолчанию — V5.6.
    Отличие от старого кода — ``block_b.work_sets`` записывается (D2)."""

    rule_id: str = "program_config_default"
    version: int = 0
    decided: bool = False
    program_version: str = "pullups_legacy_step"

    def prescribe(
        self, program_config: Mapping, assessment: AssessmentInput | None, overrides: PrescriptionOverrides,
        inputs: EntryInputs | None = None,
    ) -> dict:
        del assessment, inputs  # статус-кво устаревшей версии: замер не читается
        block_a = (program_config or {}).get(ROLE_BLOCK_A, {})
        block_b = (program_config or {}).get(ROLE_BLOCK_B, {})
        return _step_state(
            target_a=overrides.target_a if overrides.target_a is not None else block_a.get("base_target", VOLUME_BLOCK.base_target),
            target_b=overrides.target_b if overrides.target_b is not None else block_b.get("base_target", STRENGTH_BLOCK.base_target),
            work_sets_a=block_a.get("work_sets", VOLUME_BLOCK.work_sets),
            work_sets_b=block_b.get("work_sets", STRENGTH_BLOCK.work_sets),
            volume_a=overrides.volume_a, volume_b=overrides.volume_b,
        )


@dataclass(frozen=True)
class PullupsV56Rule:
    """Стартовое состояние программы V5.6 (решение владельца, заменяет вопрос OD-1 для новой версии):
    уровень и стартовые дозы — ``app.domain.pullups_v5.initial_state`` из входов §3. M берётся из
    явного ввода, иначе из валидного замера (максимум подтягиваний). Прежние ``initial_target_a/b``
    к V5.6 не относятся (это поля устаревшей версии)."""

    rule_id: str = "pullups_v5_6"
    version: int = 1
    decided: bool = True
    program_version: str = "pullups_v5_6"

    def prescribe(
        self, program_config: Mapping, assessment: AssessmentInput | None, overrides: PrescriptionOverrides,
        inputs: EntryInputs | None = None,
    ) -> dict:
        del program_config, overrides
        inputs = inputs or EntryInputs()
        if inputs.fresh_max is None and assessment is not None:
            inputs = replace(inputs, fresh_max=assessment.max_reps)
        return initial_state(inputs).to_dict()


LEGACY_INITIAL_PRESCRIPTION_RULE = "program_config_default@0"

_RULES: dict[str, Callable[[], InitialPrescriptionRule]] = {
    LEGACY_INITIAL_PRESCRIPTION_RULE: ProgramConfigDefaultRule,
    "pullups_v5_6@1": PullupsV56Rule,
}

# Текущее правило стартовой прескрипции: программа V5.6. Новое правило — новый rule_id/version,
# прежние остаются в реестре (провенанс ранее созданных инклюзий).
CURRENT_INITIAL_PRESCRIPTION_RULE = "pullups_v5_6@1"


def get_initial_prescription_rule(key: str = CURRENT_INITIAL_PRESCRIPTION_RULE) -> InitialPrescriptionRule:
    return _RULES[key]()


def rule_key(rule: InitialPrescriptionRule) -> str:
    return f"{rule.rule_id}@{rule.version}"


def rule_key_from_provenance(provenance: Mapping | None) -> str:
    """Правило, которым создана инклюзия (пересчёт при снятии ожидания замера — тем же правилом).
    Инклюзия без провенанса создана до #305 — устаревшей версией."""
    if not provenance or provenance.get("rule_id") is None:
        return LEGACY_INITIAL_PRESCRIPTION_RULE
    return f"{provenance['rule_id']}@{provenance['rule_version']}"


def prescription_provenance(
    rule: InitialPrescriptionRule, *, assessment: AssessmentInput | None, overrides: PrescriptionOverrides,
    state: InclusionAssessmentState, computed_at: datetime, inputs: EntryInputs | None = None,
) -> dict:
    """Запись на инклюзии: каким правилом и из какого замера получено стартовое состояние."""
    explicit = {
        key: value for key, value in (("target_a", overrides.target_a), ("target_b", overrides.target_b))
        if value is not None
    }
    return {
        "schema_version": 1,
        "rule_id": rule.rule_id,
        "rule_version": rule.version,
        "rule_decided": rule.decided,
        "program_version": rule.program_version,
        "inputs": inputs.to_dict() if inputs is not None else None,
        "assessment": assessment.provenance() if assessment is not None else None,
        "explicit_targets": explicit or None,
        "assessment_state": state.value,
        "computed_at": computed_at.isoformat(),
    }
