"""WorkoutDefinition v2 — версии и идентичность упражнений (issue #303).

Запись версии — save_version/sync_from_v1_head (app.db.workout_definition_store) через
AsyncSession.run_sync: одна рантайм-реализация номера версии, блокировки и W5 по всей истории.
Чтение версии — снисходительное (content_from_stored, WORKOUT_DOMAIN_V2 §9.12): хеш сверяется
с хранимым JSON, история не прогоняется через сегодняшний normalize()."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import Complex, Exercise, ExerciseCategory, WorkoutDefinitionVersion
from app.db.workout_definition_store import save_version, set_current_version, sync_from_v1_head
from app.domain.exercise_identity import analytics_identity, exercise_display_label
from app.domain.workout_definition import (
    ExerciseInfo,
    WorkoutContent,
    WorkoutDefinitionVersionRecord,
    content_from_stored,
)


def _record(row: WorkoutDefinitionVersion) -> WorkoutDefinitionVersionRecord:
    return WorkoutDefinitionVersionRecord(
        id=row.id, workout_definition_id=row.workout_definition_id, version_no=row.version_no,
        content=content_from_stored(row.content, expected_hash=row.content_hash),
        content_hash=row.content_hash, created_at=row.created_at,
    )


class WorkoutDefinitionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_content(self, workout_definition_id: int, content: WorkoutContent) -> tuple[WorkoutDefinitionVersionRecord, bool]:
        """Append-only (WORKOUT_DOMAIN_V2 §5): содержимое = текущей версии — она же, created=False;
        иначе новая версия max + 1, указатель current_version_id переходит на неё."""
        connection = await self._session.connection()

        def _save(sync_connection) -> tuple[int, bool]:
            version_id, _, created = save_version(sync_connection, workout_definition_id, content)
            set_current_version(sync_connection, workout_definition_id, version_id)
            return version_id, created

        version_id, created = await connection.run_sync(_save)
        await self._refresh_pointer(workout_definition_id)
        record = await self.get_version(version_id)
        assert record is not None
        return record, created

    async def sync_from_head(self, workout_definition_id: int) -> tuple[int | None, bool, str | None]:
        """V1-голова (complex_items) → версия. См. sync_from_v1_head."""
        complex_ = await self._session.get(Complex, workout_definition_id)
        if complex_ is None:
            return None, False, "workout not found"
        title = complex_.name
        connection = await self._session.connection()
        result = await connection.run_sync(lambda c: sync_from_v1_head(c, workout_definition_id, title))
        await self._refresh_pointer(workout_definition_id)
        return result

    async def _refresh_pointer(self, workout_definition_id: int) -> None:
        """Указатель меняется сырым SQL (общий с миграцией путь) — обновить только его у уже
        загруженного Complex, не экспайря остальные объекты сессии (иначе ленивые загрузки в
        async-контексте падают MissingGreenlet)."""
        complex_ = await self._session.get(Complex, workout_definition_id)
        if complex_ is not None:
            await self._session.refresh(complex_, attribute_names=["current_version_id"])

    async def get_version(self, version_id: int) -> WorkoutDefinitionVersionRecord | None:
        row = await self._session.get(WorkoutDefinitionVersion, version_id)
        return None if row is None else _record(row)

    async def list_versions(self, workout_definition_id: int) -> list[WorkoutDefinitionVersionRecord]:
        result = await self._session.execute(
            select(WorkoutDefinitionVersion)
            .where(WorkoutDefinitionVersion.workout_definition_id == workout_definition_id)
            .order_by(WorkoutDefinitionVersion.version_no),
        )
        return [_record(row) for row in result.scalars().all()]

    async def current_versions(self, workout_definition_ids: list[int]) -> dict[int, WorkoutDefinitionVersionRecord]:
        """complex_id → текущая версия (только у тех, где она есть). Один запрос на список."""
        if not workout_definition_ids:
            return {}
        result = await self._session.execute(
            select(WorkoutDefinitionVersion)
            .join(Complex, Complex.current_version_id == WorkoutDefinitionVersion.id)
            .where(Complex.id.in_(workout_definition_ids)),
        )
        return {row.workout_definition_id: _record(row) for row in result.scalars().all()}

    async def exercise_infos(self, exercise_ids: list[int]) -> dict[int, ExerciseInfo]:
        """Что снимок/описание знают об упражнении: подпись (E1), идентичность аналитики (E2)."""
        if not exercise_ids:
            return {}
        result = await self._session.execute(select(Exercise).where(Exercise.id.in_(exercise_ids)))
        return {
            e.id: ExerciseInfo(
                id=e.id, display_name=exercise_display_label(e.display_name, e.name),
                analytics_exercise_id=analytics_identity(e.id, e.analytics_exercise_id),
                category_id=e.category_id,
            )
            for e in result.scalars().all()
        }

    async def categories_by_ids(self, category_ids: list[int]) -> dict[int, ExerciseCategory]:
        if not category_ids:
            return {}
        result = await self._session.execute(select(ExerciseCategory).where(ExerciseCategory.id.in_(category_ids)))
        return {c.id: c for c in result.scalars().all()}

    async def category_id_by_slug(self, slug: str) -> int | None:
        result = await self._session.execute(select(ExerciseCategory.id).where(ExerciseCategory.slug == slug))
        return result.scalar_one_or_none()
