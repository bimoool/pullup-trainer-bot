"""AUDIT C-existing: realistic legacy (bot-era) users. Test-only helper.

phase=pre   : seeds audit_returning_week_transition (legacy) and runs backfill_all(now=-10d)
              (TEST HARNESS INJECTION: time travel; backfill ran 10 days ago).
phase=legacy: seeds the other legacy users. Afterwards the operator runs the REAL
              `python scripts/backfill_multi_program.py` and `python scripts/seed_exercise_library.py`.
Recipes follow scripts/e2e_seed.py (seed_ready / seed_journal_dedupe), onboarding via OnboardingService.
"""
import asyncio
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.db.base import async_session_factory
from app.db.models import ElectiveWorkout, Gender
from app.db.repositories.equipment_items import EquipmentItemRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.electives import ElectiveType
from app.domain.session import BlockLog
from app.services.onboarding import OnboardingService
from app.services.subscription import SubscriptionService

BAND = Decimal("15.0")
Q = {"weight_kg": Decimal(78), "height_cm": 181, "gender": Gender.MALE,
     "birth_date": date(1993, 4, 2), "timezone": "Europe/Moscow"}

async def legacy_user(session, tg, username, *, onboarded_days_ago, workout_days_ago, elective_days_ago=(), baseline_reps=10):
    now = datetime.now(UTC)
    t0 = now - timedelta(days=onboarded_days_ago)
    user = await UserRepository(session).create(telegram_id=tg, username=username)
    ob = OnboardingService(session)
    _b, wset, _u = await ob.record_baseline_and_start(user_id=user.id, performed_at=t0, reps=baseline_reps)
    await ob.complete_questionnaire_and_start_trial(user_id=user.id, now=t0, **Q)
    item = await EquipmentItemRepository(session).create(user_id=user.id, name="Резина 15кг", resistance_kg=BAND)
    repo = WorkoutRepository(session)
    for i, d in enumerate(sorted(workout_days_ago, reverse=True)):
        await repo.record_workout(
            user_id=user.id, workout_set_id=wset.id, performed_at=now - timedelta(days=d, hours=1),
            block_a_reps=BlockLog(working_reps=(10, 10, 10), max_reps=11 + i // 2),
            block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
            block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND,
            block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND,
            block_a_equipment_item_id=item.id, block_b_equipment_item_id=item.id,
        )
    for d in elective_days_ago:
        seq = [12, 10, 8, 6]
        session.add(ElectiveWorkout(user_id=user.id, elective_type=ElectiveType.MAX_REPS_LADDER,
            performed_at=now - timedelta(days=d), reps_sequence=seq, total_reps=sum(seq),
            equipment_type=EquipmentType.BAND, equipment_value=BAND))
    await session.flush()
    return user

async def main(phase):
    now = datetime.now(UTC)
    async with async_session_factory() as s:
        sub = SubscriptionService(s)
        if phase == "pre":
            await legacy_user(s, 7300003, "audit_returning_week_transition", onboarded_days_ago=40,
                              workout_days_ago=[30, 26, 22, 18, 14, 12])
            await sub.extend(  # paid so that access is not the variable
                (await UserRepository(s).get_by_telegram_id(7300003)).id, now=now - timedelta(days=24), days=90,
                source=__import__("app.db.models", fromlist=["SubscriptionSource"]).SubscriptionSource.STARS,
                payment_reference="audit-c-stars-3")
            await s.commit()
            from scripts.backfill_multi_program import backfill_all
            rep = await backfill_all(s, now=now - timedelta(days=10))
            print(rep.render())
        elif phase == "extra3":
            from app.db.models import SubscriptionSource
            for tg, nm in ((7300009, "audit_persist"), (7300010, "audit_interrupt")):
                u = await legacy_user(s, tg, nm, onboarded_days_ago=30, workout_days_ago=[20, 10, 5])
                await sub.extend(u.id, now=now - timedelta(days=14), days=60, source=SubscriptionSource.STARS,
                                 payment_reference=f"audit-c-stars-{tg}")
            await s.commit()
        elif phase in ("extra", "extra2"):
            # added after the first snapshot: a trial user whose last workout is outside MIN_REST_DAYS
            if phase == "extra":
                await legacy_user(s, 7300007, "audit_trial_rested", onboarded_days_ago=7, workout_days_ago=[7, 4])
            await legacy_user(s, 7300008, "audit_expired_b", onboarded_days_ago=45, workout_days_ago=[40, 33])
            await s.commit()
        else:
            u1 = await legacy_user(s, 7300001, "audit_existing_active", onboarded_days_ago=30,
                                   workout_days_ago=[25, 21, 17, 13, 9, 5])
            await sub.extend(u1.id, now=now - timedelta(days=14), days=60,
                             source=__import__("app.db.models", fromlist=["SubscriptionSource"]).SubscriptionSource.STARS,
                             payment_reference="audit-c-stars-1")
            await legacy_user(s, 7300002, "audit_legacy_existing", onboarded_days_ago=12,
                              workout_days_ago=[10, 6, 3], elective_days_ago=[8])
            await legacy_user(s, 7300004, "audit_trial", onboarded_days_ago=4, workout_days_ago=[4, 1])
            u5 = await legacy_user(s, 7300005, "audit_active_paid", onboarded_days_ago=50, workout_days_ago=[45, 38, 30, 20, 8])
            await sub.extend(u5.id, now=now - timedelta(days=20), days=60,
                             source=__import__("app.db.models", fromlist=["SubscriptionSource"]).SubscriptionSource.STARS,
                             payment_reference="audit-c-stars-5")
            await legacy_user(s, 7300006, "audit_expired", onboarded_days_ago=40, workout_days_ago=[36, 30, 24])
            await s.commit()

asyncio.run(main(sys.argv[1]))
