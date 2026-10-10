"""TrainingSession v2 — канонический контракт выполненной тренировки (issue #307, Wave 3a).

Контракт: docs/domain/TRAINING_SESSION_V2.md (§2 источники, §3 подходы и длительность, §4
редактируемость) и docs/domain/MIGRATION_V2.md §3 (детерминированный backfill). Решение AD-8: одна
сущность TrainingSession для planned live, direct live, manual existing, manual custom и внешней
активности; source_v2 задаётся при создании и потом не выводится заново.

Чистый домен: ни aiogram, ни SQLAlchemy, «сейчас» приходит снаружи. Сервисный слой
(app.services.training_session_v2) переводит строки БД в эти типы и обратно.

Продуктовые числа:
- MIN/MAX_MEASURED_SECONDS = 60 / 6 ч — то же окно, что app.domain.training_analytics
  (MIN_DURATION_SECONDS/MAX_DURATION_SECONDS) использует для минут сессий без duration_seconds;
  backfill обязан дать ровно те же минуты (итоги старых пользователей не уменьшаются). Повторено
  литералом и сверяется тестом, а не импортируется: правило длительности сессии — этот модуль.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any

from app.domain.workout_definition import (
    BlockKind,
    BlockSource,
    PrescriptionSnapshot,
    SetKind,
    SetPrescription,
    SetRole,
    SnapshotBlock,
    SnapshotProvenance,
    snapshot_to_dict,
)

MIN_MEASURED_SECONDS = 60
MAX_MEASURED_SECONDS = 6 * 3600

IDENTITY_EXACT_MATCH_V1 = "exact_match_v1"
"""identity_recovered_by: workout_definition_id восстановлен по единственному точному совпадению
упорядоченного списка упражнений (MIGRATION_V2 §3). Никаких других способов «угадать» нет."""

PRESCRIPTION_UNPRESCRIBED = "unprescribed"
"""prescription_kind синтезированного снимка без рецепта: prescribed = performed (manual_custom,
старые записи без set_targets). Ключ верхнего уровня снимка; снисходительный читатель
snapshot_from_dict незнакомые ключи игнорирует."""


class SessionKind(StrEnum):
    STRENGTH = "strength"
    EXTERNAL_ACTIVITY = "external_activity"


class SessionSourceV2(StrEnum):
    PLANNED_LIVE = "planned_live"
    DIRECT_LIVE = "direct_live"
    MANUAL_EXISTING_WORKOUT = "manual_existing_workout"
    MANUAL_CUSTOM = "manual_custom"
    EXTERNAL_ACTIVITY = "external_activity"


class SessionOrigin(StrEnum):
    """Происхождение СТРОКИ (не источник тренировки): native — записана приложением,
    legacy_backfill — копия legacy Workout (scripts/backfill_multi_program.py),
    legacy_elective — копия legacy ElectiveWorkout."""

    NATIVE = "native"
    LEGACY_BACKFILL = "legacy_backfill"
    LEGACY_ELECTIVE = "legacy_elective"


class DurationSource(StrEnum):
    MEASURED = "measured"
    ENTERED = "entered"
    UNKNOWN = "unknown"


class SetStatus(StrEnum):
    PERFORMED = "performed"
    NOT_PERFORMED = "not_performed"


# ============================================================================
# Источник: создание и детерминированный backfill (§2, MIGRATION §3)
# ============================================================================


def legacy_source_v2(
    *, legacy_source: str, has_activity: bool, has_workout_snapshot: bool, is_live: bool,
    recovered_definition: bool = False,
) -> SessionSourceV2:
    """Источник v2 строки, записанной до #307, из того, что о ней известно (MIGRATION_V2 §3).

    legacy_source — значение старой колонки training_sessions.source (plan/freeform/backdated/
    elective). is_live — у строки есть client_session_id (её создал живой старт). Строки, которых
    таблица MIGRATION не называет явно: freeform без снимка и активности — direct_live, если она
    живая (старт Workout без Builder-протокола), иначе manual_custom (свободная запись legacy).
    backdated без снимка — manual_existing_workout только при восстановленной идентичности
    (recovered_definition), иначе manual_custom: не угадываем."""
    if has_activity:
        return SessionSourceV2.EXTERNAL_ACTIVITY
    if legacy_source == "plan":
        return SessionSourceV2.PLANNED_LIVE
    if legacy_source == "elective":
        return SessionSourceV2.MANUAL_EXISTING_WORKOUT
    if legacy_source == "freeform":
        return SessionSourceV2.DIRECT_LIVE if (has_workout_snapshot or is_live) else SessionSourceV2.MANUAL_CUSTOM
    if legacy_source == "backdated":
        if has_workout_snapshot or recovered_definition:
            return SessionSourceV2.MANUAL_EXISTING_WORKOUT
        return SessionSourceV2.MANUAL_CUSTOM
    raise ValueError(f"неизвестный source {legacy_source!r}")


def kind_for_source(source: SessionSourceV2) -> SessionKind:
    return SessionKind.EXTERNAL_ACTIVITY if source is SessionSourceV2.EXTERNAL_ACTIVITY else SessionKind.STRENGTH


# Ручные/пост-фактум источники (в т.ч. копия, §2/D10): историческая запись, НЕ старт курса. Блоки ролей
# STEP, перенесённые в копию, не дают ей программной семантики: такая сессия не двигает отдых MAIN,
# счётчики инклюзии, кредит занятия и прогрессию (решение владельца, #307 финальное ревью; §4 ED1b).
MANUAL_SOURCES: frozenset[SessionSourceV2] = frozenset({
    SessionSourceV2.MANUAL_EXISTING_WORKOUT, SessionSourceV2.MANUAL_CUSTOM,
})


def clone_source(*, original_kind: SessionKind, workout_definition_id: int | None) -> SessionSourceV2:
    """Копия (§2, D10): manual_existing_workout, если у оригинала есть определение, иначе
    manual_custom; внешняя активность остаётся внешней. plan_item_id копии — всегда None."""
    if original_kind is SessionKind.EXTERNAL_ACTIVITY:
        return SessionSourceV2.EXTERNAL_ACTIVITY
    return SessionSourceV2.MANUAL_EXISTING_WORKOUT if workout_definition_id is not None else SessionSourceV2.MANUAL_CUSTOM


def recover_identity(
    session_exercise_ids: Sequence[int], candidates: Mapping[int, Collection[tuple[int, ...]]],
) -> int | None:
    """MIGRATION_V2 §3: workout_definition_id старой backdated-записи восстанавливается, ТОЛЬКО
    если ровно одна тренировка пользователя (живая или архивная) имеет тот же упорядоченный список
    упражнений. candidates — workout_id → известные упорядоченные списки упражнений (голова + все
    версии). 0 или ≥ 2 совпадений → None (manual_custom, не угадываем). Пустая запись — None."""
    wanted = tuple(session_exercise_ids)
    if not wanted:
        return None
    matches = [workout_id for workout_id, lists in candidates.items() if wanted in set(lists)]
    return matches[0] if len(matches) == 1 else None


# ============================================================================
# Длительность (R3, R4)
# ============================================================================


@dataclass(frozen=True)
class Duration:
    seconds: int | None
    source: DurationSource


UNKNOWN_DURATION = Duration(None, DurationSource.UNKNOWN)


def measured_duration(
    started_at: datetime | None, ended_at: datetime | None, *, active_elapsed_ms: int | None = None,
) -> Duration:
    """R3, живая сессия. active_elapsed_ms — от движка (паузы исключены; Live Engine v2, #306):
    ему доверяем как измерению. Без него (движок v1 паузы не считает) — стенные часы
    ended − started, но только в окне [1 мин, 6 ч], иначе unknown: брошенная на сутки сессия не
    становится 24 часами тренировки."""
    if active_elapsed_ms is not None:
        if active_elapsed_ms < 0:
            raise ValueError("active_elapsed_ms < 0")
        # #307 N2 (решено в #306): 0 мс (до секунды) — не «измеренные 0 секунд», а отсутствие измерения;
        # больше 6 ч активного времени — брошенная открытой сессия, не тренировка. Оба — unknown (A5:
        # without_duration, никогда не 0 и не выдуманная минута). Короткая честная работа (планка 40 с)
        # остаётся measured: нижнего окна в 1 мин у измерения движка нет.
        seconds = (active_elapsed_ms + 500) // 1000
        if seconds <= 0 or seconds > MAX_MEASURED_SECONDS:
            return UNKNOWN_DURATION
        return Duration(seconds, DurationSource.MEASURED)
    if started_at is None or ended_at is None:
        return UNKNOWN_DURATION
    seconds = (ended_at - started_at).total_seconds()
    if MIN_MEASURED_SECONDS <= seconds <= MAX_MEASURED_SECONDS:
        return Duration(int(seconds), DurationSource.MEASURED)
    return UNKNOWN_DURATION


def entered_duration(seconds: int | None) -> Duration:
    """R3, ручная запись: введённые пользователем секунды (entered) или unknown — никогда 0."""
    if seconds is None:
        return UNKNOWN_DURATION
    if seconds <= 0:
        raise ValueError("длительность должна быть положительной")
    return Duration(seconds, DurationSource.ENTERED)


def legacy_duration(
    *, has_activity: bool, duration_seconds: int | None, performed_at: datetime, completed_at: datetime | None,
) -> Duration:
    """MIGRATION_V2 §3: активность — её значение (entered); прочие — completed_at − performed_at в
    окне [1 мин, 6 ч] (measured), иначе unknown. Ровно то, что аналитика уже считала минутами.
    Backfill пишет только source; seconds — для читателя (effective_duration_seconds)."""
    if has_activity:
        return Duration(duration_seconds, DurationSource.ENTERED) if duration_seconds else UNKNOWN_DURATION
    if duration_seconds is not None:
        return Duration(duration_seconds, DurationSource.MEASURED)
    return measured_duration(performed_at, completed_at)


def effective_duration_seconds(
    *, duration_seconds: int | None, duration_source: str | None, performed_at: datetime,
    completed_at: datetime | None,
) -> int | None:
    """Длительность сессии для любого читателя (A5): сохранённая, иначе — у измеренной истории
    (миграция не переписывает duration_seconds) completed_at − performed_at в окне [1 мин, 6 ч];
    unknown — None (никогда не 0). Строка старого кода без duration_source читается так же, как
    читала аналитика."""
    if duration_seconds is not None:
        return duration_seconds
    if duration_source not in (None, DurationSource.MEASURED.value):
        return None
    return measured_duration(performed_at, completed_at).seconds


@dataclass(frozen=True)
class SessionTimes:
    performed_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    completed_at: datetime | None


def move_session_date(times: SessionTimes, new_performed_at: datetime) -> SessionTimes:
    """R4: правка даты сдвигает performed_at и started/ended/completed на ту же дельту;
    duration_seconds не меняется (его здесь просто нет). Раньше completed_at «подтягивался» к
    performed_at — и длительность стиралась (D13)."""
    delta: timedelta = new_performed_at - times.performed_at

    def shift(value: datetime | None) -> datetime | None:
        return None if value is None else value + delta

    return SessionTimes(
        performed_at=new_performed_at, started_at=shift(times.started_at), ended_at=shift(times.ended_at),
        completed_at=shift(times.completed_at),
    )


# ============================================================================
# Редактируемость (§4, ED1–ED3)
# ============================================================================


class EditField(StrEnum):
    DATE = "date"
    DURATION = "duration"
    EFFORT = "effort"
    COMMENT = "comment"
    SET_ACTUALS = "set_actuals"
    SET_NOTES = "set_notes"
    ACTIVITY_TYPE = "activity_type"
    DISTANCE = "distance"


REASON_ACTIVE = "Тренировка ещё идёт — изменить её можно после завершения."
REASON_LEGACY_COPY = "Запись перенесена из старой истории — её изменяет старая карточка."
REASON_ELECTIVE_NO_CLONE = "Факультатив нельзя повторить копией — запись вне плана записывается один раз."

_METADATA = frozenset({EditField.DATE, EditField.DURATION, EditField.EFFORT, EditField.COMMENT})
_FULL = _METADATA | {EditField.SET_ACTUALS, EditField.SET_NOTES}
_EXTERNAL = _METADATA | {EditField.ACTIVITY_TYPE, EditField.DISTANCE}


@dataclass(frozen=True)
class SessionFacts:
    """Что предикат знает о сессии. Связи с курсом/планом (plan_item_id, program_inclusion_id), роли
    STEP и «учтённости прогрессией» здесь нет намеренно: прогрессию двигает только подход на
    максимум и только вперёд (решение владельца, TRAINING_SESSION_V2 §4), поэтому происхождение
    сессии из плана/курса правку её фактов не ограничивает."""

    completed: bool
    kind: SessionKind
    source: SessionSourceV2
    origin: SessionOrigin


@dataclass(frozen=True)
class EditVerdict:
    fields: frozenset[EditField]
    can_clone: bool
    reason: str | None = None

    @property
    def can_edit(self) -> bool:
        return bool(self.fields)

    @property
    def can_edit_sets(self) -> bool:
        return EditField.SET_ACTUALS in self.fields


def edit_verdict(facts: SessionFacts) -> EditVerdict:
    """ED1: единственный предикат редактирования/копирования. Удаление — отдельный, более строгий
    предикат безопасного удаления (PROJECT_SPEC §3, конституция), он здесь не повторяется.

    Решение владельца (#307, финальное ревью B1): прогрессию двигает ТОЛЬКО явный подход на максимум,
    и только на прямой границе прогрессии (#305) — следующий рецепт. Значения обычных рабочих
    подходов прогрессию не питают; уже сгенерированная история и рецепты задним числом не
    пересчитываются. Поэтому завершённая силовая сессия — из плана, курса, роли STEP или
    source=planned_live — правится целиком (метаданные и значения подходов, в т.ч. подхода на
    максимум: исправляется исторический факт) и копируется по общему правилу копии."""
    if not facts.completed:
        return EditVerdict(frozenset(), can_clone=False, reason=REASON_ACTIVE)
    if facts.origin is SessionOrigin.LEGACY_BACKFILL:
        return EditVerdict(frozenset(), can_clone=False, reason=REASON_LEGACY_COPY)
    if facts.kind is SessionKind.EXTERNAL_ACTIVITY:
        return EditVerdict(_EXTERNAL, can_clone=True)
    if facts.origin is SessionOrigin.LEGACY_ELECTIVE:
        return EditVerdict(_FULL, can_clone=False, reason=REASON_ELECTIVE_NO_CLONE)
    return EditVerdict(_FULL, can_clone=True)


# ============================================================================
# Факт vs рецепт (§3, R1/R2)
# ============================================================================


@dataclass(frozen=True)
class TargetRecord:
    set_number: int
    value: Decimal
    is_max_set: bool


@dataclass(frozen=True)
class LogRecord:
    set_number: int
    value: Decimal
    is_max_set: bool
    is_extra: bool
    status: SetStatus = SetStatus.PERFORMED


@dataclass(frozen=True)
class SetOutcome:
    """Один подход в истории: prescribed_set_number/target — None у подхода сверх рецепта;
    actual — None у не выполненного. is_extra — «+ Ещё подход» или плановый подход сверх числа
    целей (сделано больше, чем предписано)."""

    prescribed_set_number: int | None
    target: Decimal | None
    actual: Decimal | None
    is_max_set: bool
    is_extra: bool
    status: SetStatus


def set_outcomes(targets: Sequence[TargetRecord], logs: Sequence[LogRecord]) -> list[SetOutcome]:
    """R1: каждая цель — ровно один исход; невыполненная — not_performed (не 0 и не цель как факт).
    Сопоставление — по порядку среди не-extra подходов (тот же порядок, в котором живая сессия и
    #305 назначают плановым подходам номер цели). R2: is_max_set — свойство цели, факт его
    наследует; так история до #305 (где SetLog писался с False) тоже читается верно."""
    ordered_targets = sorted(targets, key=lambda t: t.set_number)
    planned = [log for log in sorted(logs, key=lambda log: log.set_number) if not log.is_extra]
    extra = [log for log in sorted(logs, key=lambda log: log.set_number) if log.is_extra]
    outcomes: list[SetOutcome] = []
    for index, target in enumerate(ordered_targets):
        log = planned[index] if index < len(planned) else None
        performed = log is not None and log.status is SetStatus.PERFORMED
        outcomes.append(SetOutcome(
            prescribed_set_number=target.set_number, target=target.value,
            actual=log.value if performed else None,
            is_max_set=target.is_max_set or (log is not None and log.is_max_set),
            is_extra=False, status=SetStatus.PERFORMED if performed else SetStatus.NOT_PERFORMED,
        ))
    for log in [*planned[len(ordered_targets):], *extra]:
        performed = log.status is SetStatus.PERFORMED
        outcomes.append(SetOutcome(
            prescribed_set_number=None, target=None, actual=log.value if performed else None,
            is_max_set=log.is_max_set, is_extra=True,
            status=SetStatus.PERFORMED if performed else SetStatus.NOT_PERFORMED,
        ))
    return outcomes


# ============================================================================
# Синтезированный снимок (S4, §2 manual_custom)
# ============================================================================


@dataclass(frozen=True)
class SynthSet:
    metric: str  # "reps" | "time"
    value: Decimal
    is_max_set: bool = False


@dataclass(frozen=True)
class SynthBlock:
    exercise_id: int
    exercise_display_name: str
    analytics_exercise_id: int
    category_id: int | None
    sets: tuple[SynthSet, ...]
    is_interval: bool = False


def _synth_set(item: SynthSet) -> SetPrescription:
    amount = int(item.value)
    if item.metric == "time":
        if item.is_max_set or amount <= 0:
            return SetPrescription(kind=SetKind.MAX_TIME, role=SetRole.MAX if item.is_max_set else SetRole.WORKING)
        return SetPrescription(kind=SetKind.TIME, target_seconds=amount)
    if item.is_max_set or amount <= 0:
        return SetPrescription(kind=SetKind.MAX_REPS, role=SetRole.MAX if item.is_max_set else SetRole.WORKING)
    return SetPrescription(kind=SetKind.REPS, target_reps=amount)


def synthesize_snapshot(
    *, title: str, blocks: Sequence[SynthBlock], resolved_at: datetime, unprescribed: bool,
    workout_definition_id: int | None = None, workout_definition_version_id: int | None = None,
    version_no: int | None = None, program_inclusion_id: int | None = None,
) -> dict[str, Any]:
    """S4: самодостаточный снимок, восстановленный из того, что сессия хранит (цели подходов) или,
    без рецепта, из выполненного (unprescribed: prescribed = performed). synthesized = true —
    читатель знает, что это не снимок версии. Отдых/подготовка неизвестны и не выдумываются
    (rest_after_seconds = None, prep 0). program_inclusion_id — происхождение курса (provenance)."""
    snapshot_blocks = tuple(
        SnapshotBlock(
            key=f"b{index}", exercise_id=block.exercise_id, exercise_display_name=block.exercise_display_name,
            analytics_exercise_id=block.analytics_exercise_id, category_id=block.category_id,
            kind=BlockKind.INTERVAL if block.is_interval else BlockKind.SETS, prep_seconds=0,
            rest_after_block_seconds=None, extra_sets_allowed=True, load=None,
            sets=() if block.is_interval else tuple(_synth_set(s) for s in block.sets), interval=None,
        )
        for index, block in enumerate(blocks)
    )
    progression = program_inclusion_id is not None
    snapshot = PrescriptionSnapshot(
        workout_definition_id=workout_definition_id, workout_definition_version_id=workout_definition_version_id,
        version_no=version_no, title=title, blocks=snapshot_blocks,
        provenance=SnapshotProvenance(
            kind=BlockSource.PROGRESSION if progression else BlockSource.STATIC, resolved_at=resolved_at,
            program_inclusion_id=program_inclusion_id,
        ),
        synthesized=True,
    )
    data = snapshot_to_dict(snapshot)
    if unprescribed:
        data["prescription_kind"] = PRESCRIPTION_UNPRESCRIBED
    return data


def snapshot_matches_blocks(snapshot: Mapping[str, Any], blocks: Sequence[tuple[int | None, int]]) -> bool:
    """Снимок версии согласован с записанными блоками сессии: те же упражнения в том же порядке и,
    у блоков подходов, то же число подходов, что у SetTarget (R1). blocks — (exercise_id,
    число целей). Несогласованный снимок не пишется — вместо него синтезируется снимок из целей
    (снимок не должен противоречить SetTarget)."""
    snap_blocks = list(snapshot.get("blocks") or [])
    if len(snap_blocks) != len(blocks):
        return False
    for snap, (exercise_id, target_count) in zip(snap_blocks, blocks, strict=True):
        if snap.get("exercise_id") != exercise_id:
            return False
        if snap.get("kind") == BlockKind.SETS.value and len(snap.get("sets") or []) != target_count:
            return False
    return True
