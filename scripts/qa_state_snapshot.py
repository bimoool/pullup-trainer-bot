"""Безопасный read-only снимок состояния плана одного пользователя (recovery campaign, role C).

Зачем: на staging у «старого» пользователя план может быть в состоянии, которое не воспроизводит
свежий пользователь (инклюзия создана старым кодом/backfill'ом, снимок без program_items, строки
привязаны к прошлой неделе...). Скрипт ничего не меняет и печатает санитизированный JSON с
ДИАГНОЗАМИ — его можно целиком вставить в issue/чат.

Гарантии безопасности:
  * только SELECT, внутри транзакции `SET TRANSACTION READ ONLY` (запись Postgres просто отклонит),
    в конце всегда ROLLBACK;
  * не печатает DATABASE_URL/токены/имя/username/телефон — только telegram_id, который передали
    параметром, внутренние числовые id и даты;
  * никаких импортов бота/воркеров — не запускает ни одного побочного эффекта.

Запуск на сервере (сервис `app` собирается из Dockerfile, в котором есть каталог scripts/ и .env с
DATABASE_URL; сервис `web` — НЕТ, в образе Dockerfile.web каталога scripts/ нет):

    docker compose -p pullup-staging exec app python scripts/qa_state_snapshot.py --telegram-id <ID>

Если контейнер уже остановлен: `docker compose -p pullup-staging run --rm app python
scripts/qa_state_snapshot.py --telegram-id <ID>`. Локально: `DATABASE_URL=postgresql+asyncpg://... python
scripts/qa_state_snapshot.py --telegram-id <ID> [--today 2026-10-06]`.

Флаги: --today YYYY-MM-DD — «сегодня» для расчёта текущей недели (по умолчанию — дата в часовом поясе
пользователя). Код возврата 0 — снимок снят, 2 — пользователь не найден.
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.domain.multi_program import (
    is_plannable_week_number,
    plan_week_number,
    plan_week_start_date,
)

DEFAULT_TZ = "Europe/Moscow"  # запасной вариант; реальный проектный дефолт — app.bot.timezones.DEFAULT_TIMEZONE


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _resolve_tz(name: str | None) -> ZoneInfo:
    for candidate in (name, DEFAULT_TZ):
        if candidate:
            try:
                return ZoneInfo(candidate)
            except (ZoneInfoNotFoundError, ValueError, OSError):
                continue
    return ZoneInfo("UTC")


def _rows(result) -> list[dict]:
    return [dict(row._mapping) for row in result]


def build_diagnoses(snapshot: dict) -> list[str]:
    """Чистая функция над собранным снимком (удобно тестировать без БД)."""
    out: list[str] = []
    plan = snapshot.get("plan")
    if plan is None:
        out.append("NO_PLAN: у пользователя нет TrainingPlan — GET /plan вернёт plan=null")
        return out
    current_no = snapshot["current_week_number"]
    items = snapshot["plan_items"]
    weeks_by_no = {week["week_number"]: week for week in snapshot["plan_weeks"]}
    current_week = weeks_by_no.get(current_no)
    if current_week is None:
        out.append(
            f"CURRENT_WEEK_ROW_MISSING: PlanWeek №{current_no} ещё не создана (создастся первым GET /plan)",
        )
    current_items = [i for i in items if current_week is not None and i["plan_week_id"] == current_week["id"]]
    unweeked = [i for i in items if i["plan_week_id"] is None]
    active = [inc for inc in snapshot["inclusions"] if inc["is_active"]]
    if not active:
        out.append("NO_ACTIVE_INCLUSION: нет активных курсов — материализовать в текущую неделю нечего")
    if current_week is not None and not current_items:
        out.append(f"CURRENT_WEEK_EMPTY: в текущей неделе №{current_no} 0 PlanItem (экран «0 из 0»)")
    if unweeked:
        ids = sorted({i["program_inclusion_id"] for i in unweeked if i["program_inclusion_id"] is not None})
        out.append(
            f"UNWEEKED_ITEMS: {len(unweeked)} PlanItem без plan_week_id (инклюзии {ids}) — "
            "GET /plan привяжет их к ТЕКУЩЕЙ неделе",
        )
    for inc in snapshot["inclusions"]:
        tag = f"inclusion {inc['id']} («{inc['program_name']}», active={inc['is_active']})"
        if not inc["snapshot_has_program_items_key"]:
            out.append(f"SNAPSHOT_NO_PROGRAM_ITEMS_KEY: {tag}: snapshot без ключа program_items (legacy backfill)")
        elif inc["snapshot_program_items_count"] == 0:
            out.append(f"SNAPSHOT_PROGRAM_ITEMS_EMPTY: {tag}: snapshot.program_items пуст (Program была без ProgramItem)")
        if inc["snapshot_structure_type"] not in (None, "recurring"):
            out.append(
                f"STRUCTURE_NOT_RECURRING: {tag}: structure_type={inc['snapshot_structure_type']} — "
                "PlanWeekService не материализует не-recurring курсы",
            )
        if inc["snapshot_program_items_count"] == 0 and inc["live_program_item_count"] > 0 and inc["is_active"]:
            out.append(
                f"LIVE_HAS_ITEMS_SNAPSHOT_DOES_NOT: {tag}: у Program {inc['live_program_item_count']} ProgramItem, "
                "а в снимке 0 — материализация идёт ТОЛЬКО из снимка, неделя останется пустой",
            )
        if inc["is_active"]:
            rows_by_week = {
                i["plan_week_id"] for i in items if i["program_inclusion_id"] == inc["id"] and i["plan_week_id"]
            }
            if current_week is not None and current_week["id"] not in rows_by_week:
                out.append(f"INCLUSION_NOT_IN_CURRENT_WEEK: {tag}: нет строк в текущей неделе №{current_no}")
    if current_week is None and active:
        predicted = bool(unweeked) or any(
            inc["is_active"] and inc["snapshot_program_items_count"] > 0
            and inc["snapshot_structure_type"] in (None, "recurring")
            for inc in snapshot["inclusions"]
        )
        if not predicted:
            out.append(
                f"PREDICTED_EMPTY_CURRENT_WEEK: первый GET /plan создаст неделю №{current_no} БЕЗ строк курса "
                "(нет unweeked-строк и нет snapshot.program_items у активного recurring-курса)",
            )
    gaps = [n for n in range(1, current_no) if n not in weeks_by_no]
    if gaps:
        out.append(f"PAST_WEEK_GAPS: нет PlanWeek для недель {gaps} (пользователь не заходил; GET /plan создаст пустые)")
    if len(snapshot["programs_named_like_inclusions"]) != len({p["name"] for p in snapshot["programs_named_like_inclusions"]}):
        out.append("DUPLICATE_PROGRAM_NAMES: несколько Program с одним именем у инклюзий")
    return out


async def collect(conn, telegram_id: int, today_override: date | None) -> dict | None:
    user_rows = _rows(await conn.execute(
        text(
            "SELECT id, onboarding_completed_at, timezone, subscription_status::text AS subscription_status, "
            "subscription_expires_at FROM users WHERE telegram_id = :tg",
        ),
        {"tg": telegram_id},
    ))
    if not user_rows:
        return None
    user = user_rows[0]
    tz = _resolve_tz(user["timezone"])
    today = today_override or datetime.now(UTC).astimezone(tz).date()
    snapshot: dict = {
        "generated_for_today": today.isoformat(),
        "user": {
            "id": user["id"], "onboarded": user["onboarding_completed_at"] is not None,
            "onboarding_completed_at": _iso(user["onboarding_completed_at"]), "timezone": user["timezone"],
            "subscription_status": user["subscription_status"],
            "subscription_expires_at": _iso(user["subscription_expires_at"]),
        },
        "plan": None, "inclusions": [], "plan_weeks": [], "plan_items": [],
        "sessions": {"total": 0, "linked_to_plan_items": 0, "by_status": {}},
        "current_week_number": None, "programs_named_like_inclusions": [],
        "legacy": {},
    }
    plan_rows = _rows(await conn.execute(
        text("SELECT id, created_at FROM training_plans WHERE user_id = :u"), {"u": user["id"]},
    ))
    legacy = _rows(await conn.execute(
        text(
            "SELECT (SELECT count(*) FROM workouts WHERE user_id = :u) AS legacy_workouts, "
            "(SELECT count(*) FROM elective_workouts WHERE user_id = :u) AS legacy_electives",
        ),
        {"u": user["id"]},
    ))
    snapshot["legacy"] = legacy[0] if legacy else {}
    sess_rows = _rows(await conn.execute(
        text("SELECT status::text AS status, count(*) AS n FROM training_sessions WHERE user_id = :u GROUP BY 1"),
        {"u": user["id"]},
    ))
    snapshot["sessions"]["by_status"] = {row["status"]: row["n"] for row in sess_rows}
    snapshot["sessions"]["total"] = sum(row["n"] for row in sess_rows)
    if not plan_rows:
        snapshot["diagnoses"] = build_diagnoses(snapshot)
        return snapshot
    plan = plan_rows[0]
    created = plan["created_at"].date()
    current_no = plan_week_number(created, today)
    snapshot["plan"] = {"id": plan["id"], "created_at": _iso(plan["created_at"])}
    snapshot["current_week_number"] = current_no
    snapshot["current_week_start_date"] = plan_week_start_date(created, current_no).isoformat()
    snapshot["plannable_window"] = [n for n in range(current_no, current_no + 6) if is_plannable_week_number(n, current_no)]

    inclusions = _rows(await conn.execute(
        text(
            "SELECT i.id, i.program_id, p.name AS program_name, i.is_active, i.started_at, i.created_at, i.expires_at, "
            "(i.snapshot ? 'program_items') AS has_pi_key, "
            "COALESCE(jsonb_array_length(CASE WHEN jsonb_typeof(i.snapshot->'program_items') = 'array' "
            "THEN i.snapshot->'program_items' END), 0) AS pi_count, "
            "i.snapshot->>'structure_type' AS structure_type, "
            "(SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(i.snapshot) AS k) AS snapshot_keys, "
            "(SELECT count(*) FROM program_items pi WHERE pi.program_id = i.program_id) AS live_pi_count "
            "FROM program_inclusions i LEFT JOIN programs p ON p.id = i.program_id "
            "WHERE i.training_plan_id = :plan ORDER BY i.id",
        ),
        {"plan": plan["id"]},
    ))
    snapshot["inclusions"] = [
        {
            "id": row["id"], "program_id": row["program_id"], "program_name": row["program_name"],
            "is_active": row["is_active"], "started_at": _iso(row["started_at"]),
            "created_at": _iso(row["created_at"]), "expires_at": _iso(row["expires_at"]),
            "snapshot_keys": row["snapshot_keys"] or [], "snapshot_structure_type": row["structure_type"],
            "snapshot_has_program_items_key": bool(row["has_pi_key"]),
            "snapshot_program_items_count": row["pi_count"], "live_program_item_count": row["live_pi_count"],
        }
        for row in inclusions
    ]
    names = sorted({row["program_name"] for row in inclusions if row["program_name"]})
    if names:
        snapshot["programs_named_like_inclusions"] = _rows(await conn.execute(
            text("SELECT id, name FROM programs WHERE name = ANY(:names) ORDER BY id"), {"names": names},
        ))
    snapshot["plan_weeks"] = [
        {"id": r["id"], "week_number": r["week_number"], "start_date": _iso(r["start_date"]), "phase": r["phase"]}
        for r in _rows(await conn.execute(
            text(
                "SELECT id, week_number, start_date, phase::text AS phase FROM plan_weeks "
                "WHERE training_plan_id = :plan ORDER BY week_number",
            ),
            {"plan": plan["id"]},
        ))
    ]
    snapshot["plan_items"] = [
        {
            "id": r["id"], "plan_week_id": r["plan_week_id"], "program_inclusion_id": r["program_inclusion_id"],
            "exercise_id": r["exercise_id"], "complex_id": r["complex_id"], "count_per_week": r["count_per_week"],
            "day_of_week": r["day_of_week"], "week_phase": r["week_phase"], "linked_sessions": r["linked_sessions"],
        }
        for r in _rows(await conn.execute(
            text(
                "SELECT pi.id, pi.plan_week_id, pi.program_inclusion_id, pi.exercise_id, pi.complex_id, "
                "pi.count_per_week, pi.day_of_week, pi.week_phase::text AS week_phase, "
                "(SELECT count(*) FROM session_plan_items s WHERE s.plan_item_id = pi.id) AS linked_sessions "
                "FROM plan_items pi WHERE pi.training_plan_id = :plan ORDER BY pi.id",
            ),
            {"plan": plan["id"]},
        ))
    ]
    linked = await conn.scalar(
        text(
            "SELECT count(DISTINCT s.session_id) FROM session_plan_items s "
            "JOIN plan_items pi ON pi.id = s.plan_item_id WHERE pi.training_plan_id = :plan",
        ),
        {"plan": plan["id"]},
    )
    snapshot["sessions"]["linked_to_plan_items"] = linked or 0
    cur = next((w for w in snapshot["plan_weeks"] if w["week_number"] == current_no), None)
    snapshot["current_week_plan_item_count"] = (
        sum(1 for i in snapshot["plan_items"] if cur is not None and i["plan_week_id"] == cur["id"])
    )
    snapshot["diagnoses"] = build_diagnoses(snapshot)
    return snapshot


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--telegram-id", type=int, required=True)
    parser.add_argument("--today", type=date.fromisoformat, default=None, help="YYYY-MM-DD, по умолчанию — сегодня у пользователя")
    args = parser.parse_args()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL не задан", file=sys.stderr)
        return 1
    engine = create_async_engine(dsn)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            try:
                snapshot = await collect(conn, args.telegram_id, args.today)
            finally:
                await conn.rollback()
    finally:
        await engine.dispose()
    if snapshot is None:
        print(json.dumps({"error": "user not found", "telegram_id": args.telegram_id}, ensure_ascii=False))
        return 2
    print(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
