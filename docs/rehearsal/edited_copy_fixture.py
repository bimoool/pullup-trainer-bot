"""Fixture «отредактированная копия факультатива» — запускается СТАРЫМ кодом (develop/current) на БД со схемой a4c8e1f7b2d9.

    PYTHONPATH=<checkout develop/current> DATABASE_URL=postgresql+asyncpg://…/<db> python edited_copy_fixture.py

Каждый пользователь = «мигрированный» (journal_dedupe: 3 legacy-тренировки + их копии штатными функциями backfill) +
4 факультатива, у каждого из которых копия создана ШТАТНОЙ функцией backfill старого кода
(`_create_training_session_for_elective`), т.е. ровно как в проде:
  E1 — потом правится значение подхода (PATCH /api/v2/sessions/{id}), E2 — переносится дата (PATCH performed_on),
  E3 — не трогается (контроль), E4 — удаляется копия (DELETE /api/v2/sessions/{id}).
Пользователь A (770001): факультативы записаны ДО backfill (created_at раньше плана) — хронология реального прода.
Пользователь B (770002): created_at факультативов не раньше плана — граничный случай (в проде не ожидается).
Правки/удаление делает отдельный шаг через старое API (docs/rehearsal/edited_copy_run.sh), не этот файл.
"""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

import scripts.backfill_multi_program as backfill
import scripts.e2e_seed as seed
from app.db.base import async_session_factory
from app.db.models_program import TrainingPlan
from app.db.repositories.elective_workouts import ElectiveWorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.electives import ElectiveType

ELECTIVES = (
    ("E1", ElectiveType.MAX_REPS_LADDER, [5, 4, 3, 3], 15, 50),
    ("E2", ElectiveType.THREE_MINUTES, [9], 9, 40),
    ("E3", ElectiveType.W_LADDER, [6, 6, 6], 18, 30),
    ("E4", ElectiveType.VOLUME_TARGET, None, 30, 20),
)


async def build(telegram_id: int, *, older_than_plan: bool) -> None:
    async with async_session_factory() as session:
        await seed.seed_journal_dedupe(session, telegram_id)
        user_id = (await session.execute(text("select id from users where telegram_id=:t"), {"t": telegram_id})).scalar_one()
        now = datetime.now(UTC)
        # backfill создаёт TrainingPlan при миграции пользователя (после копий); без плана защита «электив старше
        # плана -> не воскрешать» (_converge_electives) не включается, а у реального пользователя план есть всегда.
        session.add(TrainingPlan(user_id=user_id))
        await session.flush()
        repo = ElectiveWorkoutRepository(session)
        for name, kind, sequence, total, minutes_ago in ELECTIVES:
            elective = await repo.create(
                user_id=user_id, elective_type=kind, performed_at=now - timedelta(minutes=minutes_ago),
                total_reps=total, reps_sequence=sequence, equipment_type=EquipmentType.BODYWEIGHT,
                equipment_value=None,
            )
            if older_than_plan:  # электив записан задолго до миграции (backfill создаёт план ПОСЛЕ копий)
                await session.execute(
                    text("update elective_workouts set created_at = now() - interval '30 days' where id=:i"), {"i": elective.id},
                )
            exercise_id = (await session.execute(
                text("select id from exercises where subcategory=:s"), {"s": f"elective_{kind.value}"},
            )).scalar_one()
            await session.refresh(elective)
            await backfill._create_training_session_for_elective(session, elective, exercise_id=exercise_id)
            print(f"  {telegram_id} {name}: elective_id={elective.id}")
        await session.commit()
    print(f"fixture built for telegram_id={telegram_id} older_than_plan={older_than_plan}")


async def main() -> None:
    await build(770_001, older_than_plan=True)
    await build(770_002, older_than_plan=False)


if __name__ == "__main__":
    asyncio.run(main())
