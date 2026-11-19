"""#309 / J2: identical API events, current occurrences vs reconstructed aged storage.

This checks aggregate/M2M/cache representation convergence and cross-view history,
not old-writer replay, progression migration, or the complete aged-persona matrix.
Both users explicitly keep the SAME legacy program version; V5.6 is not rewritten.
"""

import copy
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from app.db.models import SubscriptionStatus
from app.db.models_program import (
    PlanItem,
    ProgramInclusion,
    SessionPlanItem,
    TrainingPlan,
    TrainingSession,
)
from app.db.repositories import training_sessions
from app.db.repositories.training_plans import TrainingPlanRepository
from app.db.repositories.users import UserRepository
from app.services import live_session, program_inclusion
from app.services.plan_convergence import PlanConvergenceService
from app.web import routes_v2
from tests.test_web._v2_client import v2_get, v2_post
from tests.test_web.test_v2_plan_occurrences import _pullups_program

MON = datetime(2026, 10, 5, 10, tzinfo=UTC)
THU = MON + timedelta(days=3)
FRI = MON + timedelta(days=4)
PLAN_CREATED = MON - timedelta(weeks=3)


async def _history(session, user_id):
    """Every stored session field except the explicitly repairable credit; full children."""
    result = {}
    queries = {
        "sessions": "SELECT to_jsonb(s) - 'plan_item_id' FROM training_sessions s WHERE s.user_id=:uid ORDER BY s.id",
        "blocks": "SELECT to_jsonb(b) FROM session_blocks b JOIN training_sessions s ON s.id=b.session_id "
        "WHERE s.user_id=:uid ORDER BY b.id",
        "targets": "SELECT to_jsonb(t) FROM set_targets t JOIN session_blocks b ON b.id=t.session_block_id "
        "JOIN training_sessions s ON s.id=b.session_id WHERE s.user_id=:uid ORDER BY t.id",
        "logs": "SELECT to_jsonb(l) FROM set_logs l JOIN session_blocks b ON b.id=l.session_block_id "
        "JOIN training_sessions s ON s.id=b.session_id WHERE s.user_id=:uid ORDER BY l.id",
    }
    for key, sql in queries.items():
        result[key] = (await session.execute(text(sql), {"uid": user_id})).scalars().all()
    return result


def _projection(plan, inclusion_id, event_ids):
    """Replace only ownership/row identities with their week/event meanings."""
    weeks = {w["id"]: w["week_number"] for w in plan["plan_weeks"]}
    events = {session_id: index for index, session_id in enumerate(event_ids)}
    items = []
    for original in plan["plan_items"]:
        item = dict(original)
        item.pop("id")
        assert item.pop("program_inclusion_id") == inclusion_id
        for field in ("plan_week_id", "origin_plan_week_id"):
            item[field] = weeks[item[field]]
        if item["credited_session_id"] is not None:
            item["credited_session_id"] = events[item["credited_session_id"]]
        items.append(item)
    return {
        "today": plan["today"],
        "current_week": weeks[plan["current_week_id"]],
        "weeks": [{k: v for k, v in w.items() if k != "id"} for w in plan["plan_weeks"]],
        "items": sorted(
            items, key=lambda i: (i["plan_week_id"], i["program_slot_key"], i["occurrence_index"])
        ),
        "summaries": [
            {**s, "plan_week_id": weeks[s["plan_week_id"]]} for s in plan["week_summaries"]
        ],
        "spacing": plan["spacing"],
    }


async def _assert_cross_view_history(session, telegram_id, event_ids):
    async def read(path):
        response = await v2_get(session, telegram_id, path)
        assert response.status_code == 200, response.text
        return response.json()

    legacy = await read("/api/history?date_from=2026-10-05&date_to=2026-10-09")
    journal = await read(
        "/api/v2/sessions?status=completed&date_from=2026-10-05&date_to=2026-10-09&exclude_legacy_cards=true"
    )
    assert legacy["items"] == []
    assert [(s["id"], s["title"], s["duration_seconds"]) for s in journal["sessions"]] == [
        (session_id, "Подтягивания", 2400) for session_id in reversed(event_ids)
    ]
    calendar = await read("/api/v2/journal/days?month=2026-10")
    assert [(d["date"], d["count"]) for d in calendar["days"]] == [
        ("2026-10-05", 1),
        ("2026-10-08", 1),
    ]
    assert (await read("/api/profile"))["workouts_count"] == 2
    analytics = await read("/api/v2/analytics/training?from=2026-10-05&to=2026-10-09")
    metrics, distribution = analytics["metrics"], analytics["distribution"]
    assert metrics["weeks"] == [{"week_start": "2026-10-05", "workouts": 2, "minutes": 80}]
    assert metrics["without_duration"] == 0
    for view in (metrics, distribution):
        assert (view["total_workouts"], view["total_minutes"]) == (2, 80)
    assert [
        (category["name"], category["workouts"], category["minutes"])
        for category in distribution["categories"]
        if category["workouts"] or category["minutes"]
    ] == [("Подтягивания", 2, 80)]


async def test_same_api_history_converges_to_equal_fresh_and_aged_plan_state(session, monkeypatch):
    now = MON

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz is not None else now.replace(tzinfo=None)

    # Start and completion also call datetime.now directly, not just _utcnow.
    for module in (live_session, program_inclusion, training_sessions):
        monkeypatch.setattr(module, "datetime", FixedDatetime)
    monkeypatch.setattr(live_session, "_utcnow", lambda: now)
    monkeypatch.setattr(routes_v2, "_utcnow", lambda: now)
    program = await _pullups_program(session)
    users, plans, inclusions, event_ids = [], [], [], []
    repo = TrainingPlanRepository(session)
    for telegram_id in (30901, 30902):
        user = await UserRepository(session).create(telegram_id=telegram_id)
        user.timezone = "UTC"
        await UserRepository(session).update_subscription_cache(
            user.id,
            status=SubscriptionStatus.ACTIVE,
            expires_at=datetime(2100, 1, 1, tzinfo=UTC),
        )
        plan = TrainingPlan(user_id=user.id, created_at=PLAN_CREATED)
        session.add(plan)
        await session.flush()
        now = MON
        response = await v2_post(
            session,
            telegram_id,
            "/api/v2/program-inclusions",
            {
                "program_id": program.id,
                "program_version": "pullups_legacy_step",
            },
        )
        assert response.status_code == 200, response.text
        inclusion = await session.get(ProgramInclusion, response.json()["id"])
        ids = []
        for index, at in enumerate((MON, THU), start=1):
            now = at
            await v2_get(session, telegram_id, "/api/v2/plan")
            occurrence = (
                await session.execute(
                    select(PlanItem).where(
                        PlanItem.training_plan_id == plan.id,
                        PlanItem.occurrence_index == index,
                    )
                )
            ).scalar_one()
            started = await v2_post(
                session,
                telegram_id,
                "/api/v2/sessions/live",
                {
                    "client_session_id": str(uuid.uuid4()),
                    "plan_item_ids": [occurrence.id],
                },
            )
            assert started.status_code == 200, started.text
            session_id = started.json()["id"]
            roles = {e["role"]: e["exercise_id"] for e in inclusion.snapshot["exercises"]}
            sets = [(roles["block_a"], value) for value in (10, 10, 10, 11)]
            sets += [(roles["block_b"], value) for value in (3, 3, 3, 3, 4)]
            batch = await v2_post(
                session,
                telegram_id,
                f"/api/v2/sessions/live/{session_id}/sets:batch",
                {
                    "sets": [
                        {"set_index": n, "exercise_id": exercise, "value": str(value)}
                        for n, (exercise, value) in enumerate(sets)
                    ],
                },
            )
            assert batch.status_code == 200, batch.text
            now = at + timedelta(minutes=40)
            completed = await v2_post(
                session,
                telegram_id,
                f"/api/v2/sessions/live/{session_id}/complete",
                {
                    "abandoned": False,
                },
            )
            assert completed.status_code == 200, completed.text
            assert completed.json()["progression_result"] is not None
            ids.append(session_id)
        users.append(user)
        plans.append(plan)
        inclusions.append(inclusion)
        event_ids.append(ids)
    await session.commit()

    assert inclusions[0].snapshot == inclusions[1].snapshot
    assert inclusions[0].initial_progression_state == inclusions[1].initial_progression_state
    assert inclusions[0].progression_state == inclusions[1].progression_state
    histories = [await _history(session, user.id) for user in users]
    # Same actual events and complete target/log content; per-owner preservation below
    # additionally checks every stored field, including snapshots and timestamps.
    for history in histories:
        assert [
            (s["performed_at"], s["completed_at"], s["duration_seconds"], s["source_v2"])
            for s in history["sessions"]
        ] == [
            (at.isoformat(), (at + timedelta(minutes=40)).isoformat(), 2400, "planned_live")
            for at in (MON, THU)
        ]
    for table in ("blocks", "targets", "logs"):
        identity = {"id", "session_id", "session_block_id", "set_target_id", "created_at"}
        assert [
            {k: v for k, v in row.items() if k not in identity} for row in histories[0][table]
        ] == [{k: v for k, v in row.items() if k not in identity} for row in histories[1][table]]

    # Reconstruct only documented old aggregate/M2M/cache storage. Keep the same
    # canonical events, immutable snapshots and progressed legacy prescription.
    aged = inclusions[1]
    current_week = await repo.get_plan_week(training_plan_id=plans[1].id, week_number=4)
    aggregates = await repo.create_plan_items_for_week_from_snapshot(
        training_plan_id=plans[1].id,
        program_inclusion_id=aged.id,
        plan_week_id=current_week.id,
        program_items_snapshot=aged.snapshot["program_items"],
    )
    occurrences = (
        (
            await session.execute(
                select(PlanItem).where(
                    PlanItem.training_plan_id == plans[1].id,
                    PlanItem.occurrence_index.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for session_id in event_ids[1]:
        row = await session.get(TrainingSession, session_id)
        row.plan_item_id = None
        for aggregate in aggregates:
            session.add(SessionPlanItem(session_id=session_id, plan_item_id=aggregate.id))
    await session.flush()
    for occurrence in occurrences:
        await session.delete(occurrence)
    aged.status = aged.sequence_cursor = aged.completed_main_sessions = (
        aged.last_main_session_at
    ) = None
    await session.commit()
    assert await _history(session, users[1].id) == histories[1]
    protected = [
        copy.deepcopy(
            (
                i.snapshot,
                i.initial_progression_state,
                i.progression_state,
                i.prescription_provenance,
                i.started_at,
                i.progression_state_rev,
            )
        )
        for i in inclusions
    ]
    entitlements = [(u.subscription_status, u.subscription_expires_at) for u in users]
    access = program.access_level
    now = FRI
    projections, counters = [], []
    for user, plan, inclusion, ids, history, invariant, entitlement in zip(
        users,
        plans,
        inclusions,
        event_ids,
        histories,
        protected,
        entitlements,
        strict=True,
    ):
        _, report = await PlanConvergenceService(session).converge_user_plan(
            training_plan_id=plan.id,
            today=FRI.date(),
            create_until_week=5,
        )
        assert report.gaps == []
        await session.commit()
        response = await v2_get(session, user.telegram_id, "/api/v2/plan")
        assert response.status_code == 200, response.text
        projection = _projection(response.json()["plan"], inclusion.id, ids)
        await session.refresh(inclusion)
        await session.refresh(user)
        assert (
            inclusion.snapshot,
            inclusion.initial_progression_state,
            inclusion.progression_state,
            inclusion.prescription_provenance,
            inclusion.started_at,
            inclusion.progression_state_rev,
        ) == invariant
        assert (user.subscription_status, user.subscription_expires_at) == entitlement
        assert program.access_level == access == "free"
        assert await _history(session, user.id) == history
        counters.append(
            (
                inclusion.status,
                inclusion.sequence_cursor,
                inclusion.completed_main_sessions,
                inclusion.last_main_session_at,
            )
        )
        projections.append(projection)
        _, again = await PlanConvergenceService(session).converge_user_plan(
            training_plan_id=plan.id,
            today=FRI.date(),
            create_until_week=5,
        )
        assert again.mutations == 0, again.as_dict()
        await _assert_cross_view_history(session, user.telegram_id, ids)
    assert counters == [("active", 2, 2, THU)] * 2
    assert projections[0] == projections[1]
    assert projections[0]["spacing"] == [
        {
            "spacing_group": "main",
            "min_days_between_starts": 3,
            "last_start_date": "2026-10-08",
            "available_from": "2026-10-11",
        }
    ]
    assert [(s["planned"], s["completed"]) for s in projections[0]["summaries"][-2:]] == [
        (3, 2),
        (3, 0),
    ]
    assert [i["credited_session_id"] for i in projections[0]["items"][:3]] == [0, 1, None]
    for aggregate in aggregates:
        await session.refresh(aggregate)
        assert aggregate.legacy_aggregate and aggregate.status == "removed"
