"""Свой план с объёмом по неделям (issue #304, PROGRAM_PLAN_V2 §7) + общие помощники плана v2.

POST /api/v2/custom-plans — ротация тренировок + ИСТИННЫЙ объём недель (W1=2, W2=2, W3=0 …; 0 —
явная пустая неделя), необязательная подсказка дней недели (не объём). Занятия материализует
единственная converge_user_plan (окно «текущая .. +4»; дальние недели — по мере наступления).
Тренировки — свои или готовые системные (та же проверка, что «Добавить в план»: чужое/архивное/
несуществующее неразличимо → 404, PROJECT_SPEC §5)."""

from fastapi import APIRouter, Depends, HTTPException, status
from init_data_py import InitData
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import CustomPlan
from app.db.repositories.programs import ProgramRepository
from app.db.repositories.training_plans import TrainingPlanRepository
from app.domain.multi_program import (
    MAX_FUTURE_PLAN_WEEKS,
    is_plannable_week_number,
    plan_week_number,
)
from app.domain.plan_occurrence import CustomPlanError, CustomPlanRepeat, validate_custom_plan
from app.domain.plan_spec import DEFAULT_PHASE, PlanSpec, PlanSpecError, validate_matrix
from app.services.custom_plan_editor import (
    CustomPlanEditorService,
    EditorError,
    EditorResult,
    editor_view,
    schedule_view,
)
from app.services.plan_removal import PlanRemovalService
from app.services.plan_spacing import TooEarlyError
from app.services.plan_week import PlanWeekService
from app.web.auth import get_validated_init_data
from app.web.db import get_session
from app.web.schemas_v2 import (
    CustomPlanCreateRequest,
    CustomPlanEditorResponse,
    CustomPlanListResponse,
    CustomPlanResponse,
    EditorAddWorkoutRequest,
    EditorInsertWeekRequest,
    EditorPhaseRequest,
    EditorQuantitiesRequest,
    SchedulePlaceRequest,
    WeekScheduleResponse,
)

router_v2_plan = APIRouter(prefix="/api/v2")


def too_early_http_error(exc: TooEarlyError) -> HTTPException:
    """K1 / LIVE §7: старт MAIN раньше available_from — 409 с машинным кодом и датой."""
    return HTTPException(
        status.HTTP_409_CONFLICT,
        {
            "code": "too_early", "available_from": exc.available_from.isoformat(),
            "message": f"Нужно два полных дня отдыха — основная тренировка доступна с {exc.available_from:%d.%m}.",
        },
    )


def custom_plan_response(custom_plan: CustomPlan) -> CustomPlanResponse:
    return CustomPlanResponse(
        id=custom_plan.id, display_name=custom_plan.display_name, start_week_number=custom_plan.start_week_number,
        workout_ids=list(custom_plan.workouts), weeks=list(custom_plan.weeks), repeat=custom_plan.repeat,
        preferred_weekdays=list(custom_plan.preferred_weekdays) if custom_plan.preferred_weekdays is not None else None,
        is_active=custom_plan.is_active,
    )


@router_v2_plan.get("/custom-plans", response_model=CustomPlanListResponse)
async def list_custom_plans(
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> CustomPlanListResponse:
    from app.web.routes_v2 import _require_user

    user = await _require_user(session, init_data)
    plans = await TrainingPlanRepository(session).list_custom_plans_for_user(user.id)
    return CustomPlanListResponse(items=[custom_plan_response(plan) for plan in plans])


@router_v2_plan.post("/custom-plans", response_model=CustomPlanResponse)
async def create_custom_plan(
    body: CustomPlanCreateRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> CustomPlanResponse:
    from app.web.routes_v2 import _plan_today, _require_premium_feature, _require_user

    user = await _require_user(session, init_data)
    # Решение 2026-10-17: свой план — Premium (остановка своего плана — нет, deactivate ниже не гейтится).
    _require_premium_feature(user)
    spec: PlanSpec | None = None
    weeks = list(body.weeks)
    if body.quantities is not None:
        # UX-EDITOR: матрица [тренировка][неделя]; weeks выводится как недельные суммы.
        phases = list(body.phases) if body.phases is not None else None
        if len(set(body.workout_ids)) != len(body.workout_ids):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Тренировки в плане не должны повторяться")
        width = len(body.quantities[0]) if body.quantities else 0
        phases = phases if phases is not None else [DEFAULT_PHASE] * width
        try:
            validate_matrix(body.quantities, phases, len(body.workout_ids))
        except PlanSpecError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.message) from exc
        spec = PlanSpec(
            tuple(body.workout_ids), tuple(tuple(row) for row in body.quantities), tuple(phases),
            CustomPlanRepeat(body.repeat),
        )
        weeks = spec.totals()
    try:
        validate_custom_plan(
            workout_count=len(body.workout_ids), weeks=weeks, preferred_weekdays=body.preferred_weekdays,
        )
    except CustomPlanError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    programs = ProgramRepository(session)
    for workout_id in body.workout_ids:
        if await programs.get_publicly_attachable_workout_for_user(workout_id, user.id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Workout not found")

    plans = TrainingPlanRepository(session)
    plan = await plans.get_or_create_for_user(user.id)
    today = _plan_today(user)
    current_number = plan_week_number(plan.created_at.date(), today)
    start = body.start_week_number if body.start_week_number is not None else current_number
    if not is_plannable_week_number(start, current_number):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Неделя недоступна для планирования")

    if body.replace_custom_plan_id is not None:
        # Все проверки выше пройдены; остановка и создание — в одной транзакции (коммит ниже, откат при ошибке).
        stopped = await PlanRemovalService(session).deactivate_custom_plan(
            user_id=user.id, custom_plan_id=body.replace_custom_plan_id, today=today,
        )
        if stopped is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Custom plan not found")

    custom_plan = await plans.create_custom_plan(CustomPlan(
        user_id=user.id, training_plan_id=plan.id, display_name=body.display_name.strip(),
        start_week_number=start, workouts=list(body.workout_ids), weeks=weeks,
        repeat=CustomPlanRepeat(body.repeat).value, preferred_weekdays=body.preferred_weekdays, is_active=True,
        spec=spec.to_json() if spec is not None else None,
    ))
    # Недели плана в окне создаются сразу (занятия видны), дальше — сами по мере наступления.
    last_week = min(start + len(weeks) - 1, current_number + MAX_FUTURE_PLAN_WEEKS)
    await PlanWeekService(session).ensure_plannable_week(
        training_plan_id=plan.id, week_number=max(last_week, current_number), today=today,
    )
    await session.commit()
    return custom_plan_response(custom_plan)


@router_v2_plan.post("/custom-plans/{custom_plan_id}/deactivate", response_model=CustomPlanResponse)
async def deactivate_custom_plan(
    custom_plan_id: int,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> CustomPlanResponse:
    """«Остановить план» (#304 B3): is_active = false, новые занятия не материализуются; незасчитанные
    занятия текущей/будущих недель снимаются мягко; засчитанные и история — без изменений. Повтор —
    без побочных эффектов. Чужой / несуществующий — 404. Подписку и доступ не трогает."""
    from app.web.routes_v2 import _plan_today, _require_user

    user = await _require_user(session, init_data)
    result = await PlanRemovalService(session).deactivate_custom_plan(
        user_id=user.id, custom_plan_id=custom_plan_id, today=_plan_today(user),
    )
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Custom plan not found")
    await session.commit()
    return custom_plan_response(result.custom_plan)


# --- UX-EDITOR: редактор своего плана и расписание недели (contract §3) -----------------------------------


def _editor_http_error(exc: EditorError) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": exc.code, "message": exc.message, **exc.extra},
    )


def _editor_response(result: EditorResult) -> CustomPlanEditorResponse:
    return CustomPlanEditorResponse(**editor_view(result.ctx), removed_sessions=result.removed_sessions)


async def _editor_ctx(session: AsyncSession, init_data: InitData, custom_plan_id: int, *, lock: bool, premium: bool):
    from app.web.routes_v2 import _plan_today, _require_premium_feature, _require_user

    user = await _require_user(session, init_data)
    if premium:
        _require_premium_feature(user)
    service = CustomPlanEditorService(session)
    ctx = await service.load(user_id=user.id, custom_plan_id=custom_plan_id, today=_plan_today(user), lock=lock)
    if ctx is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Custom plan not found")
    return user, service, ctx


@router_v2_plan.get("/custom-plans/{custom_plan_id}/editor", response_model=CustomPlanEditorResponse)
async def get_custom_plan_editor(
    custom_plan_id: int,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> CustomPlanEditorResponse:
    _, _, ctx = await _editor_ctx(session, init_data, custom_plan_id, lock=False, premium=False)
    return CustomPlanEditorResponse(**editor_view(ctx))


@router_v2_plan.patch("/custom-plans/{custom_plan_id}/weeks/{index}/quantities", response_model=CustomPlanEditorResponse)
async def set_week_quantities(
    custom_plan_id: int, index: int, body: EditorQuantitiesRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> CustomPlanEditorResponse:
    _, service, ctx = await _editor_ctx(session, init_data, custom_plan_id, lock=True, premium=True)
    try:
        quantities = {int(key): int(value) for key, value in body.quantities.items()}
        result = await service.set_quantities(ctx, index, quantities)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Некорректные количества") from exc
    except EditorError as exc:
        raise _editor_http_error(exc) from exc
    await session.commit()
    return _editor_response(result)


@router_v2_plan.patch("/custom-plans/{custom_plan_id}/weeks/{index}", response_model=CustomPlanEditorResponse)
async def set_week_phase(
    custom_plan_id: int, index: int, body: EditorPhaseRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> CustomPlanEditorResponse:
    _, service, ctx = await _editor_ctx(session, init_data, custom_plan_id, lock=True, premium=True)
    try:
        result = await service.set_phase(ctx, index, body.phase)
    except EditorError as exc:
        raise _editor_http_error(exc) from exc
    await session.commit()
    return _editor_response(result)


@router_v2_plan.post("/custom-plans/{custom_plan_id}/weeks", response_model=CustomPlanEditorResponse)
async def insert_plan_week(
    custom_plan_id: int, body: EditorInsertWeekRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> CustomPlanEditorResponse:
    _, service, ctx = await _editor_ctx(session, init_data, custom_plan_id, lock=True, premium=True)
    try:
        result = await service.insert_week(ctx, body.after_index)
    except EditorError as exc:
        raise _editor_http_error(exc) from exc
    await session.commit()
    return _editor_response(result)


@router_v2_plan.delete("/custom-plans/{custom_plan_id}/weeks/{index}", response_model=CustomPlanEditorResponse)
async def delete_plan_week(
    custom_plan_id: int, index: int,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> CustomPlanEditorResponse:
    _, service, ctx = await _editor_ctx(session, init_data, custom_plan_id, lock=True, premium=False)
    try:
        result = await service.delete_week(ctx, index)
    except EditorError as exc:
        raise _editor_http_error(exc) from exc
    await session.commit()
    return _editor_response(result)


@router_v2_plan.post("/custom-plans/{custom_plan_id}/workouts", response_model=CustomPlanEditorResponse)
async def add_plan_workout(
    custom_plan_id: int, body: EditorAddWorkoutRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> CustomPlanEditorResponse:
    user, service, ctx = await _editor_ctx(session, init_data, custom_plan_id, lock=True, premium=True)
    if await ProgramRepository(session).get_publicly_attachable_workout_for_user(body.workout_id, user.id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workout not found")
    try:
        result = await service.add_workout(ctx, body.workout_id)
    except EditorError as exc:
        raise _editor_http_error(exc) from exc
    await session.commit()
    return _editor_response(result)


@router_v2_plan.delete("/custom-plans/{custom_plan_id}/workouts/{workout_id}", response_model=CustomPlanEditorResponse)
async def remove_plan_workout(
    custom_plan_id: int, workout_id: int,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> CustomPlanEditorResponse:
    _, service, ctx = await _editor_ctx(session, init_data, custom_plan_id, lock=True, premium=False)
    try:
        result = await service.remove_workout(ctx, workout_id)
    except EditorError as exc:
        raise _editor_http_error(exc) from exc
    await session.commit()
    return _editor_response(result)


@router_v2_plan.get("/custom-plans/{custom_plan_id}/weeks/{index}/schedule", response_model=WeekScheduleResponse)
async def get_week_schedule(
    custom_plan_id: int, index: int,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> WeekScheduleResponse:
    _, _, ctx = await _editor_ctx(session, init_data, custom_plan_id, lock=False, premium=False)
    view = schedule_view(ctx, index)
    if view is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Week not found")
    return WeekScheduleResponse(**view)


async def _place(
    custom_plan_id: int, index: int, body: SchedulePlaceRequest, init_data: InitData, session: AsyncSession,
    *, unplace: bool,
) -> WeekScheduleResponse:
    user, service, ctx = await _editor_ctx(session, init_data, custom_plan_id, lock=True, premium=False)
    if schedule_view(ctx, index) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Week not found")
    try:
        new_ctx = await service.place(ctx, index, body.workout_id, body.day_of_week, user_id=user.id, unplace=unplace)
    except EditorError as exc:
        raise _editor_http_error(exc) from exc
    await session.commit()
    return WeekScheduleResponse(**schedule_view(new_ctx, index))


@router_v2_plan.post("/custom-plans/{custom_plan_id}/weeks/{index}/place", response_model=WeekScheduleResponse)
async def place_workout_on_day(
    custom_plan_id: int, index: int, body: SchedulePlaceRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> WeekScheduleResponse:
    return await _place(custom_plan_id, index, body, init_data, session, unplace=False)


@router_v2_plan.post("/custom-plans/{custom_plan_id}/weeks/{index}/unplace", response_model=WeekScheduleResponse)
async def unplace_workout_from_day(
    custom_plan_id: int, index: int, body: SchedulePlaceRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> WeekScheduleResponse:
    return await _place(custom_plan_id, index, body, init_data, session, unplace=True)
