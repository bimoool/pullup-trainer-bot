"""Сведение legacy-истории пользователя в TrainingSession: планировщик (issue #308, MIGRATION_V2 §3–§5).

``converge_user`` приводит нативные копии пользователя к виду «ровно одна копия на каждую живую строку старой
схемы»: привязывает к строкам уже существующие копии (ТОЛЬКО по точному совпадению содержимого), создаёт
недостающие, обновляет разошедшиеся и замещает копии, чья строка исчезла. Идемпотентна: повторный apply = 0
изменений. dry-run читает и ничего не пишет (планировщик один и тот же, меняется только исполнение).

Правила неоднозначности (не угадываем):

* копия без legacy_id (создана backfill-ом #163 до ключа) привязывается к legacy Workout, только если у них
  совпадает (performed_at, источник, упражнения и подходы блоков); одинаковые между собой пары берутся по
  порядку id — они взаимозаменяемы по определению;
* что осталось без пары: legacy Workout -> создаётся новая копия (старая копия при этом замещается, т.к. её
  строку правили или удалили после backfill — какая именно, неизвестно и не нужно: старая схема остаётся
  источником правды до заморозки, Wave 4); копия без живой строки -> замещается (legacy_deleted /
  legacy_replaced), не удаляется;
* факультатив без копии создаётся, только если он записан ПОСЛЕ миграции пользователя (его TrainingPlan);
  более ранний без копии — запись, удалённая из Журнала (#279) или отредактированная там (копия факультатива
  принадлежит Журналу v2): он НЕ воскрешается и попадает в отчёт ``ambiguous_elective_without_copy``.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BlockType, ElectiveWorkout, Workout, WorkoutStatus
from app.db.models_program import SessionStatus, TrainingPlan, TrainingSession
from app.db.repositories.legacy_convergence import (
    REASON_LEGACY_DELETED,
    REASON_LEGACY_REPLACED,
    BlockSpec,
    ConvergenceOutcome,
    LegacyConvergenceRepository,
    SetSpec,
    elective_note,
    workout_block_sets,
)
from app.db.repositories.training_sessions import TrainingSessionRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.journal_dedupe import resolve_legacy_session_source
from app.domain.multi_program import SessionSource
from app.domain.training_session_v2 import SessionOrigin


@dataclass
class UserConvergenceReport:
    user_id: int
    counts: Counter = field(default_factory=Counter)
    ambiguous: list[dict] = field(default_factory=list)

    @property
    def mutations(self) -> int:
        """Сколько записей изменит (изменило) apply — для критерия «apply-again = 0»."""
        return sum(
            self.counts[key]
            for key in ("classified", "bound", "created", "updated", "superseded", "elective_created")
        )


def _workout_signature(workout: Workout, exercise_a_id: int, exercise_b_id: int) -> tuple:
    source = resolve_legacy_session_source(
        participates_in_cascade=workout.participates_in_cascade, is_free_entry=workout.is_free_entry,
    )
    blocks = [BlockSpec(0, exercise_a_id, workout_block_sets(next(b for b in workout.blocks if b.block_type == BlockType.A)))]
    if not workout.is_free_entry:
        blocks.append(
            BlockSpec(1, exercise_b_id, workout_block_sets(next(b for b in workout.blocks if b.block_type == BlockType.B))),
        )
    return (workout.performed_at, source, tuple(blocks))


class LegacyHistoryConvergenceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = LegacyConvergenceRepository(session)

    async def _copies(self, user_id: int) -> list[TrainingSession]:
        result = await self._session.execute(
            select(TrainingSession)
            .where(
                TrainingSession.user_id == user_id,
                TrainingSession.origin.in_((SessionOrigin.LEGACY_BACKFILL.value, SessionOrigin.LEGACY_ELECTIVE.value)),
            )
            .order_by(TrainingSession.id)
            .with_for_update(),
        )
        return list(result.scalars().all())

    async def _classify_unlabelled(self, user_id: int, *, apply: bool, report: UserConvergenceReport) -> None:
        """Строки без origin (код до #307 в окне деплоя): копии backfill-а узнаём по отпечатку (ТОЛЬКО здесь,
        читатели его не используют), электив — по source."""
        rows = (
            await self._session.execute(
                select(TrainingSession).where(
                    TrainingSession.user_id == user_id, TrainingSession.origin.is_(None),
                    TrainingSession.status == SessionStatus.COMPLETED,
                ).order_by(TrainingSession.id).with_for_update(),
            )
        ).scalars().all()
        if not rows:
            return
        fingerprinted = set((
            await self._session.execute(
                select(TrainingSession.id).where(
                    TrainingSession.id.in_([r.id for r in rows]),
                    TrainingSessionRepository.legacy_copy_fingerprint_for_recovery(),
                ),
            )
        ).scalars().all())
        for row in rows:
            if row.source == SessionSource.ELECTIVE:
                origin = SessionOrigin.LEGACY_ELECTIVE
            elif row.id in fingerprinted:
                origin = SessionOrigin.LEGACY_BACKFILL
            else:
                continue
            report.counts["classified"] += 1
            if apply:
                row.origin = origin.value
        if apply:
            await self._session.flush()

    async def converge_user(self, user_id: int, *, apply: bool) -> UserConvergenceReport:
        report = UserConvergenceReport(user_id)
        repo = self._repo
        await self._classify_unlabelled(user_id, apply=apply, report=report)
        exercise_a_id, exercise_b_id = await repo.course_exercise_ids()

        workouts = [
            w for w in (await self._workouts(user_id)) if w.status == WorkoutStatus.COMPLETED
        ]
        copies = [c for c in await self._copies(user_id) if c.origin == SessionOrigin.LEGACY_BACKFILL.value]
        alive = {w.id: w for w in workouts}

        # --- привязка -----------------------------------------------------------------------
        keyed = {c.legacy_id: c for c in copies if c.legacy_id is not None}
        pair_of: dict[int, TrainingSession] = {wid: copy for wid, copy in keyed.items() if wid in alive}
        unkeyed = [c for c in copies if c.legacy_id is None]
        free_workouts = sorted((w for w in workouts if w.id not in pair_of), key=lambda w: w.id)
        by_signature: dict[tuple, list[TrainingSession]] = defaultdict(list)
        for copy in unkeyed:
            by_signature[await self._copy_signature(copy)].append(copy)
        leftover_workouts: list[Workout] = []
        for workout in free_workouts:
            candidates = by_signature.get(_workout_signature(workout, exercise_a_id, exercise_b_id))
            if candidates:
                copy = candidates.pop(0)
                pair_of[workout.id] = copy
                report.counts["bound"] += 1
                if apply:
                    await repo.bind_legacy_id(copy, SessionOrigin.LEGACY_BACKFILL, workout.id)
            else:
                leftover_workouts.append(workout)
        orphans = [c for group in by_signature.values() for c in group]
        orphans += [c for wid, c in keyed.items() if wid not in alive]

        # --- замещение копий без живой строки -----------------------------------------------
        reason = REASON_LEGACY_REPLACED if leftover_workouts else REASON_LEGACY_DELETED
        for copy in sorted(orphans, key=lambda c: c.id):
            if copy.superseded_at is not None:
                continue
            report.counts["superseded"] += 1
            if apply:
                await repo.supersede_copy(copy, reason=reason)

        # --- создание/обновление копий живых строк -------------------------------------------
        for workout in sorted(workouts, key=lambda w: w.id):
            copy = pair_of.get(workout.id)
            outcome = await repo.sync_workout(
                workout, exercise_a_id=exercise_a_id, exercise_b_id=exercise_b_id, copy=copy, dry_run=not apply,
            )
            if outcome is ConvergenceOutcome.CREATED:
                report.counts["created"] += 1
            elif outcome is ConvergenceOutcome.UPDATED:
                report.counts["updated"] += 1
            else:
                report.counts["unchanged"] += 1
            if copy is not None and copy.superseded_at is not None:
                report.counts["superseded_but_alive"] += 1

        await self._converge_electives(user_id, apply=apply, report=report)
        return report

    async def _workouts(self, user_id: int) -> list[Workout]:

        return await WorkoutRepository(self._session).list_for_user(user_id)

    async def _copy_signature(self, copy: TrainingSession) -> tuple:
        return (copy.performed_at, copy.source, await self._repo.existing_blocks(copy.id))

    # --- факультативы -----------------------------------------------------------------------

    async def _converge_electives(self, user_id: int, *, apply: bool, report: UserConvergenceReport) -> None:
        repo = self._repo
        electives = list((
            await self._session.execute(
                select(ElectiveWorkout).where(ElectiveWorkout.user_id == user_id).order_by(ElectiveWorkout.id),
            )
        ).scalars().all())
        copies = [c for c in await self._copies(user_id) if c.origin == SessionOrigin.LEGACY_ELECTIVE.value]
        keyed_ids = {c.legacy_id for c in copies if c.legacy_id is not None}
        unkeyed = [c for c in copies if c.legacy_id is None]
        by_signature: dict[tuple, list[TrainingSession]] = defaultdict(list)
        for copy in unkeyed:
            blocks = await repo.existing_blocks(copy.id)
            by_signature[(copy.performed_at, blocks)].append(copy)
        plan_created_at = (
            await self._session.execute(select(TrainingPlan.created_at).where(TrainingPlan.user_id == user_id))
        ).scalar_one_or_none()

        for elective in electives:
            if elective.id in keyed_ids:
                continue
            exercise_id = await repo.elective_exercise_id(elective.elective_type)
            key = (elective.performed_at, (BlockSpec(0, exercise_id, _elective_sets(elective)),))
            candidates = by_signature.get(key)
            if candidates:
                copy = candidates.pop(0)
                report.counts["bound"] += 1
                if apply:
                    await repo.bind_legacy_id(copy, SessionOrigin.LEGACY_ELECTIVE, elective.id)
                continue
            if plan_created_at is not None and elective.created_at < plan_created_at:
                # Записан до миграции пользователя, а копии нет: её удалили/отредактировали в Журнале —
                # не воскрешаем и не дублируем.
                report.counts["ambiguous_elective_without_copy"] += 1
                report.ambiguous.append({"elective_id": elective.id, "reason": "pre_migration_without_copy"})
                continue
            outcome = await repo.sync_elective(elective, exercise_id=exercise_id, dry_run=not apply)
            if outcome is ConvergenceOutcome.CREATED:
                report.counts["elective_created"] += 1
        report.counts["elective_unkeyed_copies_kept"] += sum(len(group) for group in by_signature.values())


def _elective_sets(elective: ElectiveWorkout):


    return (SetSpec(1, False, Decimal(elective.total_reps), elective_note(elective)),)
