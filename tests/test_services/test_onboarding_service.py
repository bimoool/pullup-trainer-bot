from datetime import UTC, datetime, timedelta

from app.db.models import Branch, SubscriptionStatus, User
from app.db.repositories.achievements import AchievementRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.domain.constants import TRIAL_DAYS
from app.services.onboarding import OnboardingService

NOW = datetime(2026, 1, 1, tzinfo=UTC)


async def test_record_baseline_band_branch_creates_workout_set(session, user: User):
    service = OnboardingService(session)

    baseline, workout_set, updated_user = await service.record_baseline_and_start(
        user_id=user.id, performed_at=NOW, reps=18, band_thickness_mm=22.0,
    )

    assert baseline.branch_result == Branch.BAND
    assert workout_set is not None
    assert workout_set.set_number == 1
    assert workout_set.started_from_baseline_id == baseline.id
    assert updated_user.branch == Branch.BAND


async def test_record_baseline_assisted_branch_skips_workout_set(session, user: User):
    service = OnboardingService(session)

    baseline, workout_set, updated_user = await service.record_baseline_and_start(
        user_id=user.id, performed_at=NOW, reps=5, band_thickness_mm=32.0,
    )

    assert baseline.branch_result == Branch.ASSISTED
    assert workout_set is None
    assert updated_user.branch == Branch.ASSISTED

    sets = await WorkoutSetRepository(session).list_for_user(user.id)
    assert sets == []


async def test_record_baseline_unlocks_first_baseline_achievement(session, user: User):
    service = OnboardingService(session)
    await service.record_baseline_and_start(user_id=user.id, performed_at=NOW, reps=18, band_thickness_mm=22.0)

    assert await AchievementRepository(session).has_unlocked(user.id, "first_baseline") is True


async def test_second_baseline_does_not_unlock_again(session, user: User):
    service = OnboardingService(session)
    await service.record_baseline_and_start(user_id=user.id, performed_at=NOW, reps=18, band_thickness_mm=22.0)
    await service.record_baseline_and_start(
        user_id=user.id, performed_at=NOW + timedelta(days=90), reps=20, band_thickness_mm=20.0,
    )

    achievements = await AchievementRepository(session).list_for_user(user.id)
    assert [a.code for a in achievements].count("first_baseline") == 1


async def test_complete_questionnaire_starts_trial(session, user: User):
    service = OnboardingService(session)

    updated_user = await service.complete_questionnaire_and_start_trial(
        user_id=user.id, weight_kg=78, height_cm=180, age=27, timezone="Europe/Moscow", now=NOW,
    )

    assert updated_user.weight_kg == 78
    assert updated_user.height_cm == 180
    assert updated_user.age == 27
    assert updated_user.timezone == "Europe/Moscow"
    assert updated_user.onboarding_completed_at == NOW
    assert updated_user.subscription_status == SubscriptionStatus.TRIAL
    assert updated_user.subscription_expires_at == NOW + timedelta(days=TRIAL_DAYS)
