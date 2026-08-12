"""Форматирование доменных отчётов (app/domain/reports.py) в текст для
пользователя — вынесено отдельно от хендлеров, чтобы не дублировать между
обработчиком по запросу и еженедельным воркером (app/workers/weekly_report.py)."""

from datetime import date
from decimal import Decimal

from app.bot import texts
from app.domain.constants import EquipmentType

_EQUIPMENT_LABELS_NOMINATIVE: dict[EquipmentType, str] = {
    EquipmentType.BODYWEIGHT: "собственный вес",
    EquipmentType.BAND: "резина",
    EquipmentType.WEIGHT: "отягощение",
    EquipmentType.AUSTRALIAN: "австралийские подтягивания",
}
_EQUIPMENT_LABELS_INSTRUMENTAL: dict[EquipmentType, str] = {
    EquipmentType.BODYWEIGHT: "собственным весом",
    EquipmentType.BAND: "резиной",
    EquipmentType.WEIGHT: "отягощением",
    EquipmentType.AUSTRALIAN: "австралийскими подтягиваниями",
}


def format_equipment_label(
    equipment_type: EquipmentType, equipment_value: Decimal | None = None, *, instrumental: bool = False,
) -> str:
    """Единый источник склонений снаряда (Часть 10, пакет #2) — тип снаряда
    это фиксированный список из 4 вариантов, а не свободный текст, значит
    каждый должен быть правильно согласован в шаблоне, а не просто
    подставлен через двоеточие. instrumental=True — творительный падеж
    ("с собственным весом"), иначе именительный ("собственный вес")."""
    labels = _EQUIPMENT_LABELS_INSTRUMENTAL if instrumental else _EQUIPMENT_LABELS_NOMINATIVE
    label = labels[equipment_type]
    if equipment_type == EquipmentType.WEIGHT and equipment_value is not None:
        label += f" +{format_kg(equipment_value)} кг"
    return label


def format_reps_example(target: int, work_sets: int) -> str:
    """Пример ввода результата для подсказки — раньше был всегда одинаковым
    ("15 15 15 18"), не зависел от реальной цели пользователя (Часть 10,
    пакет #2, п.10). work_sets рабочих подходов + один на максимум, все
    числа равны цели — это только пример формата ввода (через пробел),
    а не подсказка "сколько именно делать в подходе на максимум"."""
    return " ".join(str(target) for _ in range(work_sets + 1))


def calculate_age(birth_date: date, today: date) -> int:
    """Возраст на дисплей считается на лету (Часть 10) — хранить числом
    бессмысленно, оно устаревает само по себе каждый день рождения."""
    years = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        years -= 1
    return years


def format_kg(value: Decimal) -> str:
    """Без лишних нулей (Часть 10): 48.00 -> 48, 22.50 -> 22.5. Числа из БД
    приходят с фиксированным scale колонки (Numeric(5,2)), поэтому почти
    всегда есть дробная часть, которую можно безопасно подрезать — но
    только ПОСЛЕ точки, иначе "20" превратится в "2"."""
    text = f"{value:f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text
from app.domain.recommendations import (
    Recommendation,
    RecommendationCode,
    check_consistent_streak,
    check_equipment_too_light,
    check_minimal_rest_volume_drop,
    check_underworking_sets,
    check_weak_set_index,
)
from app.domain.reports import AllCyclesAnalytics, EquipmentProgress, SetCloseSummary, WeeklySummary
from app.domain.session import WorkoutRecord

_BLOCK_LABELS = {"a": "объём", "b": "сила"}

_RECOMMENDATION_TEMPLATES = {
    RecommendationCode.UNDERWORKING_SETS: texts.RECOMMENDATION_UNDERWORKING_SETS,
    RecommendationCode.EQUIPMENT_TOO_LIGHT: texts.RECOMMENDATION_EQUIPMENT_TOO_LIGHT,
    RecommendationCode.WEAK_SET_INDEX: texts.RECOMMENDATION_WEAK_SET_INDEX,
    RecommendationCode.MINIMAL_REST_VOLUME_DROP: texts.RECOMMENDATION_MINIMAL_REST_VOLUME_DROP,
    RecommendationCode.CONSISTENT_STREAK: texts.RECOMMENDATION_CONSISTENT_STREAK,
}


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


def _format_recommendation(recommendation: Recommendation) -> str:
    template = _RECOMMENDATION_TEMPLATES[recommendation.code]
    context = dict(recommendation.context)
    if "block" in context:
        context["block_label"] = _BLOCK_LABELS[context.pop("block")]
    return template.format(**context)


def collect_recommendations(records: list[WorkoutRecord], today: date) -> list[Recommendation]:
    """Прогоняет все проверки типов 1 и 2 (Часть 6 респека) по истории.
    Тип 1 (блок/цифры) — по последней тренировке и по последним нескольким
    подряд; тип 2 (режим) — по всей истории с учётом сегодняшней даты."""
    recommendations: list[Recommendation] = []
    if records:
        last = records[-1]
        for block in ("a", "b"):
            underworking = check_underworking_sets(last, block)
            if underworking is not None:
                recommendations.append(underworking)
            equipment_too_light = check_equipment_too_light(records, block)
            if equipment_too_light is not None:
                recommendations.append(equipment_too_light)
            weak_set = check_weak_set_index(records, block)
            if weak_set is not None:
                recommendations.append(weak_set)

    volume_drop = check_minimal_rest_volume_drop(records)
    if volume_drop is not None:
        recommendations.append(volume_drop)
    streak = check_consistent_streak(records, today)
    if streak is not None:
        recommendations.append(streak)
    return recommendations


def format_recommendations(records: list[WorkoutRecord], today: date) -> str:
    recommendations = collect_recommendations(records, today)
    if not recommendations:
        return ""
    lines = "\n".join(f"— {_format_recommendation(r)}" for r in recommendations)
    return f"{texts.RECOMMENDATIONS_HEADER}\n{lines}"


def _format_cycle_volume_change(pct: float | None) -> str:
    # Отдельная реализация, не format_volume_change() — та жёстко зашивает
    # "к прошлой неделе" в текст, здесь речь про предыдущий ЦИКЛ.
    if pct is None:
        return texts.VOLUME_CHANGE_NO_BASELINE
    sign, value = _signed_pct(pct)
    return texts.CYCLE_VOLUME_CHANGE_WITH_PCT.format(sign=sign, pct=value)


def format_all_cycles_analytics(analytics: AllCyclesAnalytics) -> str:
    body = texts.ALL_CYCLES_HEADER.format(cycle_count=analytics.cycle_count, total_volume=analytics.total_volume)
    lines = []
    for index, cycle in enumerate(analytics.cycles, start=1):
        lines.append(
            texts.ALL_CYCLES_LINE.format(
                set_number=index,
                workout_count=cycle.workout_count,
                total_volume=cycle.total_volume,
                volume_change=_format_cycle_volume_change(cycle.volume_change_pct),
            ),
        )
    return body + "\n".join(lines)


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
