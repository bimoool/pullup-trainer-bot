"""Консервативное удаление завершённых Builder-сессий (REBUILD-1, R2).

Инвариант проекта (CLAUDE.md): исторические записи, от которых зависит
прогрессия/история, не удаляются разрушающе. Единственное исключение —
завершённая пользовательская Builder-сессия, для которой БЭКЕНД доказал, что
она независима от защищённой прогрессии. Всё недоказанное — отказ ("anything
unproven: deny"); фронтенд не имеет своих эвристик и показывает "Удалить"
только по can_delete из ответа.

Предикат безопасности (все условия сразу):
  1. сессия завершена (STARTED удалять нельзя — она ещё идёт);
  2. не связана с program-backed PlanItem (PlanItem.program_inclusion_id);
  3. доказана Builder-природа: валидный замороженный WorkoutSnapshot, чей
     workout — пользовательский Workout (Complex.source_type='user') этого же
     владельца, либо (сессия до снимков) все связанные PlanItem — complex-
     backed на такие же пользовательские Workout;
  4. блоки не совпадают с ролями STEP A/B ни одной STEP-инклюзии
     пользователя (совпадение = сессия питает прогрессию курса). Проверка
     строже _match_step_blocks: отказ и при любом блоке с упражнением-ролью
     block_a/block_b.

Вместо условия 3 доказуемо независимыми считаются ещё две формы записи:
свободная активность (#263) и перенесённый backfill-ом факультатив (#279):
source=elective, без связей с PlanItem, каждый блок — на СИСТЕМНОЕ Exercise с
subcategory elective_* (факультатив по определению вне плана и прогрессии,
app/domain/electives.py). Условие 4 для них проверяется так же."""

from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import Complex, Exercise, PlanItem, ProgramInclusion, SessionStatus
from app.db.repositories.legacy_convergence import (
    REASON_LEGACY_DELETED,
    LegacyConvergenceRepository,
)
from app.db.repositories.programs import ProgramRepository
from app.db.repositories.training_plans import TrainingPlanRepository
from app.db.repositories.training_sessions import SessionDetail, TrainingSessionRepository
from app.domain.multi_program import SessionSource
from app.domain.progression_strategy import ProgressionStrategyType
from app.domain.training_session_v2 import SessionOrigin
from app.domain.workout_snapshot import WorkoutSnapshot
from app.services.session_log import _match_step_blocks, _session_block_input_from_detail

REASON_ACTIVE = "Активную тренировку нельзя удалить — сначала завершите её."
REASON_PROGRAM = "Тренировка относится к курсу — её нельзя удалить, чтобы не нарушить прогрессию и историю."
REASON_STEP = "Эта тренировка учтена в прогрессии курса — удалить её нельзя."
REASON_UNPROVEN = "Не удалось убедиться, что эту тренировку можно удалить без последствий для прогрессии."


@dataclass(frozen=True)
class DeleteVerdict:
    can_delete: bool
    reason: str | None = None


_ALLOWED = DeleteVerdict(can_delete=True)


def _is_user_workout(complex_: Complex | None, user_id: int) -> bool:
    return complex_ is not None and complex_.source_type == "user" and complex_.owner_user_id == user_id


ELECTIVE_SUBCATEGORY_PREFIX = "elective_"


def _is_system_elective_exercise(exercise: Exercise | None) -> bool:
    return (
        exercise is not None and exercise.source_type == "system" and exercise.owner_user_id is None
        and (exercise.subcategory or "").startswith(ELECTIVE_SUBCATEGORY_PREFIX)
    )


def _is_proven_elective(detail: SessionDetail, linked: list[PlanItem], exercises: dict[int, Exercise]) -> bool:
    """Факультатив (#279): только source=elective, ни одной связи с планом, непустой набор блоков и
    КАЖДЫЙ блок — на системное elective_*-упражнение (не комплекс). Иначе — не доказано."""
    return (
        detail.source == SessionSource.ELECTIVE and not linked and bool(detail.blocks)
        and all(
            block.complex_id is None and _is_system_elective_exercise(exercises.get(block.exercise_id))
            for block in detail.blocks
        )
    )


def _snapshot_workout_id(detail: SessionDetail) -> int | None:
    if detail.workout_snapshot is None:
        return None
    try:
        return WorkoutSnapshot.model_validate(detail.workout_snapshot).workout_id
    except ValidationError:
        return None


class SessionDeletionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._sessions = TrainingSessionRepository(session)
        self._plans = TrainingPlanRepository(session)
        self._programs = ProgramRepository(session)

    async def evaluate(self, details: list[SessionDetail], user_id: int) -> dict[int, DeleteVerdict]:
        """Вердикты для страницы сессий — фиксированное число запросов (связи
        план-элементов, PlanItem, Complex, инклюзии), не по N на сессию."""
        if not details:
            return {}
        plan_item_ids_by_session = await self._sessions.list_plan_item_ids_by_session([d.id for d in details])
        all_plan_item_ids = sorted({pid for ids in plan_item_ids_by_session.values() for pid in ids})
        plan_items = {
            item.id: item for item in await self._plans.list_plan_items_by_ids_for_user(all_plan_item_ids, user_id)
        }

        complex_ids = {item.complex_id for item in plan_items.values() if item.complex_id is not None}
        complex_ids |= {wid for wid in (_snapshot_workout_id(d) for d in details) if wid is not None}
        complex_ids |= {d.workout_definition_id for d in details if d.workout_definition_id is not None}
        complexes = {c.id: c for c in await self._programs.list_complexes_by_ids(sorted(complex_ids))}

        elective_exercise_ids = sorted({
            block.exercise_id for d in details if d.source == SessionSource.ELECTIVE
            for block in d.blocks if block.exercise_id is not None
        })
        exercises = {e.id: e for e in await self._programs.list_exercises_by_ids(elective_exercise_ids)}

        plan = await self._plans.get_for_user(user_id)
        step_inclusions: list[ProgramInclusion] = []
        if plan is not None:
            step_inclusions = [
                inclusion for inclusion in await self._plans.list_inclusions(plan.id)
                if inclusion.snapshot.get("progression_strategy_type") == ProgressionStrategyType.STEP.value
            ]

        return {
            detail.id: self._verdict(
                detail, user_id,
                [plan_items[pid] for pid in plan_item_ids_by_session.get(detail.id, []) if pid in plan_items],
                complexes, step_inclusions, exercises,
            )
            for detail in details
        }

    @staticmethod
    def _verdict(
        detail: SessionDetail, user_id: int, linked: list[PlanItem], complexes: dict[int, Complex],
        step_inclusions: list[ProgramInclusion], exercises: dict[int, Exercise],
    ) -> DeleteVerdict:
        if detail.status != SessionStatus.COMPLETED:
            return DeleteVerdict(False, REASON_ACTIVE)
        if any(item.program_inclusion_id is not None for item in linked):
            return DeleteVerdict(False, REASON_PROGRAM)
        # Свободная активность (#263): без блоков и без связи с программой по
        # построению — прогрессии не касается, доказуемо безопасна.
        if (
            detail.source == SessionSource.FREEFORM and detail.activity_type is not None
            and not detail.blocks and not linked
        ):
            return _ALLOWED

        # Builder-природа: снимок (замороженное определение) либо, для сессий
        # до снимков, complex-backed связь на пользовательский Workout.
        snapshot_workout_id = _snapshot_workout_id(detail)
        if _is_proven_elective(detail, linked, exercises):
            proven = True
        elif detail.workout_snapshot is not None:
            proven = snapshot_workout_id is not None and _is_user_workout(complexes.get(snapshot_workout_id), user_id)
        elif detail.workout_definition_id is not None and detail.prescription_snapshot is not None:
            # issue #307: запись «Тренировку из моих» своей тренировки без Builder-протокола — идентичность
            # и замороженный рецепт хранятся явно (workout_definition_id + prescription_snapshot).
            proven = _is_user_workout(complexes.get(detail.workout_definition_id), user_id)
        else:
            proven = bool(linked) and all(
                item.complex_id is not None and _is_user_workout(complexes.get(item.complex_id), user_id)
                for item in linked
            )
        if not proven:
            return DeleteVerdict(False, REASON_UNPROVEN)

        session_blocks = [_session_block_input_from_detail(b) for b in detail.blocks]
        for inclusion in step_inclusions:
            role_exercise_ids = {item["exercise_id"] for item in inclusion.snapshot.get("exercises", [])}
            touches_role = any(block.exercise_id in role_exercise_ids for block in detail.blocks)
            if touches_role or _match_step_blocks(inclusion, session_blocks) is not None:
                return DeleteVerdict(False, REASON_STEP)
        return _ALLOWED

    async def delete(self, session_id: int, user_id: int) -> tuple[bool, DeleteVerdict | None]:
        """(найдена, вердикт). Не найдена/чужая — (False, None) -> роут 404 (не
        раскрывает существование). Небезопасная — вердикт can_delete=False ->
        409 с человекочитаемой причиной, ничего не удалено."""
        detail = await self._sessions.get_for_user(session_id, user_id)
        if detail is None:
            return False, None
        await self._sessions.lock_session(session_id)
        detail = await self._sessions.get_for_user(session_id, user_id)
        if detail is None:  # конкурентное удаление — как "не найдена"
            return False, None
        verdict = (await self.evaluate([detail], user_id))[detail.id]
        if verdict.can_delete:
            if detail.legacy_id is not None or detail.origin == SessionOrigin.LEGACY_ELECTIVE.value:
                # Копия legacy-факультатива (#308): строка legacy-таблицы остаётся, поэтому копию нельзя
                # просто удалить — повторное сведение воссоздало бы удалённую запись. Копия замещается
                # (legacy_deleted) и исчезает из canonical_sessions, не удаляясь (архивировать, не удалять);
                # ключ (origin, legacy_id) остаётся занятым, а историческую копию без ключа привяжет сведение.
                copy = await self._sessions.lock_session(session_id)
                await LegacyConvergenceRepository(self._session).supersede_copy(copy, reason=REASON_LEGACY_DELETED)
            else:
                await self._sessions.delete_session(session_id)
        return True, verdict
