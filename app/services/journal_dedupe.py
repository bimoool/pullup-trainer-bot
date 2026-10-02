"""Журнал (#282): какие legacy Workout уже показаны v2-копией, созданной backfill-ом (#163).

Только чтение: ни одна запись не меняется и не удаляется (display-only). Правило сопоставления —
app.domain.journal_dedupe; отпечаток backfill-сессии —
TrainingSessionRepository.backfilled_session_keys."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.training_sessions import TrainingSessionRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.journal_dedupe import LegacyWorkoutKey, find_backfilled_duplicates


async def list_backfilled_duplicates(session: AsyncSession, user_id: int) -> list[LegacyWorkoutKey]:
    """Legacy-тренировки пользователя, у которых в Журнале уже есть backfill-копия (v2)."""
    sessions = await TrainingSessionRepository(session).backfilled_session_keys(user_id)
    if not sessions:  # не мигрирован (или нет перенесённых записей) — legacy-запрос не нужен
        return []
    workouts = await WorkoutRepository(session).legacy_workout_keys(user_id)
    return find_backfilled_duplicates(workouts, sessions)


async def journal_workout_summary(session: AsyncSession, user_id: int) -> tuple[int, datetime | None]:
    """(число тренировок, момент последней) для сводки Профиля (#277, D2) — display-only.

    Считает legacy Workout И завершённые v2 TrainingSession; legacy-запись, уже перенесённая backfill-ом
    (та же v2-копия, что скрывает Журнал, см. list_backfilled_duplicates), в счёт не входит — иначе
    мигрированный пользователь считался бы дважды. Последняя тренировка — максимум по обеим моделям
    (хронологии не сливаются, прогрессия и готовность не затрагиваются)."""
    sessions_repo = TrainingSessionRepository(session)
    workouts = await WorkoutRepository(session).list_for_user(user_id)
    hidden = len(await list_backfilled_duplicates(session, user_id))
    count = len(workouts) - hidden + await sessions_repo.count_completed(user_id)
    moments = [w.performed_at for w in workouts]
    latest_session = await sessions_repo.latest_completed_performed_at(user_id)
    if latest_session is not None:
        moments.append(latest_session)
    return count, max(moments) if moments else None
