from dataclasses import dataclass, replace
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import Program, ProgramInclusion
from app.db.repositories.programs import ProgramRepository, program_items_snapshot
from app.db.repositories.training_plans import TrainingPlanRepository
from app.db.repositories.users import UserRepository
from app.domain.course_prescription import (
    CURRENT_INITIAL_PRESCRIPTION_RULE,
    LEGACY_INITIAL_PRESCRIPTION_RULE,
    AssessmentSource,
    InclusionAssessmentState,
    PrescriptionOverrides,
)
from app.domain.plan_occurrence import InclusionStatus, derive_slots
from app.domain.progression_strategy import ProgressionStrategyType
from app.domain.pullups_v5 import (
    LEGACY_PROGRAM_VERSION,
    PROGRAM_VERSION,
    EntryInputs,
    schedule_snapshot,
)
from app.services.course_assessment import CourseAssessmentService, initial_inclusion_state


@dataclass(frozen=True)
class ProgramInclusionRequest:
    program_id: int
    initial_target_a: int | None = None
    initial_target_b: int | None = None
    initial_volume_a: int = 0
    initial_volume_b: int = 0
    # issue #304 (PROGRAM_PLAN_V2 §2): повторное подключение снятого курса ВОЗОБНОВЛЯЕТ прежнее
    # включение (прогрессия, курсор, история). Начать заново — только явным restart=True.
    restart: bool = False
    # issue #305: версия программы новой инклюзии. None — текущая (V5.6, pullups_v5_6). Устаревшая
    # (pullups_legacy_step) — только явно: program_version или прежние поля initial_target_a/b, которые
    # описывают состояние устаревшей версии. course_inputs — входы V5.6 (§3): R, резины, E1RM, шаг веса…
    program_version: str | None = None
    course_inputs: EntryInputs | None = None


class UnknownProgramVersionError(ValueError):
    pass


def initial_rule_key(request: ProgramInclusionRequest) -> str:
    """Правило стартовой прескрипции новой инклюзии (issue #305)."""
    if request.program_version is None:
        legacy = request.initial_target_a is not None or request.initial_target_b is not None
        return LEGACY_INITIAL_PRESCRIPTION_RULE if legacy else CURRENT_INITIAL_PRESCRIPTION_RULE
    if request.program_version == LEGACY_PROGRAM_VERSION:
        return LEGACY_INITIAL_PRESCRIPTION_RULE
    if request.program_version == PROGRAM_VERSION:
        if request.initial_target_a is not None or request.initial_target_b is not None:
            raise UnknownProgramVersionError("initial_target_a/b относятся к устаревшей версии программы")
        return CURRENT_INITIAL_PRESCRIPTION_RULE
    raise UnknownProgramVersionError(f"Неизвестная версия программы: {request.program_version}")


def _build_snapshot(
    program: Program, program_items: list, step_roles: dict, strategy_type: ProgressionStrategyType | None,
) -> dict:
    """Форма снимка — единственная, см. app.db.repositories.programs
    ::program_items_snapshot (issue #188, checkpoint 1.1 — раньше здесь и
    в scripts/backfill_multi_program.py::seed_catalog были два разных
    формата, второй без program_items вообще)."""
    exercises = [
        {
            "role": role, "exercise_id": exercise.id,
            "name": exercise.name, "metric_type": exercise.metric_type.value,
        }
        for role, exercise in sorted(step_roles.items())
    ]
    return {
        "schema_version": 1,
        "program_name": program.name,
        "structure_type": program.structure_type.value,
        "progression_strategy_type": strategy_type.value if strategy_type is not None else None,
        "config": program.config,
        "exercises": exercises,
        "program_items": program_items_snapshot(program_items),
    }


def _freeze_slots(snapshot: dict, program: Program) -> dict:
    """issue #304: слоты программы замораживаются в снимок при подключении (snapshot immutability) —
    дальнейшая правка каталога не меняет уже подключённым пользователям структуру занятий."""
    slots = derive_slots(snapshot, program_slots=program.slots, program_frequency=program.frequency)
    return {**snapshot, "slots": [slot.to_dict() for slot in slots]}


class ProgramInclusionService:
    """Оркестрация POST /api/v2/program-inclusions (issue #165, волна 3):
    snapshot + копирование ProgramItem -> PlanItem + инициализация
    progression_state. Один сервис — один агрегат (TrainingPlan +
    ProgramInclusion), тот же принцип, что app.services.workout_log для
    старой схемы."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._programs = ProgramRepository(session)
        self._plans = TrainingPlanRepository(session)

    async def create_inclusion(self, *, user_id: int, request: ProgramInclusionRequest) -> ProgramInclusion | None:
        program = await self._programs.get_by_id(request.program_id)
        if program is None:
            return None

        program_items = await self._programs.list_program_items(program.id)
        strategy_profile = (
            await self._programs.get_strategy_profile(program.progression_strategy_id)
            if program.progression_strategy_id is not None else None
        )
        strategy_type = strategy_profile.strategy_type if strategy_profile is not None else None
        step_roles = await self._programs.find_step_role_exercises(category=program.category)
        is_step = strategy_type == ProgressionStrategyType.STEP and bool(
            step_roles.get("block_a") and step_roles.get("block_b"),
        )

        plan = await self._plans.get_or_create_for_user(user_id)
        if not request.restart:
            resumed = await self._resume_previous(plan.id, program.id)
            if resumed is not None:
                return resumed
        snapshot = _freeze_slots(
            _build_snapshot(program, program_items, step_roles if is_step else {}, strategy_type), program,
        )
        # issue #305 (PROGRAM_PLAN_V2 §3): стартовое состояние — чистое версионированное правило
        # (InitialPrescriptionRule) от замера; провенанс (правило, версия, замер) — на инклюзии. Замер
        # обязателен и его нет, а основных тренировок у пользователя не было → awaiting_assessment.
        status = InclusionStatus.ACTIVE
        provenance = None
        baseline_result_id = None
        rule_key = initial_rule_key(request)
        if is_step and rule_key == CURRENT_INITIAL_PRESCRIPTION_RULE:
            # issue #305 (V5.6 §1): две основные тренировки в неделю — только для новой инклюзии V5.6,
            # замораживается в её снимок. Каталог (programs.frequency) и снимки устаревших инклюзий не меняются.
            snapshot = schedule_snapshot(snapshot)
        if is_step:
            now = datetime.now(UTC)
            evaluation = await CourseAssessmentService(self._session).evaluate(user_id=user_id, program=program, now=now)
            overrides = PrescriptionOverrides(
                target_a=request.initial_target_a, target_b=request.initial_target_b,
                volume_a=request.initial_volume_a, volume_b=request.initial_volume_b,
            )
            inputs = None
            if rule_key == CURRENT_INITIAL_PRESCRIPTION_RULE:
                # BW — из профиля (V5.6 §8.5: масса тела обновляется раз в неделю), если не передана явно.
                inputs = request.course_inputs or EntryInputs()
                user = await UserRepository(self._session).get_by_id(user_id)
                if inputs.body_mass_kg is None and user is not None and user.weight_kg is not None:
                    inputs = replace(inputs, body_mass_kg=user.weight_kg)
            progression_state, provenance = initial_inclusion_state(
                program, evaluation, overrides, now=now, rule_key=rule_key, inputs=inputs,
            )
            if evaluation.state == InclusionAssessmentState.AWAITING_ASSESSMENT:
                status = InclusionStatus.AWAITING_ASSESSMENT
            if evaluation.assessment is not None and evaluation.assessment.source == AssessmentSource.ASSESSMENT_RESULT:
                baseline_result_id = evaluation.assessment.id
        else:
            progression_state = {}

        inclusion = await self._plans.create_inclusion(
            training_plan_id=plan.id, program_id=program.id, snapshot=snapshot, progression_state=progression_state,
        )
        inclusion.status = status.value
        inclusion.prescription_provenance = provenance
        inclusion.baseline_assessment_result_id = baseline_result_id
        # Занятия (одна строка = одно занятие) материализует converge_user_plan — вызывающий роут
        # зовёт PlanWeekService.ensure_current_plan_week сразу после подключения. Агрегатные строки
        # ProgramItem → PlanItem (count_per_week) больше не пишутся.
        return inclusion

    async def _resume_previous(self, training_plan_id: int, program_id: int) -> ProgramInclusion | None:
        """Снятый (is_active = false) курс той же программы возобновляется, если активного нет:
        progression_state, sequence_cursor, started_at и история сохраняются (исправление DV-05)."""
        inclusions = [i for i in await self._plans.list_inclusions(training_plan_id) if i.program_id == program_id]
        if any(inclusion.is_active for inclusion in inclusions) or not inclusions:
            return None
        previous = inclusions[-1]
        previous.is_active = True
        # issue #305: возобновление не возвращает на замер и не снимает ожидание замера само —
        # awaiting_assessment → active делает только promote_if_assessed (convergence / старт).
        if previous.status != InclusionStatus.AWAITING_ASSESSMENT.value:
            previous.status = InclusionStatus.ACTIVE.value
        previous.expires_at = None
        await self._session.flush()
        return previous
