"""Supported journal/reset journeys retain account data without a TrainingPlan."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.db.models import SubscriptionStatus
from app.db.models_program import Exercise, TrainingPlan
from app.db.repositories.users import UserRepository
from app.domain.multi_program import MetricType
from app.services.admin_reset import reset_user_progress
from app.services.onboarding import OnboardingService
from scripts.backfill_multi_program import seed_catalog
from tests.test_scripts.test_backfill_multi_program import (
    _guarded_database_hashes,
    _record_legacy_workout,
)
from tests.test_web._v2_client import v2_get, v2_patch, v2_post
from tests.test_web.test_same_schema_compatibility import _verify


@pytest_asyncio.fixture(autouse=True)
async def _remove_synthetic_cold_archives(session):
    yield
    await session.rollback()
    for table in ("workouts_archive_v1", "workout_sets_archive_v1"):
        await session.execute(text(f"DELETE FROM {table} WHERE id=787885"))
    await session.commit()


@pytest.mark.parametrize(
    "history_kind", ["native", "native_retry", "journal", "reset_archive", "cold_v1", "both"]
)
@pytest.mark.parametrize("onboarded", [False, True])
async def test_normal_planless_history_preserves_account_data(
    session, user, history_kind, onboarded
):
    now = datetime.now(UTC)
    await seed_catalog(session)
    if history_kind == "cold_v1":
        # Literal cold-store shape retained by 34d73f5e17a4, before TrainingPlan existed.
        await session.execute(
            text("""INSERT INTO workouts_archive_v1
            (id,user_id,workout_set_id,performed_at,status,created_at)
            VALUES (787885,:uid,787885,:now,'completed',:now)"""),
            {"uid": user.id, "now": now},
        )
        await session.execute(
            text("""INSERT INTO workout_sets_archive_v1
            (id,user_id,started_from_baseline_id,set_number,workouts_completed,status,started_at)
            VALUES (787885,:uid,787885,1,1,'active',:now)"""),
            {"uid": user.id, "now": now},
        )
    if history_kind in {"reset_archive", "both"}:
        # Use the normal legacy writer and normal reset. Never remove a plan to fabricate the gap.
        await _record_legacy_workout(session, user)
        assert await session.scalar(select(TrainingPlan.id)) is None
        await reset_user_progress(session, user.id)
        await session.refresh(user)
        assert await session.scalar(text("SELECT count(*) FROM workouts_archive_admin_reset")) == 1
    if onboarded:
        onboarding = OnboardingService(session)
        await onboarding.record_baseline_and_start(user_id=user.id, performed_at=now, reps=8)
        await onboarding.complete_questionnaire_and_start_trial(
            user_id=user.id, timezone="UTC", now=now
        )
    native = None
    if history_kind in {"native", "native_retry", "journal", "both"}:
        payload = {
            "source": "freeform",
            "performed_at": (now - timedelta(days=2)).isoformat(),
            "blocks": [],
            "activity_type": "running",
            "duration_seconds": 2700,
        }
        if history_kind == "journal":
            exercise = Exercise(
                name="Journal exercise", metric_type=MetricType.REPS, category="journal"
            )
            session.add(exercise)
            await session.flush()
            payload = {
                "source": "backdated",
                "performed_at": (now - timedelta(days=2)).isoformat(),
                "blocks": [
                    {
                        "exercise_id": exercise.id,
                        "sets": [
                            {
                                "set_number": 1,
                                "metric_type": "reps",
                                "value": "8",
                                "unit": "reps",
                            }
                        ],
                    }
                ],
            }
        if history_kind == "native_retry":
            payload["client_session_id"] = "12345678-1234-5678-1234-567812345678"
        created = await v2_post(session, user.telegram_id, "/api/v2/sessions", payload)
        assert created.status_code == 200, created.text
        native = created.json()
        assert native["source_v2"] == (
            "manual_custom" if history_kind == "journal" else "external_activity"
        )
        assert native["progression_skipped_reason"] == "no_program_inclusion"
        assert native["plan_item_id"] is None
        assert (
            await session.scalar(
                text("SELECT program_inclusion_id FROM training_sessions WHERE id=:id"),
                {"id": native["id"]},
            )
            is None
        )

        if history_kind == "native_retry":
            before_replay = await _guarded_database_hashes(session)
            replay = await v2_post(session, user.telegram_id, "/api/v2/sessions", payload)
            assert replay.status_code == 200 and replay.json()["id"] == native["id"]
            assert replay.json()["progression_skipped_reason"] == "already_recorded"
            assert await _guarded_database_hashes(session) == before_replay

    other = await UserRepository(session).create(telegram_id=787885)
    await session.commit()
    before = await _guarded_database_hashes(session)
    for _ in range(2):
        plan = await v2_get(session, user.telegram_id, "/api/v2/plan")
        assert plan.status_code == 200 and plan.json()["plan"] is None
        listing = await v2_get(session, user.telegram_id, "/api/v2/sessions")
        assert listing.status_code == 200, listing.text
        assert [entry["id"] for entry in listing.json()["sessions"]] == (
            [native["id"]] if native else []
        )
        for path in ("/api/hello", "/api/profile", "/api/history"):
            response = await v2_get(session, user.telegram_id, path)
            assert response.status_code == 200, (path, response.text)
    assert await _guarded_database_hashes(session) == before

    if native:
        path = f"/api/v2/sessions/{native['id']}"
        foreign = await v2_patch(session, other.telegram_id, path, {"comment": "foreign"})
        assert foreign.status_code == 404
        assert await _guarded_database_hashes(session) == before
        changes = {"comment": "Updated journal fact"}
        if history_kind != "journal":
            changes.update(activity_type="cycling", duration_seconds=3600)
        else:
            changes["sets"] = [{"block_index": 0, "set_number": 1, "value": "9"}]
        edited = await v2_patch(session, user.telegram_id, path, changes)
        assert edited.status_code == 200, edited.text
        assert edited.json()["comment"] == "Updated journal fact"
        if history_kind != "journal":
            assert (
                edited.json()["duration_seconds"] == 3600
                and edited.json()["activity_type"] == "cycling"
            )
        else:
            assert edited.json()["blocks"][0]["set_logs"][0]["value"] == "9.00"
        after_edit = await _guarded_database_hashes(session)
        expected_changed = (
            {"training_sessions", "set_logs"}
            if history_kind == "journal"
            else {"training_sessions"}
        )
        assert {table for table in before if before[table] != after_edit[table]} == expected_changed
        before = after_edit

    assert await session.scalar(select(TrainingPlan.id)) is None
    await session.refresh(user)
    assert user.subscription_status == SubscriptionStatus.TRIAL
    assert user.subscription_expires_at > now + timedelta(days=7)
    # Admission must recognize the supported shape without repairing or materializing it.
    result = await _verify(session)
    assert result["history_mutations"] == result["unresolved"] == 0, result
    assert result["verified"] is True and result["errors"] == [], result
    assert await _guarded_database_hashes(session) == before


@pytest.mark.parametrize(
    "unsafe",
    [
        "unsupported_origin",
        "unlabelled",
        "active",
        "unknown_source",
        "planned_source",
        "unknown_v2_source",
        "missing_completion",
        "engine",
        "engine_version",
        "engine_event",
        "definition_version",
        "step_block",
        "foreign_exercise",
        "unknown_block",
        "current_legacy",
        "current_progress",
        "missing_archive",
        "foreign_archive",
        "different_archive_date",
        "unknown_tombstone_reason",
        "unkeyed_tombstone",
        "live_tombstone",
        "unfinished_tombstone",
    ],
)
async def test_archives_do_not_bypass_current_or_unproved_history(session, user, unsafe):
    from app.db.models_program import SessionBlock, TrainingSession
    from tests.test_scripts.test_backfill_multi_program import _make_workout_set

    await seed_catalog(session)
    await _record_legacy_workout(session, user)
    await reset_user_progress(session, user.id)
    created = await v2_post(
        session,
        user.telegram_id,
        "/api/v2/sessions",
        {
            "source": "freeform",
            "performed_at": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
            "blocks": [],
            "activity_type": "running",
            "duration_seconds": 2700,
        },
    )
    assert created.status_code == 200, created.text
    native = await session.get(TrainingSession, created.json()["id"])
    tombstone = await session.scalar(
        select(TrainingSession).where(TrainingSession.origin == "legacy_backfill")
    )
    if unsafe in {"unsupported_origin", "unlabelled"}:
        native.origin = "legacy_elective" if unsafe == "unsupported_origin" else None
    elif unsafe == "active":
        native.status = "started"
    elif unsafe == "unknown_source":
        native.source = "elective"
    elif unsafe == "planned_source":
        native.source_v2 = "planned_live"
    elif unsafe == "unknown_v2_source":
        native.source_v2 = None
    elif unsafe == "missing_completion":
        native.completed_at = None
    elif unsafe == "engine":
        native.engine_status = "active"
    elif unsafe == "engine_version":
        native.engine_version = 2
    elif unsafe == "engine_event":
        from app.db.models_program import SessionEvent

        session.add(
            SessionEvent(
                session_id=native.id,
                seq=1,
                type="start",
                payload={},
                server_at=datetime.now(UTC),
                outcome="applied",
            )
        )
    elif unsafe == "definition_version":
        from app.db.models_program import Complex, WorkoutDefinitionVersion

        workout = Complex(name="Unproved definition", source_type="user", owner_user_id=user.id)
        session.add(workout)
        await session.flush()
        version = WorkoutDefinitionVersion(
            workout_definition_id=workout.id,
            version_no=1,
            schema_version=1,
            content={},
            content_hash="0" * 64,
        )
        session.add(version)
        await session.flush()
        native.workout_definition_version_id = version.id
    elif unsafe in {"step_block", "foreign_exercise", "unknown_block"}:
        if unsafe == "foreign_exercise":
            other = await UserRepository(session).create(telegram_id=787885)
        exercise = Exercise(
            name="Protected role",
            metric_type=MetricType.REPS,
            category="pullups",
            subcategory="block_a" if unsafe == "step_block" else None,
            source_type="user" if unsafe == "foreign_exercise" else "system",
            owner_user_id=other.id if unsafe == "foreign_exercise" else None,
        )
        session.add(exercise)
        await session.flush()
        session.add(
            SessionBlock(
                session_id=native.id,
                exercise_id=None if unsafe == "unknown_block" else exercise.id,
                order_index=0,
            )
        )
    elif unsafe == "current_legacy":
        await _record_legacy_workout(session, user)
    elif unsafe == "current_progress":
        progress = await _make_workout_set(session, user)
        progress.workouts_completed = 1
    elif unsafe == "missing_archive":
        await session.execute(text("DELETE FROM workouts_archive_admin_reset"))
    elif unsafe == "foreign_archive":
        other = await UserRepository(session).create(telegram_id=787885)
        await session.execute(
            text("UPDATE workouts_archive_admin_reset SET user_id=:uid"), {"uid": other.id}
        )
    elif unsafe == "different_archive_date":
        await session.execute(
            text(
                "UPDATE workouts_archive_admin_reset SET performed_at=performed_at-interval '1 day'"
            )
        )
    elif unsafe == "unknown_tombstone_reason":
        tombstone.superseded_reason = None
    elif unsafe == "unkeyed_tombstone":
        tombstone.legacy_id = None
    elif unsafe == "live_tombstone":
        tombstone.superseded_at = None
        tombstone.superseded_reason = None
    elif unsafe == "unfinished_tombstone":
        tombstone.status = "started"
    await session.flush()
    before = await _guarded_database_hashes(session)
    result = await _verify(session)
    assert result["verified"] is False and "history_without_plan=1" in result["errors"], result
    assert await _guarded_database_hashes(session) == before


async def test_native_reason_only_supersession_is_rejected_by_database(session, user):
    from sqlalchemy.exc import IntegrityError

    await seed_catalog(session)
    created = await v2_post(
        session,
        user.telegram_id,
        "/api/v2/sessions",
        {
            "source": "freeform",
            "performed_at": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
            "blocks": [],
            "activity_type": "running",
            "duration_seconds": 2700,
        },
    )
    assert created.status_code == 200
    await session.commit()
    before = await _guarded_database_hashes(session)
    with pytest.raises(IntegrityError, match="ck_training_sessions_superseded_pair"):
        async with session.begin_nested():
            await session.execute(
                text("UPDATE training_sessions SET superseded_reason='legacy_deleted'")
            )
    assert await _guarded_database_hashes(session) == before
    assert (await _verify(session))["verified"] is True
