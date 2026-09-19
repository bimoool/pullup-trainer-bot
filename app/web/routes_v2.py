"""Эндпоинты новой многокурсовой схемы (issue #165, волна 3) — параллельно
app/web/routes.py (старая pull-up-специфичная схема, не трогается), под
префиксом /api/v2, НЕ подключены к текущему UI. Критерий готовности волны:
ничего из webapp-frontend/src не импортирует эти пути — держать инвариантом
(проверяется тестом, см. tests/test_web/test_v2_not_wired_to_ui.py), тем же
принципом, что app/domain/ проверяется на отсутствие aiogram/sqlalchemy
(CLAUDE.md)."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from init_data_py import InitData
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import PlanItem, Program, ProgramInclusion
from app.db.repositories.programs import ProgramRepository
from app.db.repositories.training_plans import TrainingPlanRepository
from app.db.repositories.training_sessions import (
    SessionBlockInput,
    SessionDetail,
    SetLogInput,
    TrainingSessionRepository,
)
from app.db.repositories.users import UserRepository
from app.domain.multi_program import MetricType, SessionSource, WeekPhase
from app.services.program_inclusion import ProgramInclusionRequest, ProgramInclusionService
from app.services.session_log import TrainingSessionLogService
from app.web.auth import get_validated_init_data
from app.web.db import get_session
from app.web.schemas_v2 import (
    BlockProgressionResponse,
    PlanItemCreateRequest,
    PlanItemListResponse,
    PlanItemResponse,
    PlanResponse,
    ProgramInclusionCreateRequest,
    ProgramInclusionResponse,
    ProgramListResponse,
    ProgramResponse,
    SessionBlockInputSchema,
    SessionBlockResponse,
    SessionCreateRequest,
    SessionListResponse,
    SessionProgressionResponse,
    SessionResponse,
    SetLogResponse,
    TrainingPlanResponse,
)

router_v2 = APIRouter(prefix="/api/v2")


async def _require_user(session: AsyncSession, init_data: InitData):
    user = await UserRepository(session).get_by_telegram_id(init_data.user.id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


def _program_response(program: Program, strategy_type_value: str | None) -> ProgramResponse:
    return ProgramResponse(
        id=program.id, name=program.name, goal=program.goal,
        structure_type=program.structure_type.value, category=program.category,
        progression_strategy_type=strategy_type_value,
    )


def _program_inclusion_response(inclusion: ProgramInclusion) -> ProgramInclusionResponse:
    return ProgramInclusionResponse(
        id=inclusion.id, program_id=inclusion.program_id,
        program_name=inclusion.snapshot.get("program_name", ""),
        is_active=inclusion.is_active, started_at=inclusion.started_at, expires_at=inclusion.expires_at,
        snapshot=inclusion.snapshot, progression_state=inclusion.progression_state,
    )


def _plan_item_response(item: PlanItem) -> PlanItemResponse:
    return PlanItemResponse(
        id=item.id, exercise_id=item.exercise_id, complex_id=item.complex_id,
        count_per_week=item.count_per_week, day_of_week=item.day_of_week,
        week_phase=item.week_phase.value if item.week_phase is not None else None,
        program_inclusion_id=item.program_inclusion_id,
    )


def _session_response(
    detail: SessionDetail, *, progression: SessionProgressionResponse | None, skipped_reason: str | None,
) -> SessionResponse:
    return SessionResponse(
        id=detail.id, source=detail.source.value, status=detail.status.value,
        performed_at=detail.performed_at, effort=str(detail.effort) if detail.effort is not None else None,
        comment=detail.comment,
        blocks=[
            SessionBlockResponse(
                order_index=block.order_index, exercise_id=block.exercise_id, complex_id=block.complex_id,
                set_logs=[
                    SetLogResponse(
                        set_number=log.set_number, is_max_set=log.is_max_set, metric_type=log.metric_type.value,
                        value=str(log.value), unit=log.unit,
                        effort=str(log.effort) if log.effort is not None else None, note=log.note,
                    )
                    for log in block.set_logs
                ],
            )
            for block in detail.blocks
        ],
        progression_result=progression, progression_skipped_reason=skipped_reason,
    )


# --- Каталог ---------------------------------------------------------------------------


@router_v2.get("/programs", response_model=ProgramListResponse)
async def list_programs(
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> ProgramListResponse:
    await _require_user(session, init_data)
    programs_repo = ProgramRepository(session)
    programs = await programs_repo.list_all()
    responses = []
    for program in programs:
        strategy_profile = (
            await programs_repo.get_strategy_profile(program.progression_strategy_id)
            if program.progression_strategy_id is not None else None
        )
        strategy_type_value = strategy_profile.strategy_type.value if strategy_profile is not None else None
        responses.append(_program_response(program, strategy_type_value))
    return ProgramListResponse(programs=responses)


# --- План ------------------------------------------------------------------------------


@router_v2.get("/plan", response_model=PlanResponse)
async def get_plan(
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> PlanResponse:
    user = await _require_user(session, init_data)
    plans = TrainingPlanRepository(session)
    plan = await plans.get_for_user(user.id)
    if plan is None:
        return PlanResponse(plan=None)

    inclusions = await plans.list_inclusions(plan.id)
    plan_items = await plans.list_plan_items(plan.id)
    return PlanResponse(
        plan=TrainingPlanResponse(
            id=plan.id, created_at=plan.created_at,
            program_inclusions=[_program_inclusion_response(inclusion) for inclusion in inclusions],
            plan_items=[_plan_item_response(item) for item in plan_items],
        ),
    )


@router_v2.post("/program-inclusions", response_model=ProgramInclusionResponse)
async def create_program_inclusion(
    body: ProgramInclusionCreateRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> ProgramInclusionResponse:
    user = await _require_user(session, init_data)
    inclusion = await ProgramInclusionService(session).create_inclusion(
        user_id=user.id,
        request=ProgramInclusionRequest(
            program_id=body.program_id, initial_target_a=body.initial_target_a,
            initial_target_b=body.initial_target_b, initial_volume_a=body.initial_volume_a,
            initial_volume_b=body.initial_volume_b,
        ),
    )
    if inclusion is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Program not found")
    return _program_inclusion_response(inclusion)


# --- Строки недельной матрицы -----------------------------------------------------------


@router_v2.get("/plan-items", response_model=PlanItemListResponse)
async def list_plan_items(
    program_inclusion_id: int | None = Query(default=None),
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> PlanItemListResponse:
    user = await _require_user(session, init_data)
    plans = TrainingPlanRepository(session)
    plan = await plans.get_for_user(user.id)
    if plan is None:
        return PlanItemListResponse(items=[])
    items = await plans.list_plan_items(plan.id, program_inclusion_id=program_inclusion_id)
    return PlanItemListResponse(items=[_plan_item_response(item) for item in items])


@router_v2.post("/plan-items", response_model=PlanItemResponse)
async def create_plan_item(
    body: PlanItemCreateRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> PlanItemResponse:
    """program_inclusion_id всегда NULL на этом пути — по докстрингу
    PlanItem "добавлено вручную" (app/db/models_program.py). Строки из
    инклюзии заводит только POST /program-inclusions (копирование
    ProgramItem -> PlanItem), не этот эндпоинт."""
    user = await _require_user(session, init_data)
    plans = TrainingPlanRepository(session)
    plan = await plans.get_or_create_for_user(user.id)
    item = await plans.create_plan_item(
        training_plan_id=plan.id, exercise_id=body.exercise_id, complex_id=body.complex_id,
        count_per_week=body.count_per_week, day_of_week=body.day_of_week,
        week_phase=WeekPhase(body.week_phase) if body.week_phase is not None else None,
        program_inclusion_id=None,
    )
    return _plan_item_response(item)


# --- Сессии ------------------------------------------------------------------------------


@router_v2.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> SessionListResponse:
    user = await _require_user(session, init_data)
    details = await TrainingSessionRepository(session).list_for_user(user.id, limit=limit, offset=offset)
    return SessionListResponse(
        sessions=[_session_response(detail, progression=None, skipped_reason=None) for detail in details],
    )


def _block_input(block: SessionBlockInputSchema) -> SessionBlockInput:
    return SessionBlockInput(
        exercise_id=block.exercise_id, complex_id=block.complex_id,
        sets=[
            SetLogInput(
                set_number=s.set_number, metric_type=MetricType(s.metric_type), value=s.value, unit=s.unit,
                is_max_set=s.is_max_set, effort=s.effort, note=s.note,
            )
            for s in block.sets
        ],
    )


@router_v2.post("/sessions", response_model=SessionResponse)
async def create_session(
    body: SessionCreateRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> SessionResponse:
    user = await _require_user(session, init_data)
    result, inclusion_not_found = await TrainingSessionLogService(session).record_session(
        user_id=user.id, source=SessionSource(body.source), performed_at=body.performed_at,
        effort=body.effort, comment=body.comment, blocks=[_block_input(b) for b in body.blocks],
        program_inclusion_id=body.program_inclusion_id,
    )
    if inclusion_not_found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ProgramInclusion not found")

    progression = None
    if result.progression_result is not None:
        progression = SessionProgressionResponse(
            block_a=BlockProgressionResponse(
                target_before=result.progression_result.block_a.target_before,
                target_after=result.progression_result.block_a.target_after,
                equipment_changed=result.progression_result.block_a.equipment_changed,
            ),
            block_b=BlockProgressionResponse(
                target_before=result.progression_result.block_b.target_before,
                target_after=result.progression_result.block_b.target_after,
                equipment_changed=result.progression_result.block_b.equipment_changed,
            ),
        )
    return _session_response(
        result.session, progression=progression, skipped_reason=result.progression_skipped_reason,
    )
