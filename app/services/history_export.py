"""Экспорт истории тренировок в CSV (Crimpd "Export Log Data"). Только данные
вызывающего пользователя: завершённые v2-сессии (одна строка на подход) и
legacy-тренировки (колонка source). UTF-8 с BOM — для Excel."""

import csv
import hashlib
import hmac
import io
import time
from collections.abc import Iterator
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.training_sessions import SessionDetail, TrainingSessionRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.electives import format_elective_set_note
from app.domain.multi_program import SessionSource
from app.domain.workout_snapshot import positional_snapshot_items
from app.services.training_analytics import resolve_timezone

BOM = "﻿"
HEADER = [
    "source", "date", "workout", "exercise", "protocol", "set_number", "value", "unit",
    "effort", "note", "session_effort", "session_comment",
]
LINK_TTL_SECONDS = 300
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _text(value: str | None) -> str:
    """Защита от CSV-инъекции формул: ячейка с = + - @ в начале получает апостроф."""
    if not value:
        return ""
    return "'" + value if value.startswith(_FORMULA_PREFIXES) else value


def _num(value: Decimal | None) -> str:
    if value is None:
        return ""
    return str(value.quantize(Decimal(1))) if value == value.to_integral_value() else str(value.normalize())


def _v2_rows(detail: SessionDetail, names: dict[int, str], tz) -> list[list[str]]:
    date = detail.performed_at.astimezone(tz).strftime("%Y-%m-%d %H:%M")
    snapshot = detail.workout_snapshot
    title = str(snapshot.get("title", "")) if snapshot else ""
    items = positional_snapshot_items(snapshot, len(detail.blocks))
    effort, comment = _num(detail.effort), _text(detail.comment)
    rows: list[list[str]] = []
    for block, item in zip(detail.blocks, items, strict=True):
        exercise = item.exercise_name if item is not None else names.get(block.exercise_id or -1, "")
        protocol = item.protocol.type.value if item is not None else ""
        for log in block.set_logs:
            # у факультатива note — упакованный JSON backfill-а: в CSV — та же читаемая строка, что в Журнале
            note = format_elective_set_note(log.note, log.value) if detail.source == SessionSource.ELECTIVE else log.note
            rows.append([
                "v2", date, _text(title), _text(exercise), protocol, str(log.set_number), _num(log.value),
                log.unit, _num(log.effort), _text(note), effort, comment,
            ])
    if not rows:  # свободная активность / сессия без подходов — одна строка
        activity = detail.activity_type or ""
        duration = [str(detail.duration_seconds), "s"] if detail.duration_seconds else ["", ""]
        rows.append(["v2", date, _text(title), _text(activity), "", "", *duration, "", "", effort, comment])
    return rows


async def build_rows(session: AsyncSession, *, user_id: int, timezone: str | None) -> list[list[str]]:
    tz = resolve_timezone(timezone)
    sessions = TrainingSessionRepository(session)
    details = await sessions.list_all_completed(user_id)
    ids = {b.exercise_id for d in details for b in d.blocks if b.exercise_id is not None}
    names = await sessions.exercise_names(ids)
    rows: list[list[str]] = []
    for detail in details:
        rows.extend(_v2_rows(detail, names, tz))
    for workout in await WorkoutRepository(session).list_for_user(user_id):
        date = workout.performed_at.astimezone(tz).strftime("%Y-%m-%d %H:%M")
        for block in workout.blocks:
            for number, reps in enumerate(block.working_reps, start=1):
                rows.append([
                    "legacy", date, "", workout.exercise_type.value, block.block_type.value, str(number), str(reps),
                    "reps", "", "", "", _text(workout.comment),
                ])
    return rows


def render_csv(rows: list[list[str]]) -> Iterator[str]:
    """Построчно (BOM первым куском) — для StreamingResponse."""
    yield BOM
    for row in [HEADER, *rows]:
        buffer = io.StringIO()
        csv.writer(buffer, lineterminator="\r\n").writerow(row)
        yield buffer.getvalue()


def sign_link(bot_token: str, user_id: int, *, now: float | None = None) -> str:
    """Короткоживущий подписанный токен user_id.expires.hmac для ссылки без
    заголовков (Telegram.WebApp.downloadFile / window.open). initData в
    query-строку не кладём."""
    expires = int((time.time() if now is None else now) + LINK_TTL_SECONDS)
    mac = hmac.new(bot_token.encode(), f"export:{user_id}:{expires}".encode(), hashlib.sha256).hexdigest()
    return f"{user_id}.{expires}.{mac}"


def verify_link(bot_token: str, token: str, *, now: float | None = None) -> int | None:
    """Внутренний user_id или None, если подпись неверна/токен просрочен."""
    try:
        user_part, expires_part, mac = token.split(".")
        user_id, expires = int(user_part), int(expires_part)
    except ValueError:
        return None
    expected = hmac.new(bot_token.encode(), f"export:{user_id}:{expires}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, expected) or (time.time() if now is None else now) > expires:
        return None
    return user_id
