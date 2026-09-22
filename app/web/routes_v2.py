"""Эндпоинты новой многокурсовой схемы (issue #165, волна 3) — параллельно
app/web/routes.py (старая pull-up-специфичная схема, не трогается), под
префиксом /api/v2, НЕ подключены к текущему UI. Критерий готовности волны:
ничего из webapp-frontend/src не импортирует эти пути — держать инвариантом
(проверяется тестом, см. tests/test_web/test_v2_not_wired_to_ui.py), тем же
принципом, что app/domain/ проверяется на отсутствие aiogram/sqlalchemy
(CLAUDE.md)."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from init_data_py import InitData
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import (
    Exercise,
    PlanItem,
    PlanWeek,
    Program,
    ProgramInclusion,
    SessionStatus,
)
from app.db.repositories.programs import ProgramRepository
from app.db.repositories.training_plans import TrainingPlanRepository
from app.db.repositories.training_sessions import (
    BatchSetLogInput,
    SessionBlockInput,
    SessionDetail,
    SetLogInput,
    TrainingSessionRepository,
)
from app.db.repositories.users import UserRepository
from app.domain.multi_program import MetricType, SessionSource, WeekPhase
from app.services.live_session import CompleteResult, LiveSessionService
from app.services.plan_week import PlanWeekService
from app.services.program_inclusion import ProgramInclusionRequest, ProgramInclusionService
from app.services.progression_cascade import ProgressionCascadeService
from app.services.session_log import TrainingSessionLogService
from app.web.auth import get_validated_init_data
from app.web.db import get_session
from app.web.schemas_v2 import (
    BlockProgressionResponse,
    ExerciseListResponse,
    ExerciseResponse,
    PlanItemCreateRequest,
    PlanItemListResponse,
    PlanItemResponse,
    PlanResponse,
    PlanWeekResponse,
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
    SetLogInputSchema,
    SetLogResponse,
    TrainingPlanResponse,
)
from app.web.schemas_v2_session import (
    LiveSessionActiveResponse,
    LiveSessionBlockResponse,
    LiveSessionCompleteRequest,
    LiveSessionCompleteResponse,
    LiveSessionPhaseNextRequest,
    LiveSessionPhaseResponse,
    LiveSessionResponse,
    LiveSessionStartRequest,
    LiveSetBatchRequest,
    LiveSetTargetResponse,
    PlanItemDeltaResponse,
    ProgressionPreviewRequest,
    ProgressionPreviewResponse,
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
        program_inclusion_id=item.program_inclusion_id, plan_week_id=item.plan_week_id,
    )


def _plan_week_response(week: PlanWeek) -> PlanWeekResponse:
    return PlanWeekResponse(
        id=week.id, week_number=week.week_number, start_date=week.start_date, phase=week.phase.value,
    )


def _session_response(
    detail: SessionDetail, *, progression: SessionProgressionResponse | None, skipped_reason: str | None,
    title: str | None = None,
) -> SessionResponse:
    return SessionResponse(
        id=detail.id, source=detail.source.value, status=detail.status.value,
        performed_at=detail.performed_at, effort=str(detail.effort) if detail.effort is not None else None,
        comment=detail.comment, title=title,
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


@router_v2.get("/exercises", response_model=ExerciseListResponse)
async def list_exercises(
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> ExerciseListResponse:
    """Checkpoint 3A (issue #196) — минимальная Exercise Library без UI.
    Не требует admin-доступа (обычный пользователь должен пользоваться
    библиотекой). Отдаёт только поля, реально существующие в Exercise
    model — не equipment/difficulty/duration/muscles.

    Product-contract gap, найден живым Playwright-прогоном Checkpoint 3
    (не в исходном issue #196): без фильтра сюда попадали и внутренние
    step-роли программ (subcategory="block_a"/"block_b" — "Подтягивания —
    объём/сила"), позволяя пользователю добавить чужой строительный блок
    программы как самостоятельное упражнение. Исключение — по УЖЕ
    существующей конвенции, не новой эвристике: та же пара значений
    subcategory, которую ProgramRepository.find_step_role_exercises()
    использует для резолва StepProgressionStrategy (подтверждено Кириллом
    в issue #165 как достаточное, без новой колонки). Exercise с
    subcategory=NULL (обычные библиотечные упражнения) — не задет, явный
    OR по IS NULL, потому что NOT IN(...) в SQL сам по себе отбрасывает
    NULL-строки (three-valued logic), не включает их."""
    await _require_user(session, init_data)
    result = await session.execute(
        select(Exercise)
        .where(Exercise.subcategory.is_(None) | Exercise.subcategory.not_in(["block_a", "block_b"]))
        .order_by(Exercise.id),
    )
    exercises = result.scalars().all()
    return ExerciseListResponse(
        exercises=[
            ExerciseResponse(
                id=ex.id,
                name=ex.name,
                metric_type=ex.metric_type.value,
                category=ex.category,
                subcategory=ex.subcategory,
            )
            for ex in exercises
        ],
    )


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

    # Checkpoint 1 (issue #188), раздел "Rollover": единственная точка,
    # где новая календарная неделя должна материализоваться сама, без
    # действия пользователя — "пользователь не может открыть Планы и
    # остаться на прошлой неделе" (Поправка 4). Тонкий вызов, вся логика —
    # в PlanWeekService, идемпотентно на каждый GET.
    await PlanWeekService(session).ensure_current_plan_week(
        training_plan_id=plan.id, today=datetime.now(UTC).date(),
    )

    inclusions = await plans.list_inclusions(plan.id)
    plan_items = await plans.list_plan_items(plan.id)
    plan_weeks = await plans.list_plan_weeks(plan.id)
    return PlanResponse(
        plan=TrainingPlanResponse(
            id=plan.id, created_at=plan.created_at,
            program_inclusions=[_program_inclusion_response(inclusion) for inclusion in inclusions],
            plan_items=[_plan_item_response(item) for item in plan_items],
            plan_weeks=[_plan_week_response(week) for week in plan_weeks],
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
    # Checkpoint 1 (issue #188) — тонкий вызов канонического сервиса, вся
    # логика материализации в PlanWeekService, не здесь (раздел 4 preflight:
    # "не помещать бизнес-логику materialization непосредственно в route").
    await PlanWeekService(session).ensure_current_plan_week(
        training_plan_id=inclusion.training_plan_id, today=datetime.now(UTC).date(),
    )
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

    # Checkpoint 3B (issue #197): ownership-проверка plan_week_id, если передан
    if body.plan_week_id is not None:
        week = await plans.get_plan_week_for_user(body.plan_week_id, user.id)
        if week is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "PlanWeek not found")

    item = await plans.create_plan_item(
        training_plan_id=plan.id, exercise_id=body.exercise_id, complex_id=body.complex_id,
        count_per_week=body.count_per_week, day_of_week=body.day_of_week,
        week_phase=WeekPhase(body.week_phase) if body.week_phase is not None else None,
        program_inclusion_id=None, plan_week_id=body.plan_week_id,
    )
    return _plan_item_response(item)


# --- Сессии ------------------------------------------------------------------------------


async def _resolve_session_titles(
    session: AsyncSession, details: list[SessionDetail], user_id: int,
) -> dict[int, str | None]:
    """Checkpoint 4C (issue #188) — единственное место, где SessionPlanItem
    читается (заполняется с Checkpoint 4A, ранее нигде не читалась).
    Батч на всю страницу — 3 запроса суммарно, не по 3 на сессию:
    SessionPlanItem -> PlanItem -> (ProgramInclusion | Exercise).

    Program-backed: если хотя бы один source PlanItem имеет
    program_inclusion_id — заголовок это ProgramInclusion.program_name
    ("Подтягивания"), не имя отдельного блока ("Блок A"/"Блок Б" никогда
    не должны стать пользовательской карточкой верхнего уровня).
    Manual: все source PlanItem имеют program_inclusion_id=NULL —
    заголовок это имя Exercise (единственного, по факту 4B: одна manual-
    группа = одна TrainingSession).
    Отсутствует совсем — сессия создана мимо create_live_session
    (до Checkpoint 4A) или связанный PlanItem с тех пор удалён — честный
    None, не выдуманное имя."""
    plans = TrainingPlanRepository(session)
    sessions_repo = TrainingSessionRepository(session)

    session_ids = [detail.id for detail in details]
    plan_item_ids_by_session = await sessions_repo.list_plan_item_ids_by_session(session_ids)

    all_plan_item_ids = sorted({pid for ids in plan_item_ids_by_session.values() for pid in ids})
    plan_items = await plans.list_plan_items_by_ids_for_user(all_plan_item_ids, user_id)
    plan_items_by_id = {item.id: item for item in plan_items}

    inclusion_ids = sorted({item.program_inclusion_id for item in plan_items if item.program_inclusion_id is not None})
    inclusions = await plans.list_inclusions_by_ids(inclusion_ids)
    program_name_by_inclusion = {
        inclusion.id: inclusion.snapshot.get("program_name", "") for inclusion in inclusions
    }

    manual_exercise_ids = sorted({
        item.exercise_id for item in plan_items
        if item.program_inclusion_id is None and item.exercise_id is not None
    })
    exercises = await ProgramRepository(session).list_exercises_by_ids(manual_exercise_ids)
    exercise_name_by_id = {exercise.id: exercise.name for exercise in exercises}

    titles: dict[int, str | None] = {}
    for detail in details:
        source_items = [
            plan_items_by_id[pid] for pid in plan_item_ids_by_session.get(detail.id, []) if pid in plan_items_by_id
        ]
        program_backed = next((item for item in source_items if item.program_inclusion_id is not None), None)
        if program_backed is not None:
            titles[detail.id] = program_name_by_inclusion.get(program_backed.program_inclusion_id)
        elif source_items and source_items[0].exercise_id is not None:
            titles[detail.id] = exercise_name_by_id.get(source_items[0].exercise_id)
        else:
            titles[detail.id] = None
    return titles


@router_v2.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status_filter: Literal["started", "completed"] | None = Query(default=None, alias="status"),
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> SessionListResponse:
    """status (Checkpoint 4C) — опциональный фильтр, без параметра ведёт
    себя как раньше (и STARTED, и COMPLETED) — SessionV2Lab.tsx/
    SessionJournalScreen.tsx его не передают, их поведение не меняется."""
    user = await _require_user(session, init_data)
    status_value = SessionStatus(status_filter) if status_filter is not None else None
    details = await TrainingSessionRepository(session).list_for_user(
        user.id, limit=limit, offset=offset, status=status_value,
    )
    titles = await _resolve_session_titles(session, details, user.id)
    return SessionListResponse(
        sessions=[
            _session_response(detail, progression=None, skipped_reason=None, title=titles.get(detail.id))
            for detail in details
        ],
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


# --- Живая (server-driven) сессия -------------------------------------------------------
#
# Раздел 12 docs/plan-and-specs.md буквально называет эти пути "POST
# /sessions", "POST /sessions/{id}/phase/next" и т.д. — БЕЗ "/live". Это
# УЖЕ занято выше: POST /api/v2/sessions (волна 3, issue #165) — другой
# сценарий ("записать целиком уже выполненную тренировку" — источник plan/
# freeform/backdated/elective одним запросом), не сервер-управляемая
# пошаговая сессия из этого раздела. Чтобы не переиспользовать один путь
# для двух разных контрактов (разная форма тела, разный смысл), все новые
# эндпоинты этого раздела живут под /sessions/live — намеренное отклонение
# от буквального текста спеки, не недосмотр.
#
# GET /sessions/live/active объявлен ПЕРВЫМ среди /sessions/live/{id}/...
# роутов — порядок регистрации важен для FastAPI: конкретный литеральный
# путь должен идти раньше параметризованного {session_id}, иначе "active"
# рискует быть склеен как значение session_id (см. план задачи).


def _live_session_response_fields(detail: SessionDetail) -> dict:
    """Построение LiveSessionResponse из SessionDetail. Phase B1 (issue #215):
    добавляет server_time (UTC timestamp генерации) и interval state (только
    для interval workouts, вычисляется на лету из workout_snapshot)."""
    from datetime import UTC, datetime

    from pydantic import TypeAdapter

    from app.domain.interval_timing import compute_interval_timing
    from app.domain.workout_protocol import ProtocolType, ResolvedInterval
    from app.domain.workout_snapshot import WorkoutSnapshot
    from app.web.schemas_v2_session import IntervalStateResponse

    now = datetime.now(UTC)

    # Phase B1: вычисление interval state, если workout_snapshot присутствует
    interval_state: IntervalStateResponse | None = None
    if detail.workout_snapshot is not None:
        try:
            snapshot = TypeAdapter(WorkoutSnapshot).validate_python(detail.workout_snapshot)
            # Ищем первый interval блок (пока поддерживается один interval на сессию)
            for item_snapshot in snapshot.items:
                if item_snapshot.protocol.type == ProtocolType.INTERVAL:
                    protocol = TypeAdapter(ResolvedInterval).validate_python(item_snapshot.protocol.model_dump())
                    timing = compute_interval_timing(
                        performed_at=detail.performed_at, now=now,
                        total_duration_seconds=protocol.total_duration_seconds,
                        work_seconds=protocol.work_seconds, rest_seconds=protocol.rest_seconds,
                    )
                    interval_state = IntervalStateResponse(
                        execution_started_at=timing.execution_started_at,
                        total_end_at=timing.total_end_at,
                        phase=timing.phase.value,
                        phase_ends_at=timing.phase_ends_at,
                        total_duration_seconds=timing.total_duration_seconds,
                        work_seconds=timing.work_seconds,
                        rest_seconds=timing.rest_seconds,
                        completed_cycles=timing.completed_cycles,
                    )
                    break  # только первый interval блок
        except Exception:
            pass  # невалидный snapshot — игнорируем, interval_state остаётся None

    return {
        "id": detail.id, "client_session_id": detail.client_session_id, "status": detail.status.value,
        "phase": LiveSessionPhaseResponse(name=detail.phase_name.value, ends_at=detail.phase_ends_at),
        "phase_index": detail.phase_index, "current_block_index": detail.current_block_index,
        "current_set_number": detail.current_set_number,
        "blocks": [
            LiveSessionBlockResponse(
                order_index=block.order_index, exercise_id=block.exercise_id, complex_id=block.complex_id,
                targets=[
                    LiveSetTargetResponse(
                        set_number=target.set_number, metric_type=target.metric_type.value,
                        value=str(target.value), unit=target.unit,
                    )
                    for target in block.set_targets
                ],
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
        "server_time": now,
        "interval": interval_state,
    }


def _live_session_response(detail: SessionDetail) -> LiveSessionResponse:
    return LiveSessionResponse(**_live_session_response_fields(detail))


def _live_session_complete_response(result: CompleteResult) -> LiveSessionCompleteResponse:
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
    return LiveSessionCompleteResponse(
        **_live_session_response_fields(result.session),
        progression_result=progression, progression_skipped_reason=result.progression_skipped_reason,
    )


@router_v2.post("/sessions/live", response_model=LiveSessionResponse)
async def start_live_session(
    body: LiveSessionStartRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> LiveSessionResponse:
    user = await _require_user(session, init_data)
    result = await LiveSessionService(session).start_session(
        user_id=user.id, client_session_id=body.client_session_id, plan_item_ids=body.plan_item_ids,
    )
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "PlanItem not found")
    return _live_session_response(result.session)


@router_v2.get("/sessions/live/active", response_model=LiveSessionActiveResponse)
async def get_active_live_session(
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> LiveSessionActiveResponse:
    user = await _require_user(session, init_data)
    result = await LiveSessionService(session).get_active(user_id=user.id)
    return LiveSessionActiveResponse(session=_live_session_response(result.session) if result is not None else None)


@router_v2.post("/sessions/live/{session_id}/phase/next", response_model=LiveSessionResponse)
async def advance_live_session_phase(
    session_id: int,
    body: LiveSessionPhaseNextRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> LiveSessionResponse:
    user = await _require_user(session, init_data)
    result = await LiveSessionService(session).advance_phase(
        session_id=session_id, user_id=user.id, expected_phase_index=body.expected_phase_index,
    )
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Live session not found")
    return _live_session_response(result.session)


@router_v2.post("/sessions/live/{session_id}/sets:batch", response_model=LiveSessionResponse)
async def batch_live_session_sets(
    session_id: int,
    body: LiveSetBatchRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> LiveSessionResponse:
    user = await _require_user(session, init_data)
    entries = [
        BatchSetLogInput(
            set_index=entry.set_index, exercise_id=entry.exercise_id, value=entry.value,
            effort=entry.effort, note=entry.note,
        )
        for entry in body.sets
    ]
    try:
        result = await LiveSessionService(session).batch_sets(
            session_id=session_id, user_id=user.id, entries=entries,
        )
    except ValueError as exc:
        # Exercise из батча не найден среди блоков сессии — см. докстринг
        # TrainingSessionRepository.upsert_set_logs_batch: репозиторий сам
        # не знает про HTTPException, роут переводит ValueError в 404.
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Live session not found")
    return _live_session_response(result.session)


@router_v2.post("/sessions/live/{session_id}/complete", response_model=LiveSessionCompleteResponse)
async def complete_live_session(
    session_id: int,
    body: LiveSessionCompleteRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> LiveSessionCompleteResponse:
    user = await _require_user(session, init_data)
    result, not_found = await LiveSessionService(session).complete_session(
        session_id=session_id, user_id=user.id, abandoned=body.abandoned,
    )
    if not_found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Live session not found")
    return _live_session_complete_response(result)


# --- Каскад прогрессии (правка исторической сессии) -------------------------------------


def _set_log_inputs(sets: list[SetLogInputSchema] | None) -> list[SetLogInput] | None:
    if sets is None:
        return None
    return [
        SetLogInput(
            set_number=s.set_number, metric_type=MetricType(s.metric_type), value=s.value, unit=s.unit,
            is_max_set=s.is_max_set, effort=s.effort, note=s.note,
        )
        for s in sets
    ]


def _progression_preview_response(deltas) -> ProgressionPreviewResponse:
    return ProgressionPreviewResponse(
        deltas=[
            PlanItemDeltaResponse(plan_item_id=d.plan_item_id, exercise=d.exercise, before=d.before, after=d.after)
            for d in deltas
        ],
    )


@router_v2.post("/program-inclusions/{inclusion_id}/progression/preview", response_model=ProgressionPreviewResponse)
async def preview_progression_cascade(
    inclusion_id: int,
    body: ProgressionPreviewRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> ProgressionPreviewResponse:
    user = await _require_user(session, init_data)
    deltas, not_applicable = await ProgressionCascadeService(session).preview(
        inclusion_id=inclusion_id, user_id=user.id, edited_session_id=body.edited_session_id,
        edited_block_a_sets=_set_log_inputs(body.block_a), edited_block_b_sets=_set_log_inputs(body.block_b),
    )
    if deltas is None:
        if not_applicable:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "ProgramInclusion is not a step-strategy inclusion",
            )
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ProgramInclusion or session not found")
    return _progression_preview_response(deltas)


@router_v2.post("/program-inclusions/{inclusion_id}/progression/apply", response_model=ProgressionPreviewResponse)
async def apply_progression_cascade(
    inclusion_id: int,
    body: ProgressionPreviewRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> ProgressionPreviewResponse:
    user = await _require_user(session, init_data)
    deltas, not_applicable = await ProgressionCascadeService(session).apply(
        inclusion_id=inclusion_id, user_id=user.id, edited_session_id=body.edited_session_id,
        edited_block_a_sets=_set_log_inputs(body.block_a), edited_block_b_sets=_set_log_inputs(body.block_b),
    )
    if deltas is None:
        if not_applicable:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "ProgramInclusion is not a step-strategy inclusion",
            )
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ProgramInclusion or session not found")
    return _progression_preview_response(deltas)
