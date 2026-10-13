"""Как ШТАТНЫЙ backfill старого кода расставляет created_at (STAGING_RC_REHEARSAL §8, «Фикс», п. «created_at»).

Запускается СТАРЫМ кодом на чистой БД с его собственной головой Alembic (изолированный Postgres, синтетика):

    cd <old checkout>; PYTHONPATH=<old checkout> BOT_TOKEN=x DATABASE_URL=postgresql+asyncpg://…/<db> \
        alembic upgrade head && python <this repo>/docs/rehearsal/old_backfill_created_at.py

Шаги: (1) онбордингованный пользователь, legacy-тренировка и 2 факультатива — отдельными транзакциями, задолго до
backfill; (2) `backfill_all` — ровно то, что делает `scripts/backfill_multi_program.py` без флагов; (3) пользователь
пишет ещё один факультатив; (4) повторный `backfill_all`. Печатает created_at плана и всех строк training_sessions.
Ожидание (код): копии и план — одна транзакция (равные created_at, now() = начало транзакции); повторный прогон
пользователя с планом пропускает целиком (факультатив из шага 3 копии не получает); путей удаления плана нет.
"""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

import scripts.backfill_multi_program as backfill
from app.db.base import async_session_factory
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.elective_workouts import ElectiveWorkoutRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.electives import ElectiveType
from app.domain.session import BlockLog

TELEGRAM_ID = 880_901


async def _elective(session, user_id: int, kind: ElectiveType, at: datetime, total: int, sequence) -> int:
    elective = await ElectiveWorkoutRepository(session).create(
        user_id=user_id, elective_type=kind, performed_at=at, total_reps=total, reps_sequence=sequence,
        equipment_type=EquipmentType.BODYWEIGHT, equipment_value=None,
    )
    return elective.id


async def _dump(session, user_id: int, title: str) -> None:
    print(f"--- {title}")
    rows = (await session.execute(text(
        "select 'plan' as kind, id, created_at, null as source from training_plans where user_id = :u "
        "union all select 'elective', id, created_at, elective_type::text from elective_workouts where user_id = :u "
        "union all select 'workout', id, created_at, null from workouts where user_id = :u "
        "union all select 'session', id, created_at, source::text from training_sessions where user_id = :u order by 1, 2"),
        {"u": user_id})).all()
    for row in rows:
        print(f"  {row.kind:9} id={row.id:<4} created_at={row.created_at.isoformat()} {row.source or ''}")


async def main() -> None:
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        user = await UserRepository(session).create(telegram_id=TELEGRAM_ID, username="old_backfill_probe")
        await session.execute(text("update users set onboarding_completed_at = now() where id = :u"), {"u": user.id})
        baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=now - timedelta(days=40), reps=10)
        workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
        user_id, workout_set_id = user.id, workout_set.id
        await session.commit()
    async with async_session_factory() as session:
        await WorkoutRepository(session).record_free_workout(
            user_id=user_id, workout_set_id=workout_set_id, performed_at=now - timedelta(days=3),
            block_a_reps=BlockLog(working_reps=(5, 5), max_reps=6), equipment_type=EquipmentType.BODYWEIGHT,
        )
        await session.commit()
    async with async_session_factory() as session:
        await _elective(session, user_id, ElectiveType.THREE_MINUTES, now - timedelta(days=2), 9, [9])
        await session.commit()
    async with async_session_factory() as session:
        await _elective(session, user_id, ElectiveType.VOLUME_TARGET, now - timedelta(days=1), 30, None)
        await session.commit()

    async with async_session_factory() as session:
        report = await backfill.backfill_all(session, now=datetime.now(UTC))
        print("backfill #1:", report.users_migrated_this_run, "migrated,", report.users_already_migrated, "already migrated")
        await _dump(session, user_id, "after backfill #1")

    async with async_session_factory() as session:
        await _elective(session, user_id, ElectiveType.W_LADDER, now, 12, [4, 4, 4])
        await session.commit()
    async with async_session_factory() as session:
        report = await backfill.backfill_all(session, now=datetime.now(UTC))
        print("backfill #2:", report.users_migrated_this_run, "migrated,", report.users_already_migrated, "already migrated")
        await _dump(session, user_id, "after elective #3 + backfill #2")
        same = (await session.execute(text(
            "select count(distinct ts.created_at) = 1 and min(ts.created_at) = (select created_at from training_plans where user_id = :u) "
            "from training_sessions ts where ts.user_id = :u"), {"u": user_id})).scalar_one()
        print("ALL COPIES created_at == plan.created_at:", same)


if __name__ == "__main__":
    asyncio.run(main())
