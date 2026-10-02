"""Display-only дедупликация Журнала (#282): legacy Workout, уже перенесённая backfill-ом
(scripts/backfill_multi_program.py, #163) в v2 TrainingSession, не показывается второй раз.

Чистая логика: без sqlalchemy/aiogram. Какие именно TrainingSession считаются «созданными backfill-ом»
(отпечаток), решает репозиторий (TrainingSessionRepository.backfilled_session_keys); здесь —
отображение legacy -> source и сопоставление.

Правило сопоставления (детерминированное, один-к-одному):
  legacy Workout W скрыта, если у того же пользователя есть ещё не «занятая» backfill-сессия S с
    S.performed_at == W.performed_at (точное равенство момента) и
    S.source == resolve_legacy_session_source(W)  (та же таблица, что в backfill).
  Сессия «занимается» одной legacy-записью: две legacy на один момент при одной v2-копии скроют
  только одну (вторая остаётся видна — лучше дубль, чем потеря записи)."""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from app.domain.multi_program import SessionSource


def resolve_legacy_session_source(*, participates_in_cascade: bool, is_free_entry: bool) -> SessionSource:
    """Источник v2-сессии, в которую backfill переносит legacy Workout (#163/#160): прямое отражение
    participates_in_cascade/is_free_entry. Единственная таблица — её же использует backfill."""
    if participates_in_cascade:
        return SessionSource.PLAN
    if is_free_entry:
        return SessionSource.FREEFORM
    return SessionSource.BACKDATED


@dataclass(frozen=True)
class LegacyWorkoutKey:
    workout_id: int
    performed_at: datetime
    source: SessionSource


def find_backfilled_duplicates(
    workouts: Iterable[LegacyWorkoutKey], backfilled_sessions: Iterable[tuple[datetime, SessionSource]],
) -> list[LegacyWorkoutKey]:
    """Legacy-записи, у которых есть backfill-копия (см. правило в докстринге модуля). Порядок
    обработки — по (performed_at, workout_id), поэтому результат детерминирован."""
    available = Counter(backfilled_sessions)
    duplicates: list[LegacyWorkoutKey] = []
    for workout in sorted(workouts, key=lambda w: (w.performed_at, w.workout_id)):
        slot = (workout.performed_at, workout.source)
        if available[slot] > 0:
            available[slot] -= 1
            duplicates.append(workout)
    return duplicates
