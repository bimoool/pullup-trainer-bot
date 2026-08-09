from decimal import Decimal

from app.bot.formatting import (
    format_equipment_progress_line,
    format_progress_report,
    format_set_close_report,
    format_volume_change,
    format_weekly_summary,
)
from app.domain.constants import EquipmentType
from app.domain.reports import EquipmentProgress, SetCloseSummary, WeeklySummary


def test_format_volume_change_none_omits_percentage():
    assert format_volume_change(None) == ""


def test_format_volume_change_positive_has_plus_sign():
    assert "+50.0%" in format_volume_change(50.0)


def test_format_volume_change_negative_keeps_minus_sign():
    assert "-10.0%" in format_volume_change(-10.0)


def test_format_equipment_progress_line_none_placeholder():
    assert format_equipment_progress_line(None) == "пока нет данных"


def test_format_equipment_progress_line_includes_values():
    progress = EquipmentProgress(
        equipment_type=EquipmentType.BAND, equipment_value=Decimal("20.0"),
        first_volume=40, current_volume=80, change_pct=100.0,
    )
    line = format_equipment_progress_line(progress)
    assert "40" in line
    assert "80" in line
    assert "+100.0%" in line


def test_format_weekly_summary_lists_changed_blocks():
    summary = WeeklySummary(
        workout_count=3, total_volume=200, volume_change_pct=10.0,
        equipment_changed_a=True, equipment_changed_b=False,
    )
    text = format_weekly_summary(summary)
    assert "Снаряд сменился: объём" in text


def test_format_weekly_summary_omits_line_when_nothing_changed():
    summary = WeeklySummary(
        workout_count=3, total_volume=200, volume_change_pct=10.0,
        equipment_changed_a=False, equipment_changed_b=False,
    )
    assert "Снаряд сменился" not in format_weekly_summary(summary)


def test_format_progress_report_includes_both_blocks():
    summary = WeeklySummary(1, 100, None, False, False)
    text = format_progress_report(summary, None, None)
    assert "Объём:" in text
    assert "Сила:" in text


def test_format_set_close_report_includes_set_length_and_growth():
    summary = SetCloseSummary(
        workout_count=12, total_volume=900, max_reps_growth_a=5, max_reps_growth_b=2,
        equipment_changes_count=1, volume_change_pct=20.0,
    )
    text = format_set_close_report(summary, set_length=12)
    assert "12" in text
    assert "+5" in text
    assert "+2" in text
