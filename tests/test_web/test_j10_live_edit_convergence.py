"""#309 J10: one edit of measured direct-live history reaches every API read model.

This complements the manual/entered-duration case in test_canonical_history.py
with measured Builder sessions on both live engines.
"""

import copy
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.db.models_program import SessionEvent, TrainingSession
from app.db.repositories import training_sessions
from app.services import live_engine, live_session
from app.web import routes_v2, routes_v2_analytics
from tests.test_web._premium import create_premium_user
from tests.test_web._v2_client import v2_get, v2_patch, v2_post
from tests.test_web.test_v2_live_engine import _active, _event, _post_events, _state, _submit
from tests.test_web.test_v2_training_session_v2 import REPS_2x8, _complete, _start, _workout

FIRST = datetime(2026, 10, 7, 9, tzinfo=UTC)
CONTROL = datetime(2026, 10, 8, 9, tzinfo=UTC)


async def _read_views(session, user):
    analytics = await v2_get(
        session,
        user.telegram_id,
        "/api/v2/analytics/training?from=2026-09-28&to=2026-10-11",
    )
    assert analytics.status_code == 200, analytics.text
    days = {}
    for month in ("2026-09", "2026-10"):
        calendar = await v2_get(session, user.telegram_id, f"/api/v2/journal/days?month={month}")
        assert calendar.status_code == 200, calendar.text
        days.update({d["date"]: d["count"] for d in calendar.json()["days"]})
    listed = await v2_get(
        session,
        user.telegram_id,
        "/api/v2/sessions?status=completed&date_from=2026-09-28&date_to=2026-10-11",
    )
    assert listed.status_code == 200, listed.text
    return analytics.json(), days, {card["id"]: card for card in listed.json()["sessions"]}


async def _frozen_recipe_and_credit(session, session_id):
    row = await session.get(TrainingSession, session_id, populate_existing=True)
    targets = (
        (
            await session.execute(
                text(
                    "SELECT row_to_json(t)::text FROM set_targets t JOIN session_blocks b ON b.id=t.session_block_id "
                    "WHERE b.session_id=:sid ORDER BY t.id",
                ),
                {"sid": session_id},
            )
        )
        .scalars()
        .all()
    )
    events = (
        await session.execute(
            select(SessionEvent.id, SessionEvent.type, SessionEvent.server_at, SessionEvent.payload)
            .where(SessionEvent.session_id == session_id)
            .order_by(SessionEvent.id)
        )
    ).all()
    return copy.deepcopy(
        (
            row.workout_definition_id,
            row.workout_definition_version_id,
            row.workout_snapshot,
            row.prescription_snapshot,
            row.plan_item_id,
            row.program_inclusion_id,
            row.engine_version,
            row.engine_state,
            targets,
            [tuple(event) for event in events],
        )
    )


@pytest.mark.parametrize("engine_version", [pytest.param(1, id="v1"), pytest.param(2, id="v2")])
async def test_date_and_value_edit_of_measured_live_session_moves_journal_and_analytics(
    session,
    monkeypatch,
    engine_version,
):
    now = FIRST

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz is not None else now.replace(tzinfo=None)

    # Both wall-clock duration endpoints and the edit/analytics clocks are fixed.
    for module in (live_session, training_sessions, routes_v2, routes_v2_analytics):
        monkeypatch.setattr(module, "datetime", FixedDatetime)
    monkeypatch.setattr(live_session, "_utcnow", lambda: now)
    monkeypatch.setattr(live_engine, "_utcnow", lambda: now)
    monkeypatch.setattr(routes_v2, "_utcnow", lambda: now)
    # Existing synthetic trial-cache helper satisfies the public Builder gate;
    # this fixture does not create Subscription/payment-provider entitlement rows.
    user = await create_premium_user(session, telegram_id=30910)
    user.timezone = "UTC"
    workout, [exercise] = await _workout(session, user, [REPS_2x8], title="Measured J10 workout")
    ids = []
    for at, minutes, values in ((FIRST, 30, (8, 8)), (CONTROL, 10, (6, 6))):
        now = at
        started = await _start(
            session, user, {"workout_id": workout.id, "engine_version": engine_version}
        )
        session_id = started["id"]
        assert started["engine_version"] == engine_version
        if engine_version == 2:
            now = at + timedelta(seconds=10)
            work = _state(await _active(session, user))
            rest = _state(await _post_events(session, user, session_id, _submit(work, values[0])))
            now += timedelta(seconds=10)
            paused = _state(
                await _post_events(
                    session,
                    user,
                    session_id,
                    _event("pause", {"phase_seq": rest["phase_seq"]}),
                )
            )
            assert paused["phase"] == "REST" and paused["paused_at"] is not None
            now += timedelta(seconds=90)
            await _post_events(
                session, user, session_id, _event("resume", {"phase_seq": paused["phase_seq"]})
            )
            now = at + timedelta(minutes=minutes, seconds=90)
            work = _state(await _active(session, user))
            completed = await _post_events(session, user, session_id, _submit(work, values[1]))
        else:
            batch = await v2_post(
                session,
                user.telegram_id,
                f"/api/v2/sessions/live/{session_id}/sets:batch",
                {
                    "sets": [
                        {
                            "set_index": index,
                            "exercise_id": exercise.id,
                            "value": str(value),
                            "block_index": 0,
                        }
                        for index, value in enumerate(values)
                    ],
                },
            )
            assert batch.status_code == 200, batch.text
            now = at + timedelta(minutes=minutes)
            completed = await _complete(session, user, session_id)
        assert completed["status"] == "completed"
        ids.append(session_id)
    await session.commit()
    target_id, control_id = ids
    recipes = [await _frozen_recipe_and_credit(session, session_id) for session_id in ids]
    before, days, cards = await _read_views(session, user)
    assert days == {"2026-10-07": 1, "2026-10-08": 1}
    assert set(cards) == set(ids)
    target_before = cards[target_id]
    stable = (
        "id",
        "title",
        "source",
        "source_v2",
        "origin",
        "kind",
        "workout_definition_id",
        "workout_definition_version_id",
        "plan_item_id",
        "duration_source",
        "duration_seconds",
    )
    identity = {key: target_before[key] for key in stable}
    assert identity["title"] == "Measured J10 workout"
    assert (identity["source_v2"], identity["kind"]) == ("direct_live", "strength")
    assert identity["workout_definition_id"] == workout.id
    assert identity["plan_item_id"] is None
    row = await session.get(TrainingSession, target_id, populate_existing=True)
    assert row.engine_version == engine_version and row.program_inclusion_id is None
    if engine_version == 2:
        assert row.engine_state["status"] == "completed"
        assert (
            await session.scalar(
                select(SessionEvent.id).where(
                    SessionEvent.session_id == target_id,
                    SessionEvent.type == "pause",
                )
            )
            is not None
        )
    assert (identity["duration_source"], identity["duration_seconds"]) == ("measured", 1800)
    assert (cards[control_id]["duration_source"], cards[control_id]["duration_seconds"]) == (
        "measured",
        600,
    )
    metrics = before["metrics"]
    assert metrics["weeks"] == [
        {"week_start": "2026-09-28", "workouts": 0, "minutes": 0},
        {"week_start": "2026-10-05", "workouts": 2, "minutes": 40},
    ]
    assert (metrics["total_workouts"], metrics["total_minutes"], metrics["without_duration"]) == (
        2,
        40,
        0,
    )
    assert (before["distribution"]["total_workouts"], before["distribution"]["total_minutes"]) == (
        2,
        40,
    )
    [analytics_exercise] = before["exercises"]
    assert analytics_exercise["exercise_id"] == exercise.id
    [panel] = analytics_exercise["panels"]
    assert panel["protocol_type"] == "reps_sets"
    assert (Decimal(panel["total_reps"]), Decimal(panel["best_set"])) == (28, 8)
    assert [p["at"][:10] for p in panel["points"]] == ["2026-10-07", "2026-10-08"]

    edited = await v2_patch(
        session,
        user.telegram_id,
        f"/api/v2/sessions/{target_id}",
        {
            "performed_on": "2026-09-30",
            "sets": [{"block_index": 0, "set_number": 1, "value": "20"}],
        },
    )
    assert edited.status_code == 200, edited.text
    after, days, cards = await _read_views(session, user)
    assert days == {"2026-09-30": 1, "2026-10-08": 1}
    assert set(cards) == set(ids)
    target_after = cards[target_id]
    assert {key: target_after[key] for key in stable} == identity
    assert datetime.fromisoformat(target_before["performed_at"]) == FIRST
    assert datetime.fromisoformat(target_after["performed_at"]) == datetime(
        2026, 9, 30, 9, tzinfo=UTC
    )
    assert target_after["revision"] == target_before["revision"] + 1
    assert [Decimal(log["value"]) for log in target_after["blocks"][0]["set_logs"]] == [20, 8]
    assert [Decimal(log["value"]) for log in cards[control_id]["blocks"][0]["set_logs"]] == [6, 6]
    metrics = after["metrics"]
    assert metrics["weeks"] == [
        {"week_start": "2026-09-28", "workouts": 1, "minutes": 30},
        {"week_start": "2026-10-05", "workouts": 1, "minutes": 10},
    ]
    assert (metrics["total_workouts"], metrics["total_minutes"], metrics["without_duration"]) == (
        2,
        40,
        0,
    )
    assert (after["distribution"]["total_workouts"], after["distribution"]["total_minutes"]) == (
        2,
        40,
    )
    [analytics_exercise] = after["exercises"]
    assert analytics_exercise["exercise_id"] == exercise.id
    [panel] = analytics_exercise["panels"]
    assert panel["protocol_type"] == "reps_sets"
    assert (Decimal(panel["total_reps"]), Decimal(panel["best_set"])) == (40, 20)
    assert [p["at"][:10] for p in panel["points"]] == ["2026-09-30", "2026-10-08"]
    moved_day = await v2_get(
        session,
        user.telegram_id,
        "/api/v2/sessions?status=completed&date_from=2026-09-30&date_to=2026-09-30",
    )
    assert moved_day.status_code == 200, moved_day.text
    assert [card["id"] for card in moved_day.json()["sessions"]] == [target_id]
    assert [await _frozen_recipe_and_credit(session, session_id) for session_id in ids] == recipes
