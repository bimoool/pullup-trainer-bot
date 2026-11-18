"""#309 J9: external activity leaves an existing exercise history/custom plan intact.

One UTC profile, real API-created custom-plan occurrences and manual history.
There is no course inclusion/progression or credited completion in this fixture;
this does not prove preservation of progressed courses or every J9 persona/UI.
"""

import copy
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import text

from app.db.models_program import TrainingPlan, TrainingSession
from app.db.repositories import training_sessions
from app.services import live_session
from app.web import routes_v2, routes_v2_analytics
from tests.test_web._premium import create_premium_user
from tests.test_web._v2_client import v2_get, v2_patch, v2_post
from tests.test_web.test_v2_training_session_v2 import REPS_2x8, _manual, _workout

NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)


async def _protected_rows(session, user_id, manual_id):
    """Full owned plan, preexisting session/definition and all session children."""
    queries = {
        "plan": "SELECT row_to_json(p)::text FROM training_plans p WHERE p.user_id=:uid ORDER BY p.id",
        "weeks": "SELECT row_to_json(w)::text FROM plan_weeks w JOIN training_plans p ON p.id=w.training_plan_id "
        "WHERE p.user_id=:uid ORDER BY w.id",
        "custom_plans": "SELECT row_to_json(c)::text FROM custom_plans c WHERE c.user_id=:uid ORDER BY c.id",
        "occurrences": "SELECT row_to_json(i)::text FROM plan_items i JOIN training_plans p ON p.id=i.training_plan_id "
        "WHERE p.user_id=:uid ORDER BY i.id",
        "manual": "SELECT row_to_json(s)::text FROM training_sessions s WHERE s.id=:sid AND s.user_id=:uid",
        "definitions": "SELECT row_to_json(c)::text FROM complexes c WHERE c.owner_user_id=:uid ORDER BY c.id",
        "items": "SELECT row_to_json(i)::text FROM complex_items i JOIN complexes c ON c.id=i.complex_id "
        "WHERE c.owner_user_id=:uid ORDER BY i.id",
        "blocks": "SELECT row_to_json(b)::text FROM session_blocks b JOIN training_sessions s ON s.id=b.session_id "
        "WHERE s.user_id=:uid ORDER BY b.id",
        "targets": "SELECT row_to_json(t)::text FROM set_targets t JOIN session_blocks b ON b.id=t.session_block_id "
        "JOIN training_sessions s ON s.id=b.session_id WHERE s.user_id=:uid ORDER BY t.id",
        "logs": "SELECT row_to_json(l)::text FROM set_logs l JOIN session_blocks b ON b.id=l.session_block_id "
        "JOIN training_sessions s ON s.id=b.session_id WHERE s.user_id=:uid ORDER BY l.id",
    }
    return {
        key: (await session.execute(text(sql), {"uid": user_id, "sid": manual_id})).scalars().all()
        for key, sql in queries.items()
    }


async def _views(session, user):
    plan = await v2_get(session, user.telegram_id, "/api/v2/plan")
    assert plan.status_code == 200, plan.text
    analytics = await v2_get(
        session,
        user.telegram_id,
        "/api/v2/analytics/training?from=2026-10-05&to=2026-10-11",
    )
    assert analytics.status_code == 200, analytics.text
    journal = await v2_get(session, user.telegram_id, "/api/v2/sessions?status=completed")
    assert journal.status_code == 200, journal.text
    return plan.json(), analytics.json(), {card["id"]: card for card in journal.json()["sessions"]}


async def test_external_activity_create_and_edit_preserve_nonempty_history_and_actual_custom_plan(
    session, monkeypatch
):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz is not None else NOW.replace(tzinfo=None)

    # Plan creation delegates to routes_v2._plan_today; manual creation/edit and
    # analytics also use direct datetime.now. Freeze recipe/completion clocks too.
    for module in (routes_v2, routes_v2_analytics, live_session, training_sessions):
        monkeypatch.setattr(module, "datetime", FixedDatetime)
    monkeypatch.setattr(routes_v2, "_utcnow", lambda: NOW)
    user = await create_premium_user(session, telegram_id=30909)
    user.timezone = "UTC"
    # Synthetic TRIAL cache satisfies the Builder/custom-plan gate. No provider
    # payment or Subscription entitlement rows are created or claimed.
    session.add(TrainingPlan(user_id=user.id, created_at=datetime(2026, 10, 5, 9, tzinfo=UTC)))
    workout, [exercise] = await _workout(session, user, [REPS_2x8], title="J9 existing workout")
    created_plan = await v2_post(
        session,
        user.telegram_id,
        "/api/v2/custom-plans",
        {
            "display_name": "J9 actual plan",
            "workout_ids": [workout.id],
            "weeks": [2],
        },
    )
    assert created_plan.status_code == 200, created_plan.text
    custom_id = created_plan.json()["id"]
    manual = await _manual(
        session,
        user,
        workout,
        [["8", "7"]],
        performed_at="2026-10-07T09:00:00+00:00",
        duration_seconds=1800,
    )
    assert manual.status_code == 200, manual.text
    manual_id = manual.json()["id"]
    plan_before, analytics_before, cards_before = await _views(session, user)
    plan = plan_before["plan"]
    rows = sorted(plan["plan_items"], key=lambda item: item["occurrence_index"])
    assert [
        (i["source"], i["custom_plan_id"], i["count_per_week"], i["occurrence_index"]) for i in rows
    ] == [("custom_plan", custom_id, 1, 1), ("custom_plan", custom_id, 1, 2)]
    assert all(i["credited_session_id"] is None and i["done_count"] == 0 for i in rows)
    assert [(s["planned"], s["completed"]) for s in plan["week_summaries"]] == [(2, 0)]
    assert (
        analytics_before["metrics"]["total_workouts"],
        analytics_before["metrics"]["total_minutes"],
    ) == (1, 30)
    [existing_exercise] = analytics_before["exercises"]
    assert existing_exercise["exercise_id"] == exercise.id
    [panel] = existing_exercise["panels"]
    assert panel["protocol_type"] == "reps_sets"
    assert (Decimal(panel["total_reps"]), Decimal(panel["best_set"])) == (15, 8)
    assert set(cards_before) == {manual_id}
    assert (cards_before[manual_id]["source_v2"], cards_before[manual_id]["duration_source"]) == (
        "manual_existing_workout",
        "entered",
    )
    protected = await _protected_rows(session, user.id, manual_id)
    assert len(protected["targets"]) == len(protected["logs"]) == 2
    exercise_before = copy.deepcopy(analytics_before["exercises"])

    created = await v2_post(
        session,
        user.telegram_id,
        "/api/v2/sessions",
        {
            "source": "freeform",
            "performed_at": "2026-10-08T09:00:00+00:00",
            "blocks": [],
            "activity_type": "running",
            "duration_seconds": 2700,
        },
    )
    assert created.status_code == 200, created.text
    activity_id = created.json()["id"]
    for kind, title, seconds, minutes, global_minutes in (
        ("running", "Бег", 2700, 45, 75),
        ("cycling", "Велосипед", 3600, 60, 90),
    ):
        if kind == "cycling":
            edited = await v2_patch(
                session,
                user.telegram_id,
                f"/api/v2/sessions/{activity_id}",
                {
                    "activity_type": kind,
                    "duration_seconds": seconds,
                },
            )
            assert edited.status_code == 200, edited.text
        plan_after, analytics_after, cards_after = await _views(session, user)
        assert plan_after == plan_before
        assert analytics_after["exercises"] == exercise_before
        assert cards_after[manual_id] == cards_before[manual_id]
        assert set(cards_after) == {manual_id, activity_id}
        card = cards_after[activity_id]
        assert (card["id"], card["title"], card["activity_type"], card["duration_seconds"]) == (
            activity_id,
            title,
            kind,
            seconds,
        )
        assert (
            card["source"],
            card["source_v2"],
            card["kind"],
            card["origin"],
            card["duration_source"],
        ) == (
            "freeform",
            "external_activity",
            "external_activity",
            "native",
            "entered",
        )
        assert (
            card["plan_item_id"] is None
            and card["workout_definition_id"] is None
            and card["blocks"] == []
        )
        assert datetime.fromisoformat(card["performed_at"]) == datetime(2026, 10, 8, 9, tzinfo=UTC)
        assert card["revision"] == (0 if kind == "running" else 1)
        metrics = analytics_after["metrics"]
        assert (
            metrics["total_workouts"],
            metrics["total_minutes"],
            metrics["without_duration"],
        ) == (2, global_minutes, 0)
        assert metrics["weeks"] == [
            {"week_start": "2026-10-05", "workouts": 2, "minutes": global_minutes}
        ]
        distribution = analytics_after["distribution"]
        assert (distribution["total_workouts"], distribution["total_minutes"]) == (
            2,
            global_minutes,
        )
        other = next(c for c in distribution["categories"] if c["name"] == "Другая активность")
        assert (other["workouts"], other["minutes"]) == (1, minutes)
        assert [(s["name"], s["workouts"], s["minutes"]) for s in other["subcategories"]] == [
            (title, 1, minutes)
        ]
        row = await session.get(TrainingSession, activity_id, populate_existing=True)
        assert row.plan_item_id is None and row.program_inclusion_id is None
        assert await _protected_rows(session, user.id, manual_id) == protected
