"""Targeted aged-state convergence repair for ONE user (#301, owner decision 2026-10-06).

Why this exists: a course included long ago can have a ProgramInclusion snapshot with no
"program_items" (pre-checkpoint-1.1 backfill) or an empty list (Program had no ProgramItem when the
course was added). Weekly rows are materialised only from the snapshot, so such a plan shows
"Week N · 0 из 0" forever. The runtime now heals it (PlanWeekService.converge_inclusion_snapshot,
called while materialising the current week on GET /plan). This script runs EXACTLY THAT runtime
entry point (PlanWeekService.ensure_current_plan_week) for one identity, so the operator can see the
mutation before anyone opens the app, and apply it under guards. It is not the old broad backfill: it
never enrols anyone, never touches another user, never rewrites a non-empty snapshot.

    # dry run (default): same code, transaction ROLLED BACK, prints the exact proposed mutation
    docker compose -p pullup-staging run --rm app python scripts/repair_plan_convergence.py --telegram-id <ID>
    # apply to that identity only (idempotent: a second run reports "nothing to do")
    docker compose -p pullup-staging run --rm app python scripts/repair_plan_convergence.py --telegram-id <ID> --apply

Guards (any violation aborts with exit code 4 and rolls back, even with --apply):
  * only the "program_items" key of an ACTIVE inclusion's snapshot may change, and only from missing/[]
    to a non-empty list; every other snapshot key, progression_state, started_at, is_active unchanged;
  * existing PlanItems are never deleted or edited (except a NULL plan_week_id being attached, the
    runtime orphan/unweeked attach); new PlanItems only in the current or future weeks;
  * PlanWeeks are only added; completed/other sessions and the subscription are unchanged;
  * rows of every OTHER training plan are unchanged.

Exit codes: 0 ok (or nothing to do), 2 user not found, 3 user has no training plan, 4 guard violated.
Output: one JSON document on stdout; the runtime's structured WARNING lines go to stderr.
"""

import argparse
import asyncio
import copy
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import async_session_factory
from app.db.models import User  # also registers "users" for models_program FKs (standalone run)
from app.db.models_program import (
    PlanItem,
    PlanWeek,
    ProgramInclusion,
    TrainingPlan,
    TrainingSession,
)
from app.domain.multi_program import plan_week_number, snapshot_program_items_gap
from app.services.plan_week import PlanWeekService
from app.services.training_analytics import resolve_timezone

EXIT_OK, EXIT_NO_USER, EXIT_NO_PLAN, EXIT_GUARD = 0, 2, 3, 4

_ITEM_FIELDS = (
    "plan_week_id", "program_inclusion_id", "exercise_id", "complex_id", "count_per_week", "day_of_week", "week_phase",
)


def user_local_today(user: User, now: datetime | None = None) -> date:
    """Same rule as app.web.routes_v2._plan_today: today in the user's timezone."""
    return (now or datetime.now(UTC)).astimezone(resolve_timezone(user.timezone)).date()


@dataclass
class _State:
    inclusions: dict[int, dict] = field(default_factory=dict)
    weeks: dict[int, dict] = field(default_factory=dict)
    items: dict[int, dict] = field(default_factory=dict)
    sessions: dict[str, int] = field(default_factory=dict)
    subscription: dict = field(default_factory=dict)
    other_plans: dict[str, int] = field(default_factory=dict)


def _value(v):
    return v.value if hasattr(v, "value") else v


async def _capture(session: AsyncSession, user: User, plan: TrainingPlan) -> _State:
    state = _State()
    for inc in (await session.execute(
        select(ProgramInclusion).where(ProgramInclusion.training_plan_id == plan.id).order_by(ProgramInclusion.id),
    )).scalars():
        state.inclusions[inc.id] = {
            "program_id": inc.program_id, "is_active": inc.is_active, "started_at": inc.started_at,
            "expires_at": inc.expires_at, "snapshot": copy.deepcopy(inc.snapshot),
            "progression_state": copy.deepcopy(inc.progression_state),
            "initial_progression_state": copy.deepcopy(inc.initial_progression_state),
        }
    for week in (await session.execute(select(PlanWeek).where(PlanWeek.training_plan_id == plan.id))).scalars():
        state.weeks[week.id] = {"week_number": week.week_number, "start_date": week.start_date}
    for item in (await session.execute(select(PlanItem).where(PlanItem.training_plan_id == plan.id))).scalars():
        state.items[item.id] = {name: _value(getattr(item, name)) for name in _ITEM_FIELDS}
    rows = await session.execute(
        select(TrainingSession.status, func.count()).where(TrainingSession.user_id == user.id)
        .group_by(TrainingSession.status),
    )
    state.sessions = {str(_value(status)): n for status, n in rows}
    state.subscription = {"status": _value(user.subscription_status), "expires_at": user.subscription_expires_at}
    for name, model, column in (
        ("plan_items", PlanItem, PlanItem.training_plan_id),
        ("plan_weeks", PlanWeek, PlanWeek.training_plan_id),
        ("program_inclusions", ProgramInclusion, ProgramInclusion.training_plan_id),
    ):
        state.other_plans[name] = (await session.execute(
            select(func.count()).select_from(model).where(column != plan.id),
        )).scalar_one()
    return state


def _diff(before: _State, after: _State, *, current_week_number: int) -> tuple[dict, list[str]]:
    violations: list[str] = []
    snapshot_changes = []
    for inc_id, b in before.inclusions.items():
        a = after.inclusions.get(inc_id)
        if a is None:
            violations.append(f"inclusion {inc_id} disappeared")
            continue
        for key in ("program_id", "is_active", "started_at", "expires_at", "progression_state", "initial_progression_state"):
            if a[key] != b[key]:
                violations.append(f"inclusion {inc_id}: {key} changed")
        b_snap, a_snap = b["snapshot"] or {}, a["snapshot"] or {}
        if a_snap == b_snap:
            continue
        changed_keys = sorted(k for k in set(a_snap) | set(b_snap) if a_snap.get(k, ...) != b_snap.get(k, ...))
        gap = snapshot_program_items_gap(b_snap)
        if changed_keys != ["program_items"]:
            violations.append(f"inclusion {inc_id}: snapshot keys other than program_items changed: {changed_keys}")
        if gap is None:
            violations.append(f"inclusion {inc_id}: non-empty historical snapshot.program_items was rewritten")
        if not b["is_active"]:
            violations.append(f"inclusion {inc_id}: inactive inclusion snapshot changed")
        if not a_snap.get("program_items"):
            violations.append(f"inclusion {inc_id}: program_items still empty after change")
        snapshot_changes.append({
            "inclusion_id": inc_id, "program_id": b["program_id"],
            "reason": gap.value if gap is not None else None,
            "program_items_before": b_snap.get("program_items", "<missing key>"),
            "program_items_after": a_snap.get("program_items"),
        })
    for inc_id in after.inclusions.keys() - before.inclusions.keys():
        violations.append(f"inclusion {inc_id} was created")

    week_number_by_id = {wid: w["week_number"] for wid, w in after.weeks.items()}
    for week_id in before.weeks.keys() - after.weeks.keys():
        violations.append(f"plan week {week_id} disappeared")
    weeks_created = []
    for week_id in sorted(after.weeks.keys() - before.weeks.keys(), key=lambda wid: after.weeks[wid]["week_number"]):
        number = after.weeks[week_id]["week_number"]
        kind = "past_gap_empty" if number < current_week_number else "current" if number == current_week_number else "future"
        weeks_created.append({"plan_week_id": week_id, "week_number": number,
                              "start_date": after.weeks[week_id]["start_date"].isoformat(), "kind": kind})

    items_attached = []
    for item_id, b in before.items.items():
        a = after.items.get(item_id)
        if a is None:
            violations.append(f"plan item {item_id} was deleted")
            continue
        changed = [name for name in _ITEM_FIELDS if a[name] != b[name]]
        if changed == ["plan_week_id"] and b["plan_week_id"] is None:
            items_attached.append({"plan_item_id": item_id, "week_number": week_number_by_id.get(a["plan_week_id"])})
        elif changed:
            violations.append(f"plan item {item_id}: fields changed {changed}")
    items_created = []
    for item_id in sorted(after.items.keys() - before.items.keys()):
        a = after.items[item_id]
        number = week_number_by_id.get(a["plan_week_id"])
        if number is None or number < current_week_number:
            violations.append(f"plan item {item_id} created outside current/future weeks (week {number})")
        items_created.append({"plan_item_id": item_id, "week_number": number, **a})

    if after.sessions != before.sessions:
        violations.append(f"sessions changed: {before.sessions} -> {after.sessions}")
    if after.subscription != before.subscription:
        violations.append("subscription changed")
    if after.other_plans != before.other_plans:
        violations.append(f"other users' plans changed: {before.other_plans} -> {after.other_plans}")

    mutation = {
        "snapshot_repairs": snapshot_changes,
        "plan_weeks_created": weeks_created,
        "plan_items_attached_to_week": items_attached,
        "plan_items_created": items_created,
    }
    return mutation, violations


def _summary(state: _State, current_week_number: int) -> dict:
    current_ids = {wid for wid, w in state.weeks.items() if w["week_number"] == current_week_number}
    return {
        "current_week_exists": bool(current_ids),
        "current_week_plan_items": sum(1 for i in state.items.values() if i["plan_week_id"] in current_ids),
        "plan_items_total": len(state.items),
        "plan_weeks": sorted(w["week_number"] for w in state.weeks.values()),
        "sessions_by_status": state.sessions,
        "inclusions": [
            {
                "inclusion_id": inc_id, "program_id": inc["program_id"], "is_active": inc["is_active"],
                "started_at": inc["started_at"],
                "snapshot_program_items": (
                    "<missing key>" if "program_items" not in (inc["snapshot"] or {})
                    else len(inc["snapshot"]["program_items"] or [])
                ),
                "gap": _value(snapshot_program_items_gap(inc["snapshot"])) if inc["is_active"] else None,
            }
            for inc_id, inc in state.inclusions.items()
        ],
    }


async def run_repair(session: AsyncSession, *, telegram_id: int, apply: bool, today: date | None = None) -> tuple[int, dict]:
    """Runs the canonical runtime convergence for one identity inside the caller's transaction.
    Commits only when apply=True and every guard holds; otherwise rolls back."""
    user = (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()
    if user is None:
        return EXIT_NO_USER, {"error": "user not found", "telegram_id": telegram_id}
    plan = (await session.execute(select(TrainingPlan).where(TrainingPlan.user_id == user.id))).scalar_one_or_none()
    if plan is None:
        return EXIT_NO_PLAN, {"error": "user has no training plan", "telegram_id": telegram_id}

    plan_id = plan.id  # read before commit/rollback: the ORM objects are expired afterwards
    today = today or user_local_today(user)
    current_week_number = plan_week_number(plan.created_at.date(), today)
    before = await _capture(session, user, plan)
    await PlanWeekService(session).ensure_current_plan_week(training_plan_id=plan_id, today=today)
    await session.flush()
    after = await _capture(session, user, plan)
    mutation, violations = _diff(before, after, current_week_number=current_week_number)
    nothing_to_do = not any(mutation.values())

    if violations or not apply:
        await session.rollback()
    else:
        await session.commit()
    report = {
        "mode": "apply" if apply else "dry-run",
        "result": (
            "ABORTED: guard violated, rolled back" if violations
            else "nothing to do" if nothing_to_do
            else "applied" if apply else "dry-run: rolled back, nothing written"
        ),
        "telegram_id": telegram_id, "training_plan_id": plan_id, "today": today.isoformat(),
        "current_week_number": current_week_number,
        "before": _summary(before, current_week_number),
        "mutation": mutation,
        "after": _summary(after, current_week_number),
        "guard_violations": violations,
    }
    return (EXIT_GUARD if violations else EXIT_OK), report


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--telegram-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true", help="write the repair (default: dry run, rolled back)")
    parser.add_argument("--today", type=date.fromisoformat, default=None,
                        help="YYYY-MM-DD; default: today in the user's timezone (as GET /plan)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr, format="%(levelname)s %(name)s %(message)s")
    async with async_session_factory() as session:
        code, report = await run_repair(session, telegram_id=args.telegram_id, apply=args.apply, today=args.today)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
