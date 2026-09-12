from dataclasses import dataclass
from decimal import Decimal

from app.domain.constants import EquipmentType
from app.domain.session import BlockAssignment, WorkoutRecord


def _record_volume(record: WorkoutRecord) -> int:
    return record.block_a.log.volume + record.block_b.log.volume


def _pct_change(previous: float, current: float) -> float | None:
    """None, если раньше объём был 0 — процент от нуля не определён."""
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


def _block(record: WorkoutRecord, block: str):
    return record.block_a if block == "a" else record.block_b


def _same_equipment(a: BlockAssignment, b: BlockAssignment) -> bool:
    """«Тот же снаряд» больше не сравнивается по equipment_value напрямую —
    у резины теперь личный список (см. Часть 8 респека): kg опционален и
    может отличаться у одного и того же физического снаряда, если позже
    его отредактировать. Для BAND identity — equipment_item_id; для WEIGHT
    (там число обязательно и стабильно) — по-прежнему equipment_value;
    для BODYWEIGHT/AUSTRALIAN значения нет, достаточно совпадения типа."""
    if a.equipment_type != b.equipment_type:
        return False
    if a.equipment_type == EquipmentType.BAND:
        return a.equipment_item_id == b.equipment_item_id
    if a.equipment_type == EquipmentType.WEIGHT:
        return a.equipment_value == b.equipment_value
    return True


@dataclass(frozen=True)
class WeeklySummary:
    """Сводка «раз в неделю» — см. Часть 5 респека. previous_week_volume
    передаёт вызывающий код (нужна отдельная выборка за прошлую неделю)."""

    workout_count: int
    total_volume: int
    volume_change_pct: float | None
    equipment_changed_a: bool
    equipment_changed_b: bool


def weekly_summary(records_this_week: list[WorkoutRecord], previous_week_volume: int) -> WeeklySummary:
    total_volume = sum(_record_volume(r) for r in records_this_week)
    return WeeklySummary(
        workout_count=len(records_this_week),
        total_volume=total_volume,
        volume_change_pct=_pct_change(previous_week_volume, total_volume),
        equipment_changed_a=any(r.block_a.equipment_changed for r in records_this_week),
        equipment_changed_b=any(r.block_b.equipment_changed for r in records_this_week),
    )


@dataclass(frozen=True)
class EquipmentProgress:
    """Динамика объёма на ТЕКУЩЕМ (последнем использованном) снаряде —
    ключевая метрика спеки: "с этой резиной делал 40, сейчас 80, +100%".
    Сравнивает первую и последнюю тренировку НЕПРЕРЫВНОГО хвоста истории
    на одном и том же снаряде (см. _same_equipment)."""

    equipment_type: EquipmentType
    equipment_value: Decimal | None
    equipment_item_id: int | None
    first_volume: int
    current_volume: int
    change_pct: float | None


def current_equipment_progress(records: list[WorkoutRecord], block: str) -> EquipmentProgress | None:
    """block: "a" (объём) или "b" (сила). None, если истории нет вовсе."""
    if not records:
        return None

    last_equipment = _block(records[-1], block)
    segment: list[WorkoutRecord] = []
    for record in reversed(records):
        current = _block(record, block)
        if not _same_equipment(current, last_equipment):
            break
        segment.append(record)
    segment.reverse()

    first_volume = _block(segment[0], block).log.volume
    current_volume = _block(segment[-1], block).log.volume
    return EquipmentProgress(
        equipment_type=last_equipment.equipment_type,
        equipment_value=last_equipment.equipment_value,
        equipment_item_id=last_equipment.equipment_item_id,
        first_volume=first_volume,
        current_volume=current_volume,
        change_pct=_pct_change(first_volume, current_volume),
    )


@dataclass(frozen=True)
class SetCloseSummary:
    """Большой отчёт по закрытии сета (12 тренировок) — см. Часть 5 респека.
    previous_set_total_volume=None, если это первый сет (сравнивать не с чем)."""

    workout_count: int
    total_volume: int
    max_reps_growth_a: int
    max_reps_growth_b: int
    equipment_changes_count: int
    volume_change_pct: float | None


def set_close_summary(records_in_set: list[WorkoutRecord], previous_set_total_volume: int | None) -> SetCloseSummary:
    total_volume = sum(_record_volume(r) for r in records_in_set)
    volume_change_pct = (
        _pct_change(previous_set_total_volume, total_volume) if previous_set_total_volume is not None else None
    )
    if not records_in_set:
        return SetCloseSummary(0, total_volume, 0, 0, 0, volume_change_pct)

    max_growth_a = records_in_set[-1].block_a.log.max_reps - records_in_set[0].block_a.log.max_reps
    max_growth_b = records_in_set[-1].block_b.log.max_reps - records_in_set[0].block_b.log.max_reps
    equipment_changes = sum(
        1 for r in records_in_set if r.block_a.equipment_changed or r.block_b.equipment_changed
    )
    return SetCloseSummary(
        workout_count=len(records_in_set),
        total_volume=total_volume,
        max_reps_growth_a=max_growth_a,
        max_reps_growth_b=max_growth_b,
        equipment_changes_count=equipment_changes,
        volume_change_pct=volume_change_pct,
    )


@dataclass(frozen=True)
class CycleVolume:
    workout_set_id: int
    workout_count: int
    total_volume: int
    volume_change_pct: float | None  # относительно предыдущего цикла в списке


@dataclass(frozen=True)
class AllCyclesAnalytics:
    """Сводная аналитика по ВСЕЙ истории пользователя, а не одному циклу —
    "📈 Аналитика по всем циклам" в «Прогресс» (см. Часть 8 респека, в
    отличие от недельной сводки/отчёта по закрытии, которые скоупятся по
    одному WorkoutSet)."""

    total_volume: int
    cycle_count: int
    cycles: list[CycleVolume]  # в хронологическом порядке


def all_cycles_analytics(records: list[WorkoutRecord]) -> AllCyclesAnalytics:
    """Группирует по record.workout_set_id, сохраняя порядок первого
    появления (== хронологический порядок циклов, они всегда открываются
    последовательно). Записи без workout_set_id (не должно случаться для
    завершённых тренировок) в группировку не попадают."""
    order: list[int] = []
    grouped: dict[int, list[WorkoutRecord]] = {}
    for record in records:
        if record.workout_set_id is None:
            continue
        if record.workout_set_id not in grouped:
            order.append(record.workout_set_id)
            grouped[record.workout_set_id] = []
        grouped[record.workout_set_id].append(record)

    cycles: list[CycleVolume] = []
    previous_volume: int | None = None
    total_volume = 0
    for workout_set_id in order:
        group = grouped[workout_set_id]
        volume = sum(_record_volume(r) for r in group)
        total_volume += volume
        cycles.append(
            CycleVolume(
                workout_set_id=workout_set_id,
                workout_count=len(group),
                total_volume=volume,
                volume_change_pct=_pct_change(previous_volume, volume) if previous_volume is not None else None,
            ),
        )
        previous_volume = volume

    return AllCyclesAnalytics(total_volume=total_volume, cycle_count=len(cycles), cycles=cycles)


# --- Формула Эпли: оценочная сила блока Б (issue #96) ------------------------------

_EPLEY_ELIGIBLE_TYPES = (EquipmentType.WEIGHT, EquipmentType.BODYWEIGHT)
# Резина (BAND) сознательно исключена целиком, а не сведена к общей шкале
# нагрузки через to_signed_load — реальное сопротивление резины физически
# неизвестно (стёртая маркировка, растяжение со временем), в отличие от
# кг отягощения или собственного веса. Явное решение автора продукта (issue
# #96, комментарий): "не пытайся приводить резину к общей шкале с весом —
# это должно быть отдельное измерение". AUSTRALIAN исключена по тому же
# принципу, что и в метрике "strength" графика прогресса (issue #82) — там
# нет кг вообще, только угол корпуса.


def _epley_eligible(block: BlockAssignment) -> bool:
    """best_set > 0 отсекает бэкдейт-итог блока Б без введённого максимума
    (issue #88: reported_volume задан, working_reps=(), max_reps=0) — там
    "0 повторений" исказило бы Эпли до голого веса снаряда."""
    return block.equipment_type in _EPLEY_ELIGIBLE_TYPES and block.log.best_set > 0


def _epley_load(weight_kg: Decimal, block: BlockAssignment) -> float:
    """(вес тела + отягощение) × (1 + повторения / 30) — расчётный
    эквивалент нагрузки на 1 повторение, не буквальный вес."""
    equipment_value = block.equipment_value if block.equipment_type == EquipmentType.WEIGHT else Decimal(0)
    reps = block.log.best_set
    return float((weight_kg + (equipment_value or Decimal(0))) * (Decimal(1) + Decimal(reps) / Decimal(30)))


@dataclass(frozen=True)
class EpleyProgress:
    """Оценочная сила блока Б (issue #96). current_load_kg — по последней
    подходящей тренировке ЛЮБОГО происхождения (в т.ч. бэкдейт/свободная —
    это факт "сейчас", а не сравнение). change_pct_vs_previous/vs_first
    сравнивают текущее значение ТОЛЬКО с официальными тренировками основной
    программы (participates_in_cascade=True) — согласовано в issue: бэкдейт/
    свободные видны на графике факта, но не становятся анкорами для %."""

    current_load_kg: float
    change_pct_vs_previous: float | None
    change_pct_vs_first: float | None


def epley_progress(records: list[WorkoutRecord], weight_kg: Decimal | None) -> EpleyProgress | None:
    """None, если вес тела не заполнен в профиле (формула невозможна) или ни
    одна тренировка блока Б не подходит под формулу (только WEIGHT/
    BODYWEIGHT с зафиксированным максимумом, см. _epley_eligible)."""
    if weight_kg is None:
        return None

    eligible = [r for r in records if _epley_eligible(r.block_b)]
    if not eligible:
        return None

    # current_load — неокруглённая величина используется для % (иначе
    # сравнение "самого-себя-с-собой", когда анкор совпадает с текущей
    # тренировкой, давало бы не ровно 0.0%, а погрешность округления вроде
    # -0.0%); округляется только то, что идёт в current_load_kg на показ.
    current_load = _epley_load(weight_kg, eligible[-1].block_b)
    official = [r for r in eligible if r.participates_in_cascade]
    if not official:
        return EpleyProgress(
            current_load_kg=round(current_load, 1), change_pct_vs_previous=None, change_pct_vs_first=None,
        )

    first_anchor = official[0]
    # Если самая свежая подходящая тренировка сама официальная — она же
    # official[-1] (eligible/official сохраняют хронологический порядок), и
    # "прошлая" не должна сравнивать её саму с собой, если есть кто-то раньше.
    # Единственное исключение — когда официальная тренировка блока Б всего
    # одна: тогда "прошлая"/"первая" намеренно совпадают (сравнение текущего
    # значения с самим собой, 0%), а не None — так и есть на практике на
    # первой тренировке блока Б.
    if eligible[-1].participates_in_cascade and len(official) >= 2:
        previous_anchor = official[-2]
    else:
        previous_anchor = official[-1]

    previous_load = _epley_load(weight_kg, previous_anchor.block_b)
    first_load = _epley_load(weight_kg, first_anchor.block_b)
    return EpleyProgress(
        current_load_kg=round(current_load, 1),
        change_pct_vs_previous=_pct_change(previous_load, current_load),
        change_pct_vs_first=_pct_change(first_load, current_load),
    )
