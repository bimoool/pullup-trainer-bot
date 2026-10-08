"""Web-представление WorkoutDefinition v2 и идентичности упражнений (issue #303).

Тонкий слой над app.services.workout_definition / app.domain.*: никакой собственной
интерпретации рецепта — только перекладка describe()/display_name в схемы ответа."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import Exercise
from app.db.repositories.workout_definitions import WorkoutDefinitionRepository
from app.domain.exercise_identity import exercise_display_label, looks_like_slug
from app.domain.workout_definition import Block, BlockKind
from app.services.workout_definition import BlockPrescriptionView, PrescriptionView
from app.web.schemas_v2 import (
    ExerciseResponse,
    LabelRef,
    PrescriptionBlockResponse,
    PrescriptionIntervalResponse,
    PrescriptionSetResponse,
    WorkoutVersionRef,
)

UNCATEGORIZED_LABEL = "Без категории"


def block_response(view: BlockPrescriptionView) -> PrescriptionBlockResponse:
    block: Block = view.block
    return PrescriptionBlockResponse(
        key=view.key,
        exercise=LabelRef(id=view.exercise.id, display_name=view.exercise.display_name),
        kind=view.kind, description=view.description, rest_description=view.rest_description,
        prep_seconds=view.prep_seconds, rest_after_block_seconds=view.rest_after_block_seconds,
        total_target_reps=view.total_target_reps,
        sets=None if block.kind is BlockKind.INTERVAL else [
            PrescriptionSetResponse(
                kind=s.kind.value, target_reps=s.target_reps, target_seconds=s.target_seconds,
                rest_after_seconds=s.rest_after_seconds, role=s.role.value,
            )
            for s in block.sets
        ],
        interval=None if block.interval is None else PrescriptionIntervalResponse(
            work_seconds=block.interval.work_seconds, rest_seconds=block.interval.rest_seconds,
            rounds=block.interval.rounds, record_reps_per_round=block.interval.record_reps_per_round,
        ),
    )


def prescription_fields(view: PrescriptionView | None) -> dict:
    """Поля WorkoutResponse.current_version/prescription."""
    if view is None:
        return {"current_version": None, "prescription": None}
    return {
        "current_version": WorkoutVersionRef(
            id=view.version.id, version_no=view.version.version_no, content_hash=view.version.content_hash,
        ),
        "prescription": [block_response(b) for b in view.blocks],
    }


def _legacy_label(text: str | None) -> str | None:
    """Строка старой колонки category/subcategory как подпись — только если это не slug (E1)."""
    if text is None or looks_like_slug(text.strip()):
        return None
    return text.strip() or None


async def exercise_responses(session: AsyncSession, exercises: list[Exercise]) -> list[ExerciseResponse]:
    """name/category/subcategory — человеческие подписи (E1, E3). Категории — одним запросом."""
    category_ids = sorted({
        cid for e in exercises for cid in (e.category_id, e.subcategory_id) if cid is not None
    })
    categories = await WorkoutDefinitionRepository(session).categories_by_ids(category_ids)
    responses: list[ExerciseResponse] = []
    for exercise in exercises:
        category = categories.get(exercise.category_id) if exercise.category_id is not None else None
        subcategory = categories.get(exercise.subcategory_id) if exercise.subcategory_id is not None else None
        label = exercise_display_label(exercise.display_name, exercise.name)
        category_label = (
            category.display_name if category is not None
            else _legacy_label(exercise.category) or UNCATEGORIZED_LABEL
        )
        subcategory_label = (
            subcategory.display_name if subcategory is not None else _legacy_label(exercise.subcategory)
        )
        responses.append(ExerciseResponse(
            id=exercise.id, name=label, display_name=label, metric_type=exercise.metric_type.value,
            category=category_label, subcategory=subcategory_label,
            category_ref=None if category is None else LabelRef(id=category.id, display_name=category.display_name),
            subcategory_ref=None if subcategory is None else LabelRef(
                id=subcategory.id, display_name=subcategory.display_name,
            ),
        ))
    return responses
