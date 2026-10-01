"""GET /api/v2/analytics/training (REBUILD-1, R3) — отдельный конвейер
аналитики завершённых TrainingSession. Считается на бэкенде по ВСЕМ сессиям
пользователя, а не выводится из страниц Журнала на фронтенде."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from init_data_py import InitData
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.users import UserRepository
from app.domain.training_analytics import MAX_RANGE_DAYS, ProtocolPanel, TrendPoint
from app.services.training_analytics import TrainingAnalyticsService, resolve_timezone
from app.web.auth import get_validated_init_data
from app.web.db import get_session
from app.web.schemas_v2_analytics import (
    AnalyticsActivityResponse,
    AnalyticsExerciseResponse,
    AnalyticsMetricsResponse,
    AnalyticsMetricWeekResponse,
    AnalyticsPanelResponse,
    AnalyticsPointResponse,
    AnalyticsWeekResponse,
    TrainingAnalyticsResponse,
)

router_v2_analytics = APIRouter(prefix="/api/v2/analytics")


def _dec(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value.quantize(Decimal(1))) if value == value.to_integral_value() else str(value.normalize())


def _point(point: TrendPoint) -> AnalyticsPointResponse:
    return AnalyticsPointResponse(
        at=point.at, value=_dec(point.value), best=_dec(point.best), cumulative_best=_dec(point.cumulative_best),
        is_new_pb=point.is_new_pb, cycles=point.cycles,
    )


def _panel(panel: ProtocolPanel) -> AnalyticsPanelResponse:
    return AnalyticsPanelResponse(
        protocol_type=panel.protocol_type, session_count=panel.session_count, unit=panel.unit,
        total_reps=_dec(panel.total_reps), total_work_seconds=_dec(panel.total_work_seconds),
        set_count=panel.set_count, best_set=_dec(panel.best_set), attempt_count=panel.attempt_count,
        best=_dec(panel.best), actual_duration_seconds=panel.actual_duration_seconds, cycles=panel.cycles,
        points=[_point(p) for p in panel.points], points_total=panel.points_total,
    )


@router_v2_analytics.get("/training", response_model=TrainingAnalyticsResponse)
async def get_training_analytics(
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> TrainingAnalyticsResponse:
    user = await UserRepository(session).get_by_telegram_id(init_data.user.id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    now = datetime.now(UTC)
    # Диапазон по умолчанию — последние 30 локальных дней (пресет "1 мес").
    to_day = date_to if date_to is not None else now.astimezone(resolve_timezone(user.timezone)).date()
    from_day = date_from if date_from is not None else to_day - timedelta(days=29)
    if from_day > to_day or (to_day - from_day).days >= MAX_RANGE_DAYS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid date range")
    analytics, metrics, tz = await TrainingAnalyticsService(session).build(
        user_id=user.id, timezone=user.timezone, now=now, date_from=from_day, date_to=to_day,
    )

    exercises: dict[int, AnalyticsExerciseResponse] = {}
    for panel in analytics.panels:
        entry = exercises.setdefault(
            panel.exercise_id,
            AnalyticsExerciseResponse(exercise_id=panel.exercise_id, exercise_name=panel.exercise_name, panels=[]),
        )
        entry.panels.append(_panel(panel))

    return TrainingAnalyticsResponse(
        timezone=str(tz),
        metrics=AnalyticsMetricsResponse(
            date_from=metrics.date_from, date_to=metrics.date_to,
            weeks=[
                AnalyticsMetricWeekResponse(week_start=w.week_start, workouts=w.workouts, minutes=w.minutes)
                for w in metrics.weeks
            ],
            total_workouts=metrics.total_workouts, total_minutes=metrics.total_minutes,
            without_duration=metrics.without_duration,
        ),
        activity=AnalyticsActivityResponse(
            sessions_last_30_days=analytics.activity.sessions_last_30_days,
            active_days_last_30_days=analytics.activity.active_days_last_30_days,
            weeks=[
                AnalyticsWeekResponse(week_start=w.week_start, sessions=w.sessions, active_days=w.active_days)
                for w in analytics.activity.weeks
            ],
        ),
        exercises=list(exercises.values()),
    )
