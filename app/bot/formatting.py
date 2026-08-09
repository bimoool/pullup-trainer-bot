"""Форматирование доменных отчётов (app/domain/reports.py) в текст для
пользователя — вынесено отдельно от хендлеров, чтобы не дублировать между
обработчиком по запросу и еженедельным воркером (app/workers/weekly_report.py)."""

from app.bot import texts
from app.domain.reports import EquipmentProgress, SetCloseSummary, WeeklySummary

_BLOCK_LABELS = {"a": "объём", "b": "сила"}


def _signed_pct(pct: float) -> tuple[str, float]:
    return ("+" if pct >= 0 else ""), pct


def format_volume_change(pct: float | None) -> str:
    if pct is None:
        return texts.VOLUME_CHANGE_NO_BASELINE
    sign, value = _signed_pct(pct)
    return texts.VOLUME_CHANGE_WITH_PCT.format(sign=sign, pct=value)


def format_equipment_progress_line(progress: EquipmentProgress | None) -> str:
    if progress is None:
        return texts.EQUIPMENT_PROGRESS_NONE
    if progress.change_pct is None:
        return texts.EQUIPMENT_PROGRESS_NO_PCT.format(first=progress.first_volume, current=progress.current_volume)
    sign, value = _signed_pct(progress.change_pct)
    return texts.EQUIPMENT_PROGRESS_WITH_PCT.format(
        first=progress.first_volume, current=progress.current_volume, sign=sign, pct=value,
    )


def format_weekly_summary(summary: WeeklySummary) -> str:
    body = texts.WEEKLY_REPORT_BODY.format(
        workout_count=summary.workout_count,
        total_volume=summary.total_volume,
        volume_change=format_volume_change(summary.volume_change_pct),
    )
    changed_blocks = [
        _BLOCK_LABELS[key]
        for key, changed in (("a", summary.equipment_changed_a), ("b", summary.equipment_changed_b))
        if changed
    ]
    if changed_blocks:
        body += texts.WEEKLY_REPORT_EQUIPMENT_CHANGED.format(blocks=", ".join(changed_blocks))
    return body


def format_progress_report(
    summary: WeeklySummary, progress_a: EquipmentProgress | None, progress_b: EquipmentProgress | None,
) -> str:
    body = f"{texts.WEEKLY_REPORT_HEADER}\n\n{format_weekly_summary(summary)}"
    body += texts.PROGRESS_REPORT_EQUIPMENT_HEADER
    body += texts.PROGRESS_REPORT_EQUIPMENT_LINE_A.format(line=format_equipment_progress_line(progress_a))
    body += texts.PROGRESS_REPORT_EQUIPMENT_LINE_B.format(line=format_equipment_progress_line(progress_b))
    return body


def format_set_close_report(summary: SetCloseSummary, set_length: int) -> str:
    body = texts.SET_CLOSE_REPORT_HEADER.format(set_length=set_length)
    body += "\n\n" + texts.SET_CLOSE_REPORT_BODY.format(
        total_volume=summary.total_volume,
        volume_change=format_volume_change(summary.volume_change_pct),
        growth_a=summary.max_reps_growth_a,
        growth_b=summary.max_reps_growth_b,
        equipment_changes=summary.equipment_changes_count,
    )
    return body
