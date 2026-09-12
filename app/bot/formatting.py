"""Форматирование доменных отчётов (app/domain/reports.py) в текст для
пользователя — вынесено отдельно от хендлеров, чтобы не дублировать между
обработчиком по запросу и еженедельным воркером (app/workers/weekly_report.py)."""

import math
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.bot import texts
from app.db.models import SubscriptionStatus, User
from app.domain.anomalies import AnomalyFlags
from app.domain.constants import MIN_REST_DAYS, EquipmentType

SUBSCRIPTION_STATUS_LABELS = {
    SubscriptionStatus.NONE: "нет подписки",
    SubscriptionStatus.TRIAL: "пробный период",
    SubscriptionStatus.ACTIVE: "активна",
    SubscriptionStatus.EXPIRED: "истекла",
}


def format_subscription_status(user: User, *, show_expired_date: bool = False) -> str:
    """Единый источник представления статуса подписки — Профиль
    пользователя и карточка/список в /admin показывают одно и то же
    (запрос автора после фидбека с реальной карточки: дата окончания была
    не видна в админке). Дата для TRIAL/ACTIVE — везде, как и раньше.

    show_expired_date=True (только /admin — админу дата истечения полезна
    при решении, продлевать ли и на сколько; в Профиле пользователя
    сознательно не показывается, оставляем прежнее поведение) добавляет
    дату и для EXPIRED."""
    label = SUBSCRIPTION_STATUS_LABELS[user.subscription_status]
    if user.subscription_expires_at is not None and user.subscription_status in (
        SubscriptionStatus.TRIAL, SubscriptionStatus.ACTIVE,
    ):
        days_left = max((user.subscription_expires_at.date() - datetime.now(UTC).date()).days, 0)
        label += texts.PROFILE_SUBSCRIPTION_DAYS_LEFT.format(
            days_left=days_left, expires_at=user.subscription_expires_at.strftime("%d.%m.%Y"),
        )
    elif show_expired_date and user.subscription_expires_at is not None and user.subscription_status == SubscriptionStatus.EXPIRED:
        label += texts.ADMIN_SUBSCRIPTION_EXPIRED_DATE.format(
            expires_at=user.subscription_expires_at.strftime("%d.%m.%Y"),
        )
    return label

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


def format_equipment_from_result(result: dict[str, str | int | None], *, instrumental: bool = False) -> str:
    """Тот же format_equipment_label, но прямо из equipment_results[block_key]
    (FSM-словарь с типом/значением строками, см. app/bot/handlers/equipment.py)
    — до записи в БД снаряд блока живёт только там, не в виде Block/
    NextBlockState с типизированными полями."""
    equipment_type = EquipmentType(result["type"])
    equipment_value = Decimal(result["value"]) if result["value"] else None
    return format_equipment_label(equipment_type, equipment_value, instrumental=instrumental)


def format_reps_example(target: int, work_sets: int) -> str:
    """Пример ввода результата для подсказки — раньше был всегда одинаковым
    ("15 15 15 18"), не зависел от реальной цели пользователя (Часть 10,
    пакет #2, п.10). work_sets рабочих подходов + один на максимум, все
    числа равны цели — это только пример формата ввода (через пробел),
    а не подсказка "сколько именно делать в подходе на максимум"."""
    return " ".join(str(target) for _ in range(work_sets + 1))


def format_sets_word(work_sets: int) -> str:
    """Склонение "подход" под число рабочих подходов — блок на объём
    (ревизия формулы прогрессии) растёт от VOLUME_BLOCK.work_sets до
    VOLUME_WORK_SETS_CEILING, фиксированное "3 подхода" в текстах больше
    не годится везде, где раньше был этот блок."""
    if work_sets % 10 == 1 and work_sets % 100 != 11:
        return "подход"
    if 2 <= work_sets % 10 <= 4 and not (12 <= work_sets % 100 <= 14):
        return "подхода"
    return "подходов"


def format_block_result(working_reps: Sequence[int], max_reps: int, *, reported_volume: int | None = None) -> str:
    """"18, 18, 18, максимум 21" — рабочие подходы (сколько бы их ни было,
    Часть 10, пакет #4) плюс подход на максимум, для отображения того, что
    реально было введено (история, детали дня в календаре, итог сразу
    после записи/правки) — раньше в этих местах показывался только
    максимум, без рабочих подходов, и свериться с фактически введёнными
    числами было нечем. working_reps может быть пустым (единичный ввод,
    например свободные подтягивания одним числом) — тогда только максимум.

    reported_volume (issue #88) — итог за тренировку без раскладки по
    подходам (бэкдейт блока Б, см. app.domain.session.BlockLog): когда
    задан, working_reps пуст, а max_reps — либо реальный лучший подход,
    либо 0 (не зафиксирован) — печатать "максимум 0" в этом случае было бы
    неверно (ложно предполагало бы, что 0 повторений — это факт), поэтому
    эта ветка проверяется первой и явно называет итог итогом, а не
    подходом на максимум."""
    if reported_volume is not None:
        if max_reps > 0:
            return f"итого {reported_volume}, лучший подход {max_reps}"
        return f"итого {reported_volume} (без раскладки по подходам)"
    if not working_reps:
        return f"максимум {max_reps}"
    working = ", ".join(str(reps) for reps in working_reps)
    return f"{working}, максимум {max_reps}"


def format_elective_result(reps_sequence: Sequence[int] | None, total_reps: int) -> str:
    """"12, 10, 8, 6 (всего 36)" для 3 факультативов, фиксирующих
    последовательность подходов, или "52 повторений всего" для
    volume_target (пакет #6) — там последовательность не хранится
    вообще, только сумма (см. ElectiveWorkout.reps_sequence)."""
    if not reps_sequence:
        return f"{total_reps} повторений всего"
    sequence = ", ".join(str(reps) for reps in reps_sequence)
    return f"{sequence} (всего {total_reps})"


def format_too_early_message(last_workout_performed_at: datetime, now: datetime) -> str:
    """Таймер + дата/время вместе (Часть 10, пакет #2, п.23) — общий для
    реактивного показа (после клика "Начать тренировку", когда рано —
    app/bot/handlers/workout.py::handle_start_workout) и проактивного
    (при открытии раздела "Тренировка" — app/bot/handlers/menu.py::
    handle_workout_section, issue #94), чтобы формула "сколько реально
    ждать" не разъезжалась между двумя местами показа одного и того же
    статуса. Домен (check_training_readiness) считает только по date —
    здесь для реального "сколько ждать" в часах нужна полная дата-время
    последней тренировки, поэтому здесь, не в домене (презентационный
    расчёт, не влияет на саму логику готовности)."""
    ready_at_dt = last_workout_performed_at + timedelta(days=MIN_REST_DAYS)
    hours_left = max(0, math.ceil((ready_at_dt - now).total_seconds() / 3600))
    return texts.TOO_EARLY_FOR_WORKOUT.format(
        hours_left=hours_left,
        ready_date=ready_at_dt.strftime("%d.%m"),
        ready_time=ready_at_dt.strftime("%H:%M"),
    )


def format_anomaly_message(flags: AnomalyFlags) -> str | None:
    """Складывает сработавшие проверки detect_anomalies в одно сообщение
    (пакет #4) — если сработало несколько сразу, все строки идут одна под
    другой, вопрос "Всё верно?" — один общий, не по очереди на каждую.
    None, если аномалий нет вообще (вызывающий тогда просто не показывает
    уточнение)."""
    lines = []
    if flags.large_value is not None:
        lines.append(texts.ANOMALY_LARGE_VALUE_LINE.format(value=flags.large_value))
    if flags.previous_avg is not None:
        lines.append(
            texts.ANOMALY_JUMP_LINE.format(
                previous=_format_avg(flags.previous_avg), current=_format_avg(flags.current_avg),
            ),
        )
    if flags.actual_set_count is not None:
        lines.append(
            texts.ANOMALY_SET_COUNT_LINE.format(expected=flags.expected_set_count, actual=flags.actual_set_count),
        )
    if not lines:
        return None
    return "\n".join(lines) + texts.ANOMALY_CONFIRM_QUESTION


def _format_avg(value: float) -> str:
    # 12.0 -> "12", 12.5 -> "12.5" — то же самое правило округления, что и
    # format_kg, просто без Decimal (среднее всегда float).
    return f"{value:.1f}".rstrip("0").rstrip(".")


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
