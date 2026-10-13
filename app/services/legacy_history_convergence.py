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
* факультатив без копии создаётся, только если НЕ доказано, что его уже обработал старый backfill (#163).
  Старый backfill — единственный писатель копий факультативов без ключа: переносил ВСЕ факультативы
  пользователя, существовавшие на момент прогона, одной транзакцией вместе с TrainingPlan. Поэтому
  «факультатив уже обработан» = он существовал к моменту прогона: его created_at не позже created_at
  исторической копии (``_backfill_marks``) или TrainingPlan. Копии у такого факультатива нет (или она не
  совпадает) — её удалили или отредактировали в Журнале (#279; копия принадлежит Журналу v2): он НЕ
  воскрешается и НЕ дублируется, а попадает в отчёт ``ambiguous_elective_without_copy`` с доказательством и
  кандидатами. Кандидат (копия, которую, вероятно, правили) НЕ привязывается: одинаковые время, число
  повторов или сумма — не доказательство происхождения.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import and_, or_, select
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

    async def _elective_copies(self, user_id: int) -> list[TrainingSession]:
        """Копии факультативов, включая ещё не классифицированные (origin NULL, source=elective — их
        ``_classify_unlabelled`` в apply помечает legacy_elective): иначе dry-run их не видел бы и обещал
        создать копию, которую apply не создаст (dry-run != apply)."""
        result = await self._session.execute(
            select(TrainingSession)
            .where(
                TrainingSession.user_id == user_id,
                or_(
                    TrainingSession.origin == SessionOrigin.LEGACY_ELECTIVE.value,
                    and_(
                        TrainingSession.origin.is_(None), TrainingSession.source == SessionSource.ELECTIVE,
                        TrainingSession.status == SessionStatus.COMPLETED,
                    ),
                ),
            )
            .order_by(TrainingSession.id)
            .with_for_update(),
        )
        return list(result.scalars().all())

    async def _converge_electives(self, user_id: int, *, apply: bool, report: UserConvergenceReport) -> None:
        repo = self._repo
        electives = list((
            await self._session.execute(
                select(ElectiveWorkout).where(ElectiveWorkout.user_id == user_id).order_by(ElectiveWorkout.id),
            )
        ).scalars().all())
        created_at_of = {e.id: e.created_at for e in electives}
        copies = await self._elective_copies(user_id)
        keyed_ids = {c.legacy_id for c in copies if c.legacy_id is not None}
        unkeyed = [c for c in copies if c.legacy_id is None]
        by_signature: dict[tuple, list[TrainingSession]] = defaultdict(list)
        for copy in unkeyed:
            blocks = await repo.existing_blocks(copy.id)
            by_signature[(copy.performed_at, blocks)].append(copy)
        plan_created_at = (
            await self._session.execute(select(TrainingPlan.created_at).where(TrainingPlan.user_id == user_id))
        ).scalar_one_or_none()
        marks = _backfill_marks(copies, created_at_of)

        for elective in electives:
            if elective.id in keyed_ids:
                continue
            exercise_id = await repo.elective_exercise_id(elective.elective_type)
            key = (elective.performed_at, (BlockSpec(0, exercise_id, _elective_sets(elective)),))
            # копия не может быть старше своего факультатива — такая не его, даже при совпадении содержимого
            candidates = [c for c in by_signature.get(key, ()) if c.created_at >= elective.created_at]
            if candidates:
                copy = candidates[0]
                by_signature[key].remove(copy)
                report.counts["bound"] += 1
                if apply:
                    await repo.bind_legacy_id(copy, SessionOrigin.LEGACY_ELECTIVE, elective.id)
                continue
            evidence = _processed_by_old_backfill(elective, marks, plan_created_at)
            if evidence is None and by_signature.get(key):
                # Копия того же содержимого есть, но она старше факультатива — не его и не «ничья»: не привязываем
                # и не создаём вторую такую же.
                evidence = REASON_EXACT_COPY_PREDATES_ELECTIVE
            if evidence is not None:
                # Старый backfill его уже перенёс, а точной копии нет: её удалили или отредактировали в
                # Журнале. Не воскрешаем и не дублируем; какая из оставшихся копий — правленая, не угадываем.
                report.counts["ambiguous_elective_without_copy"] += 1
                report.ambiguous.append({
                    "elective_id": elective.id, "reason": evidence,
                    "elective_type": elective.elective_type.value,
                    "performed_at": elective.performed_at.isoformat(), "total_reps": elective.total_reps,
                    # непривязанные копии того же формата, созданные не раньше факультатива — только для
                    # ручной проверки оператором; сведение их не привязывает
                    "candidate_copy_ids": sorted(
                        c.id for (_, blocks), group in by_signature.items() for c in group
                        if c.created_at >= elective.created_at and [b.exercise_id for b in blocks] == [exercise_id]
                    ),
                })
                continue
            outcome = await repo.sync_elective(elective, exercise_id=exercise_id, dry_run=not apply)
            if outcome is ConvergenceOutcome.CREATED:
                report.counts["elective_created"] += 1
        report.counts["elective_unkeyed_copies_kept"] += sum(len(group) for group in by_signature.values())


def _elective_sets(elective: ElectiveWorkout):


    return (SetSpec(1, False, Decimal(elective.total_reps), elective_note(elective)),)


REASON_BACKFILL_COPY_CHANGED = "backfilled_copy_edited_or_deleted"
REASON_PRE_PLAN_WITHOUT_COPY = "pre_migration_without_copy"
REASON_EXACT_COPY_PREDATES_ELECTIVE = "exact_copy_predates_elective"


def _backfill_marks(copies: list[TrainingSession], created_at_of: dict[int, datetime]) -> list[datetime]:
    """Моменты прогонов, которые переносили ВСЕ существовавшие тогда факультативы пользователя (created_at
    копии = начало транзакции прогона). Учитываются:

    * копии без ключа — их создавал только старый backfill (#163): новый код пишет ключ при вставке;
    * копии с ключом, созданные ПОЗЖЕ своего факультатива: историческая копия, которой ключ дало сведение,
      либо копия, созданная самим сведением/новым backfill-ом — оба прогона тоже обрабатывали всё, что
      существовало к их началу.

    Не учитывается копия dual-write (ElectiveWorkoutRepository.create): она в одной транзакции со своим
    факультативом (created_at равны) и прогоном не является — иначе запись нового факультатива «доказала» бы
    обработку более раннего факультатива, записанного старым кодом без копии (окно отката)."""
    marks = []
    for copy in copies:
        own = created_at_of.get(copy.legacy_id) if copy.legacy_id is not None else None
        if copy.legacy_id is None or (own is not None and copy.created_at > own):
            marks.append(copy.created_at)
    return marks


def _processed_by_old_backfill(
    elective: ElectiveWorkout, marks: list[datetime], plan_created_at: datetime | None,
) -> str | None:
    """Причина считать факультатив уже обработанным старым backfill-ом (None — не доказано, копию создаём).
    Backfill переносил ВСЕ факультативы, существовавшие к прогону, поэтому достаточно created_at факультатива
    не позже момента прогона (равенство — одна транзакция). Прямое доказательство — историческая копия;
    TrainingPlan (создавался в той же транзакции) — косвенное: им покрыт случай «удалены все копии»."""
    if any(mark >= elective.created_at for mark in marks):
        return REASON_BACKFILL_COPY_CHANGED
    if plan_created_at is not None and elective.created_at <= plan_created_at:
        return REASON_PRE_PLAN_WITHOUT_COPY
    return None
