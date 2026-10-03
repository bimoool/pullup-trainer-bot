"""REBUILD-1 (R3): чистый расчёт аналитики TrainingSession v2."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.domain.training_analytics import (
    MAX_TREND_POINTS,
    AnalyticsBlock,
    AnalyticsSession,
    AnalyticsSetLog,
    compute_activity,
    compute_training_analytics,
)

MSK = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)  # вторник


def _reps(values, exercise_id=1, name="Подтягивания", protocol="reps_sets", unit="reps"):
    return AnalyticsBlock(
        exercise_id=exercise_id, exercise_name=name, protocol_type=protocol,
        set_logs=[AnalyticsSetLog(Decimal(v), unit) for v in values],
    )


def _session(at, *blocks):
    return AnalyticsSession(performed_at=at, blocks=list(blocks))


def test_same_exercise_with_reps_and_max_stays_separated():
    sessions = [
        _session(NOW - timedelta(days=3), _reps([8, 7]), _reps([20, 22], protocol="max_effort")),
        _session(NOW - timedelta(days=1), _reps([9]), _reps([25], protocol="max_effort")),
    ]
    analytics = compute_training_analytics(sessions, NOW, MSK)

    reps, max_ = analytics.panels
    assert (reps.protocol_type, max_.protocol_type) == ("reps_sets", "max_effort")
    assert (reps.total_reps, reps.set_count, reps.best_set) == (Decimal(24), 3, Decimal(9))
    assert (max_.attempt_count, max_.best) == (3, Decimal(25))  # повторения НЕ примешаны к максимуму
    assert [p.value for p in reps.points] == [Decimal(15), Decimal(9)]


def test_max_effort_cumulative_pb_and_flags():
    sessions = [
        _session(NOW - timedelta(days=4), _reps([20], protocol="max_effort")),
        _session(NOW - timedelta(days=3), _reps([18], protocol="max_effort")),  # хуже рекорда
        _session(NOW - timedelta(days=2), _reps([22, 21], protocol="max_effort")),  # новый рекорд
        _session(NOW - timedelta(days=1), _reps([22], protocol="max_effort")),  # равен — не рекорд
    ]
    [panel] = compute_training_analytics(sessions, NOW, MSK).panels

    assert [p.cumulative_best for p in panel.points] == [Decimal(v) for v in (20, 20, 22, 22)]
    assert [p.is_new_pb for p in panel.points] == [False, False, True, False]  # первая запись — точка отсчёта
    assert panel.best == Decimal(22) and panel.attempt_count == 5


def test_time_and_interval_metrics_and_step_blocks_excluded():
    interval_result = {"type": "interval", "actual_duration_seconds": 15, "completed_cycles": 2}
    sessions = [
        _session(
            NOW - timedelta(days=2),
            _reps([30, 25], exercise_id=2, name="Планка", protocol="time_sets", unit="s"),
            AnalyticsBlock(3, "Бёрпи", "interval", [], interval_result),
            AnalyticsBlock(3, "Бёрпи", "interval", [], None),  # невыполненный блок — не вклад
            _reps([10, 10], protocol=None),  # STEP/legacy: только активность
        ),
    ]
    analytics = compute_training_analytics(sessions, NOW, MSK)

    by_type = {p.protocol_type: p for p in analytics.panels}
    assert set(by_type) == {"time_sets", "interval"}  # блок без протокола в метрики не попал
    assert (by_type["time_sets"].total_work_seconds, by_type["time_sets"].best_set) == (Decimal(55), Decimal(30))
    assert (by_type["interval"].actual_duration_seconds, by_type["interval"].cycles) == (15, 2)
    assert analytics.activity.sessions_last_30_days == 1  # смешанная сессия — один раз


def test_activity_window_weeks_and_future_exclusion():
    today = NOW.astimezone(MSK).date()
    edge_in = datetime.combine(today - timedelta(days=29), datetime.min.time(), tzinfo=MSK) + timedelta(hours=10)
    edge_out = datetime.combine(today - timedelta(days=30), datetime.min.time(), tzinfo=MSK) + timedelta(hours=10)
    sessions = [
        _session(edge_in), _session(edge_out), _session(NOW - timedelta(hours=1)), _session(NOW - timedelta(hours=2)),
        _session(NOW + timedelta(days=1)),  # будущая — исключена
    ]
    analytics = compute_training_analytics(sessions, NOW, MSK)

    assert analytics.activity.sessions_last_30_days == 3  # edge_in + две сегодняшние; edge_out и будущая — нет
    assert analytics.activity.active_days_last_30_days == 2
    weeks = analytics.activity.weeks
    assert len(weeks) == 12 and weeks[-1].week_start == today - timedelta(days=today.weekday())  # понедельник
    assert weeks[-1].sessions == 2 and weeks[-1].active_days == 1
    assert all(b.week_start.weekday() == 0 for b in weeks)


def test_local_calendar_day_uses_user_timezone():
    # 23:30 UTC 27 сентября — уже 28 сентября 11:30 в Kiritimati (+14), но 27-е в UTC.
    session = _session(datetime(2026, 9, 27, 23, 30, tzinfo=UTC))
    kiritimati = compute_activity([session], NOW, ZoneInfo("Pacific/Kiritimati"))
    utc = compute_activity([session], NOW, ZoneInfo("UTC"))

    def week_of_session(activity):
        return next(w.week_start.isoformat() for w in activity.weeks if w.sessions == 1)

    assert week_of_session(utc) == "2026-09-21"  # 27.09 — воскресенье прошлой недели
    assert week_of_session(kiritimati) == "2026-09-28"  # 28.09 — понедельник новой недели


def test_trend_is_bounded_but_totals_cover_everything():
    sessions = [_session(NOW - timedelta(minutes=i + 1), _reps([5])) for i in range(MAX_TREND_POINTS + 25)]
    [panel] = compute_training_analytics(sessions, NOW, MSK).panels

    assert panel.points_total == MAX_TREND_POINTS + 25
    assert len(panel.points) == MAX_TREND_POINTS
    assert panel.total_reps == Decimal(5 * (MAX_TREND_POINTS + 25))  # агрегаты — по всем сессиям
    assert panel.points[0].at < panel.points[-1].at  # хронологически, самые свежие сохранены
