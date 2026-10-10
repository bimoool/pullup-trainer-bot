"""Прескрипция курса «Подтягивания» (issue #305, W1c; WORKOUT_DOMAIN_V2 §6, PROGRAM_PLAN_V2 §3,
MIGRATION_V2 §3/§5). Чистая логика: без aiogram/sqlalchemy, «сегодня» приходит параметром.

Три части:

1. ``normalize_progression_state`` — каноническая форма STEP-состояния: ОБЕ роли несут ``work_sets``.
   У ``block_b`` старых инклюзий поля нет (D2) — дописывается ``STRENGTH_BLOCK.work_sets``; присутствующее
   значение не трогается. Тот же источник, что у миграции ``e3b9c5d7a2f1`` (литерал 4) и convergence.
2. ``resolve_progression_block(role, state)`` — подходы блока курса: ``work_sets`` рабочих (без тихого «1»
   по умолчанию) + один явный подход на максимум (OD-3 решён: включать). ``advance_step_progression`` —
   шаг прогрессии: только подход на максимум, только вперёд (решение владельца).
3. ``InitialPrescriptionRule`` — чистое версионированное правило стартового состояния из замера
   (решение владельца **OD-1** — числа). Пока OD-1 не решён, зарегистрировано единственное правило
   ``program_config_default@0`` = прежнее поведение (``config.block_*.base_target``, собственный вес),
   помеченное ``decided = False``: оно НЕ ответ на OD-1, а сохранённый статус-кво с провенансом, чтобы
   инклюзии, созданные до решения, были отличимы. Плюс ворота ``awaiting_assessment``.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol

from app.domain.constants import STRENGTH_BLOCK, VOLUME_BLOCK, EquipmentType
from app.domain.progression import recalculate_target, recalculate_volume_block

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
    """Подходы блока роли ``block_a`` / ``block_b`` (WORKOUT_DOMAIN_V2 §6): ровно ``work_sets`` рабочих
    подходов (для обеих ролей) на ``target`` роли и ПОСЛЕДНИМ — один явный подход на максимум
    (``is_max_set``, ``target_reps = 0``). OD-3 решён владельцем: подход на максимум включается — это
    замер цикла и единственный вход прогрессии (``advance_step_progression``). Состояние должно быть
    нормализовано."""
    if role not in PROGRESSION_ROLES:
        raise InvalidProgressionStateError(f"unknown progression role {role!r}")
    work_sets = role_work_sets(role, progression_state)
    target = int(progression_state[role]["target"])
    sets = [ProgressionSetPrescription(set_number=i + 1, target_reps=target) for i in range(work_sets)]
    sets.append(ProgressionSetPrescription(set_number=work_sets + 1, target_reps=0, is_max_set=True))
    return tuple(sets)


# --- 2b. Прогрессия курса: только подход на максимум, только вперёд ----------------------------


@dataclass(frozen=True)
class RoleAdvance:
    """Итог шага прогрессии одной роли. ``measured`` — был ли в сессии выполненный подход на
    максимум этой роли; без замера роль не двигается (``target_before == target_after``)."""

    target_before: int
    target_after: int
    equipment_changed: bool
    measured: bool


def _prescribed_working_reps(role_state: Mapping) -> tuple[int, ...]:
    """Рабочие подходы цикла так, как они были ПРЕДПИСАНЫ (``work_sets`` × ``target``), — не как
    выполнены. Формула шага берёт из рабочих подходов среднее (ветка роста) и порог смены снаряда;
    подставляя предписание, а не факт, мы гарантируем, что фактические рабочие подходы прогрессию
    не двигают (решение владельца): при выполнении «по плану» результат тот же, что у прежней формулы."""
    return (int(role_state["target"]),) * int(role_state["work_sets"])


def _max_miss_signal(missed: bool) -> tuple[int, int]:
    """Вход «слабой тренировки» формулы — ``volume < prev_volume`` (объём рабочих подходов). Курс
    подаёт туда ПРОМАХ ЗАМЕРА (подход на максимум ниже цели): (0, 1) — промах, (0, 0) — нет. Счётчик
    ``weak_streak`` роли считает подряд идущие промахи замера, а не просадки объёма."""
    return (0, 1) if missed else (0, 0)


def advance_step_progression(
    progression_state: Mapping, *, max_a: int | None, max_b: int | None,
) -> tuple[dict, RoleAdvance, RoleAdvance]:
    """Шаг прогрессии курса на прямой границе (завершение основной тренировки курса). Решение
    владельца: прогрессию двигает ТОЛЬКО явный подход на максимум; рабочие подходы хранятся и
    показываются, но не меняют состояние.

    ``max_a`` / ``max_b`` — повторения выполненного подхода на максимум этой сессии (``None`` — замера
    роли нет: подход на максимум не выполнен или отсутствует; роль не двигается). Формула — прежняя
    (``recalculate_volume_block`` для блока А, ``recalculate_target`` для блока Б: рост, если
    max > target, на ``max(1, ceil(target·STEP_PCT))``; max = target — держим; откат −1 после
    ``WEAK_STREAK_ROLLBACK_THRESHOLD`` подряд промахов; смена снаряда, иерархия подходов блока А),
    но все её входы выводятся из предписания и замера (``_prescribed_working_reps``,
    ``_max_miss_signal``). Поле ``volume`` состояния больше не вход и не переписывается.

    Только вперёд: функция получает текущее состояние и замер ЭТОЙ сессии; прошлые сессии, их правки
    и уже выданные рецепты она не читает и не пересчитывает. Чистая и детерминированная."""
    state = normalize_progression_state(progression_state)
    block_a, block_b = dict(state[ROLE_BLOCK_A]), dict(state[ROLE_BLOCK_B])
    advance_a = RoleAdvance(block_a["target"], block_a["target"], False, measured=False)
    advance_b = RoleAdvance(block_b["target"], block_b["target"], False, measured=False)

    if max_a is not None:
        target, work_sets = int(block_a["target"]), int(block_a["work_sets"])
        missed = max_a < target
        volume, prev_volume = _max_miss_signal(missed)
        result = recalculate_volume_block(
            target, work_sets, _prescribed_working_reps(block_a), max_a, volume, prev_volume,
            EquipmentType(block_a["equipment_type"]),
            consecutive_weak_before=int(block_a.get("weak_streak") or 0),
            consecutive_stall_before=int(block_a.get("stall_streak") or 0),
        )
        grew = result.new_target > target or result.new_work_sets > work_sets
        block_a.update({
            "target": result.new_target,
            "work_sets": result.new_work_sets,
            "work_sets_growth_reason": (
                result.work_sets_growth_reason.value if result.work_sets_growth_reason is not None else None
            ),
            "weak_streak": int(block_a.get("weak_streak") or 0) + 1 if missed else 0,
            "stall_streak": 0 if grew else int(block_a.get("stall_streak") or 0) + 1,
            "needs_new_equipment": result.equipment_changed,
        })
        advance_a = RoleAdvance(target, result.new_target, result.equipment_changed, measured=True)

    if max_b is not None:
        target = int(block_b["target"])
        missed = max_b < target
        volume, prev_volume = _max_miss_signal(missed)
        result_b = recalculate_target(
            STRENGTH_BLOCK, target, _prescribed_working_reps(block_b), max_b, volume, prev_volume,
            consecutive_weak_before=int(block_b.get("weak_streak") or 0),
        )
        block_b.update({
            "target": result_b.new_target,
            "weak_streak": int(block_b.get("weak_streak") or 0) + 1 if missed else 0,
            "needs_new_equipment": result_b.equipment_changed,
        })
        advance_b = RoleAdvance(target, result_b.new_target, result_b.equipment_changed, measured=True)

    new_state = {
        **state,
        "schema_version": state.get("schema_version", 1),
        ROLE_BLOCK_A: block_a,
        ROLE_BLOCK_B: block_b,
        "workouts_completed_in_set": state.get("workouts_completed_in_set", 0) + 1,
    }
    return new_state, advance_a, advance_b


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
    # False — правило не утверждено владельцем (OD-1 открыт): сохранённый статус-кво.
    decided: bool

    def prescribe(
        self, program_config: Mapping, assessment: AssessmentInput | None, overrides: PrescriptionOverrides,
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
    """Прежнее (до #305) поведение Mini App: цели — ``config.block_a/b.base_target`` (иначе
    ``VOLUME_BLOCK``/``STRENGTH_BLOCK``), снаряд — собственный вес, замер не читается.

    НЕ решение OD-1 (``decided = False``): сохранено без изменений, чтобы подключение продолжало
    работать до решения владельца; провенанс ``program_config_default@0`` помечает такие инклюзии.
    Единственное отличие от старого кода — ``block_b.work_sets`` теперь записывается (D2)."""

    rule_id: str = "program_config_default"
    version: int = 0
    decided: bool = False

    def prescribe(
        self, program_config: Mapping, assessment: AssessmentInput | None, overrides: PrescriptionOverrides,
    ) -> dict:
        del assessment  # статус-кво: замер не читается (OD-1 открыт)
        block_a = (program_config or {}).get(ROLE_BLOCK_A, {})
        block_b = (program_config or {}).get(ROLE_BLOCK_B, {})
        return _step_state(
            target_a=overrides.target_a if overrides.target_a is not None else block_a.get("base_target", VOLUME_BLOCK.base_target),
            target_b=overrides.target_b if overrides.target_b is not None else block_b.get("base_target", STRENGTH_BLOCK.base_target),
            work_sets_a=block_a.get("work_sets", VOLUME_BLOCK.work_sets),
            work_sets_b=block_b.get("work_sets", STRENGTH_BLOCK.work_sets),
            volume_a=overrides.volume_a, volume_b=overrides.volume_b,
        )


_RULES: dict[str, Callable[[], InitialPrescriptionRule]] = {
    "program_config_default@0": ProgramConfigDefaultRule,
}

# Текущее правило стартовой прескрипции. Меняется ТОЛЬКО по записанному решению OD-1 (#310):
# новое правило — новый rule_id/version, старое остаётся в реестре (провенанс прежних инклюзий).
CURRENT_INITIAL_PRESCRIPTION_RULE = "program_config_default@0"


def get_initial_prescription_rule(key: str = CURRENT_INITIAL_PRESCRIPTION_RULE) -> InitialPrescriptionRule:
    return _RULES[key]()


def prescription_provenance(
    rule: InitialPrescriptionRule, *, assessment: AssessmentInput | None, overrides: PrescriptionOverrides,
    state: InclusionAssessmentState, computed_at: datetime,
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
        "assessment": assessment.provenance() if assessment is not None else None,
        "explicit_targets": explicit or None,
        "assessment_state": state.value,
        "computed_at": computed_at.isoformat(),
    }
