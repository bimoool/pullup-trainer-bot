"""Сведение legacy-истории в TrainingSession (issue #308, MIGRATION_V2 §4, TRAINING_SESSION_V2 §6 A6).

У каждой завершённой строки старой схемы — ``workouts`` (origin = legacy_backfill) и ``elective_workouts``
(origin = legacy_elective) — ровно ОДНА нативная копия в ``training_sessions`` с ключом
``(origin, legacy_id)`` (уникальный индекс). Этот модуль — единственное место, которое создаёт, обновляет и
замещает такие копии, и им пользуются ОБЕ стороны, чтобы они не могли разойтись:

* dual-write — писатели старой схемы (WorkoutRepository.record_*/edit_*, ElectiveLogService, удаление
  тренировки) вызывают ``sync_*``/``supersede_*`` в той же транзакции;
* backfill — scripts/backfill_multi_program.py вызывает те же ``sync_*`` для уже существующих строк.

Повторное сведение ничего не дублирует: ``sync_*`` сравнивает желаемое содержимое с записанным и пишет только
разницу (UNCHANGED = 0 изменений). Правка legacy-строки обновляет копию (revision + 1), удаление — замещает
её (``superseded_at``/``superseded_reason = legacy_deleted``), строка копии при этом не удаляется
(CLAUDE.md: архивировать, не удалять). Писатели старой схемы НЕ заморожены — это работа Wave 4.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Block, BlockType, ElectiveWorkout, Workout, WorkoutStatus
from app.db.models_program import (
    Exercise,
    SessionBlock,
    SessionStatus,
    SetLog,
    TrainingSession,
)
from app.domain.constants import ExerciseType
from app.domain.electives import ElectiveType
from app.domain.journal_dedupe import resolve_legacy_session_source
from app.domain.multi_program import MetricType, SessionSource
from app.domain.training_session_v2 import (
    DurationSource,
    SessionKind,
    SessionOrigin,
    SessionSourceV2,
    legacy_source_v2,
)

EXERCISE_BLOCK_A_NAME = "Подтягивания — объём"
EXERCISE_BLOCK_B_NAME = "Подтягивания — сила"
ELECTIVE_EXERCISE_NAMES: dict[ElectiveType, str] = {
    ElectiveType.MAX_REPS_LADDER: "Факультатив — подтягивания на максимум",
    ElectiveType.W_LADDER: "Факультатив — подтягивания W",
    ElectiveType.THREE_MINUTES: "Факультатив — 3 минуты подтягиваний",
    ElectiveType.VOLUME_TARGET: "Факультатив — подтягивания на объём",
}

REASON_LEGACY_DELETED = "legacy_deleted"
REASON_LEGACY_REPLACED = "legacy_replaced"
REASON_NATIVE_DUPLICATE = "native_duplicate"


class ConvergenceOutcome(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    SKIPPED = "skipped"  # строка старой схемы ещё не завершена — копии нет


@dataclass(frozen=True)
class SetSpec:
    set_number: int
    is_max_set: bool
    value: Decimal
    note: str | None = None


@dataclass(frozen=True)
class BlockSpec:
    order_index: int
    exercise_id: int
    sets: tuple[SetSpec, ...]


def workout_block_sets(block: Block) -> tuple[SetSpec, ...]:
    """Подходы блока старой схемы в форме SetLog. «Итог без раскладки» (reported_volume, #88) — один
    подход-итог (+ подход на максимум, если он есть); иначе рабочие подходы по порядку и подход на максимум
    (всегда, как писал backfill #163)."""
    if block.reported_volume is not None:
        specs = [SetSpec(1, False, Decimal(block.reported_volume), "итог без раскладки по подходам")]
        if block.max_reps:
            specs.append(SetSpec(2, True, Decimal(block.max_reps)))
        return tuple(specs)
    specs = [SetSpec(number, False, Decimal(reps)) for number, reps in enumerate(block.working_reps, start=1)]
    specs.append(SetSpec(len(specs) + 1, True, Decimal(block.max_reps)))
    return tuple(specs)


def elective_note(elective: ElectiveWorkout) -> str:
    """Снаряд факультатива — единственная деталь, для которой нет структурных полей в SetLog; упакован в
    note (JSON), как писал backfill #163 (читатель — app.bot.formatting.format_elective_set_note)."""
    return json.dumps(
        {
            "format": elective.elective_type.value,
            "reps_sequence": elective.reps_sequence,
            "equipment_type": elective.equipment_type.value,
            "equipment_value": str(elective.equipment_value) if elective.equipment_value is not None else None,
            "equipment_item_id": elective.equipment_item_id,
            "equipment_item_name": elective.equipment_item_name,
        },
        ensure_ascii=False,
    )


class LegacyConvergenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- справочные упражнения --------------------------------------------------------------

    async def _get_or_create_exercise(self, *, name: str, subcategory: str) -> Exercise:
        result = await self._session.execute(select(Exercise).where(Exercise.name == name))
        existing = result.scalars().first()
        if existing is not None:
            return existing
        exercise = Exercise(
            name=name, metric_type=MetricType.REPS, category=ExerciseType.PULL_UPS.value, subcategory=subcategory,
        )
        self._session.add(exercise)
        await self._session.flush()
        return exercise

    async def course_exercise_ids(self) -> tuple[int, int]:
        exercise_a = await self._get_or_create_exercise(name=EXERCISE_BLOCK_A_NAME, subcategory="block_a")
        exercise_b = await self._get_or_create_exercise(name=EXERCISE_BLOCK_B_NAME, subcategory="block_b")
        return exercise_a.id, exercise_b.id

    async def elective_exercise_id(self, elective_type: ElectiveType) -> int:
        exercise = await self._get_or_create_exercise(
            name=ELECTIVE_EXERCISE_NAMES[elective_type], subcategory=f"elective_{elective_type.value}",
        )
        return exercise.id

    # --- чтение копий -----------------------------------------------------------------------

    async def find_copy(self, origin: SessionOrigin, legacy_id: int, *, lock: bool = True) -> TrainingSession | None:
        query = select(TrainingSession).where(
            TrainingSession.origin == origin.value, TrainingSession.legacy_id == legacy_id,
        )
        if lock:
            query = query.with_for_update()
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def existing_blocks(self, session_id: int) -> tuple[BlockSpec, ...]:
        blocks = (
            await self._session.execute(
                select(SessionBlock).where(SessionBlock.session_id == session_id).order_by(SessionBlock.order_index),
            )
        ).scalars().all()
        specs: list[BlockSpec] = []
        for block in blocks:
            logs = (
                await self._session.execute(
                    select(SetLog).where(SetLog.session_block_id == block.id).order_by(SetLog.set_number),
                )
            ).scalars().all()
            specs.append(BlockSpec(
                block.order_index, block.exercise_id or 0,
                tuple(SetSpec(log.set_number, log.is_max_set, log.value, log.note) for log in logs),
            ))
        return tuple(specs)

    async def _write_blocks(self, session_id: int, blocks: tuple[BlockSpec, ...]) -> None:
        await self._session.execute(delete(SessionBlock).where(SessionBlock.session_id == session_id))
        for spec in blocks:
            block = SessionBlock(session_id=session_id, order_index=spec.order_index, exercise_id=spec.exercise_id)
            self._session.add(block)
            await self._session.flush()
            for item in spec.sets:
                self._session.add(SetLog(
                    session_block_id=block.id, set_number=item.set_number, is_max_set=item.is_max_set,
                    metric_type=MetricType.REPS, value=item.value, unit="reps", note=item.note,
                ))
        await self._session.flush()

    # --- sync -------------------------------------------------------------------------------

    async def _upsert(
        self, *, origin: SessionOrigin, legacy_id: int, fields: dict, blocks: tuple[BlockSpec, ...],
        copy: TrainingSession | None = None, dry_run: bool = False,
    ) -> ConvergenceOutcome:
        """Создать копию или привести существующую к желаемому виду; пишет только разницу. copy — уже
        найденная копия (планировщик сведения передаёт её явно, пока legacy_id ещё не записан); dry_run —
        ничего не пишет, возвращает то, что сделал бы apply."""
        if copy is None:
            copy = await self.find_copy(origin, legacy_id, lock=not dry_run)
        if copy is None:
            if dry_run:
                return ConvergenceOutcome.CREATED
            insert = (
                pg_insert(TrainingSession)
                .values(
                    **fields, status=SessionStatus.COMPLETED, origin=origin.value, legacy_id=legacy_id,
                    kind=SessionKind.STRENGTH.value, duration_source=DurationSource.UNKNOWN.value,
                )
                .on_conflict_do_nothing(
                    index_elements=["origin", "legacy_id"], index_where=TrainingSession.legacy_id.is_not(None),
                )
                .returning(TrainingSession.id)
            )
            created_id = (await self._session.execute(insert)).scalar_one_or_none()
            if created_id is not None:
                await self._write_blocks(created_id, blocks)
                return ConvergenceOutcome.CREATED
            copy = await self.find_copy(origin, legacy_id)  # гонка с другим писателем: копия уже есть
            if copy is None:  # pragma: no cover - индекс гарантирует либо вставку, либо строку
                raise RuntimeError("legacy convergence: conflict without an existing copy")

        # Замещение (superseded_at) явное и окончательное: sync его не снимает. Иначе повторное сведение
        # воскресило бы копию, которую заместили как дубль нативной сессии (native_duplicate), и тренировка
        # снова считалась бы дважды.
        content = {name: value for name, value in fields.items() if getattr(copy, name) != value}
        binding = copy.legacy_id != legacy_id or copy.origin != origin.value
        blocks_differ = await self.existing_blocks(copy.id) != blocks
        if not content and not blocks_differ:
            if binding and not dry_run:  # привязка ключа — не правка содержимого (revision не растёт)
                copy.origin, copy.legacy_id = origin.value, legacy_id
                await self._session.flush()
            return ConvergenceOutcome.UNCHANGED
        if dry_run:
            return ConvergenceOutcome.UPDATED
        for name, value in content.items():
            setattr(copy, name, value)
        copy.origin, copy.legacy_id = origin.value, legacy_id
        if blocks_differ:
            await self._write_blocks(copy.id, blocks)
        copy.revision += 1
        await self._session.flush()
        return ConvergenceOutcome.UPDATED

    async def sync_workout(
        self, workout: Workout, *, exercise_a_id: int | None = None, exercise_b_id: int | None = None,
        copy: TrainingSession | None = None, dry_run: bool = False,
    ) -> ConvergenceOutcome:
        """Копия завершённой legacy Workout (MIGRATION_V2 §3: legacy_backfill; длительность неизвестна —
        не выдумываем). Фиктивный блок Б свободных подтягиваний (#109/#156) не переносится."""
        if workout.status != WorkoutStatus.COMPLETED:
            return ConvergenceOutcome.SKIPPED
        if exercise_a_id is None or exercise_b_id is None:
            exercise_a_id, exercise_b_id = await self.course_exercise_ids()
        source = resolve_legacy_session_source(
            participates_in_cascade=workout.participates_in_cascade, is_free_entry=workout.is_free_entry,
        )
        blocks = [BlockSpec(
            0, exercise_a_id, workout_block_sets(next(b for b in workout.blocks if b.block_type == BlockType.A)),
        )]
        if not workout.is_free_entry:
            blocks.append(BlockSpec(
                1, exercise_b_id, workout_block_sets(next(b for b in workout.blocks if b.block_type == BlockType.B)),
            ))
        fields = {
            "user_id": workout.user_id, "source": source, "performed_at": workout.performed_at,
            "comment": workout.comment,
            "source_v2": legacy_source_v2(
                legacy_source=source.value, has_activity=False, has_workout_snapshot=False, is_live=False,
            ).value,
        }
        return await self._upsert(
            origin=SessionOrigin.LEGACY_BACKFILL, legacy_id=workout.id, fields=fields, blocks=tuple(blocks),
            copy=copy, dry_run=dry_run,
        )

    async def sync_elective(
        self, elective: ElectiveWorkout, *, exercise_id: int | None = None, dry_run: bool = False,
    ) -> ConvergenceOutcome:
        """Копия факультатива создаётся ОДИН раз и дальше принадлежит Журналу v2: у legacy-факультатива нет
        писателей правки/удаления, а правка/удаление доказанного факультатива в Журнале (#279) идёт по копии.
        Поэтому существующая копия (в т.ч. отредактированная или замещённая удалением) НЕ перезаписывается
        значениями legacy-строки — повторное сведение не откатывает правку и не воскрешает удалённое."""
        if await self.find_copy(SessionOrigin.LEGACY_ELECTIVE, elective.id, lock=False) is not None:
            return ConvergenceOutcome.UNCHANGED
        if dry_run:
            return ConvergenceOutcome.CREATED
        if exercise_id is None:
            exercise_id = await self.elective_exercise_id(elective.elective_type)
        blocks = (BlockSpec(0, exercise_id, (SetSpec(1, False, Decimal(elective.total_reps), elective_note(elective)),)),)
        fields = {
            "user_id": elective.user_id, "source": SessionSource.ELECTIVE, "performed_at": elective.performed_at,
            "source_v2": SessionSourceV2.MANUAL_EXISTING_WORKOUT.value,
        }
        return await self._upsert(
            origin=SessionOrigin.LEGACY_ELECTIVE, legacy_id=elective.id, fields=fields, blocks=blocks,
        )

    async def bind_legacy_id(self, copy: TrainingSession, origin: SessionOrigin, legacy_id: int) -> None:
        """Привязка историческая копия (создана backfill-ом до #308 без ключа) -> строка старой схемы. Только
        по ТОЧНОМУ совпадению (решает app.services.legacy_history_convergence); содержимое не трогает."""
        copy.origin = origin.value
        copy.legacy_id = legacy_id
        await self._session.flush()

    # --- supersede --------------------------------------------------------------------------

    async def supersede_copy(
        self, copy: TrainingSession, *, reason: str, superseded_by_id: int | None = None, now: datetime | None = None,
    ) -> bool:
        """Явное замещение: строка перестаёт быть тренировкой (canonical_sessions), но не удаляется.
        True — состояние изменилось (повтор = False, идемпотентно)."""
        if copy.superseded_at is not None:
            return False
        copy.superseded_at = now or datetime.now(UTC)
        copy.superseded_reason = reason
        copy.superseded_by_id = superseded_by_id
        copy.revision += 1
        await self._session.flush()
        return True

    async def supersede_deleted_workout(self, workout_id: int) -> bool:
        """Dual-write удаления: legacy Workout удалена (в архив) — её копия замещается (legacy_deleted)."""
        copy = await self.find_copy(SessionOrigin.LEGACY_BACKFILL, workout_id)
        return copy is not None and await self.supersede_copy(copy, reason=REASON_LEGACY_DELETED)

    async def supersede_user_legacy_copies(self, user_id: int) -> int:
        """Админ-сброс прогресса (app.services.admin_reset) архивирует и удаляет ВСЕ workouts пользователя —
        их копии замещаются разом."""
        result = await self._session.execute(
            update(TrainingSession)
            .where(
                TrainingSession.user_id == user_id, TrainingSession.origin == SessionOrigin.LEGACY_BACKFILL.value,
                TrainingSession.superseded_at.is_(None),
            )
            .values(superseded_at=datetime.now(UTC), superseded_reason=REASON_LEGACY_DELETED)
        )
        return result.rowcount or 0
