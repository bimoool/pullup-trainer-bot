"""WorkoutDefinition v2 — оркестрация (issue #303, WORKOUT_DOMAIN_V2 §3–§5, §7).

- save(): normalize (W1–W8, W6 по видимости упражнений владельцу) → проверка стабильности
  ключей блоков относительно текущей версии (W5) → идемпотентная версия.
- sync_head(): после правки V1-головы (complex_items) Builder'ом — версия догоняет голову.
- prescription(): описание текущей версии — то, что показывают Detail/каталог/план/пре-скрин
  (один describe() на всех, §7).
- build_snapshot(): самодостаточный PrescriptionSnapshot для версии. Запись снимка в сессию —
  Wave 3a (#307), здесь только построитель.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import Complex
from app.db.repositories.workout_definitions import WorkoutDefinitionRepository
from app.domain.workout_definition import (
    Block,
    ExerciseInfo,
    PrescriptionSnapshot,
    ProgressionBlockResolver,
    SnapshotResolutionError,
    WorkoutContent,
    WorkoutDefinitionVersionRecord,
    assert_block_keys_stable,
    build_prescription_snapshot,
    describe,
    describe_rest,
    normalize,
    total_target_reps,
)


@dataclass(frozen=True)
class BlockPrescriptionView:
    """Один блок для UI: подписи — только display_name и describe() (E1, §7)."""

    key: str
    exercise: ExerciseInfo
    kind: str
    description: str
    rest_description: str | None
    rest_after_block_seconds: int | None
    prep_seconds: int
    total_target_reps: int | None
    block: Block


@dataclass(frozen=True)
class PrescriptionView:
    version: WorkoutDefinitionVersionRecord
    blocks: tuple[BlockPrescriptionView, ...]


def block_views(content: WorkoutContent, exercises: Mapping[int, ExerciseInfo]) -> tuple[BlockPrescriptionView, ...]:
    """Один построитель текста рецепта для сохранённых версий и превью Builder'а."""
    return tuple(
        BlockPrescriptionView(
            key=block.key,
            exercise=exercises.get(block.exercise_id) or ExerciseInfo(
                id=block.exercise_id, display_name=f"Упражнение #{block.exercise_id}",
                analytics_exercise_id=block.exercise_id, category_id=None,
            ),
            kind=block.kind.value, description=describe(block), rest_description=describe_rest(block),
            rest_after_block_seconds=block.rest_after_block_seconds, prep_seconds=block.prep_seconds,
            total_target_reps=total_target_reps(block), block=block,
        )
        for block in content.blocks
    )


class WorkoutDefinitionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = WorkoutDefinitionRepository(session)

    async def save(
        self,
        workout_definition_id: int,
        raw: Mapping[str, Any] | WorkoutContent,
        *,
        visible_exercise_ids: Collection[int] | None,
    ) -> tuple[WorkoutDefinitionVersionRecord, bool]:
        content = normalize(raw, visible_exercise_ids=visible_exercise_ids)
        complex_ = await self._session.get(Complex, workout_definition_id)
        if complex_ is not None and complex_.current_version_id is not None:
            current = await self._repo.get_version(complex_.current_version_id)
            if current is not None:
                assert_block_keys_stable(current.content, content)
        return await self._repo.save_content(workout_definition_id, content)

    async def sync_head(self, workout_definition_id: int) -> tuple[int | None, bool, str | None]:
        return await self._repo.sync_from_head(workout_definition_id)

    async def prescriptions(self, workout_definition_ids: list[int]) -> dict[int, PrescriptionView]:
        versions = await self._repo.current_versions(workout_definition_ids)
        exercise_ids = sorted({b.exercise_id for v in versions.values() for b in v.content.blocks})
        exercises = await self._repo.exercise_infos(exercise_ids)
        return {
            definition_id: PrescriptionView(version=version, blocks=block_views(version.content, exercises))
            for definition_id, version in versions.items()
        }

    async def build_snapshot(
        self,
        version_id: int,
        *,
        resolved_at: datetime,
        resolve_progression: ProgressionBlockResolver | None = None,
        program_inclusion_id: int | None = None,
        strategy: str | None = None,
        progression_state_rev: int | None = None,
    ) -> PrescriptionSnapshot:
        version = await self._repo.get_version(version_id)
        if version is None:
            raise SnapshotResolutionError(f"версия {version_id} не найдена")
        exercises = await self._repo.exercise_infos(sorted({b.exercise_id for b in version.content.blocks}))
        return build_prescription_snapshot(
            version.content, workout_definition_id=version.workout_definition_id,
            workout_definition_version_id=version.id, version_no=version.version_no,
            exercises=exercises, resolved_at=resolved_at, resolve_progression=resolve_progression,
            program_inclusion_id=program_inclusion_id, strategy=strategy,
            progression_state_rev=progression_state_rev,
        )
