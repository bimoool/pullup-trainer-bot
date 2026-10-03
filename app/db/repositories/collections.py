from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import Collection, CollectionItem, Exercise, Program

# Внутренние step-роли программ (subcategory) — не публичные упражнения, как в GET /exercises.
_INTERNAL_EXERCISE_SUBCATEGORIES = ("block_a", "block_b")


@dataclass(frozen=True)
class VisibleCollectionItem:
    item_type: str  # "program" | "exercise"
    target_id: int
    title: str
    subtitle: str | None


@dataclass(frozen=True)
class VisibleCollection:
    collection: Collection
    items: list[VisibleCollectionItem]


class CollectionRepository:
    """Подборки (issue #271). Чтение — только опубликованные подборки и только видимые
    элементы (PROJECT_SPEC §5): программа каталога (у Program нет флага публикации — каталог
    виден всем) или system Exercise вне внутренних step-ролей. Подборка без видимых
    элементов считается отсутствующей. Запись (upsert_collection) — только сид/админ-скрипт."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_visible(self) -> list[VisibleCollection]:
        collections = list((await self._session.execute(
            select(Collection).where(Collection.is_published.is_(True)).order_by(Collection.sort_order, Collection.id),
        )).scalars().all())
        return await self._resolve(collections)

    async def get_visible(self, collection_id: int) -> VisibleCollection | None:
        collection = (await self._session.execute(
            select(Collection).where(Collection.id == collection_id, Collection.is_published.is_(True)),
        )).scalars().first()
        if collection is None:
            return None
        resolved = await self._resolve([collection])
        return resolved[0] if resolved else None

    async def _resolve(self, collections: list[Collection]) -> list[VisibleCollection]:
        if not collections:
            return []
        rows = list((await self._session.execute(
            select(CollectionItem)
            .where(CollectionItem.collection_id.in_([c.id for c in collections]))
            .order_by(CollectionItem.position, CollectionItem.id),
        )).scalars().all())
        program_ids = {r.program_id for r in rows if r.program_id is not None}
        exercise_ids = {r.exercise_id for r in rows if r.exercise_id is not None}
        programs = {
            p.id: p for p in (await self._session.execute(
                select(Program).where(Program.id.in_(program_ids)),
            )).scalars().all()
        } if program_ids else {}
        exercises = {
            e.id: e for e in (await self._session.execute(
                select(Exercise).where(
                    Exercise.id.in_(exercise_ids),
                    Exercise.source_type == "system",
                    Exercise.subcategory.is_(None) | Exercise.subcategory.not_in(_INTERNAL_EXERCISE_SUBCATEGORIES),
                ),
            )).scalars().all()
        } if exercise_ids else {}

        by_collection: dict[int, list[VisibleCollectionItem]] = {c.id: [] for c in collections}
        for row in rows:
            if row.program_id is not None and row.program_id in programs:
                program = programs[row.program_id]
                by_collection[row.collection_id].append(VisibleCollectionItem(
                    item_type="program", target_id=program.id, title=program.name, subtitle=program.goal,
                ))
            elif row.exercise_id is not None and row.exercise_id in exercises:
                exercise = exercises[row.exercise_id]
                by_collection[row.collection_id].append(VisibleCollectionItem(
                    item_type="exercise", target_id=exercise.id, title=exercise.name, subtitle=exercise.category,
                ))
        return [VisibleCollection(c, by_collection[c.id]) for c in collections if by_collection[c.id]]

    async def upsert_collection(
        self,
        *,
        slug: str,
        title: str,
        description: str | None,
        author_label: str = "Турникмэн",
        sort_order: int = 0,
        is_published: bool = True,
        program_ids: list[int] | None = None,
        exercise_ids: list[int] | None = None,
    ) -> Collection:
        """Идемпотентный сид по slug: поля обновляются, элементы пересоздаются
        (программы по порядку, затем упражнения). Только сид/админ-скрипт."""
        collection = (await self._session.execute(
            select(Collection).where(Collection.slug == slug),
        )).scalars().first()
        if collection is None:
            collection = Collection(slug=slug, title=title)
            self._session.add(collection)
        collection.title = title
        collection.description = description
        collection.author_label = author_label
        collection.sort_order = sort_order
        collection.is_published = is_published
        await self._session.flush()
        await self._session.execute(delete(CollectionItem).where(CollectionItem.collection_id == collection.id))
        position = 0
        for program_id in program_ids or []:
            self._session.add(CollectionItem(collection_id=collection.id, program_id=program_id, position=position))
            position += 1
        for exercise_id in exercise_ids or []:
            self._session.add(CollectionItem(collection_id=collection.id, exercise_id=exercise_id, position=position))
            position += 1
        await self._session.flush()
        return collection
