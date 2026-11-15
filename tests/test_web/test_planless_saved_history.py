"""Ordinary saved-workout producers are independent of plans and account progress."""

import uuid
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.db.models import SubscriptionStatus
from app.db.models_program import (
    SessionEvent,
    TrainingPlan,
    TrainingSession,
    WorkoutDefinitionVersion,
)
from app.db.repositories.training_sessions import TrainingSessionRepository
from app.db.repositories.users import UserRepository
from app.domain import live_engine as engine_domain
from app.domain.live_engine import EngineError
from app.services import live_engine
from app.services.live_engine import LiveEngineService
from app.services.workout_definition import WorkoutDefinitionService
from scripts.backfill_multi_program import seed_catalog
from tests.test_scripts.test_backfill_multi_program import _guarded_database_hashes
from tests.test_scripts.test_planless_candidate_preflight import candidate_counts
from tests.test_web._v2_client import v2_get, v2_patch, v2_post
from tests.test_web.test_same_schema_compatibility import _verify
from tests.test_web.test_v2_mixed_workout import _advance, _log_set
from tests.test_web.test_v2_training_session_v2 import _manual, _workout

LIVE = "/api/v2/sessions/live"
PROTOCOL = {
    "type": "reps_sets",
    "rest_seconds": 0,
    "prescription": {"source": "static", "sets": 1, "reps": 8},
}


@pytest.mark.parametrize("producer", ["manual", "live_v1", "live_v2"])
@pytest.mark.parametrize("versioned", [False, True])
@pytest.mark.parametrize("owner", ["user", "system"])
async def test_saved_workout_planless_account_invariance(
    session, user, test_dsn, monkeypatch, producer, versioned, owner
):
    await seed_catalog(session)
    now = datetime.now(UTC)
    await UserRepository(session).update_subscription_cache(
        user.id,
        status=SubscriptionStatus.TRIAL,
        expires_at=now + timedelta(days=14),
    )
    workout, [exercise] = await _workout(session, user, [PROTOCOL])
    if owner == "system":
        workout.source_type = "system"
        workout.owner_user_id = None
    if versioned:
        await WorkoutDefinitionService(session).sync_head(workout.id)
    other = await UserRepository(session).create(telegram_id=787889)
    await session.commit()
    account = await _guarded_database_hashes(session)
    key = str(uuid.uuid4())
    if producer == "manual":
        path = "/api/v2/sessions"
        payload = {
            "client_session_id": key,
            "source": "backdated",
            "performed_at": now.isoformat(),
            "workout_definition_id": workout.id,
            "blocks": [
                {
                    "exercise_id": exercise.id,
                    "sets": [
                        {"set_number": 1, "metric_type": "reps", "value": "8", "unit": "reps"},
                    ],
                }
            ],
        }
    else:
        path = LIVE
        payload = {
            "client_session_id": key,
            "workout_id": workout.id,
            "engine_version": 2 if producer == "live_v2" else 1,
        }
    response = await v2_post(session, user.telegram_id, path, payload)
    assert response.status_code == 200, response.text
    sid = response.json()["id"]
    if producer == "live_v1":
        body = await _advance(session, user, response.json())
        await _log_set(session, user, body, set_index=0, value="8")
    elif producer == "live_v2":
        started_at = response.json()["engine"]["state"]["started_at"]
        monkeypatch.setattr(live_engine, "_utcnow", lambda: live_engine.from_ms(started_at + 6000))
        event = {
            "client_event_id": str(uuid.uuid4()),
            "type": "submit_result",
            "payload": {
                "block_index": 0,
                "set_index": 0,
                "round_index": None,
                "value": 8,
            },
        }
        logged = await v2_post(
            session, user.telegram_id, f"{LIVE}/{sid}/events", {"events": [event]}
        )
        assert logged.status_code == 200, logged.text
    if producer != "manual":
        complete = await v2_post(
            session, user.telegram_id, f"{LIVE}/{sid}/complete", {"abandoned": True}
        )
        assert complete.status_code == 200, complete.text
    after = await _guarded_database_hashes(session)
    assert {table for table in account if account[table] != after[table]} <= {
        "training_sessions",
        "session_blocks",
        "set_targets",
        "set_logs",
        "session_events",
    }
    replay = await v2_post(session, user.telegram_id, path, payload)
    assert replay.status_code == 200 and replay.json()["id"] == sid, replay.text
    assert await _guarded_database_hashes(session) == after
    if producer == "live_v1":
        replay = await v2_post(
            session, user.telegram_id, f"{LIVE}/{sid}/complete", {"abandoned": True}
        )
        assert replay.status_code == 200
        assert await _guarded_database_hashes(session) == after
    elif producer == "live_v2":
        replay = await v2_post(
            session, user.telegram_id, f"{LIVE}/{sid}/events", {"events": [event]}
        )
        assert replay.status_code == 200
        assert await _guarded_database_hashes(session) == after
    if producer == "live_v2":
        stored = await session.get(TrainingSession, sid)
        assert await LiveEngineService(session).rebuild_state(sid) == stored.engine_state
        await session.commit()
    listing = await v2_get(session, user.telegram_id, "/api/v2/sessions")
    card = listing.json()["sessions"][0]
    assert card["id"] == sid and card["workout_definition_id"] == workout.id
    frozen = card["prescription_snapshot"]
    assert frozen and frozen["workout_definition_id"] == workout.id
    assert card["source_v2"] == (
        "manual_existing_workout" if producer == "manual" else "direct_live"
    )
    for endpoint in ("/api/v2/plan", "/api/hello", "/api/profile", "/api/history"):
        assert (await v2_get(session, user.telegram_id, endpoint)).status_code == 200
    assert await _guarded_database_hashes(session) == after
    assert (
        await v2_patch(
            session, other.telegram_id, f"/api/v2/sessions/{sid}", {"comment": "foreign"}
        )
    ).status_code == 404
    assert await _guarded_database_hashes(session) == after
    edited = await v2_patch(
        session,
        user.telegram_id,
        f"/api/v2/sessions/{sid}",
        {
            "comment": "Corrected historical fact",
            "sets": [{"block_index": 0, "set_number": 1, "value": "9"}],
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["prescription_snapshot"] == frozen
    assert edited.json()["comment"] == "Corrected historical fact"
    assert edited.json()["blocks"][0]["set_logs"][0]["value"] == "9.00"
    edited_hashes = await _guarded_database_hashes(session)
    assert {table for table in after if after[table] != edited_hashes[table]} <= {
        "training_sessions",
        "set_logs",
    }
    clone = await v2_post(
        session,
        user.telegram_id,
        f"/api/v2/sessions/{sid}/clone",
        {
            "performed_at": (now - timedelta(days=1)).isoformat(),
        },
    )
    assert clone.status_code == 201, clone.text
    assert clone.json()["source_v2"] == "manual_existing_workout"
    assert clone.json()["workout_definition_id"] == workout.id
    assert clone.json()["prescription_snapshot"] == frozen
    reread = await v2_get(session, user.telegram_id, "/api/v2/sessions")
    original = next(card for card in reread.json()["sessions"] if card["id"] == sid)
    assert original["blocks"][0]["set_logs"][0]["value"] == "9.00"
    before_verify = await _guarded_database_hashes(session)
    assert {table for table in account if account[table] != before_verify[table]} <= {
        "training_sessions",
        "session_blocks",
        "set_targets",
        "set_logs",
        "session_events",
    }
    assert await session.scalar(select(TrainingPlan.id)) is None
    result = await _verify(session)
    assert result["verified"] is True and result["errors"] == [], result
    assert result["history_mutations"] == result["unresolved"] == 0
    assert (await candidate_counts(test_dsn))[:8] == [
        result["counts"][key]
        for key in (
            "users_total",
            "users_onboarded",
            "onboarded_with_plan",
            "compatible_onboarded_without_plan",
            "non_onboarded_with_plan",
            "compatible_non_onboarded_without_plan",
            "blocked_without_plan",
            "training_plans_total",
        )
    ]
    assert await _guarded_database_hashes(session) == before_verify


@pytest.mark.parametrize(
    "unsafe",
    [
        "foreign_definition",
        "foreign_version",
        "snapshot_identity",
        "snapshot_version",
        "snapshot_missing",
        "snapshot_blocks",
        "snapshot_progression",
        "snapshot_unknown_provenance",
        "snapshot_course",
        "workout_snapshot_identity",
        "manual_engine",
        "unknown_kind",
        "planned_source",
        "direct_missing_engine",
        "direct_unknown_engine",
        "direct_v1_with_cache",
        "direct_v2_active",
        "direct_v2_cancelled",
        "direct_v2_missing_events",
        "direct_v2_start_only",
    ],
)
async def test_saved_history_unknown_or_progression_shapes_remain_blocked(
    session, user, test_dsn, unsafe
):
    await seed_catalog(session)
    workout, _ = await _workout(session, user, [PROTOCOL])
    await WorkoutDefinitionService(session).sync_head(workout.id)
    created = await _manual(session, user, workout, [["8"]])
    assert created.status_code == 200, created.text
    # A safe second record must never mask one unproved record on the same account.
    safe = await _manual(session, user, workout, [["8"]])
    assert safe.status_code == 200
    native = await session.get(TrainingSession, created.json()["id"])
    snapshot = deepcopy(native.prescription_snapshot)
    if unsafe == "foreign_definition":
        workout.owner_user_id = (await UserRepository(session).create(telegram_id=787889)).id
    elif unsafe == "foreign_version":
        other, _ = await _workout(session, user, [PROTOCOL])
        await WorkoutDefinitionService(session).sync_head(other.id)
        version = await session.scalar(
            select(WorkoutDefinitionVersion).where(
                WorkoutDefinitionVersion.workout_definition_id == other.id,
            )
        )
        native.workout_definition_version_id = version.id
        snapshot["workout_definition_version_id"] = version.id
    elif unsafe == "snapshot_identity":
        snapshot["workout_definition_id"] = workout.id + 100
    elif unsafe == "snapshot_version":
        snapshot["workout_definition_version_id"] = None
    elif unsafe == "snapshot_missing":
        snapshot = None
    elif unsafe == "snapshot_blocks":
        snapshot["blocks"] = {}
    elif unsafe == "snapshot_progression":
        snapshot["provenance"]["kind"] = "progression"
    elif unsafe == "snapshot_unknown_provenance":
        snapshot["provenance"]["kind"] = "unprescribed"
    elif unsafe == "snapshot_course":
        snapshot["provenance"]["program_inclusion_id"] = 123
    elif unsafe == "workout_snapshot_identity":
        native.workout_snapshot = {**native.workout_snapshot, "workout_id": workout.id + 100}
    elif unsafe == "manual_engine":
        native.engine_version = 1
    elif unsafe == "unknown_kind":
        native.kind = "external_activity"
    elif unsafe == "planned_source":
        native.source_v2 = "planned_live"
    else:
        native.source_v2 = "direct_live"
        native.source = "freeform"
        if unsafe == "direct_unknown_engine":
            native.engine_version = 99
        elif unsafe == "direct_v1_with_cache":
            native.engine_version = 1
            native.engine_state = {}
        elif unsafe != "direct_missing_engine":
            native.engine_version = 2
            native.engine_status = (
                "active"
                if unsafe == "direct_v2_active"
                else "cancelled"
                if unsafe == "direct_v2_cancelled"
                else "completed"
            )
            native.engine_plan = {"blocks": []}
            native.engine_state = {
                "engine_version": 2,
                "status": native.engine_status,
                "phase": "COMPLETE",
            }
            if unsafe == "direct_v2_start_only":
                session.add(
                    SessionEvent(
                        session_id=native.id,
                        seq=0,
                        type="start",
                        payload={},
                        server_at=datetime.now(UTC),
                        outcome="applied",
                    )
                )
    native.prescription_snapshot = snapshot
    await session.flush()
    if unsafe == "direct_v2_start_only":
        detail = await TrainingSessionRepository(session).get_for_user(native.id, user.id)
        with pytest.raises(KeyError, match="paused_at"):
            live_engine.engine_view(detail, datetime.now(UTC))
        with pytest.raises(EngineError, match="plan.blocks"):
            await LiveEngineService(session).rebuild_state(native.id)
    before = await _guarded_database_hashes(session)
    result = await _verify(session)
    assert result["verified"] is False and "history_without_plan=1" in result["errors"], result
    fields = await candidate_counts(test_dsn)
    expected_reason = (
        13
        if unsafe == "planned_source"
        else 16
        if "engine" in unsafe or unsafe.startswith("direct_")
        else 15
    )
    assert fields[6] == 1
    assert fields[8:18] == [int(index == expected_reason) for index in range(8, 18)]
    assert await _guarded_database_hashes(session) == before


@pytest.mark.parametrize("protocol_kind", ["time", "max", "interval", "extra"])
async def test_terminal_engine_protocols_and_extra_sets_remain_compatible(
    session, user, test_dsn, monkeypatch, protocol_kind
):
    from tests.test_web.test_v2_live_engine import _builder

    await seed_catalog(session)
    protocol = {
        "time": {
            "type": "time_sets",
            "rest_seconds": 0,
            "prescription": {"source": "static", "sets": 1, "duration_seconds": 1},
        },
        "max": {
            "type": "max_effort",
            "rest_seconds": 0,
            "prescription": {"source": "static", "attempts": 1},
        },
        "interval": {
            "type": "interval",
            "total_duration_seconds": 2,
            "work_seconds": 1,
            "rest_seconds": 1,
            "starts_with": "work",
        },
        "extra": PROTOCOL,
    }[protocol_kind]
    workout = await _builder(session, user, [protocol])
    started = await v2_post(
        session,
        user.telegram_id,
        LIVE,
        {
            "client_session_id": str(uuid.uuid4()),
            "workout_id": workout.id,
            "engine_version": 2,
        },
    )
    assert started.status_code == 200, started.text
    sid = started.json()["id"]
    at = started.json()["engine"]["state"]["started_at"] + 10000
    monkeypatch.setattr(live_engine, "_utcnow", lambda: live_engine.from_ms(at))
    if protocol_kind in {"max", "extra"}:
        response = await v2_post(
            session,
            user.telegram_id,
            f"{LIVE}/{sid}/events",
            {
                "events": [
                    {
                        "client_event_id": str(uuid.uuid4()),
                        "type": "submit_result",
                        "payload": {
                            "block_index": 0,
                            "set_index": 0,
                            "round_index": None,
                            "value": 8,
                        },
                    }
                ]
            },
        )
        assert response.status_code == 200, response.text
        if protocol_kind == "extra":
            response = await v2_post(
                session,
                user.telegram_id,
                f"{LIVE}/{sid}/events",
                {
                    "events": [
                        {
                            "client_event_id": str(uuid.uuid4()),
                            "type": "add_extra_set",
                            "payload": {"block_index": 0, "value": 7},
                        }
                    ]
                },
            )
            assert response.status_code == 200, response.text
    else:
        assert (await v2_get(session, user.telegram_id, f"{LIVE}/active")).json()["session"] is None
    native = await session.get(TrainingSession, sid)
    assert native.engine_status == "completed"
    assert await LiveEngineService(session).rebuild_state(sid) == native.engine_state
    await session.commit()
    before = await _guarded_database_hashes(session)
    result = await _verify(session)
    assert result["verified"] is True, result
    assert (await candidate_counts(test_dsn))[6] == 0
    assert await _guarded_database_hashes(session) == before


@pytest.mark.parametrize(
    "tamper",
    [
        "logs",
        "time_target",
        "set_rest",
        "block_rest",
        "finishing_events",
        "cursor_block",
        "cursor_set",
        "cursor_huge",
        "log_index_huge",
        "log_set_huge",
        "log_round_huge",
    ],
)
async def test_completed_engine_cache_must_satisfy_actual_readers(
    session, user, test_dsn, monkeypatch, tamper
):
    await seed_catalog(session)
    workout, _ = await _workout(session, user, [PROTOCOL])
    started = await v2_post(
        session,
        user.telegram_id,
        LIVE,
        {
            "client_session_id": str(uuid.uuid4()),
            "workout_id": workout.id,
            "engine_version": 2,
        },
    )
    assert started.status_code == 200, started.text
    sid = started.json()["id"]
    at = started.json()["engine"]["state"]["started_at"] + 6000
    monkeypatch.setattr(live_engine, "_utcnow", lambda: live_engine.from_ms(at))
    completed = await v2_post(
        session,
        user.telegram_id,
        f"{LIVE}/{sid}/events",
        {
            "events": [
                {
                    "client_event_id": str(uuid.uuid4()),
                    "type": "submit_result",
                    "payload": {
                        "block_index": 0,
                        "set_index": 0,
                        "round_index": None,
                        "value": 8,
                    },
                }
            ]
        },
    )
    assert completed.status_code == 200, completed.text
    row = await session.get(TrainingSession, sid)
    assert row.engine_status == "completed"
    plan, state = deepcopy(row.engine_plan), deepcopy(row.engine_state)
    if tamper == "logs":
        state["logs"] = [{}]
        with pytest.raises(KeyError, match="block_index"):
            engine_domain.advance(
                plan,
                state,
                {
                    "type": "correct_previous",
                    "payload": {
                        "block_index": 0,
                        "set_index": 0,
                        "value": 9,
                    },
                },
                at,
            )
    elif tamper.startswith("log_"):
        key = {
            "log_index_huge": "log_index",
            "log_set_huge": "set_index",
            "log_round_huge": "round_index",
        }[tamper]
        state["logs"][0][key] = 10**20
        log = state["logs"][0]
        _, effects = engine_domain.advance(
            plan,
            state,
            {
                "type": "correct_previous",
                "payload": {
                    "block_index": log["block_index"],
                    "set_index": log["set_index"],
                    "round_index": log["round_index"],
                    "value": 9,
                },
            },
            at,
        )
        with pytest.raises(DBAPIError):
            async with session.begin_nested():
                await LiveEngineService(session)._write_log(
                    sid, plan, effects[0]["log"], corrected=True
                )
    elif tamper.startswith("cursor_"):
        state["cursor"]["block_index" if tamper == "cursor_block" else "set_index"] = (
            100000000000000000000 if tamper == "cursor_huge" else 1
        )
        mirrored = live_engine.mirror(state)
        assert mirrored.current_block_index >= len(
            plan["blocks"]
        ) or mirrored.current_set_number > len(plan["blocks"][0]["sets"])
    elif tamper == "finishing_events":
        from sqlalchemy import delete

        await session.execute(
            delete(SessionEvent).where(SessionEvent.session_id == sid, SessionEvent.seq > 0)
        )
        assert await LiveEngineService(session).rebuild_state(sid) != state
    else:
        if tamper == "time_target":
            plan["blocks"][0]["sets"][0] = {"kind": "time"}
        elif tamper == "set_rest":
            plan["blocks"][0]["sets"][0]["rest_after_seconds"] = -1
        else:
            plan["blocks"][0]["rest_after_block_seconds"] = -1
        with pytest.raises(EngineError):
            engine_domain.validate_plan(plan)
    row.engine_plan, row.engine_state = plan, state
    await session.flush()
    before = await _guarded_database_hashes(session)
    result = await _verify(session)
    assert result["verified"] is False and "history_without_plan=1" in result["errors"], result
    counts = await candidate_counts(test_dsn)
    assert counts[6] == counts[16] == 1
    assert await _guarded_database_hashes(session) == before
