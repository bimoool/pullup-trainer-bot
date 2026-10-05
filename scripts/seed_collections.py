"""Админ-скрипт сида редакционных подборок («Подборки» на Главной, issue #271).

Подборки создаёт только этот скрипт / data-миграция — пользовательских подборок нет.
Идемпотентно (ключ — slug): повторный прогон обновляет поля и пересобирает состав.
Состав стартовой подборки «Начни с подтягиваний» — все программы каталога с категорией
`pull_ups` (в порядке id). Программу «Подтягивания» в подборку кладёт и data-миграция
`a4c8e1f7b2d9` (#296), так что на свежей установке скрипт не нужен; он пересобирает состав
подборки (например, если появились другие программы `pull_ups`).

    python scripts/seed_collections.py --dry-run
    python scripts/seed_collections.py
"""

import argparse
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import async_session_factory
from app.db.models_program import Program
from app.db.repositories.collections import CollectionRepository
from app.domain.constants import ExerciseType

START_SLUG = "start-with-pull-ups"
START_TITLE = "Начни с подтягиваний"
START_DESCRIPTION = (
    "Программы Турникмэна, с которых удобно начать: объём и сила в подтягиваниях "
    "с понятной прогрессией."
)


async def seed_collections(session: AsyncSession, *, dry_run: bool = False) -> list[str]:
    """Возвращает человекочитаемый отчёт; при dry_run ничего не пишет."""
    program_ids = list((await session.execute(
        select(Program.id).where(Program.category == ExerciseType.PULL_UPS.value).order_by(Program.id),
    )).scalars().all())
    report = [f"{START_SLUG}: {len(program_ids)} программ(ы) {program_ids}"]
    if dry_run:
        return report
    await CollectionRepository(session).upsert_collection(
        slug=START_SLUG, title=START_TITLE, description=START_DESCRIPTION,
        sort_order=0, is_published=True, program_ids=program_ids,
    )
    return report


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="только показать состав, ничего не писать")
    args = parser.parse_args()
    async with async_session_factory() as session:
        for line in await seed_collections(session, dry_run=args.dry_run):
            print(line)
        if not args.dry_run:
            await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
