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
* факультатив без копии — по инварианту ШТАТНЫХ писателей (проверено на коде 1735cad и 4298f8b, где у
  staging/прода жил старый backfill; docs/STAGING_RC_REHEARSAL.md §8 «Фикс»): старый backfill (#163)
  переносит ВСЕ факультативы пользователя одной транзакцией вместе с его TrainingPlan (created_at копий =
  created_at плана) и только пользователям без плана; план уникален и не удаляется ни одним путём кода.
  Отсюда для пользователя со «штатной» историей: факультатив не позже плана — уже перенесён (копии нет —
  её удалили/правили в Журнале #279: НЕ воскрешаем, НЕ дублируем, в отчёт); позже плана или плана нет —
  не переносился никогда, копия создаётся (первый импорт).
* история пользователя не объяснима штатными писателями (уцелевшая историческая копия вне транзакции плана
  или при отсутствии плана — ручной SQL, сиды, ручной фикс) — вывод «никогда не переносился» недоказуем:
  у пользователя НИ ОДИН факультатив без копии не получает копию и привязку, всё — в отчёт
  ``ambiguous_elective_without_copy`` с причиной и кандидатами. Guard ничего не меняет — повторный прогон
  видит те же следы (стабилен). Если и следов не осталось, удаление неотличимо от «не импортировалось» без
  маркера прогона backfill — это известный пробел (§8 «Фикс»), а не доказательство.
* кандидат (копия, которую, вероятно, правили) НЕ привязывается: одинаковые время, число повторов или сумма —
  не доказательство происхождения.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Select, and_, or_, select, text
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

# Счётчики, означающие запись в БД (критерий «повторный apply = 0 изменений»); читаются и машинным результатом
# scripts/backfill_multi_program.py --converge-history (строка RESULT-JSON).
MUTATING_KEYS = ("classified", "bound", "created", "updated", "superseded", "elective_created")


@dataclass
class UserConvergenceReport:
    user_id: int
    counts: Counter = field(default_factory=Counter)
    ambiguous: list[dict] = field(default_factory=list)

    @property
    def mutations(self) -> int:
        """Сколько записей изменит (изменило) apply — для критерия «apply-again = 0»."""
        return sum(self.counts[key] for key in MUTATING_KEYS)


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
    def __init__(self, session: AsyncSession, *, read_only: bool = False) -> None:
        self._session = session
        self._read_only = read_only
        self._repo = LegacyConvergenceRepository(session)

    def _query(self, query: Select) -> Select:
        return query if self._read_only else query.with_for_update()

    async def _copies(self, user_id: int) -> list[TrainingSession]:
        result = await self._session.execute(
            self._query(select(TrainingSession).where(
                TrainingSession.user_id == user_id,
                TrainingSession.origin.in_((SessionOrigin.LEGACY_BACKFILL.value, SessionOrigin.LEGACY_ELECTIVE.value)),
            )
            .order_by(TrainingSession.id)),
        )
        return list(result.scalars().all())

    async def _classify_unlabelled(self, user_id: int, *, apply: bool, report: UserConvergenceReport) -> None:
        """Строки без origin (код до #307 в окне деплоя): копии backfill-а узнаём по отпечатку (ТОЛЬКО здесь,
        читатели его не используют), электив — по source."""
        rows = (
            await self._session.execute(
                self._query(select(TrainingSession).where(
                    TrainingSession.user_id == user_id, TrainingSession.origin.is_(None),
                    TrainingSession.status == SessionStatus.COMPLETED,
                ).order_by(TrainingSession.id)),
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
        if apply and self._read_only:
            raise ValueError("read-only convergence cannot apply")
        report = UserConvergenceReport(user_id)
        repo = self._repo
        plan_created_at = (
            await self._session.execute(select(TrainingPlan.created_at).where(TrainingPlan.user_id == user_id))
        ).scalar_one_or_none()
        # до любых записей прогона: копии, созданные сведением сейчас, следом нештатной истории не считаются
        nonstandard = await self._nonstandard_history(user_id, plan_created_at)
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

        await self._converge_electives(
            user_id, apply=apply, report=report, nonstandard=nonstandard, plan_created_at=plan_created_at,
        )
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
            self._query(select(TrainingSession).where(
                TrainingSession.user_id == user_id,
                or_(
                    TrainingSession.origin == SessionOrigin.LEGACY_ELECTIVE.value,
                    and_(
                        TrainingSession.origin.is_(None), TrainingSession.source == SessionSource.ELECTIVE,
                        TrainingSession.status == SessionStatus.COMPLETED,
                    ),
                ),
            )
            .order_by(TrainingSession.id)),
        )
        return list(result.scalars().all())

    async def _nonstandard_history(self, user_id: int, plan_created_at: datetime | None) -> str | None:
        """Следы, которые штатные писатели оставить не могли (None — история объяснима штатными путями).
        Читается ДО любых записей этого прогона (копии, созданные сведением сейчас, следом не считаются).

        Штатные писатели копий факультативов: старый backfill — без ключа, в транзакции плана (created_at
        равны); сведение/новый backfill/dual-write — с ключом, не раньше своего факультатива (dual-write — в
        одной транзакции с ним); факультативу не позже плана сведение копию не создаёт. Ключ теряется только
        при ``alembic downgrade`` a7e2c5b9d1f4 — такая копия остаётся точной копией своего факультатива. След:

        * план есть: копия без ключа вне транзакции плана, которая не является точной копией факультатива,
          записанного после плана и не позже неё;
        * плана нет: любая копия без ключа, кроме точной копии факультатива не позже неё, и любая копия с
          ключом, созданная позже своей legacy-строки (прогон импорта) — backfill без плана копий не пишет, а
          план не удаляется ни одним путём кода. Копия dual-write (created_at равен строке) следом не является.
        Привязка ключа (её делает только этот же сервис) след не стирает: без плана «с ключом и позже своей
        строки» покрывает и привязанную; с планом у пользователя под guard'ом привязки нет."""
        rows = (await self._session.execute(text("""
            SELECT ts.id, ts.origin, ts.source, ts.legacy_id, ts.created_at, ts.performed_at,
                   coalesce(w.created_at, e.created_at) AS own_created_at
            FROM training_sessions ts
            LEFT JOIN workouts w ON ts.origin = 'legacy_backfill' AND w.id = ts.legacy_id
            LEFT JOIN elective_workouts e ON ts.origin = 'legacy_elective' AND e.id = ts.legacy_id
            WHERE ts.user_id = :user_id
              AND (ts.origin IN ('legacy_backfill', 'legacy_elective')
                   OR (ts.origin IS NULL AND ts.source = 'elective' AND ts.status = 'completed'))
              AND ts.created_at < now()
            ORDER BY ts.id
        """), {"user_id": user_id})).all()
        unkeyed_electives = [
            r for r in rows if r.legacy_id is None and r.origin != SessionOrigin.LEGACY_BACKFILL.value
            and (plan_created_at is None or r.created_at != plan_created_at)
        ]
        stray = [r.id for r in unkeyed_electives if not await self._is_exact_later_import_copy(user_id, r, plan_created_at)]
        if plan_created_at is not None:
            return f"unkeyed_elective_copy_outside_plan_transaction:{stray}" if stray else None
        stray += [
            r.id for r in rows
            if (r.legacy_id is None and r.origin == SessionOrigin.LEGACY_BACKFILL.value)
            or (r.legacy_id is not None and r.own_created_at is not None and r.created_at > r.own_created_at)
        ]
        return f"import_copy_without_plan:{sorted(stray)}" if stray else None

    async def _is_exact_later_import_copy(self, user_id: int, row, plan_created_at: datetime | None) -> bool:
        """Копия без ключа — точная копия факультатива, которому штатный импорт копию создаёт (после плана или
        без плана), и не старше его: копия сведения/dual-write, потерявшая ключ при downgrade."""
        blocks = await self._repo.existing_blocks(row.id)
        if len(blocks) != 1:
            return False
        electives = (await self._session.execute(
            select(ElectiveWorkout).where(
                ElectiveWorkout.user_id == user_id, ElectiveWorkout.performed_at == row.performed_at,
                ElectiveWorkout.created_at <= row.created_at,
            ),
        )).scalars().all()
        for elective in electives:
            if plan_created_at is not None and elective.created_at <= plan_created_at:
                continue
            exercise_id = await self._repo.elective_exercise_id(elective.elective_type)
            if blocks == (BlockSpec(0, exercise_id, _elective_sets(elective)),):
                return True
        return False

    async def _converge_electives(
        self, user_id: int, *, apply: bool, report: UserConvergenceReport, nonstandard: str | None,
        plan_created_at: datetime | None,
    ) -> None:
        repo = self._repo
        electives = list((
            await self._session.execute(
                select(ElectiveWorkout).where(ElectiveWorkout.user_id == user_id).order_by(ElectiveWorkout.id),
            )
        ).scalars().all())
        copies = await self._elective_copies(user_id)
        keyed_ids = {c.legacy_id for c in copies if c.legacy_id is not None}
        unkeyed = [c for c in copies if c.legacy_id is None]
        by_signature: dict[tuple, list[TrainingSession]] = defaultdict(list)
        for copy in unkeyed:
            blocks = await repo.existing_blocks(copy.id)
            by_signature[(copy.performed_at, blocks)].append(copy)
        # перенос прогоном backfill доказан уцелевшей копией из транзакции плана (иначе — только планом)
        run_proven = plan_created_at is not None and any(c.created_at == plan_created_at for c in copies)

        def unresolved(elective: ElectiveWorkout, exercise_id: int, reason: str) -> None:
            report.counts["ambiguous_elective_without_copy"] += 1
            report.ambiguous.append({
                "elective_id": elective.id, "reason": reason,
                "elective_type": elective.elective_type.value,
                "performed_at": elective.performed_at.isoformat(), "total_reps": elective.total_reps,
                # непривязанные копии того же формата, созданные не раньше факультатива — только для ручной
                # проверки оператором; сведение их не привязывает
                "candidate_copy_ids": sorted(
                    c.id for (_, blocks), group in by_signature.items() for c in group
                    if c.created_at >= elective.created_at and [b.exercise_id for b in blocks] == [exercise_id]
                ),
                **({"evidence": nonstandard} if reason == REASON_NONSTANDARD_HISTORY else {}),
            })

        for elective in electives:
            if elective.id in keyed_ids:
                continue
            exercise_id = await repo.elective_exercise_id(elective.elective_type)
            if nonstandard is not None:
                unresolved(elective, exercise_id, REASON_NONSTANDARD_HISTORY)
                continue
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
            if plan_created_at is not None and elective.created_at <= plan_created_at:
                # Существовал к прогону backfill (равенство — одна транзакция), а точной копии нет: её удалили или
                # отредактировали в Журнале. Не воскрешаем и не дублируем; какая копия правленая — не угадываем.
                unresolved(
                    elective, exercise_id, REASON_BACKFILL_COPY_CHANGED if run_proven else REASON_PRE_PLAN_WITHOUT_COPY,
                )
                continue
            if by_signature.get(key):
                # Копия того же содержимого есть, но она старше факультатива — не его и не «ничья»: не привязываем
                # и не создаём вторую такую же.
                unresolved(elective, exercise_id, REASON_EXACT_COPY_PREDATES_ELECTIVE)
                continue
            outcome = await repo.sync_elective(elective, exercise_id=exercise_id, dry_run=not apply)
            if outcome is ConvergenceOutcome.CREATED:
                report.counts["elective_created"] += 1
                if plan_created_at is None:
                    # основание — штатный инвариант «плана нет -> backfill не проходил», не след первого импорта
                    report.counts["elective_first_import_without_plan"] += 1
        report.counts["elective_unkeyed_copies_kept"] += sum(len(group) for group in by_signature.values())


def _elective_sets(elective: ElectiveWorkout):
    return (SetSpec(1, False, Decimal(elective.total_reps), elective_note(elective)),)


REASON_BACKFILL_COPY_CHANGED = "backfilled_copy_edited_or_deleted"
REASON_PRE_PLAN_WITHOUT_COPY = "pre_migration_without_copy"
REASON_EXACT_COPY_PREDATES_ELECTIVE = "exact_copy_predates_elective"
REASON_NONSTANDARD_HISTORY = "nonstandard_copy_history"
