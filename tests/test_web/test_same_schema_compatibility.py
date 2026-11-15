"""Same-schema verification accepts states produced by supported onboarding and plan APIs."""

from datetime import date

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Gender
from app.db.models_program import TrainingPlan
from app.domain.multi_program import is_plannable_week_number, plan_week_number
from app.services.onboarding import OnboardingService
from scripts.backfill_multi_program import seed_catalog, verify_compatible_database
from tests.test_scripts.test_backfill_multi_program import NOW, _guarded_database_hashes
from tests.test_web._v2_client import v2_get, v2_post
from tests.test_web.test_v2_plan_items_with_week import _make_exercise, _make_workout
from tests.test_web.test_v2_plan_overview import _program

pytestmark = pytest.mark.usefixtures("plan_calendar")


async def _verify(session):
    await session.commit()
    async with AsyncSession(bind=session.bind, expire_on_commit=False) as verifier:
        return await verify_compatible_database(verifier)


async def test_real_onboarding_without_plan_is_compatible_and_read_only(session, user):
    await seed_catalog(session)
    onboarding = OnboardingService(session)
    await onboarding.record_baseline_and_start(user_id=user.id, performed_at=NOW, reps=8)
    await onboarding.complete_questionnaire_and_start_trial(
        user_id=user.id,
        weight_kg=78,
        height_cm=180,
        gender=Gender.MALE,
        birth_date=date(1998, 5, 20),
        timezone="UTC",
        now=NOW,
    )
    response = await v2_get(session, user.telegram_id, "/api/v2/plan")
    assert response.status_code == 200 and response.json()["plan"] is None
    assert await session.scalar(select(TrainingPlan).where(TrainingPlan.user_id == user.id)) is None
    before = await _guarded_database_hashes(session)
    result = await _verify(session)
    assert result["verified"] is True, result
    assert result["mode"] == "verify-compatible"
    assert result["counts"]["compatible_onboarded_without_plan"] == 1
    assert await _guarded_database_hashes(session) == before


@pytest.mark.parametrize("runtime_state", ["empty", "manual", "custom", "removed", "multiple"])
async def test_public_runtime_plan_states_are_compatible_without_onboarding(
    session, user, runtime_state
):
    await seed_catalog(session)
    assert user.onboarding_completed_at is None
    if runtime_state == "empty":
        response = await v2_post(
            session, user.telegram_id, "/api/v2/plan/weeks", {"week_number": 1}
        )
    elif runtime_state == "manual":
        exercise = await _make_exercise(session)
        response = await v2_post(
            session,
            user.telegram_id,
            "/api/v2/plan-items",
            {
                "exercise_id": exercise.id,
                "count_per_week": 2,
            },
        )
    elif runtime_state == "custom":
        workout = await _make_workout(session, user)
        response = await v2_post(
            session,
            user.telegram_id,
            "/api/v2/custom-plans",
            {
                "display_name": "Custom",
                "workout_ids": [workout.id],
                "weeks": [2, 0, 2],
            },
        )
    else:
        program = await _program(session)
        response = await v2_post(
            session, user.telegram_id, "/api/v2/program-inclusions", {"program_id": program.id}
        )
        assert response.status_code == 200, response.text
        if runtime_state == "removed":
            response = await v2_post(
                session,
                user.telegram_id,
                f"/api/v2/program-inclusions/{response.json()['id']}/deactivate",
                {},
            )
        else:
            other = await _program(session)
            response = await v2_post(
                session, user.telegram_id, "/api/v2/program-inclusions", {"program_id": other.id}
            )
    assert response.status_code == 200, response.text
    before = await _guarded_database_hashes(session)
    result = await _verify(session)
    assert result["verified"] is True, result
    assert result["counts"]["non_onboarded_with_plan"] == 1
    assert result["counts"]["training_plans_total"] == 1
    assert await _guarded_database_hashes(session) == before


@pytest.mark.parametrize("created,today,expected_week", [
    (date(2026, 11, 15), date(2026, 11, 15), 1),
    (date(2026, 11, 15), date(2026, 11, 16), 2),
    (date(2026, 5, 31), date(2026, 6, 1), 2),
    (date(2028, 12, 31), date(2029, 1, 1), 2),
])
def test_fresh_empty_plan_forward_week_stays_valid_at_calendar_boundaries(created, today, expected_week):
    current_week = plan_week_number(created, today)
    assert current_week == expected_week
    assert is_plannable_week_number(2, current_week)


@pytest.mark.parametrize(
    "reference",
    [
        "week",
        "origin_week",
        "inclusion",
        "custom",
        "custom_owner",
        "session_item",
        "session_inclusion",
        "session_m2m",
    ],
)
async def test_cross_owner_references_are_not_runtime_compatible(session, user, reference):
    from app.db.models import User
    from app.db.models_program import (
        CustomPlan,
        PlanItem,
        PlanWeek,
        ProgramInclusion,
        SessionPlanItem,
        TrainingSession,
    )
    from app.db.repositories.training_plans import TrainingPlanRepository
    from app.domain.multi_program import SessionSource, WeekPhase

    await seed_catalog(session)
    plans = TrainingPlanRepository(session)
    own = await plans.get_or_create_for_user(user.id)
    other = User(telegram_id=787878)
    session.add(other)
    await session.flush()
    foreign = await plans.get_or_create_for_user(other.id)
    week = PlanWeek(
        training_plan_id=foreign.id, week_number=1, start_date=NOW.date(), phase=WeekPhase.BASE
    )
    program = await _program(session)
    inclusion = ProgramInclusion(
        training_plan_id=foreign.id, program_id=program.id, snapshot={}, progression_state={}
    )
    custom = CustomPlan(
        user_id=other.id,
        training_plan_id=foreign.id,
        display_name="Foreign",
        start_week_number=1,
        workouts=[],
        weeks=[],
    )
    session.add_all([week, inclusion, custom])
    await session.flush()
    exercise = await _make_exercise(session)
    item = PlanItem(training_plan_id=own.id, exercise_id=exercise.id, count_per_week=1)
    session.add(item)
    await session.flush()
    expected = "plan_item_reference_mismatch=1"
    if reference == "week":
        item.plan_week_id = week.id
    elif reference == "origin_week":
        item.origin_plan_week_id = week.id
    elif reference == "inclusion":
        item.program_inclusion_id = inclusion.id
    elif reference == "custom":
        item.custom_plan_id = custom.id
    elif reference == "custom_owner":
        custom.user_id = user.id
        expected = "custom_plan_owner_mismatch=1"
    else:
        foreign_item = PlanItem(
            training_plan_id=foreign.id, exercise_id=exercise.id, count_per_week=1
        )
        session.add(foreign_item)
        await session.flush()
        native = TrainingSession(
            user_id=user.id,
            source=SessionSource.FREEFORM,
            origin="native",
            status="completed",
            performed_at=NOW,
        )
        session.add(native)
        await session.flush()
        expected = "session_reference_owner_mismatch=1"
        if reference == "session_item":
            native.plan_item_id = foreign_item.id
        elif reference == "session_inclusion":
            native.program_inclusion_id = inclusion.id
        else:
            session.add(SessionPlanItem(session_id=native.id, plan_item_id=foreign_item.id))
            expected = "session_plan_item_owner_mismatch=1"
    await session.flush()
    before = await _guarded_database_hashes(session)
    result = await _verify(session)
    assert result["verified"] is False
    assert expected in result["errors"]
    assert await _guarded_database_hashes(session) == before


async def test_compatible_mode_server_rejects_accidental_write(session, user, monkeypatch):
    from sqlalchemy.exc import DBAPIError

    from app.services.legacy_history_convergence import LegacyHistoryConvergenceService

    await seed_catalog(session)

    async def accidental_writer(self, user_id, *, apply):
        await self._session.execute(
            text("UPDATE users SET username='must not write' WHERE id=:id"), {"id": user_id}
        )

    monkeypatch.setattr(LegacyHistoryConvergenceService, "converge_user", accidental_writer)
    with pytest.raises(DBAPIError, match="read-only"):
        await _verify(session)


async def test_mixed_migrated_history_removed_course_and_empty_onboarding_are_compatible(
    session, user
):
    from app.db.repositories.users import UserRepository
    from scripts.backfill_multi_program import backfill_all
    from tests.test_scripts.test_backfill_multi_program import _onboard, _record_legacy_workout

    await _onboard(session, user)
    await _record_legacy_workout(session, user)
    await backfill_all(session, now=NOW)
    plan = (await v2_get(session, user.telegram_id, "/api/v2/plan")).json()["plan"]
    inclusion = plan["program_inclusions"][0]
    removed = await v2_post(
        session, user.telegram_id, f"/api/v2/program-inclusions/{inclusion['id']}/deactivate", {}
    )
    assert removed.status_code == 200
    empty = await UserRepository(session).create(telegram_id=787879)
    await _onboard(session, empty)
    before = await _guarded_database_hashes(session)
    result = await _verify(session)
    assert result["verified"] is True, result
    assert result["history_mutations"] == result["unresolved"] == 0
    assert (
        result["counts"]["onboarded_with_plan"]
        == result["counts"]["compatible_onboarded_without_plan"]
        == 1
    )
    assert await _guarded_database_hashes(session) == before


async def test_compatible_all_user_history_ambiguity_still_blocks_without_writes(session):
    from tests.test_web.test_elective_copy_convergence import _all_copies_deleted

    await seed_catalog(session)
    user, _ = await _all_copies_deleted(session, 787880, with_workout=True)
    await session.execute(text("DELETE FROM training_plans WHERE user_id=:id"), {"id": user.id})
    before = await _guarded_database_hashes(session)
    result = await _verify(session)
    assert result["verified"] is False
    assert result["unresolved"] > 0
    assert "history_without_plan=1" in result["errors"]
    assert await _guarded_database_hashes(session) == before
