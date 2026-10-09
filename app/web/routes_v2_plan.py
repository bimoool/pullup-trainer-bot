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
from app.services.plan_removal import PlanRemovalService
from app.services.plan_spacing import TooEarlyError
from app.services.plan_week import PlanWeekService
from app.web.auth import get_validated_init_data
from app.web.db import get_session
from app.web.schemas_v2 import CustomPlanCreateRequest, CustomPlanListResponse, CustomPlanResponse

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
    session: AsyncSession = Depends(get_session),
) -> CustomPlanListResponse:
    from app.web.routes_v2 import _require_user

    user = await _require_user(session, init_data)
    plans = await TrainingPlanRepository(session).list_custom_plans_for_user(user.id)
    return CustomPlanListResponse(items=[custom_plan_response(plan) for plan in plans])


@router_v2_plan.post("/custom-plans", response_model=CustomPlanResponse)
async def create_custom_plan(
    body: CustomPlanCreateRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> CustomPlanResponse:
    from app.web.routes_v2 import _plan_today, _require_user

    user = await _require_user(session, init_data)
    try:
        validate_custom_plan(
            workout_count=len(body.workout_ids), weeks=body.weeks, preferred_weekdays=body.preferred_weekdays,
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

    custom_plan = await plans.create_custom_plan(CustomPlan(
        user_id=user.id, training_plan_id=plan.id, display_name=body.display_name.strip(),
        start_week_number=start, workouts=list(body.workout_ids), weeks=list(body.weeks),
        repeat=CustomPlanRepeat(body.repeat).value, preferred_weekdays=body.preferred_weekdays, is_active=True,
    ))
    # Недели плана в окне создаются сразу (занятия видны), дальше — сами по мере наступления.
    last_week = min(start + len(body.weeks) - 1, current_number + MAX_FUTURE_PLAN_WEEKS)
    await PlanWeekService(session).ensure_plannable_week(
        training_plan_id=plan.id, week_number=max(last_week, current_number), today=today,
    )
    await session.commit()
    return custom_plan_response(custom_plan)


@router_v2_plan.post("/custom-plans/{custom_plan_id}/deactivate", response_model=CustomPlanResponse)
async def deactivate_custom_plan(
    custom_plan_id: int,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
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
