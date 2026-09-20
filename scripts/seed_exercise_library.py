"""Seed минимальной Exercise Library (Checkpoint 3A, issue #196) — 2 упражнения
(Планка/Отжимания), NOT part of program seed (не смешивается с
backfill_multi_program.py::seed_catalog).

Production-compatible/idempotent — find-or-create по имени, повторный запуск
не создаёт дубликаты. Использование:

    python scripts/seed_exercise_library.py
"""

import asyncio

from sqlalchemy import select

from app.db.base import async_session_factory
from app.db.models_program import Exercise
from app.domain.multi_program import MetricType


async def _get_or_create_exercise(session, *, name: str, metric_type: MetricType, category: str) -> Exercise:
    """Production-compatible idempotent seed — тот же паттерн, что
    backfill_multi_program.py::_get_or_create_exercise, но НЕ та же
    функция (эти упражнения не принадлежат программе «Подтягивания»,
    не заводятся как ProgramItem). subcategory=None для обоих — не
    block_a/block_b/elective_*, это свободные упражнения библиотеки."""
    result = await session.execute(select(Exercise).where(Exercise.name == name))
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing
    exercise = Exercise(
        name=name,
        metric_type=metric_type,
        category=category,
        subcategory=None,
    )
    session.add(exercise)
    await session.flush()
    return exercise


async def seed_exercise_library(session) -> dict[str, int]:
    """Seed двух упражнений Checkpoint 3A (issue #196): Планка (time) и
    Отжимания (reps). Возвращает dict {name: id} для проверки в тестах."""
    plank = await _get_or_create_exercise(
        session,
        name="Планка",
        metric_type=MetricType.TIME,
        category="Общая физическая подготовка",
    )
    pushups = await _get_or_create_exercise(
        session,
        name="Отжимания",
        metric_type=MetricType.REPS,
        category="Общая физическая подготовка",
    )
    await session.commit()
    return {"Планка": plank.id, "Отжимания": pushups.id}


async def main() -> None:
    async with async_session_factory() as session:
        result = await seed_exercise_library(session)
        print(f"Exercise Library засидирована: {list(result.keys())}")
        for name, exercise_id in result.items():
            print(f"  {name}: id={exercise_id}")


if __name__ == "__main__":
    asyncio.run(main())
