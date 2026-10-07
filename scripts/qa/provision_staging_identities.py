"""Provision the dedicated QA identities on STAGING (run INSIDE the staging container).

    docker compose -p pullup-staging run --rm -e QA_ALLOW_STAGING=1 app \
        python scripts/qa/provision_staging_identities.py            # all identities
        ... --only qa_aged_active                                    # one identity
        ... --snapshot                                               # read-only state dump

Safety (all must hold or the script exits 3 before opening the database):
  * env QA_ALLOW_STAGING=1 is set explicitly;
  * DATABASE_URL names a database that contains "staging" and is not the prod/test DB;
  * if POSTGRES_DB / MINI_APP_URL are present they must agree (staging DB name, staging host);
  * only telegram ids in the reserved QA range (scripts/qa/identities.py) are ever touched:
    every identity is purged and recreated (delete-recreate, same helper as scripts/e2e_seed.py),
    so a rerun always resets to the documented state. Other users' rows are never read or written.

How realistic is each state (be honest about what is synthetic — see docs/STAGING_QA_HARNESS.md):
  REAL code paths: UserRepository.create, OnboardingService (baseline + questionnaire + trial),
  SubscriptionService, ProgramInclusionService.create_inclusion, PlanWeekService.ensure_current_plan_week,
  TrainingSessionLogService.record_session (STEP progression), scripts.backfill_multi_program helpers.
  SYNTHETIC: timestamps are moved into the past (users.created_at, training_plans.created_at,
  program_inclusions.created_at, onboarding/session times) by UPDATE/`now=` arguments; the paid
  subscription is an ADMIN_GRANT (no payment); the historical sessions are recorded via the
  session-log service, not by driving the live-session UI. The CURRENT week is deliberately NOT
  materialised here: it is created by the product's own GET /api/v2/plan on the first open,
  exactly as for the owner whose plan was created weeks ago and who last opened Plans in week 1.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal

STAGING_FLAG = "QA_ALLOW_STAGING"


class RefusedError(RuntimeError):
    """Raised when the environment does not look like staging (exit code 3)."""


def assert_staging_environment(env: dict[str, str] | os._Environ) -> str:
    """Return the staging DB name or raise RefusedError. Pure function (unit-tested, no I/O).
    The staging identification itself is the shared app.services.qa_staging_guard.identify_staging (one
    definition with the staging bot's QA reset); this script additionally requires the explicit opt-in flag."""
    from app.services.qa_staging_guard import NotStagingError, identify_staging

    if env.get(STAGING_FLAG) != "1":
        raise RefusedError(f"{STAGING_FLAG}=1 must be set explicitly")
    try:
        staging = identify_staging(
            database_url=env.get("DATABASE_URL", ""), mini_app_url=env.get("MINI_APP_URL", ""),
            postgres_db=env.get("POSTGRES_DB"),
        )
    except NotStagingError as exc:
        raise RefusedError(str(exc)) from exc
    if not env.get("BOT_TOKEN"):
        raise RefusedError("BOT_TOKEN is not set")
    return staging.db_name


async def _purge(session, telegram_id: int) -> None:
    from app.db.repositories.users import UserRepository
    from scripts.e2e_seed import _purge_user
    from scripts.qa.identities import is_qa_id

    assert is_qa_id(telegram_id), "refusing to purge a non-QA telegram id"
    existing = await UserRepository(session).get_by_telegram_id(telegram_id)
    if existing is not None:
        await _purge_user(session, existing.id)


async def _onboard_at(session, telegram_id: int, *, at: datetime, reps: int = 8):
    """Real onboarding services with `now=at` in the past; user.created_at moved to `at` (synthetic)."""
    from datetime import date

    from sqlalchemy import update

    from app.db.models import Gender, User
    from app.db.repositories.users import UserRepository
    from app.services.onboarding import OnboardingService

    user = await UserRepository(session).create(telegram_id=telegram_id, username=f"qa{telegram_id}")
    await session.execute(update(User).where(User.id == user.id).values(created_at=at))
    onboarding = OnboardingService(session)
    await onboarding.record_baseline_and_start(user_id=user.id, performed_at=at, reps=reps)
    await onboarding.complete_questionnaire_and_start_trial(
        user_id=user.id, now=at, weight_kg=Decimal(78), height_cm=180,
        gender=Gender.MALE, birth_date=date(1992, 4, 15), timezone="Europe/Moscow",
    )
    await session.refresh(user)
    return user


async def _grant_active(session, user_id: int, *, now: datetime, days: int = 90) -> None:
    from app.services.subscription import SubscriptionService

    await SubscriptionService(session).grant_by_admin(user_id, now=now, days=days)


async def _include_course_in_past(session, user, *, start: datetime, visited_weeks: int):
    """Real course inclusion, then plan/inclusion created_at moved to `start` (synthetic) and the
    plan weeks the user "opened" materialised with the real PlanWeekService at the then-current day."""
    from sqlalchemy import update

    from app.db.models_program import ProgramInclusion, TrainingPlan
    from app.db.repositories.training_plans import TrainingPlanRepository
    from app.services.plan_week import PlanWeekService
    from app.services.program_inclusion import ProgramInclusionRequest, ProgramInclusionService
    from scripts.e2e_seed import _shipped_pull_ups_program

    program = await _shipped_pull_ups_program(session)
    inclusion = await ProgramInclusionService(session).create_inclusion(
        user_id=user.id, request=ProgramInclusionRequest(program_id=program.id),
    )
    plan = await TrainingPlanRepository(session).get_for_user(user.id)
    await session.execute(update(TrainingPlan).where(TrainingPlan.id == plan.id).values(created_at=start))
    await session.execute(update(ProgramInclusion).where(ProgramInclusion.id == inclusion.id).values(created_at=start))
    await session.flush()
    await session.refresh(plan)  # core UPDATE bypassed the identity map; ensure created_at is the past value
    await session.refresh(inclusion)
    weeks = PlanWeekService(session)
    for offset in range(visited_weeks):
        await weeks.ensure_current_plan_week(
            training_plan_id=plan.id, today=(start + timedelta(weeks=offset)).date(),
        )
    return program, inclusion, plan


async def _record_course_sessions(session, user, inclusion, *, times: list[datetime]) -> None:
    from app.db.repositories.training_sessions import SessionBlockInput, SetLogInput
    from app.domain.multi_program import MetricType, SessionSource
    from app.services.session_log import TrainingSessionLogService

    role_to_exercise = {e["role"]: e["exercise_id"] for e in inclusion.snapshot["exercises"]}
    if not {"block_a", "block_b"} <= set(role_to_exercise):
        return  # shipped course without STEP roles: nothing to record, do not invent

    def block(exercise_id: int, working: list[int], max_value: int) -> SessionBlockInput:
        sets = [
            SetLogInput(set_number=i + 1, metric_type=MetricType.REPS, value=Decimal(r), unit="reps")
            for i, r in enumerate(working)
        ]
        sets.append(SetLogInput(
            set_number=len(working) + 1, metric_type=MetricType.REPS, value=Decimal(max_value),
            unit="reps", is_max_set=True,
        ))
        return SessionBlockInput(exercise_id=exercise_id, sets=sets)

    for performed_at in times:
        await TrainingSessionLogService(session).record_session(
            user_id=user.id, source=SessionSource.PLAN, performed_at=performed_at, effort=None, comment=None,
            program_inclusion_id=inclusion.id, completed_at=performed_at + timedelta(minutes=25),
            blocks=[
                block(role_to_exercise["block_a"], [8, 8, 7], 9),
                block(role_to_exercise["block_b"], [3, 3, 3, 3], 3),
            ],
        )


async def provision_fresh_active(session, telegram_id: int, now: datetime) -> None:
    """Onboarded today (real services), active (admin-granted) subscription, NO plan, NO history."""
    user = await _onboard_at(session, telegram_id, at=now, reps=8)
    await _grant_active(session, user.id, now=now)


async def provision_aged_active(session, telegram_id: int, now: datetime, *, aged_days: int, visited_weeks: int) -> None:
    """Mimics the owner's account: onboarded ~aged_days ago with «Подтягивания» included from day one,
    the plan was created then, Plans was last opened during week 1 (only `visited_weeks` weeks are
    materialised), two sessions were done in week 1. Current week is left to the product."""
    start = now - timedelta(days=aged_days)
    user = await _onboard_at(session, telegram_id, at=start, reps=8)
    await _grant_active(session, user.id, now=now)
    _program, inclusion, _plan = await _include_course_in_past(session, user, start=start, visited_weeks=visited_weeks)
    await _record_course_sessions(
        session, user, inclusion, times=[start + timedelta(days=2), start + timedelta(days=4)],
    )


async def provision_aged_legacy_snapshot(session, telegram_id: int, now: datetime, *, visited_weeks: int) -> None:
    """Same as qa_aged_active (plan ~23 d old, week 1 materialised by the real service, current week left to
    the product) plus ONE synthetic mutation reproducing the historical source shape: the inclusion snapshot
    loses its "program_items" key. That is the shape written by the pre-checkpoint-1.1 backfill
    (scripts/backfill_multi_program.py::seed_catalog at commit cd2808f had no "program_items" in the snapshot).
    No PlanItem / PlanWeek is inserted or edited by hand; weeks 2..current stay unmaterialised."""
    from sqlalchemy import update

    from app.db.models_program import ProgramInclusion

    start = now - timedelta(days=23)
    user = await _onboard_at(session, telegram_id, at=start, reps=8)
    await _grant_active(session, user.id, now=now)
    _program, inclusion, _plan = await _include_course_in_past(session, user, start=start, visited_weeks=visited_weeks)
    await _record_course_sessions(
        session, user, inclusion, times=[start + timedelta(days=2), start + timedelta(days=4)],
    )
    legacy_snapshot = {k: v for k, v in (inclusion.snapshot or {}).items() if k != "program_items"}
    await session.execute(
        update(ProgramInclusion).where(ProgramInclusion.id == inclusion.id).values(snapshot=legacy_snapshot),
    )
    await session.flush()


async def provision_expired(session, telegram_id: int, now: datetime) -> None:
    """Onboarded 40 days ago, 14-day trial ended, never paid -> EXPIRED (cache refreshed by the real
    SubscriptionService); the course is still in the plan so the expired-course gate is reachable."""
    from app.services.subscription import SubscriptionService

    start = now - timedelta(days=40)
    user = await _onboard_at(session, telegram_id, at=start, reps=8)
    await _include_course_in_past(session, user, start=start, visited_weeks=1)
    await SubscriptionService(session).refresh_status(user.id, now=now)


async def provision_legacy_or_partial(session, telegram_id: int, now: datetime) -> None:
    """Legacy Workout rows carried over by the real backfill helpers (3 migrated + 1 legacy-only after
    migration) plus two backfilled electives; no plan. Reuses scripts/e2e_seed.py::seed_journal_dedupe."""
    from app.db.repositories.users import UserRepository
    from scripts.e2e_seed import _seed_backfilled_electives, seed_journal_dedupe

    await seed_journal_dedupe(session, telegram_id)
    user = await UserRepository(session).get_by_telegram_id(telegram_id)
    await _seed_backfilled_electives(session, user)


async def snapshot(session, telegram_id: int) -> dict:
    """Read-only state summary of one QA identity (no secrets, no PII beyond the QA id)."""
    from sqlalchemy import func, select

    from app.db.models import Workout
    from app.db.models_program import (
        PlanItem,
        PlanWeek,
        ProgramInclusion,
        TrainingPlan,
        TrainingSession,
    )
    from app.db.repositories.users import UserRepository
    from app.domain.multi_program import plan_week_number

    user = await UserRepository(session).get_by_telegram_id(telegram_id)
    if user is None:
        return {"telegram_id": telegram_id, "exists": False}
    out: dict = {
        "telegram_id": telegram_id, "exists": True,
        "onboarded_at": str(user.onboarding_completed_at),
        "subscription": {"status": str(user.subscription_status), "expires_at": str(user.subscription_expires_at)},
        "legacy_workouts": (await session.execute(
            select(func.count()).select_from(Workout).where(Workout.user_id == user.id))).scalar_one(),
        "training_sessions": (await session.execute(
            select(func.count()).select_from(TrainingSession).where(TrainingSession.user_id == user.id))).scalar_one(),
    }
    plan = (await session.execute(select(TrainingPlan).where(TrainingPlan.user_id == user.id))).scalar_one_or_none()
    if plan is None:
        out["plan"] = None
        return out
    today = datetime.now(UTC).date()
    inclusions = (await session.execute(
        select(ProgramInclusion).where(ProgramInclusion.training_plan_id == plan.id))).scalars().all()
    out["inclusions"] = [
        {
            "id": i.id, "active": i.is_active, "created_at": str(i.created_at),
            "snapshot_has_program_items": "program_items" in (i.snapshot or {}),
            "snapshot_program_items_count": len((i.snapshot or {}).get("program_items") or []),
        }
        for i in inclusions
    ]
    out["plan"] = {
        "created_at": str(plan.created_at),
        "current_week_number": plan_week_number(plan.created_at.date(), today),
        "weeks": [
            {
                "week_number": week.week_number, "start_date": str(week.start_date),
                "plan_items": (await session.execute(
                    select(func.count()).select_from(PlanItem).where(PlanItem.plan_week_id == week.id))).scalar_one(),
            }
            for week in (await session.execute(
                select(PlanWeek).where(PlanWeek.training_plan_id == plan.id).order_by(PlanWeek.week_number))).scalars()
        ],
    }
    return out


async def run(args: argparse.Namespace) -> int:
    from app.db.base import async_session_factory
    from scripts.qa.identities import QA_IDENTITIES

    names = args.only or list(QA_IDENTITIES)
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        if args.snapshot:
            print(json.dumps([await snapshot(session, QA_IDENTITIES[n]) for n in names], ensure_ascii=False, indent=2))
            return 0
        for name in names:
            telegram_id = QA_IDENTITIES[name]
            await _purge(session, telegram_id)
            if name == "qa_fresh_active":
                await provision_fresh_active(session, telegram_id, now)
            elif name == "qa_aged_active":
                await provision_aged_active(
                    session, telegram_id, now, aged_days=args.aged_days, visited_weeks=args.visited_weeks,
                )
            elif name == "qa_aged_legacy_snapshot":
                await provision_aged_legacy_snapshot(session, telegram_id, now, visited_weeks=args.visited_weeks)
            elif name == "qa_expired":
                await provision_expired(session, telegram_id, now)
            elif name == "qa_legacy_or_partial":
                await provision_legacy_or_partial(session, telegram_id, now)
            else:  # pragma: no cover - guarded by argparse choices
                raise SystemExit(f"no provisioner for {name}")
            await session.commit()
            print(f"provisioned {name} -> telegram_id={telegram_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    from scripts.qa.identities import QA_IDENTITIES

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="+", choices=sorted(QA_IDENTITIES), help="subset of identities")
    parser.add_argument("--snapshot", action="store_true", help="read-only JSON state dump, no changes")
    parser.add_argument("--aged-days", type=int, default=26, help="age of qa_aged_active plan (default 26 = ~3.7 weeks)")
    parser.add_argument("--visited-weeks", type=int, default=1,
                        help="plan weeks materialised in the past for qa_aged_active (default 1)")
    args = parser.parse_args(argv)
    try:
        db_name = assert_staging_environment(os.environ)
    except RefusedError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 3
    print(f"staging guard ok (db={db_name})")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    raise SystemExit(main())
