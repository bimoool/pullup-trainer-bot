from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import Program, ProgramInclusion
from app.db.repositories.programs import ProgramRepository, program_items_snapshot
from app.db.repositories.training_plans import TrainingPlanRepository
from app.domain.constants import STRENGTH_BLOCK, VOLUME_BLOCK, EquipmentType
from app.domain.plan_occurrence import InclusionStatus, derive_slots
from app.domain.progression_strategy import ProgressionStrategyType


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


def _build_initial_progression_state(
    program: Program, request: ProgramInclusionRequest, is_step: bool,
) -> dict:
    """Форма — та же, что app.db.repositories.workouts.NextBlockState/
    scripts/backfill_multi_program.py::_build_progression_state отдают для
    старой схемы (issue #165, план п.2 подтверждён Кириллом): GET
    /api/v2/plan не должен видеть два разных формата progression_state в
    зависимости от того, откуда взялась инклюзия. Без замера/интеграции с
    AssessmentResult в этой волне (открытый вопрос плана, согласовано
    Кириллом как "ок для этой волны") — старт либо с явно переданных
    initial_target_a/b, либо с config.block_a/b.base_target, как у нового
    пользователя без замера."""
    if not is_step:
        return {}

    config = program.config or {}
    block_a_config = config.get("block_a", {})
    block_b_config = config.get("block_b", {})
    target_a = request.initial_target_a if request.initial_target_a is not None else (
        block_a_config.get("base_target", VOLUME_BLOCK.base_target)
    )
    target_b = request.initial_target_b if request.initial_target_b is not None else (
        block_b_config.get("base_target", STRENGTH_BLOCK.base_target)
    )
    work_sets_a = block_a_config.get("work_sets", VOLUME_BLOCK.work_sets)

    return {
        "schema_version": 1,
        "strategy_type": ProgressionStrategyType.STEP.value,
        "block_a": {
            "target": target_a,
            "volume": request.initial_volume_a,
            "work_sets": work_sets_a,
            "work_sets_growth_reason": None,
            "weak_streak": 0,
            "stall_streak": 0,
            "equipment_type": EquipmentType.BODYWEIGHT.value,
            "equipment_value": None,
            "equipment_item_id": None,
            "needs_new_equipment": False,
        },
        "block_b": {
            "target": target_b,
            "volume": request.initial_volume_b,
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
        progression_state = _build_initial_progression_state(program, request, is_step)

        inclusion = await self._plans.create_inclusion(
            training_plan_id=plan.id, program_id=program.id, snapshot=snapshot, progression_state=progression_state,
        )
        inclusion.status = InclusionStatus.ACTIVE.value
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
        previous.status = InclusionStatus.ACTIVE.value
        previous.expires_at = None
        await self._session.flush()
        return previous
