from datetime import UTC, datetime
from decimal import Decimal

from app.db.models import SubscriptionSource, SubscriptionStatus, User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.subscriptions import SubscriptionRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.session import BlockLog
from app.services.admin import AdminService

BAND = Decimal("20.0")


async def _record_workout(session, user_id: int, workout_set_id: int) -> None:
    await WorkoutRepository(session).record_workout(
        user_id=user_id, workout_set_id=workout_set_id, performed_at=datetime(2026, 1, 1, tzinfo=UTC),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND,
    )


async def test_compute_funnel_buckets_users_by_furthest_step(session, user: User):
    # user fixture: только создан, ничего больше — "Старт"
    users_repo = UserRepository(session)

    measured = await users_repo.create(telegram_id=2001, username="measured")
    await BaselineRepository(session).create(user_id=measured.id, performed_at=datetime(2026, 1, 1, tzinfo=UTC), reps=8)

    onboarded = await users_repo.create(telegram_id=2002, username="onboarded")
    await BaselineRepository(session).create(user_id=onboarded.id, performed_at=datetime(2026, 1, 1, tzinfo=UTC), reps=8)
    await users_repo.complete_onboarding(onboarded.id, datetime(2026, 1, 1, tzinfo=UTC))

    trained = await users_repo.create(telegram_id=2003, username="trained")
    baseline = await BaselineRepository(session).create(
        user_id=trained.id, performed_at=datetime(2026, 1, 1, tzinfo=UTC), reps=8,
    )
    await users_repo.complete_onboarding(trained.id, datetime(2026, 1, 1, tzinfo=UTC))
    workout_set = await WorkoutSetRepository(session).create(user_id=trained.id, started_from_baseline_id=baseline.id)
    await _record_workout(session, trained.id, workout_set.id)

    trialed = await users_repo.create(telegram_id=2004, username="trialed")
    trialed_baseline = await BaselineRepository(session).create(
        user_id=trialed.id, performed_at=datetime(2026, 1, 1, tzinfo=UTC), reps=8,
    )
    await users_repo.complete_onboarding(trialed.id, datetime(2026, 1, 1, tzinfo=UTC))
    trialed_set = await WorkoutSetRepository(session).create(
        user_id=trialed.id, started_from_baseline_id=trialed_baseline.id,
    )
    await _record_workout(session, trialed.id, trialed_set.id)
    await SubscriptionRepository(session).create(
        user_id=trialed.id, status=SubscriptionStatus.TRIAL, source=SubscriptionSource.TRIAL,
        started_at=datetime(2026, 1, 1, tzinfo=UTC), ends_at=datetime(2026, 1, 15, tzinfo=UTC),
    )

    paid = await users_repo.create(telegram_id=2005, username="paid")
    paid_baseline = await BaselineRepository(session).create(
        user_id=paid.id, performed_at=datetime(2026, 1, 1, tzinfo=UTC), reps=8,
    )
    await users_repo.complete_onboarding(paid.id, datetime(2026, 1, 1, tzinfo=UTC))
    paid_set = await WorkoutSetRepository(session).create(user_id=paid.id, started_from_baseline_id=paid_baseline.id)
    await _record_workout(session, paid.id, paid_set.id)
    await SubscriptionRepository(session).create(
        user_id=paid.id, status=SubscriptionStatus.ACTIVE, source=SubscriptionSource.STARS,
        started_at=datetime(2026, 1, 1, tzinfo=UTC), ends_at=datetime(2026, 2, 1, tzinfo=UTC),
    )

    funnel = await AdminService(session).compute_funnel()

    assert [u.id for u in funnel.steps["Старт"]] == [user.id]
    assert [u.id for u in funnel.steps["Замер"]] == [measured.id]
    assert [u.id for u in funnel.steps["Анкета"]] == [onboarded.id]
    assert [u.id for u in funnel.steps["Первая тренировка"]] == [trained.id]
    assert [u.id for u in funnel.steps["Триал"]] == [trialed.id]
    assert [u.id for u in funnel.steps["Подписка"]] == [paid.id]


async def test_build_user_card_reports_counts_and_targets(session, user: User):
    baseline = await BaselineRepository(session).create(
        user_id=user.id, performed_at=datetime(2026, 1, 1, tzinfo=UTC), reps=8,
    )
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await _record_workout(session, user.id, workout_set.id)

    card = await AdminService(session).build_user_card(user)

    assert card.user.id == user.id
    assert card.baseline_count == 1
    assert card.workout_count == 1
    assert card.target_a.target == 12  # avg=11, step=max(1,ceil(10*0.05)=1)=1 -> 12
