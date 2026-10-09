"""Канонический слой TrainingSession v2 (issue #307, docs/domain/TRAINING_SESSION_V2.md).

Здесь — всё, что делает сессию самодостаточной записью выполненной работы, одинаково для каждого
писателя:

- ``stamp_new`` — поля v2 только что созданной сессии (source_v2/kind/origin, определение и версия,
  PrescriptionSnapshot, инклюзия, начало, часовой пояс, длительность). Вызывают: живой старт
  (planned_live/direct_live), ручная запись (manual_*/external_activity, app.services.manual_session),
  копия (``clone``).
- ``prescription_snapshot`` — снимок рецепта (S1): снимок текущей версии определения, если он
  согласован с записанными целями (R1), иначе синтезированный из целей (S4) или, без рецепта, из факта
  (unprescribed).
- ``verdicts`` — ED1 (правка/копия) рядом с предикатом безопасного удаления (не заменяя его).
- ``clone`` — копия без кредита плана (D10) с источником по правилу §2.

Завершение живой сессии (ended_at, длительность R3) — TrainingSessionRepository.mark_completed: это
единственная точка, через которую проходят все пути завершения (complete, finish interval, ленивая
финализация). Интерфейс завершения для движка v2 (#306) — LiveSessionService.complete_session(...,
active_elapsed_ms=...); контракт — docs/domain/TRAINING_SESSION_V2.md §8.
"""

from dataclasses import dataclass, replace
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.programs import ProgramRepository
from app.db.repositories.training_plans import TrainingPlanRepository
from app.db.repositories.training_sessions import (
    SessionBlockDetail,
    SessionDetail,
    SessionV2Stamp,
    TrainingSessionRepository,
)
from app.db.repositories.workout_definitions import WorkoutDefinitionRepository
from app.domain.multi_program import INTERNAL_ROLE_SUBCATEGORIES, MetricType
from app.domain.training_session_v2 import (
    UNKNOWN_DURATION,
    Duration,
    DurationSource,
    EditVerdict,
    LogRecord,
    SessionFacts,
    SessionKind,
    SessionOrigin,
    SessionSourceV2,
    SetOutcome,
    SetStatus,
    SynthBlock,
    SynthSet,
    TargetRecord,
    clone_source,
    edit_verdict,
    set_outcomes,
    snapshot_matches_blocks,
    synthesize_snapshot,
)
from app.domain.workout_definition import SnapshotResolutionError, snapshot_to_dict
from app.domain.workout_snapshot import positional_snapshot_items
from app.services.session_deletion import (
    REASON_PROGRAM,
    REASON_STEP,
    DeleteVerdict,
    SessionDeletionService,
)
from app.services.workout_definition import WorkoutDefinitionService


@dataclass(frozen=True)
class SessionVerdicts:
    delete: DeleteVerdict
    edit: EditVerdict


class TrainingSessionV2Service:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._sessions = TrainingSessionRepository(session)
        self._programs = ProgramRepository(session)
        self._plans = TrainingPlanRepository(session)
        self._definitions = WorkoutDefinitionRepository(session)

    # --- Снимок рецепта ---------------------------------------------------------------------

    async def _title(self, workout_definition_id: int | None, program_inclusion_id: int | None) -> str:
        if workout_definition_id is not None:
            complex_ = await self._programs.get_complex(workout_definition_id)
            if complex_ is not None:
                return complex_.name
        if program_inclusion_id is not None:
            inclusion = await self._plans.get_inclusion_by_id(program_inclusion_id)
            if inclusion is not None:
                return (inclusion.snapshot or {}).get("program_name", "")
        return ""

    async def _version_snapshot(
        self, detail: SessionDetail, workout_definition_id: int, resolved_at: datetime,
    ) -> dict | None:
        """Снимок текущей версии определения (WORKOUT §5) — только если он согласован с тем, что
        сессия реально записала (те же упражнения по порядку, то же число подходов, R1). Иначе None:
        снимок не должен противоречить SetTarget (так бывает, пока движок v1 строит цели из V1-головы,
        а версия v2 явнее, например лесенка; #306 строит цели из снимка — расхождение исчезнет)."""
        complex_ = await self._programs.get_complex(workout_definition_id)
        if complex_ is None or complex_.current_version_id is None:
            return None
        try:
            snapshot = await WorkoutDefinitionService(self._session).build_snapshot(
                complex_.current_version_id, resolved_at=resolved_at,
            )
        except SnapshotResolutionError:
            return None  # progression-блок без резолвера: рецепт курса — из целей (#305)
        data = snapshot_to_dict(snapshot)
        blocks = [(block.exercise_id, len(block.set_targets)) for block in detail.blocks]
        return data if snapshot_matches_blocks(data, blocks) else None

    async def prescription_snapshot(
        self, detail: SessionDetail, *, workout_definition_id: int | None, program_inclusion_id: int | None,
        resolved_at: datetime,
    ) -> dict | None:
        """S1: снимок рецепта сессии; у внешней активности снимка нет (§7)."""
        if detail.kind == SessionKind.EXTERNAL_ACTIVITY.value:
            return None
        if workout_definition_id is not None:
            version = await self._version_snapshot(detail, workout_definition_id, resolved_at)
            if version is not None:
                return version
        return await self.synthesized_snapshot(
            detail, workout_definition_id=workout_definition_id, program_inclusion_id=program_inclusion_id,
            resolved_at=resolved_at,
        )

    async def synthesized_snapshot(
        self, detail: SessionDetail, *, workout_definition_id: int | None, program_inclusion_id: int | None,
        resolved_at: datetime,
    ) -> dict:
        """S4: из целей сессии; без единой цели — из выполненного (prescribed = performed,
        unprescribed). Имена/идентичность аналитики — из каталога (E1/E2), блок интервала — по
        v1-снимку/результату."""
        exercise_ids = sorted({b.exercise_id for b in detail.blocks if b.exercise_id is not None})
        infos = await self._definitions.exercise_infos(exercise_ids)
        v1_items = positional_snapshot_items(detail.workout_snapshot, len(detail.blocks))
        unprescribed = not any(block.set_targets for block in detail.blocks)
        blocks: list[SynthBlock] = []
        for block, item in zip(detail.blocks, v1_items, strict=True):
            if block.exercise_id is None:
                continue  # complex-блок без упражнения (легаси форма) — в рецепте не выражается
            info = infos.get(block.exercise_id)
            is_interval = (item is not None and item.protocol.type.value == "interval") or (
                isinstance(block.result, dict) and block.result.get("type") == "interval"
            )
            source = block.set_targets if not unprescribed else [log for log in block.set_logs if not log.is_extra]
            blocks.append(SynthBlock(
                exercise_id=block.exercise_id,
                exercise_display_name=info.display_name if info is not None else f"Упражнение #{block.exercise_id}",
                analytics_exercise_id=info.analytics_exercise_id if info is not None else block.exercise_id,
                category_id=info.category_id if info is not None else None,
                sets=tuple(
                    SynthSet(
                        metric="time" if s.metric_type == MetricType.TIME else "reps", value=s.value,
                        is_max_set=s.is_max_set,
                    )
                    for s in source
                ),
                is_interval=is_interval,
            ))
        return synthesize_snapshot(
            title=await self._title(workout_definition_id, program_inclusion_id), blocks=blocks,
            resolved_at=resolved_at, unprescribed=unprescribed, workout_definition_id=workout_definition_id,
            program_inclusion_id=program_inclusion_id,
        )

    # --- Создание -------------------------------------------------------------------------

    async def stamp_new(
        self, session_id: int, user_id: int, *, source: SessionSourceV2, resolved_at: datetime,
        workout_definition_id: int | None = None, program_inclusion_id: int | None = None,
        started_at: datetime | None = None, timezone: str | None = None, duration: Duration | None = None,
        distance_meters: int | None = None, engine_version: int | None = None,
        origin: SessionOrigin = SessionOrigin.NATIVE,
    ) -> SessionDetail:
        """Поля v2 сессии, созданной в этой же транзакции. duration=None — не трогать (живая сессия
        получает длительность при завершении)."""
        detail = await self._sessions.get_for_user(session_id, user_id)
        kind = SessionKind.EXTERNAL_ACTIVITY if source is SessionSourceV2.EXTERNAL_ACTIVITY else SessionKind.STRENGTH
        detail_for_snapshot = detail if detail.kind == kind.value else _with_kind(detail, kind)
        snapshot = await self.prescription_snapshot(
            detail_for_snapshot, workout_definition_id=workout_definition_id,
            program_inclusion_id=program_inclusion_id, resolved_at=resolved_at,
        )
        await self._sessions.apply_v2_stamp(session_id, SessionV2Stamp(
            kind=kind.value, source_v2=source.value, origin=origin.value,
            workout_definition_id=workout_definition_id,
            workout_definition_version_id=(snapshot or {}).get("workout_definition_version_id"),
            prescription_snapshot=snapshot, program_inclusion_id=program_inclusion_id, started_at=started_at,
            timezone=timezone, duration_seconds=duration.seconds if duration is not None else None,
            duration_source=duration.source.value if duration is not None else None,
            distance_meters=distance_meters, engine_version=engine_version,
        ))
        return await self._sessions.get_for_user(session_id, user_id)

    # --- Предикаты (ED1 + удаление) --------------------------------------------------------

    async def verdicts(self, details: list[SessionDetail], user_id: int) -> dict[int, SessionVerdicts]:
        """Удаление — прежний строгий предикат (PROJECT_SPEC §3). Правка/копия — ED1;
        consumed_by_progression — сессия связана с курсом или касается роли STEP (по вердикту
        удаления или по самим блокам — у недоказуемых сессий удаление роль не проверяет)."""
        if not details:
            return {}
        deletion = await SessionDeletionService(self._session).evaluate(details, user_id)
        exercise_ids = sorted({b.exercise_id for d in details for b in d.blocks if b.exercise_id is not None})
        role_exercise_ids = {
            e.id for e in await self._programs.list_exercises_by_ids(exercise_ids)
            if e.subcategory in INTERNAL_ROLE_SUBCATEGORIES
        }
        result: dict[int, SessionVerdicts] = {}
        for detail in details:
            delete_verdict = deletion[detail.id]
            consumed = (
                delete_verdict.reason in (REASON_PROGRAM, REASON_STEP)
                or detail.program_inclusion_id is not None
                or any(block.exercise_id in role_exercise_ids for block in detail.blocks)
            )
            facts = SessionFacts(
                completed=detail.status.value == "completed", kind=SessionKind(detail.kind),
                source=SessionSourceV2(detail.source_v2), origin=SessionOrigin(detail.origin),
                consumed_by_progression=consumed,
            )
            result[detail.id] = SessionVerdicts(delete=delete_verdict, edit=edit_verdict(facts))
        return result

    # --- Копия ----------------------------------------------------------------------------

    async def clone(self, detail: SessionDetail, user_id: int, *, performed_at: datetime, now: datetime) -> int:
        """§2/D10: копия — manual_existing_workout (есть определение) / manual_custom / внешняя
        активность; тот же снимок рецепта и определение, БЕЗ plan_item_id и инклюзии. Длительность:
        у внешней активности — введённая (это и есть запись активности), у силовой — неизвестна
        (копия не измерялась; не выдумываем)."""
        kind = SessionKind(detail.kind)
        source = clone_source(original_kind=kind, workout_definition_id=detail.workout_definition_id)
        duration = (
            Duration(detail.duration_seconds, detail_duration_source(detail))
            if kind is SessionKind.EXTERNAL_ACTIVITY and detail.duration_seconds is not None else UNKNOWN_DURATION
        )
        stamp = SessionV2Stamp(
            kind=kind.value, source_v2=source.value, origin=SessionOrigin.NATIVE.value,
            workout_definition_id=detail.workout_definition_id,
            workout_definition_version_id=detail.workout_definition_version_id,
            prescription_snapshot=detail.prescription_snapshot, timezone=detail.timezone,
            duration_seconds=duration.seconds, duration_source=duration.source.value,
            distance_meters=detail.distance_meters,
        )
        clone = await self._sessions.clone_session(detail.id, user_id=user_id, performed_at=performed_at, stamp=stamp)
        if kind is SessionKind.STRENGTH and detail.prescription_snapshot is None:
            # Оригинал — история до синтеза снимков (скрипт ещё не прошёл): копия получает свой.
            clone_detail = await self._sessions.get_for_user(clone.id, user_id)
            snapshot = await self.synthesized_snapshot(
                clone_detail, workout_definition_id=detail.workout_definition_id, program_inclusion_id=None,
                resolved_at=now,
            )
            await self._sessions.apply_v2_stamp(clone.id, replace(stamp, prescription_snapshot=snapshot))
        return clone.id


def detail_duration_source(detail: SessionDetail) -> DurationSource:
    return DurationSource(detail.duration_source) if detail.duration_source else DurationSource.ENTERED


def _with_kind(detail: SessionDetail, kind: SessionKind) -> SessionDetail:
    return replace(detail, kind=kind.value)


# --- Контракт чтения для Журнала/Аналитики (#308) -------------------------------------------


def block_outcomes(block: SessionBlockDetail) -> list[SetOutcome]:
    """Исходы подходов блока: факт против рецепта (R1/R2) — невыполненные цели, подходы сверх
    рецепта, подход на максимум. Чистое чтение SetTarget/SetLog, без запросов."""
    return set_outcomes(
        [TargetRecord(set_number=t.set_number, value=t.value, is_max_set=t.is_max_set) for t in block.set_targets],
        [
            LogRecord(
                set_number=log.set_number, value=log.value, is_max_set=log.is_max_set, is_extra=log.is_extra,
                status=SetStatus(log.status),
            )
            for log in block.set_logs
        ],
    )
