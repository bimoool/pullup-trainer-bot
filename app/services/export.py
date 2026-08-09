import io
from collections import defaultdict
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from app.db.models import Baseline
from app.domain.constants import EquipmentType
from app.domain.session import BlockAssignment, WorkoutRecord

_EQUIPMENT_LABELS = {
    EquipmentType.BAND: "резина",
    EquipmentType.BODYWEIGHT: "свой вес",
    EquipmentType.WEIGHT: "отягощение",
    EquipmentType.AUSTRALIAN: "австралийские",
}

_HISTORY_HEADER = [
    "Дата", "Объём: снаряд", "Объём: макс", "Объём: цель",
    "Сила: снаряд", "Сила: макс", "Сила: цель", "Комментарий",
]
_BASELINES_HEADER = ["Дата", "Повторения"]
_PROGRESS_HEADER = ["Неделя", "Тренировок", "Суммарный объём"]
_OFFLINE_HEADER = [
    "Дата", "Объём: раб. подходы", "Объём: макс", "Сила: раб. подходы", "Сила: макс", "Комментарий",
]


def _equipment_label(block: BlockAssignment) -> str:
    label = _EQUIPMENT_LABELS[block.equipment_type]
    if block.equipment_value is not None:
        value: Decimal = block.equipment_value
        return f"{label} {value}кг"
    return label


def _write_history_sheet(ws: Worksheet, records: list[WorkoutRecord]) -> None:
    ws.append(_HISTORY_HEADER)
    for record in records:
        ws.append([
            record.performed_at.strftime("%d.%m.%Y"),
            _equipment_label(record.block_a), record.block_a.log.max_reps, record.block_a.target_after,
            _equipment_label(record.block_b), record.block_b.log.max_reps, record.block_b.target_after,
            record.comment or "",
        ])


def _write_baselines_sheet(ws: Worksheet, baselines: list[Baseline]) -> None:
    ws.append(_BASELINES_HEADER)
    for baseline in baselines:
        ws.append([baseline.performed_at.strftime("%d.%m.%Y"), baseline.reps])


def _write_progress_sheet(ws: Worksheet, records: list[WorkoutRecord]) -> None:
    """Объём по неделям (ISO-неделя даты тренировки) — та же метрика, что
    в еженедельном отчёте (app/domain/reports.weekly_summary), но за всю
    историю целиком, а не только за последнюю неделю."""
    ws.append(_PROGRESS_HEADER)
    weekly: dict[tuple[int, int], list[WorkoutRecord]] = defaultdict(list)
    for record in records:
        iso = record.performed_at.isocalendar()
        weekly[(iso[0], iso[1])].append(record)

    for (year, week), week_records in sorted(weekly.items()):
        total_volume = sum(r.block_a.log.volume + r.block_b.log.volume for r in week_records)
        ws.append([f"{year}-W{week:02d}", len(week_records), total_volume])


def _write_offline_template_sheet(ws: Worksheet) -> None:
    """Пустой шаблон без формул — для тех, кто боится потерять записи после
    окончания подписки (см. Часть 5 респека). Только заголовок, без данных."""
    ws.append(_OFFLINE_HEADER)


def build_export_workbook(records: list[WorkoutRecord], baselines: list[Baseline]) -> io.BytesIO:
    workbook = Workbook()
    history_sheet = workbook.active
    history_sheet.title = "История"
    _write_history_sheet(history_sheet, records)

    _write_baselines_sheet(workbook.create_sheet("Замеры"), baselines)
    _write_progress_sheet(workbook.create_sheet("Прогресс"), records)
    _write_offline_template_sheet(workbook.create_sheet("Продолжить офлайн"))

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer
