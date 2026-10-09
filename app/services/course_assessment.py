"""Ворота замера курса и стартовая прескрипция (issue #305, PROGRAM_PLAN_V2 §3, MIGRATION_V2 §5.4).

Один код для подключения курса, convergence и старта main-занятия:

* ``CourseAssessmentService.evaluate`` — валидный замер (assessment_results протокола программы ИЛИ
  замер онбординга ``baselines`` — тот же «максимум подтягиваний»), история основных тренировок
  (legacy ``workouts`` + нативные main-сессии, тот же источник, что K1) и итоговое состояние;
* ``promote_if_assessed`` — ЕДИНСТВЕННЫЙ переход ``awaiting_assessment → active``. Обратного перехода
  нет нигде: активная инклюзия на замер не возвращается (aged-пользователи с историей — никогда).
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import Program, ProgramInclusion
from app.db.repositories.assessments import AssessmentRepository
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.training_plans import TrainingPlanRepository
from app.db.repositories.users import UserRepository
from app.domain.course_prescription import (
    AssessmentInput,
    AssessmentRequirement,
    AssessmentSource,
    InclusionAssessmentState,
    PrescriptionOverrides,
    get_initial_prescription_rule,
    initial_assessment_state,
    latest_valid_assessment,
    prescription_provenance,
)
from app.domain.plan_occurrence import InclusionStatus
from app.services.plan_spacing import MainSpacingService
from app.services.training_analytics import resolve_timezone


class AssessmentRequiredError(Exception):
    """Старт main-занятия инклюзии в awaiting_assessment — роут → 409 {code: assessment_required}."""

    def __init__(self, inclusion_id: int, protocol_id: int | None) -> None:
        super().__init__(f"assessment_required: inclusion={inclusion_id}")
        self.inclusion_id = inclusion_id
        self.protocol_id = protocol_id


@dataclass(frozen=True)
class AssessmentEvaluation:
    requirement: AssessmentRequirement | None
    assessment: AssessmentInput | None
    has_main_history: bool
    state: InclusionAssessmentState


class CourseAssessmentService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def evaluate(self, *, user_id: int, program: Program | None, now: datetime) -> AssessmentEvaluation:
        requirement = AssessmentRequirement.from_config(program.assessment if program is not None else None)
        user = await UserRepository(self._session).get_by_id(user_id)
        tz = resolve_timezone(user.timezone if user is not None else None)
        today = now.astimezone(tz).date()

        candidates: list[AssessmentInput] = []
        if requirement is not None and requirement.protocol_id is not None:
            for result in await AssessmentRepository(self._session).list_results_for_user(
                user_id, requirement.protocol_id,
            ):
                candidates.append(AssessmentInput(
                    source=AssessmentSource.ASSESSMENT_RESULT, id=result.id, max_reps=int(result.value),
                    performed_on=result.performed_at.astimezone(tz).date(),
                ))
        for baseline in await BaselineRepository(self._session).list_for_user(user_id):
            candidates.append(AssessmentInput(
                source=AssessmentSource.BASELINE, id=baseline.id, max_reps=int(baseline.reps),
                performed_on=baseline.performed_at.astimezone(tz).date(),
            ))
        assessment = latest_valid_assessment(
            candidates, today=today, validity_days=requirement.validity_days if requirement else None,
        )
        has_history = await MainSpacingService(self._session).last_main_start_at(user_id) is not None
        state = initial_assessment_state(requirement, assessment=assessment, has_main_history=has_history)
        return AssessmentEvaluation(
            requirement=requirement, assessment=assessment, has_main_history=has_history, state=state,
        )


def initial_inclusion_state(
    program: Program, evaluation: AssessmentEvaluation, overrides: PrescriptionOverrides, *, now: datetime,
) -> tuple[dict, dict]:
    """(progression_state, prescription_provenance) нового STEP-включения по текущему правилу."""
    rule = get_initial_prescription_rule()
    state = rule.prescribe(program.config or {}, evaluation.assessment, overrides)
    provenance = prescription_provenance(
        rule, assessment=evaluation.assessment, overrides=overrides, state=evaluation.state, computed_at=now,
    )
    return state, provenance


def _overrides_from_provenance(provenance: dict | None) -> PrescriptionOverrides:
    explicit = (provenance or {}).get("explicit_targets") or {}
    return PrescriptionOverrides(target_a=explicit.get("target_a"), target_b=explicit.get("target_b"))


async def promote_if_assessed(
    session: AsyncSession, inclusion: ProgramInclusion, program: Program | None, *, now: datetime | None = None,
) -> bool:
    """awaiting_assessment → active, когда появился валидный замер (или история основных тренировок).
    Стартовое состояние пересчитывается тем же правилом уже С замером (у awaiting-инклюзии основных
    тренировок нет по построению — терять нечего); запись только при отличии. Идемпотентно: у не-awaiting
    инклюзии ничего не делает. True — инклюзия переведена."""
    if inclusion.status != InclusionStatus.AWAITING_ASSESSMENT.value or program is None:
        return False
    now = now or datetime.now(UTC)
    plan_user_id = await _inclusion_user_id(session, inclusion)
    evaluation = await CourseAssessmentService(session).evaluate(user_id=plan_user_id, program=program, now=now)
    if evaluation.state != InclusionAssessmentState.ACTIVE:
        return False
    overrides = _overrides_from_provenance(inclusion.prescription_provenance)
    state, provenance = initial_inclusion_state(program, evaluation, overrides, now=now)
    if state != inclusion.progression_state:
        inclusion.progression_state = state
        inclusion.initial_progression_state = state
    inclusion.prescription_provenance = provenance
    if evaluation.assessment is not None and evaluation.assessment.source == AssessmentSource.ASSESSMENT_RESULT:
        inclusion.baseline_assessment_result_id = evaluation.assessment.id
    inclusion.status = InclusionStatus.ACTIVE.value
    await session.flush()
    return True


async def _inclusion_user_id(session: AsyncSession, inclusion: ProgramInclusion) -> int:
    plan = await TrainingPlanRepository(session).get_by_id(inclusion.training_plan_id)
    return plan.user_id
