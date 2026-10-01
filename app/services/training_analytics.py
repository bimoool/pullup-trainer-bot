"""Аналитика TrainingSession v2 (REBUILD-1, R3): загрузка ВСЕХ завершённых
сессий пользователя (не через страницы Журнала) и перевод их в вход чистого
домена app.domain.training_analytics."""

from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.timezones import DEFAULT_TIMEZONE
from app.db.repositories.training_sessions import SessionDetail, TrainingSessionRepository
from app.domain.training_analytics import (
    AnalyticsBlock,
    AnalyticsSession,
    AnalyticsSetLog,
    MetricsSeries,
    TrainingAnalytics,
    compute_metrics_series,
    compute_training_analytics,
)
from app.domain.workout_snapshot import positional_snapshot_items


def resolve_timezone(name: str | None) -> ZoneInfo:
    """Часовой пояс пользователя; пустой/невалидный — проектный дефолт
    (app.bot.timezones.DEFAULT_TIMEZONE), не падение."""
    for candidate in (name, DEFAULT_TIMEZONE):
        if not candidate:
            continue
        try:
            return ZoneInfo(candidate)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            continue
    return ZoneInfo("UTC")


def to_analytics_session(detail: SessionDetail) -> AnalyticsSession:
    items = positional_snapshot_items(detail.workout_snapshot, len(detail.blocks))
    return AnalyticsSession(
        performed_at=detail.performed_at,
        completed_at=detail.completed_at,
        blocks=[
            AnalyticsBlock(
                exercise_id=block.exercise_id,
                exercise_name=item.exercise_name if item is not None else None,
                protocol_type=item.protocol.type.value if item is not None else None,
                set_logs=[AnalyticsSetLog(value=log.value, unit=log.unit) for log in block.set_logs],
                result=block.result,
            )
            for block, item in zip(detail.blocks, items, strict=True)
        ],
    )


class TrainingAnalyticsService:
    def __init__(self, session: AsyncSession) -> None:
        self._sessions = TrainingSessionRepository(session)

    async def build(
        self, *, user_id: int, timezone: str | None, now: datetime, date_from: date, date_to: date,
    ) -> tuple[TrainingAnalytics, MetricsSeries, ZoneInfo]:
        tz = resolve_timezone(timezone)
        details = await self._sessions.list_all_completed(user_id)
        sessions = [to_analytics_session(d) for d in details]
        analytics = compute_training_analytics(sessions, now, tz)
        return analytics, compute_metrics_series(sessions, date_from, date_to, now, tz), tz
