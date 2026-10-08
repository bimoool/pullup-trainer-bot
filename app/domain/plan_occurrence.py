"""Program + Plan v2 (issue #304, docs/domain/PROGRAM_PLAN_V2.md §1, §4–§7) — чистая логика.

Одна строка PlanItem = ОДНО занятие одной тренировки (AD-4). Здесь только арифметика без БД и
без «сейчас»: слоты программы, желаемый объём недели, минимальный отдых между стартами MAIN
(OD-2: два ПОЛНЫХ дня отдыха → min_days_between_starts = 3, Пн → Чт), раскладка по неделе (K2),
производные состояния занятий (available / too_early / infeasible / missed / completed) и
объём своего плана по неделям (W1=2, W2=2, W3=0 …). Сегодняшняя дата, часовой пояс и история —
у вызывающего сервиса (конституция: `datetime.now()` только снаружи домена)."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

# --- Константы контракта -------------------------------------------------------------------

MAIN_SLOT_KEY = "main"
MAIN_SPACING_GROUP = "main"

# OD-2 (решение владельца 2026-10-08): «2 дня отдыха между MAIN» = ДВА ПОЛНЫХ дня отдыха.
# Пн — тренировка, Вт и Ср — отдых, ближайший следующий MAIN — Чт: разница локальных дат стартов
# ≥ 3. Это НЕ старый MIN_REST_DAYS=2 (Пн → Ср). Значение по умолчанию — когда у программы нет
# явного ограничения в programs.constraints (источник чтения — конфиг, см. app.services.plan_spacing).
DEFAULT_MAIN_MIN_DAYS_BETWEEN_STARTS = 3

# Объём недели своего плана: 0 — валидное явное значение (W3 = 0), верх — защита от опечаток.
CUSTOM_WEEK_MAX_COUNT = 14
CUSTOM_PLAN_MAX_WEEKS = 52


class SlotRole(StrEnum):
    MAIN = "main"
    OPTIONAL = "optional"
    ASSESSMENT = "assessment"


class OccurrenceSource(StrEnum):
    PROGRAM = "program"
    CUSTOM_PLAN = "custom_plan"
    MANUAL = "manual"


class PlanItemStatus(StrEnum):
    """Хранимый статус строки (§5). removed — строка выведена из плана, но не удалена (на неё могут
    ссылаться сессии старой M2M-связи: агрегатные строки текущей/будущих недель после разворота)."""

    OPEN = "open"
    RESCHEDULED = "rescheduled"
    REMOVED = "removed"


class OccurrenceState(StrEnum):
    """Производное состояние занятия (§5, PL4/PL5, K2). Не хранится — считается на чтение."""

    COMPLETED = "completed"
    MISSED = "missed"
    INFEASIBLE = "infeasible"
    AVAILABLE = "available"
    TOO_EARLY = "too_early"


class InclusionStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    REMOVED = "removed"


class CustomPlanRepeat(StrEnum):
    ONCE = "once"
    CYCLE = "cycle"


# --- Слоты программы ------------------------------------------------------------------------


@dataclass(frozen=True)
class SlotMember:
    """Элемент программы, исполняемый в каждом занятии слота (блок/тренировка внутри занятия)."""

    exercise_id: int
    complex_id: int | None = None


@dataclass(frozen=True)
class ProgramSlot:
    """Слот программы (§1): одно занятие слота = все его members в одной тренировке (AD-3 для MAIN
    «Подтягиваний»: роли block_a + block_b). exercise_id / complex_id строки PlanItem — первый member
    (PlanItem.exercise_id NOT NULL); при старте блоки резолвятся по всем members.
    workout_definition_id — WorkoutDefinition слота, если есть (у MAIN появится в #305)."""

    key: str
    role: SlotRole
    sessions_per_week: int
    spacing_group: str | None
    counts_toward_progression: bool
    members: tuple[SlotMember, ...] = ()
    workout_definition_id: int | None = None
    day_of_week: int | None = None

    @property
    def exercise_id(self) -> int | None:
        return self.members[0].exercise_id if self.members else None

    @property
    def complex_id(self) -> int | None:
        return self.members[0].complex_id if self.members else None

    def to_dict(self) -> dict:
        return {
            "key": self.key, "role": self.role.value, "sessions_per_week": self.sessions_per_week,
            "spacing_group": self.spacing_group, "counts_toward_progression": self.counts_toward_progression,
            "workout_definition_id": self.workout_definition_id, "day_of_week": self.day_of_week,
            "members": [{"exercise_id": m.exercise_id, "complex_id": m.complex_id} for m in self.members],
        }

    @classmethod
    def from_dict(cls, raw: Mapping) -> "ProgramSlot":
        members = tuple(
            SlotMember(exercise_id=int(m["exercise_id"]), complex_id=m.get("complex_id"))
            for m in raw.get("members") or [] if isinstance(m, Mapping) and m.get("exercise_id") is not None
        )
        return cls(
            key=str(raw["key"]), role=SlotRole(raw.get("role", SlotRole.OPTIONAL.value)),
            sessions_per_week=int(raw.get("sessions_per_week", 0)), spacing_group=raw.get("spacing_group"),
            counts_toward_progression=bool(raw.get("counts_toward_progression", False)), members=members,
            workout_definition_id=raw.get("workout_definition_id"), day_of_week=raw.get("day_of_week"),
        )


def _role_exercise_ids(snapshot: Mapping) -> dict[str, int]:
    return {
        str(item["role"]): int(item["exercise_id"])
        for item in snapshot.get("exercises") or []
        if isinstance(item, Mapping) and item.get("role") and item.get("exercise_id") is not None
    }


def derive_slots(
    snapshot: Mapping | None, *, program_slots: Sequence[Mapping] | None = None,
    program_frequency: Mapping | None = None,
) -> list[ProgramSlot]:
    """Слоты инклюзии. Источник — СНИМОК (snapshot immutability):
    1. snapshot["slots"] — заморожены при подключении (инклюзии после #304);
    2. иначе — legacy-снимок program_items. Прежняя семантика плана сохраняется: элементы с одним днём
       недели (NULL — свободный пул) исполнялись ОДНОЙ тренировкой (карточка группировалась по
       (курс, день), старт слал все её строки) — это и есть одно занятие слота. Группа из ролей STEP
       (block_a/block_b) — слот main (AD-3: занятие = блоки A + Б, группа отдыха main, прогрессия);
       прочие — optional без группы отдыха (K4). Объём = max(count_per_week) группы.
    program_slots / program_frequency — каталожная разметка (programs.slots / frequency): уточняет
    роль/группу/частоту main-слота legacy-снимка, но не добавляет и не убирает слоты."""
    snapshot = snapshot or {}
    frozen = snapshot.get("slots")
    if isinstance(frozen, list) and frozen:
        return [ProgramSlot.from_dict(raw) for raw in frozen if isinstance(raw, Mapping) and raw.get("key")]

    roles = _role_exercise_ids(snapshot)
    role_ids = {roles.get("block_a"), roles.get("block_b")} - {None}
    items = [
        item for item in snapshot.get("program_items") or []
        if isinstance(item, Mapping) and item.get("exercise_id") is not None
    ]
    catalogue = {str(raw.get("key")): raw for raw in program_slots or [] if isinstance(raw, Mapping)}
    frequency = program_frequency or {}
    per_slot = dict(frequency.get("per_slot") or {})

    groups: dict[int | None, list[Mapping]] = {}
    for item in items:
        groups.setdefault(item.get("day_of_week"), []).append(item)

    slots: list[ProgramSlot] = []
    for day, members in sorted(groups.items(), key=lambda pair: (pair[0] is not None, pair[0] or 0)):
        is_main = bool(role_ids) and any(item.get("exercise_id") in role_ids for item in members) and not any(
            slot.key == MAIN_SLOT_KEY for slot in slots
        )
        if is_main:
            ordered = sorted(members, key=lambda item: (
                0 if item.get("exercise_id") == roles.get("block_a") else
                1 if item.get("exercise_id") == roles.get("block_b") else 2,
                item.get("id") or 0,
            ))
            key = MAIN_SLOT_KEY
        else:
            ordered = sorted(members, key=lambda item: item.get("id") or 0)
            key = "pool" if day is None else f"day{day}"
        meta = catalogue.get(key, {})
        count = per_slot.get(key)
        if count is None and is_main:
            count = frequency.get("sessions_per_week")
        if count is None:
            count = max(int(item.get("count_per_week") or 0) for item in members)
        slots.append(ProgramSlot(
            key=key, role=SlotRole(meta.get("role", (SlotRole.MAIN if is_main else SlotRole.OPTIONAL).value)),
            sessions_per_week=int(count),
            spacing_group=meta.get("spacing_group", MAIN_SPACING_GROUP if is_main else None),
            counts_toward_progression=bool(meta.get("counts_toward_progression", is_main)),
            members=tuple(
                SlotMember(exercise_id=int(item["exercise_id"]), complex_id=item.get("complex_id")) for item in ordered
            ),
            workout_definition_id=meta.get(
                "workout_definition_id", ordered[0].get("complex_id") if len(ordered) == 1 else None,
            ),
            day_of_week=day,
        ))
    return slots


def spacing_days_by_group(constraints: Iterable[Mapping] | None, *, default_main: int) -> dict[str, int]:
    """programs.constraints → {spacing_group: min_days_between_starts}. Группа main всегда
    присутствует (значение по умолчанию — конфиг), невалидные записи игнорируются."""
    result = {MAIN_SPACING_GROUP: int(default_main)}
    for raw in constraints or []:
        if not isinstance(raw, Mapping):
            continue
        group, days = raw.get("spacing_group"), raw.get("min_days_between_starts")
        if isinstance(group, str) and isinstance(days, int) and days >= 0:
            result[group] = days
    return result


# --- Отдых между стартами (K1) --------------------------------------------------------------


def available_from(last_start_local_date: date | None, min_days_between_starts: int) -> date | None:
    """§4: local_date(последний старт группы) + min_days_between_starts. None — истории нет."""
    if last_start_local_date is None:
        return None
    return last_start_local_date + timedelta(days=min_days_between_starts)


def is_too_early(today: date, available: date | None) -> bool:
    return available is not None and today < available


# --- Состояния и раскладка (K2, PL4, PL5) ---------------------------------------------------


@dataclass(frozen=True)
class OccurrenceInput:
    item_id: int
    week_start: date
    occurrence_index: int | None
    spacing_group: str | None
    completed: bool
    scheduled_date: date | None = None
    legacy_aggregate: bool = False
    planned_count: int = 1
    done_count: int = 0


@dataclass(frozen=True)
class OccurrenceStateResult:
    state: OccurrenceState
    available_from: date | None = None
    projected_date: date | None = None


def _week_end(week_start: date) -> date:
    return week_start + timedelta(days=6)


def derive_occurrence_states(
    occurrences: Sequence[OccurrenceInput], *, today: date,
    available_from_by_group: Mapping[str, date | None], min_days_by_group: Mapping[str, int],
) -> dict[int, OccurrenceStateResult]:
    """Состояние каждого занятия.

    * completed — занятие засчитано (явный кредит сессии, PL2/PL4), в любой неделе.
    * missed — неделя закончилась, занятие открыто (PL5). Перенос долга не порождается.
    * Открытые занятия текущей и будущих недель группы отдыха раскладываются цепочкой по порядку
      (неделя, scheduled_date, occurrence_index): первое — не раньше max(today, available_from),
      каждое следующее — не раньше предыдущего + min_days. Не поместившееся до конца своей недели —
      infeasible («не успеть на этой неделе», K2): не долг и не пропуск, цепочку не сдвигает.
    * Поместившееся: too_early, пока сегодня < available_from группы (K1 решает старт), иначе
      available. Будущие недели видимы и стартуемы (§6) — ограничивает только K1.
    * Без группы отдыха — available (и projected_date = scheduled_date, если задана)."""
    results: dict[int, OccurrenceStateResult] = {}
    chains: dict[str, list[OccurrenceInput]] = {}
    for occ in occurrences:
        if occ.legacy_aggregate:
            done = occ.done_count >= occ.planned_count > 0
            if done:
                results[occ.item_id] = OccurrenceStateResult(OccurrenceState.COMPLETED)
            elif _week_end(occ.week_start) < today:
                results[occ.item_id] = OccurrenceStateResult(OccurrenceState.MISSED)
            else:
                results[occ.item_id] = OccurrenceStateResult(OccurrenceState.AVAILABLE)
            continue
        if occ.completed:
            results[occ.item_id] = OccurrenceStateResult(OccurrenceState.COMPLETED)
            continue
        if _week_end(occ.week_start) < today:
            results[occ.item_id] = OccurrenceStateResult(OccurrenceState.MISSED)
            continue
        if occ.spacing_group is None:
            results[occ.item_id] = OccurrenceStateResult(OccurrenceState.AVAILABLE, projected_date=occ.scheduled_date)
            continue
        chains.setdefault(occ.spacing_group, []).append(occ)

    for group, members in chains.items():
        available = available_from_by_group.get(group)
        min_days = min_days_by_group.get(group, 0)
        cursor = max(today, available) if available is not None else today
        ordered = sorted(
            members,
            key=lambda o: (o.week_start, o.scheduled_date or date.max, o.occurrence_index or 0, o.item_id),
        )
        for occ in ordered:
            earliest = max(cursor, occ.week_start)
            projected = occ.scheduled_date if occ.scheduled_date is not None and occ.scheduled_date >= earliest else earliest
            if projected > _week_end(occ.week_start):
                results[occ.item_id] = OccurrenceStateResult(OccurrenceState.INFEASIBLE, available_from=available)
                continue
            cursor = projected + timedelta(days=min_days)
            state = OccurrenceState.TOO_EARLY if is_too_early(today, available) else OccurrenceState.AVAILABLE
            results[occ.item_id] = OccurrenceStateResult(state, available_from=available, projected_date=projected)
    return results


def feasible_remaining(week_start: date, *, today: date, available: date | None, min_days: int) -> int:
    """K2 дословно: число дат d в [max(today, available_from), week_end] с шагом min_days."""
    start = max(today, week_start)
    if available is not None:
        start = max(start, available)
    end = _week_end(week_start)
    if start > end:
        return 0
    if min_days <= 0:
        return (end - start).days + 1
    return (end - start).days // min_days + 1


@dataclass(frozen=True)
class WeekSummary:
    planned: int
    completed: int
    infeasible: int
    missed: int


def summarize_week(occurrences: Sequence[OccurrenceInput], states: Mapping[int, OccurrenceStateResult]) -> WeekSummary:
    """«N из M» считает занятия (PL1): legacy-агрегат — своим count_per_week, занятие — единицей."""
    planned = completed = infeasible = missed = 0
    for occ in occurrences:
        state = states[occ.item_id].state
        if occ.legacy_aggregate:
            planned += occ.planned_count
            completed += min(occ.done_count, occ.planned_count)
            continue
        planned += 1
        completed += state == OccurrenceState.COMPLETED
        infeasible += state == OccurrenceState.INFEASIBLE
        missed += state == OccurrenceState.MISSED
    return WeekSummary(planned=planned, completed=completed, infeasible=infeasible, missed=missed)


# --- Свой план: объём по неделям (§7) ------------------------------------------------------


class CustomPlanError(ValueError):
    """Невалидный свой план (роут → 422)."""


def validate_custom_plan(
    *, workout_count: int, weeks: Sequence[int], preferred_weekdays: Sequence[int] | None,
) -> None:
    if workout_count < 1:
        raise CustomPlanError("В плане должна быть хотя бы одна тренировка")
    if not 1 <= len(weeks) <= CUSTOM_PLAN_MAX_WEEKS:
        raise CustomPlanError(f"Недель в плане: от 1 до {CUSTOM_PLAN_MAX_WEEKS}")
    for count in weeks:
        if not isinstance(count, int) or isinstance(count, bool) or not 0 <= count <= CUSTOM_WEEK_MAX_COUNT:
            raise CustomPlanError(f"Тренировок в неделю: от 0 до {CUSTOM_WEEK_MAX_COUNT}")
    if not any(weeks):
        raise CustomPlanError("Хотя бы в одной неделе должна быть тренировка")
    if preferred_weekdays is not None and (
        len(set(preferred_weekdays)) != len(preferred_weekdays)
        or any(not isinstance(day, int) or not 0 <= day <= 6 for day in preferred_weekdays)
    ):
        raise CustomPlanError("Дни недели: 0 (понедельник) … 6 (воскресенье), без повторов")


def custom_week_count(weeks: Sequence[int], repeat: CustomPlanRepeat, week_offset: int) -> int:
    """Объём недели с номером week_offset от старта плана (0 — первая). Вне плана — 0."""
    if week_offset < 0 or not weeks:
        return 0
    if week_offset >= len(weeks):
        if repeat != CustomPlanRepeat.CYCLE:
            return 0
        week_offset %= len(weeks)
    return weeks[week_offset]


@dataclass(frozen=True)
class CustomOccurrenceSpec:
    occurrence_index: int
    workout_definition_id: int
    day_of_week: int | None


def custom_week_occurrences(
    *, workout_ids: Sequence[int], weeks: Sequence[int], repeat: CustomPlanRepeat, week_offset: int,
    preferred_weekdays: Sequence[int] | None,
) -> list[CustomOccurrenceSpec]:
    """Занятия недели: ровно custom_week_count штук, тренировки — по ротации через всю
    последовательность недель (сквозной счётчик), день недели — ПОДСКАЗКА размещения
    (i-е занятие → i-й предпочтительный день, если он есть), объём от неё не зависит."""
    count = custom_week_count(weeks, repeat, week_offset)
    if count == 0 or not workout_ids:
        return []
    before = 0
    for offset in range(week_offset):
        before += custom_week_count(weeks, repeat, offset)
    hints = list(preferred_weekdays or [])
    return [
        CustomOccurrenceSpec(
            occurrence_index=index + 1, workout_definition_id=workout_ids[(before + index) % len(workout_ids)],
            day_of_week=hints[index] if index < len(hints) else None,
        )
        for index in range(count)
    ]


# --- Разворот legacy-агрегата (MIGRATION_V2 §3, §5 п.2) -------------------------------------


def assign_aggregate_credits(
    occurrence_indexes: Sequence[int], sessions: Sequence[tuple[int, object]],
) -> dict[int, int]:
    """Агрегатная строка с k сессиями → k засчитанных занятий, по порядку (performed_at, id).
    sessions — (session_id, sort_key). Сессий больше, чем занятий, — лишние не засчитываются
    (кредит не выдумывается). Возвращает {occurrence_index: session_id}."""
    ordered = sorted(sessions, key=lambda pair: (pair[1], pair[0]))
    return {index: session_id for index, (session_id, _) in zip(sorted(occurrence_indexes), ordered, strict=False)}
