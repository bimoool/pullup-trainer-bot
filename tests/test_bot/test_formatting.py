from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.bot.formatting import (
    format_anomaly_message,
    format_block_result,
    format_equipment_progress_line,
    format_progress_report,
    format_recommendations,
    format_set_close_report,
    format_subscription_status,
    format_volume_change,
    format_weekly_summary,
)
from app.db.models import SubscriptionStatus, User
from app.domain.anomalies import AnomalyFlags
from app.domain.constants import EquipmentType
from app.domain.reports import EquipmentProgress, SetCloseSummary, WeeklySummary
from app.domain.session import BlockAssignment, BlockLog, WorkoutRecord


def _user(status: SubscriptionStatus, expires_at: datetime | None) -> User:
    return User(subscription_status=status, subscription_expires_at=expires_at)


def test_format_subscription_status_active_shows_days_left_and_date():
    expires_at = datetime.now(UTC) + timedelta(days=10)
    label = format_subscription_status(_user(SubscriptionStatus.ACTIVE, expires_at))
    assert "активна" in label
    assert expires_at.strftime("%d.%m.%Y") in label
    assert "осталось" in label


def test_format_subscription_status_expired_omits_date_by_default():
    expires_at = datetime.now(UTC) - timedelta(days=30)
    label = format_subscription_status(_user(SubscriptionStatus.EXPIRED, expires_at))
    assert label == "истекла"
    assert expires_at.strftime("%d.%m.%Y") not in label


def test_format_subscription_status_expired_shows_date_when_requested():
    """/admin-запрос: дата важна для решения, продлевать ли и на сколько
    (заходил неделю назад — одно, полгода назад — совсем другое)."""
    expires_at = datetime.now(UTC) - timedelta(days=30)
    label = format_subscription_status(_user(SubscriptionStatus.EXPIRED, expires_at), show_expired_date=True)
    assert label == f"истекла {expires_at.strftime('%d.%m.%Y')}"


def test_format_subscription_status_none_never_shows_date_even_when_requested():
    label = format_subscription_status(_user(SubscriptionStatus.NONE, None), show_expired_date=True)
    assert label == "нет подписки"


def test_format_volume_change_none_omits_percentage():
    assert format_volume_change(None) == ""


def test_format_volume_change_positive_has_plus_sign():
    assert "+50.0%" in format_volume_change(50.0)


def test_format_volume_change_negative_keeps_minus_sign():
    assert "-10.0%" in format_volume_change(-10.0)


def test_format_block_result_lists_working_reps_before_max():
    assert format_block_result((18, 18, 18), 21) == "18, 18, 18, максимум 21"


def test_format_block_result_falls_back_to_max_only_when_working_reps_empty():
    # Единичный ввод (например, свободные подтягивания одним числом) — нет
    # рабочих подходов вообще, working_reps=() (см. parse_free_reps).
    assert format_block_result((), 8) == "максимум 8"


def test_format_anomaly_message_none_when_no_anomalies():
    assert format_anomaly_message(AnomalyFlags()) is None


def test_format_anomaly_message_large_value_only():
    message = format_anomaly_message(AnomalyFlags(large_value=55))
    assert "55" in message
    assert message.endswith("Всё верно?")


def test_format_anomaly_message_jump_formats_averages_without_trailing_zero():
    message = format_anomaly_message(AnomalyFlags(previous_avg=12.0, current_avg=28.0))
    assert "12" in message
    assert "28" in message
    assert "12.0" not in message


def test_format_anomaly_message_set_count():
    message = format_anomaly_message(AnomalyFlags(expected_set_count=3, actual_set_count=5))
    assert "3" in message
    assert "5" in message


def test_format_anomaly_message_combines_all_three_in_one_message():
    message = format_anomaly_message(
        AnomalyFlags(large_value=60, previous_avg=10.0, current_avg=55.0, expected_set_count=3, actual_set_count=2),
    )
    assert message.count("Всё верно?") == 1
    assert "60" in message
    assert "10" in message and "55" in message
    assert "2" in message


def test_format_equipment_progress_line_none_placeholder():
    assert format_equipment_progress_line(None) == "пока нет данных"


def test_format_equipment_progress_line_includes_values():
    progress = EquipmentProgress(
        equipment_type=EquipmentType.BAND, equipment_value=Decimal("20.0"), equipment_item_id=None,
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


def _record() -> WorkoutRecord:
    band = Decimal("20.0")
    return WorkoutRecord(
        performed_at=datetime(2026, 1, 1, tzinfo=UTC),
        block_a=BlockAssignment(
            log=BlockLog(working_reps=(10, 10, 10), max_reps=16), target_before=10, target_after=11,
            equipment_changed=False, equipment_type=EquipmentType.BAND, equipment_value=band,
        ),
        block_b=BlockAssignment(
            log=BlockLog(working_reps=(3, 3, 3, 3), max_reps=4), target_before=3, target_after=4,
            equipment_changed=False, equipment_type=EquipmentType.BAND, equipment_value=band,
        ),
    )


def test_format_recommendations_empty_history_gives_empty_string():
    assert format_recommendations([], date(2026, 1, 1)) == ""


def test_format_recommendations_includes_triggered_recommendation():
    # gap = max(16) - mean(10,10,10) = 6 >= порог -> underworking_sets на объёме
    text = format_recommendations([_record()], date(2026, 1, 1))
    assert "💡" in text
    assert "объём" in text
