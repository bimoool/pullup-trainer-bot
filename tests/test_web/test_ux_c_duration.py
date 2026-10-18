"""UX-03 (executor C): одна длительность занятия — активное время движка — во всех местах.

Итог тренировки (ответ завершения), карточка Журнала и минуты Аналитики читают один и тот же duration_seconds;
0/нет значения не превращается в «0:00» (на экране — «без длительности»)."""

import pytest

from tests.test_web._v2_client import v2_get
from tests.test_web.test_v2_live_engine import (  # noqa: F401  (clock — фикстура)
    REPS_2x8_R30,
    _active,
    _builder,
    _event,
    _post_events,
    _start,
    _state,
    _submit,
    _user,
    clock,
)


async def _finish_early_after_one_set(session, clock, telegram_id: int, *, set_at_s: int, finish_at_s: int):  # noqa: F811
    user = await _user(session, telegram_id)
    workout = await _builder(session, user, [REPS_2x8_R30])
    body = await _start(session, user, clock, workout_id=workout.id)
    t0 = _state(body)["started_at"]
    clock.ms = t0 + set_at_s * 1000
    await _post_events(session, user, body["id"], _submit(_state(await _active(session, user)), 8))
    clock.ms = t0 + finish_at_s * 1000
    result = await _post_events(session, user, body["id"], _event("finish_early"))
    return user, body["id"], result


async def _card_and_minutes(session, user, session_id: int):
    sessions = (await v2_get(session, user.telegram_id, "/api/v2/sessions?status=completed")).json()["sessions"]
    card = next(c for c in sessions if c["id"] == session_id)
    analytics = (await v2_get(session, user.telegram_id, "/api/v2/analytics/training")).json()
    return card, analytics["metrics"]["total_minutes"]


@pytest.mark.parametrize(
    ("finish_at_s", "minutes"),
    [
        (40, 1),   # досрочно на 40-й секунде: 40 с -> (40 + 30) // 60 = 1 мин (половина вверх)
        (90, 2),   # 90 с -> (90 + 30) // 60 = 2 мин
        (20, 0),   # 20 с -> (20 + 30) // 60 = 0 мин (на экране занятия при этом «20 с», не «0:00»)
    ],
)
async def test_same_active_duration_in_summary_journal_and_analytics(session, clock, finish_at_s, minutes):  # noqa: F811
    user, session_id, result = await _finish_early_after_one_set(
        session, clock, 900100 + finish_at_s, set_at_s=min(9, finish_at_s - 1), finish_at_s=finish_at_s,
    )
    card, total_minutes = await _card_and_minutes(session, user, session_id)

    assert result["duration_seconds"] == finish_at_s  # Итог: активное время, не None и не 0
    assert card["duration_seconds"] == finish_at_s  # деталь/карточка Журнала — то же число
    assert total_minutes == minutes  # Аналитика: round(Σ секунд / 60), половина вверх
