"""Журнал и backfill (#282 → #284).

Старая схема (Workout) остаётся источником правды для перенесённой backfill-ом (#163) истории:
Журнал показывает ВСЕ legacy-карточки (с «Изменить»/«Удалить») и скрывает v2-копии, которые
создал backfill (отпечаток — TrainingSessionRepository._backfilled_fingerprint; не зависит от того,
жива ли ещё парная legacy-запись). Здесь — только таблица источника, общая для backfill и тестов."""

from app.domain.multi_program import SessionSource


def resolve_legacy_session_source(*, participates_in_cascade: bool, is_free_entry: bool) -> SessionSource:
    """Источник v2-сессии, в которую backfill переносит legacy Workout (#163/#160): прямое отражение
    participates_in_cascade/is_free_entry. Единственная таблица — её же использует backfill."""
    if participates_in_cascade:
        return SessionSource.PLAN
    if is_free_entry:
        return SessionSource.FREEFORM
    return SessionSource.BACKDATED
