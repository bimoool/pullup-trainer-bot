"""Synthetic, production-SHAPED database for rehearsing the release tooling on a clean CI host (NOT real data).

Run against an empty database already migrated to the alembic head (`alembic upgrade head`):
  DATABASE_URL=postgresql+asyncpg://... python deploy/rehearsal/make_synthetic_dump.py

Shape (mirrors the production state seen in the 2026-10-19/20 guarded runs): several onboarded users, some with legacy
workouts, every onboarded user ALREADY migrated by the backfill — but the calendar is 3 weeks behind "today", so a
backfill re-apply rolls the PlanWeek over (the exact cause of the phase-8 abort), while --verify-only must not.
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import EquipmentType
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.session import BlockLog
from scripts.backfill_multi_program import backfill_all

BAND = Decimal("18.0")


async def main() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    then = datetime.now(UTC) - timedelta(days=21)
    async with async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)() as session:
        users = UserRepository(session)
        created = [await users.create(telegram_id=910_000_001 + i, username=f"synthetic{i}") for i in range(5)]
        for user in created[:4]:
            await users.complete_onboarding(user.id, then)
        await session.execute(text(
            "update users set rest_seconds_block_a = 300, rest_seconds_block_b = 210, big_break_seconds = 600 where id = :i",
        ), {"i": created[2].id})
        for user in created[:3]:  # legacy history for three users
            baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=then - timedelta(days=60), reps=8)
            workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
            await WorkoutRepository(session).record_workout(
                user_id=user.id, workout_set_id=workout_set.id, performed_at=then,
                block_a_reps=BlockLog(working_reps=(10, 10, 9), max_reps=11),
                block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
                block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND,
                block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND,
            )
        report = await backfill_all(session, now=then)
        await session.commit()
        print(f"synthetic dump source ready: onboarded={report.users_onboarded} migrated={report.users_migrated_this_run} "
              f"calendar anchored at {then.date()}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
