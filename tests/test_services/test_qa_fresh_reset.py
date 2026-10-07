"""🧪 Fresh reset (staging): app/services/qa_fresh_reset.py on a real Postgres.

The caller and a bystander are built with the repo's own realistic recipes (scripts/e2e_seed.py: populated v2 user
with plan/sessions/tests/body metrics/electives; legacy bot workouts; own exercise/workout; favorites; coins;
achievements; events), plus subscription history and a pending payment that must survive."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.db.models import (
    Achievement,
    Coin,
    CoinReason,
    Event,
    PendingPayment,
    PendingPaymentProvider,
    PendingPaymentStatus,
    Subscription,
    SubscriptionSource,
    SubscriptionStatus,
)
from app.db.models_program import Complex, ComplexItem, Exercise, UserFavorite
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.equipment_items import EquipmentItemRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.multi_program import MetricType
from app.domain.session import BlockLog
from app.services import qa_fresh_reset
from app.services.qa_fresh_reset import RESET_STEPS, SYSTEM_COUNTS, run_fresh_reset, schema_drift
from app.services.qa_staging_guard import NotStagingError, StagingEnvironment, identify_staging
from scripts.e2e_seed import seed_sweep_populated

CALLER_TG, OTHER_TG = 7_000_000_101, 7_000_000_102
NOW = datetime.now(UTC)


@pytest.fixture
def staging():
    return StagingEnvironment(db_name="pullup_test", mini_app_host="staging.app.bimoool.com")


async def _populate(session, telegram_id: int) -> int:
    await seed_sweep_populated(session, telegram_id)
    user = await UserRepository(session).get_by_telegram_id(telegram_id)
    uid = user.id
    # legacy (bot era) progress
    baseline = await BaselineRepository(session).create(user_id=uid, performed_at=NOW - timedelta(days=9), reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=uid, started_from_baseline_id=baseline.id)
    band = await EquipmentItemRepository(session).create(user_id=uid, name="зелёная")
    await WorkoutRepository(session).record_workout(
        user_id=uid, workout_set_id=workout_set.id, performed_at=NOW - timedelta(days=8),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=Decimal("20.0"),
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=Decimal("20.0"),
    )
    assert band.id
    # own exercise + own workout + favorite
    own = Exercise(name=f"Своё {telegram_id}", metric_type=MetricType.REPS, category="user", source_type="user", owner_user_id=uid)
    session.add(own)
    await session.flush()
    workout = Complex(name=f"Моя {telegram_id}", source_type="user", owner_user_id=uid)
    session.add(workout)
    await session.flush()
    session.add(ComplexItem(complex_id=workout.id, exercise_id=own.id, order_index=0, sets=0,
                            protocol={"type": "reps_sets", "rest_seconds": 0}))
    session.add(UserFavorite(user_id=uid, target_type="workout", target_id=workout.id))
    # gamification / analytics / payments
    achievement = Achievement(user_id=uid, code="first_workout")
    session.add(achievement)
    await session.flush()
    session.add(Coin(user_id=uid, amount=50, reason=CoinReason.ACHIEVEMENT_UNLOCKED, related_achievement_id=achievement.id))
    session.add(Event(user_id=uid, event_type="workout_completed", payload={}))
    session.add(Subscription(user_id=uid, status=SubscriptionStatus.ACTIVE, source=SubscriptionSource.ADMIN_GRANT,
                             started_at=NOW - timedelta(days=3), ends_at=NOW + timedelta(days=30)))
    session.add(PendingPayment(user_id=uid, provider=PendingPaymentProvider.ROBOKASSA, external_order_id=f"qa-{telegram_id}",
                               days=30, status=PendingPaymentStatus.PENDING))
    user.coins_balance = 50
    user.subscription_status = SubscriptionStatus.ACTIVE
    user.subscription_expires_at = NOW + timedelta(days=30)
    await session.commit()
    return uid


async def _caller_counts(session, uid: int) -> dict[str, int]:
    return {t: (await session.execute(text(f"SELECT count(*) FROM {t} WHERE {w}"), {"uid": uid})).scalar_one()
            for t, w, _ in RESET_STEPS}


async def _all_counts(session) -> dict[str, int]:
    tables = [t for t, _, _ in RESET_STEPS] + ["users", "subscriptions", "pending_payments"]
    out = {t: (await session.execute(text(f"SELECT count(*) FROM {t}"))).scalar_one() for t in tables}
    out.update({k: (await session.execute(text(sql))).scalar_one() for k, sql in SYSTEM_COUNTS.items()})
    return out


async def _user_row(session, uid: int):
    return (await session.execute(text(
        "SELECT telegram_id, username, created_at, subscription_status, subscription_expires_at, "
        "onboarding_completed_at, coins_balance, weight_kg, timezone FROM users WHERE id = :uid",
    ), {"uid": uid})).one()


# --- staging identification (pure) ---------------------------------------------------------------------------------


@pytest.mark.parametrize(("database_url", "mini_app_url", "postgres_db"), [
    ("postgresql+asyncpg://pullup:pw@db:5432/pullup", "https://app.bimoool.com", "pullup"),  # production
    ("postgresql+asyncpg://p:pw@db:5432/pullup_staging", "https://app.bimoool.com", None),  # prod host
    ("postgresql+asyncpg://p:pw@db:5432/pullup", "https://staging.app.bimoool.com", None),  # prod db
    ("postgresql+asyncpg://p:pw@db:5432/pullup_test", "https://staging.app.bimoool.com", None),
    ("postgresql+asyncpg://p:pw@db:5432/pullup_staging", "", None),  # cannot confirm the host
    ("", "https://staging.app.bimoool.com", None),
    ("postgresql+asyncpg://p:pw@db:5432/pullup_staging", "https://staging.app.bimoool.com", "pullup"),
])
def test_anything_not_positively_staging_is_refused(database_url, mini_app_url, postgres_db):
    with pytest.raises(NotStagingError):
        identify_staging(database_url=database_url, mini_app_url=mini_app_url, postgres_db=postgres_db)


def test_staging_is_identified():
    env = identify_staging(
        database_url="postgresql+asyncpg://pullup_staging:pw@db:5432/pullup_staging",
        mini_app_url="https://staging.app.bimoool.com", postgres_db="pullup_staging",
    )
    assert env == StagingEnvironment(db_name="pullup_staging", mini_app_host="staging.app.bimoool.com")


def test_registry_covers_every_orm_table_and_drift_is_detected():
    from app.db.base import Base

    assert schema_drift(set(Base.metadata.tables)) == []
    assert schema_drift(set(Base.metadata.tables) | {"new_user_table"}) == [
        "table 'new_user_table' is not classified for the QA reset",
    ]


# --- service on Postgres ---------------------------------------------------------------------------------------------


async def test_not_staging_is_refused_and_nothing_changes(session):
    uid = await _populate(session, CALLER_TG)
    before = await _caller_counts(session, uid)

    report = await run_fresh_reset(session, telegram_id=CALLER_TG, staging=None, apply=True)

    assert not report.applied and report.guard_failures
    assert await _caller_counts(session, uid) == before


async def test_connected_database_must_be_the_identified_staging_database(session):
    uid = await _populate(session, CALLER_TG)
    before = await _caller_counts(session, uid)
    lying = StagingEnvironment(db_name="pullup_staging", mini_app_host="staging.app.bimoool.com")

    report = await run_fresh_reset(session, telegram_id=CALLER_TG, staging=lying, apply=True)

    assert not report.applied
    assert any("connected database" in f for f in report.guard_failures)
    assert await _caller_counts(session, uid) == before


async def test_dry_run_reports_counts_and_writes_nothing(session, staging):
    uid = await _populate(session, CALLER_TG)
    before_all = await _all_counts(session)
    user_before = await _user_row(session, uid)

    report = await run_fresh_reset(session, telegram_id=CALLER_TG, staging=staging, apply=False)

    assert report.ok and not report.applied and report.guard_failures == []
    for category in ("sessions", "plan", "legacy", "own workouts/exercises", "coins/achievements", "tests"):
        assert report.rows_by_category[category] > 0, category
    assert report.entitlement_status == "active"
    assert await _all_counts(session) == before_all
    assert await _user_row(session, uid) == user_before


async def test_apply_resets_v2_and_legacy_state_and_preserves_identity_entitlement_system_and_others(session, staging):
    uid = await _populate(session, CALLER_TG)
    other_uid = await _populate(session, OTHER_TG)
    other_before = await _caller_counts(session, other_uid)
    all_before = await _all_counts(session)
    caller_before = await _caller_counts(session, uid)
    identity_before = (await _user_row(session, uid))[:5]
    other_user_before = await _user_row(session, other_uid)

    report = await run_fresh_reset(session, telegram_id=CALLER_TG, staging=staging, apply=True)

    assert report.applied and report.ok, report.guard_failures
    assert report.post_state["onboarding"] is False
    assert (report.post_state["plans"], report.post_state["sessions"], report.post_state["coins"]) == (0, 0, 0)
    assert report.post_state["entitlement"] == "active"
    assert all(n == 0 for n in (await _caller_counts(session, uid)).values())
    row = await _user_row(session, uid)
    assert row[:5] == identity_before  # telegram_id, username, created_at, subscription status/expiry
    assert row.onboarding_completed_at is None and row.coins_balance == 0
    assert row.weight_kg is None and row.timezone is None
    # subscription history, pending payments, system catalogue: untouched
    for key in ("subscriptions", "pending_payments", "users", *SYSTEM_COUNTS):
        assert (await _all_counts(session))[key] == all_before[key], key
    # the bystander is untouched
    assert await _caller_counts(session, other_uid) == other_before
    assert await _user_row(session, other_uid) == other_user_before
    # legacy rows are archived, not only deleted (same archive tables as «🧪 Полный сброс»)
    archived = (await session.execute(
        text("SELECT count(*) FROM workouts_archive_admin_reset WHERE user_id = :uid"), {"uid": uid},
    )).scalar_one()
    assert archived == caller_before["workouts"] > 0


async def test_second_reset_is_idempotent(session, staging):
    uid = await _populate(session, CALLER_TG)
    assert (await run_fresh_reset(session, telegram_id=CALLER_TG, staging=staging, apply=True)).applied

    again = await run_fresh_reset(session, telegram_id=CALLER_TG, staging=staging, apply=True)

    assert again.applied and again.ok
    assert sum(again.rows_by_table.values()) == 0
    assert all(n == 0 for n in (await _caller_counts(session, uid)).values())


async def test_expired_entitlement_is_refused(session, staging):
    uid = await _populate(session, CALLER_TG)
    await session.execute(text("UPDATE users SET subscription_expires_at = :t WHERE id = :uid"),
                          {"t": NOW - timedelta(days=1), "uid": uid})
    await session.commit()
    before = await _caller_counts(session, uid)

    report = await run_fresh_reset(session, telegram_id=CALLER_TG, staging=staging, apply=True)

    assert not report.applied
    assert any("entitlement" in f for f in report.guard_failures)
    assert await _caller_counts(session, uid) == before


async def test_reference_from_another_users_row_to_a_caller_row_refuses(session, staging):
    uid = await _populate(session, CALLER_TG)
    other_uid = await _populate(session, OTHER_TG)
    own_exercise_id = (await session.execute(
        text("SELECT id FROM exercises WHERE owner_user_id = :uid LIMIT 1"), {"uid": uid},
    )).scalar_one()
    other_workout = Complex(name="чужая", source_type="user", owner_user_id=other_uid)
    session.add(other_workout)
    await session.flush()
    session.add(ComplexItem(complex_id=other_workout.id, exercise_id=own_exercise_id, order_index=0, sets=0,
                            protocol={"type": "reps_sets", "rest_seconds": 0}))
    await session.commit()
    before = await _all_counts(session)

    report = await run_fresh_reset(session, telegram_id=CALLER_TG, staging=staging, apply=True)

    assert not report.applied
    assert any("complex_items.exercise_id" in f for f in report.guard_failures)
    assert await _all_counts(session) == before


async def test_post_condition_failure_rolls_back_every_delete(session, staging, monkeypatch):
    """The deletes have run; a post-condition (system catalogue changed) fails before COMMIT -> nothing persists."""
    uid = await _populate(session, CALLER_TG)
    all_before = await _all_counts(session)
    user_before = await _user_row(session, uid)
    real = qa_fresh_reset._system_counts
    calls = {"n": 0}

    async def drifting(s):
        calls["n"] += 1
        counts = await real(s)
        return counts if calls["n"] == 1 else {**counts, "programs": counts["programs"] + 1}

    monkeypatch.setattr(qa_fresh_reset, "_system_counts", drifting)

    report = await run_fresh_reset(session, telegram_id=CALLER_TG, staging=staging, apply=True)

    assert not report.applied
    assert "system catalogue counts changed" in report.guard_failures
    assert calls["n"] == 2  # really reached the post-condition after the deletes
    assert await _all_counts(session) == all_before
    assert await _user_row(session, uid) == user_before
    assert (await session.execute(text("SELECT count(*) FROM workouts_archive_admin_reset"))).scalar_one() == 0
