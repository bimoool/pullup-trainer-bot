"""Harness for webapp-frontend/e2e/scenarios/fix-wave1/expired-course-gate.spec.ts (issue #300).

Subcommands (DATABASE_URL points at the journey DB):
  seed-paid-course      create the PAID test course «Платный тестовый курс» (programs.access_level = premium, one
                        real library exercise «Отжимания»; idempotent find-or-create by name). The expired-user
                        gate is checked against THIS course: «Подтягивания» is free forever (owner rule 2026-10-07,
                        app/domain/program_access.py), so it can never be the gated course.
  seed-catalog          create the «Подтягивания» course via backfill_multi_program.seed_catalog (environment setup only;
                        no enrolment loop). TODO(director): drop once the course ships with migrations (worker A).
  expire <telegram_id>  TEST HARNESS INJECTION: move subscription_expires_at one day into the past and LEAVE the cached
                        status as-is (`trial`) — exactly what a real user reaches by waiting for the trial to end.
  grant <telegram_id> <days>
                        the sanctioned admin «Выдать подписку» (admin_grant_days) run THROUGH the real bot handler via
                        aiogram Dispatcher.feed_update (StubSession bot, no network), as scripts/audit/c_admin_grant.py.
"""
import asyncio
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

ADMIN_TG = 7300099


async def _seed_catalog() -> None:
    from app.db.base import async_session_factory
    from scripts.backfill_multi_program import seed_catalog

    async with async_session_factory() as session:
        await seed_catalog(session)
        await session.commit()
    print("catalog seeded")


PAID_COURSE_NAME = "Платный тестовый курс"
PAID_COURSE_CATEGORY = "Тестовый курс"


async def _seed_paid_course() -> None:
    from sqlalchemy import select

    from app.db.base import async_session_factory
    from app.db.models_program import Exercise, Program, ProgramItem
    from app.domain.multi_program import ProgramStructureType, WeekPhase
    from app.domain.program_access import ProgramAccessLevel

    async with async_session_factory() as session:
        existing = (await session.execute(select(Program).where(Program.name == PAID_COURSE_NAME))).scalars().first()
        if existing is not None:
            assert existing.access_level == ProgramAccessLevel.PREMIUM.value
            print(f"paid course exists: program_id={existing.id}")
            return
        exercise = (await session.execute(
            select(Exercise).where(Exercise.name == "Отжимания", Exercise.owner_user_id.is_(None)),
        )).scalars().first()
        assert exercise is not None, "system library exercise «Отжимания» missing — run alembic upgrade head"
        program = Program(
            name=PAID_COURSE_NAME, goal="Проверка платного доступа (E2E)", structure_type=ProgramStructureType.RECURRING,
            category=PAID_COURSE_CATEGORY, config={}, access_level=ProgramAccessLevel.PREMIUM.value,
        )
        session.add(program)
        await session.flush()
        session.add(ProgramItem(
            program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=exercise.id, count_per_week=3, day_of_week=None,
        ))
        await session.commit()
        print(f"paid course created: program_id={program.id}")


async def _expire(telegram_id: int) -> None:
    from app.db.base import async_session_factory

    async with async_session_factory() as session:
        await session.execute(
            text("UPDATE users SET subscription_expires_at = :ts WHERE telegram_id = :tg"),
            {"ts": datetime.now(UTC) - timedelta(days=1), "tg": telegram_id},
        )
        await session.commit()
    print(f"expired {telegram_id} (status cache untouched)")


async def _grant(telegram_id: int, days: int) -> None:
    from aiogram import Bot, Dispatcher
    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.types import Chat, Message, Update
    from aiogram.types import User as TgUser

    from app.bot.handlers import router
    from app.config import settings
    from app.db.base import async_session_factory
    from app.db.repositories.users import UserRepository
    from tests.test_bot.conftest import FAKE_TOKEN, StubSession, make_callback_update

    settings.admin_ids = str(ADMIN_TG)  # in-process only
    bot = Bot(token=FAKE_TOKEN, session=StubSession())
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    typed = Update(update_id=2, message=Message(
        message_id=101, date=datetime.now(UTC), chat=Chat(id=ADMIN_TG, type="private"),
        from_user=TgUser(id=ADMIN_TG, is_bot=False, first_name="Admin"), text=str(days),
    ))
    async with async_session_factory() as session:
        target = await UserRepository(session).get_by_telegram_id(telegram_id)
        print("BEFORE", target.subscription_status, target.subscription_expires_at)
        await dp.feed_update(bot, make_callback_update(telegram_id=ADMIN_TG, data=f"admin_grant_days:{target.id}"), session=session)
        await dp.feed_update(bot, typed, session=session)
        await session.commit()
        await session.refresh(target)
        print("AFTER", target.subscription_status, target.subscription_expires_at)


if __name__ == "__main__":
    command = sys.argv[1]
    if command == "seed-paid-course":
        asyncio.run(_seed_paid_course())
    elif command == "seed-catalog":
        asyncio.run(_seed_catalog())
    elif command == "expire":
        asyncio.run(_expire(int(sys.argv[2])))
    elif command == "grant":
        asyncio.run(_grant(int(sys.argv[2]), int(sys.argv[3])))
    else:
        raise SystemExit(__doc__)
