"""Журнал (#282): какие legacy Workout уже показаны v2-копией, созданной backfill-ом (#163).

Только чтение: ни одна запись не меняется и не удаляется (display-only). Правило сопоставления —
app.domain.journal_dedupe; отпечаток backfill-сессии —
TrainingSessionRepository.backfilled_session_keys."""

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
