"""Аналитика TrainingSession v2 (REBUILD-1, R3): загрузка ВСЕХ завершённых
сессий пользователя (не через страницы Журнала) и перевод их в вход чистого
домена app.domain.training_analytics."""

from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.timezones import DEFAULT_TIMEZONE
from app.db.repositories.training_sessions import (
    ExerciseCatalogInfo,
    SessionBlockDetail,
    SessionDetail,
    TrainingSessionRepository,
)
from app.domain.activity_types import activity_label
from app.domain.training_analytics import (
    AnalyticsBlock,
    AnalyticsSession,
    AnalyticsSetLog,
    Distribution,
    MetricsSeries,
    TrainingAnalytics,
    compute_distribution,
    compute_metrics_series,
    compute_training_analytics,
)
from app.domain.training_session_v2 import SetStatus, effective_duration_seconds
from app.domain.workout_snapshot import positional_snapshot_items
from app.services.training_session_v2 import block_outcomes


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


def _performed(logs) -> list[AnalyticsSetLog]:
    return [AnalyticsSetLog(value=log.value, unit=log.unit) for log in logs if log.status == SetStatus.PERFORMED.value]


def _block_history(block: SessionBlockDetail, v1_item) -> tuple[str | None, list[AnalyticsSetLog], list[AnalyticsSetLog]]:
    """(protocol_type, set_logs, max_set_logs) блока для истории упражнения (A4) — одинаково для любого
    источника сессии (planned/direct/manual existing/manual custom/копия/сведённая legacy).

    1. Протокол замороженного v1-снимка (Builder-сессии до #307) — как раньше, подходы блока целиком.
    2. Иначе — из выполненного: интервал (результат блока) / рабочие подходы (reps_sets или time_sets по
       единице) + подходы на максимум отдельно (панель max_effort того же упражнения); только максимумы —
       max_effort. Что выполнено, то и история: не выполненные подходы не считаются."""
    if v1_item is not None:
        return v1_item.protocol.type.value, _performed(block.set_logs), []
    if isinstance(block.result, dict) and block.result.get("type") == "interval":
        return "interval", [], []
    outcomes = [o for o in block_outcomes(block) if o.status is SetStatus.PERFORMED and o.actual is not None]
    unit_by_number = {log.set_number: log.unit for log in block.set_logs}
    unit = "s" if any(unit == "s" for unit in unit_by_number.values()) else "reps"
    work = [AnalyticsSetLog(value=o.actual, unit=unit) for o in outcomes if not o.is_max_set]
    maxes = [AnalyticsSetLog(value=o.actual, unit=unit) for o in outcomes if o.is_max_set]
    if work:
        return ("time_sets" if unit == "s" else "reps_sets"), work, maxes
    if maxes:
        return "max_effort", maxes, []
    return None, [], []


def to_analytics_session(
    detail: SessionDetail, catalog: dict[int, ExerciseCatalogInfo] | None = None,
) -> AnalyticsSession:
    """Каноническая сессия -> вход чистого домена. Упражнение блока — analytics_identity (E2), подпись —
    display_name идентичности (E1), категория — самого упражнения (A2/A3 решает домен)."""
    catalog = catalog or {}
    items = positional_snapshot_items(detail.workout_snapshot, len(detail.blocks))
    blocks: list[AnalyticsBlock] = []
    for block, item in zip(detail.blocks, items, strict=True):
        info = catalog.get(block.exercise_id) if block.exercise_id is not None else None
        protocol, set_logs, max_logs = _block_history(block, item)
        blocks.append(AnalyticsBlock(
            exercise_id=info.identity_id if info is not None else block.exercise_id,
            exercise_name=info.label if info is not None else (item.exercise_name if item is not None else None),
            protocol_type=protocol, set_logs=set_logs, max_set_logs=max_logs, result=block.result,
            category=info.category if info is not None else None,
            subcategory=info.subcategory if info is not None else None,
        ))
    return AnalyticsSession(
        performed_at=detail.performed_at,
        # A5: длительность решает ОДНО правило сессии (effective_duration_seconds: сохранённая, у измеренной
        # истории — completed_at − performed_at в окне, unknown — None). completed_at домену не отдаём,
        # чтобы он не «достроил» минуты для unknown второй раз.
        duration_seconds=effective_duration_seconds(
            duration_seconds=detail.duration_seconds, duration_source=detail.duration_source,
            performed_at=detail.performed_at, completed_at=detail.completed_at,
        ),
        activity_type=detail.activity_type, activity_label=activity_label(detail.activity_type),
        blocks=blocks, session_id=detail.id,
    )


class TrainingAnalyticsService:
    def __init__(self, session: AsyncSession) -> None:
        self._sessions = TrainingSessionRepository(session)

    async def build(
        self, *, user_id: int, timezone: str | None, now: datetime, date_from: date, date_to: date,
    ) -> tuple[TrainingAnalytics, MetricsSeries, Distribution, ZoneInfo]:
        tz = resolve_timezone(timezone)
        # canonical_sessions (A1/A6): тот же предикат, что у Журнала и Профиля; копии legacy входят один раз.
        details = await self._sessions.list_all_completed(user_id)
        exercise_ids = {b.exercise_id for d in details for b in d.blocks if b.exercise_id is not None}
        catalog = await self._sessions.exercise_catalog(exercise_ids)
        sessions = [to_analytics_session(d, catalog) for d in details]
        analytics = compute_training_analytics(sessions, now, tz)
        library = await self._sessions.library_categories(user_id)
        return (
            analytics,
            compute_metrics_series(sessions, date_from, date_to, now, tz),
            compute_distribution(sessions, library, date_from, date_to, now, tz),
            tz,
        )
