from datetime import UTC, datetime
from io import BytesIO

from openpyxl import load_workbook

from app.db.models import Baseline
from app.domain.constants import EquipmentType
from app.services.export import build_export_workbook
from tests.test_reports import _record


def test_build_export_workbook_creates_all_four_sheets():
    records = [_record(1), _record(4, a_equipment_type=EquipmentType.BODYWEIGHT, a_equipment_value=None)]
    baselines = [Baseline(performed_at=datetime(2025, 12, 1, tzinfo=UTC), reps=8)]

    buffer = build_export_workbook(records, baselines)
    workbook = load_workbook(BytesIO(buffer.read()))

    assert workbook.sheetnames == ["История", "Замеры", "Прогресс", "Продолжить офлайн"]


def test_history_sheet_has_header_and_one_row_per_workout():
    records = [_record(1), _record(4)]
    buffer = build_export_workbook(records, baselines=[])
    workbook = load_workbook(BytesIO(buffer.read()))

    ws = workbook["История"]
    assert ws.max_row == 1 + len(records)
    assert ws.cell(row=1, column=1).value == "Дата"
    assert ws.cell(row=2, column=1).value == "01.01.2026"
    assert "20.0" in str(ws.cell(row=2, column=2).value)  # снаряд блока на объём


def test_baselines_sheet_lists_each_baseline():
    baselines = [
        Baseline(performed_at=datetime(2025, 12, 1, tzinfo=UTC), reps=8),
        Baseline(performed_at=datetime(2026, 2, 1, tzinfo=UTC), reps=12),
    ]
    buffer = build_export_workbook(records=[], baselines=baselines)
    workbook = load_workbook(BytesIO(buffer.read()))

    ws = workbook["Замеры"]
    assert ws.max_row == 1 + len(baselines)
    assert ws.cell(row=2, column=2).value == 8
    assert ws.cell(row=3, column=2).value == 12


def test_progress_sheet_groups_by_iso_week():
    same_week = [_record(1), _record(3)]  # 1 и 3 января 2026 — один календарный год/неделя
    buffer = build_export_workbook(records=same_week, baselines=[])
    workbook = load_workbook(BytesIO(buffer.read()))

    ws = workbook["Прогресс"]
    assert ws.max_row == 2  # заголовок + одна неделя
    assert ws.cell(row=2, column=2).value == 2  # 2 тренировки в этой неделе


def test_offline_template_sheet_has_only_header():
    buffer = build_export_workbook(records=[_record(1)], baselines=[])
    workbook = load_workbook(BytesIO(buffer.read()))

    ws = workbook["Продолжить офлайн"]
    assert ws.max_row == 1
    assert ws.cell(row=1, column=1).value == "Дата"
