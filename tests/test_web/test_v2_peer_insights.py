"""/api/v2/assessments/{id}/peer-insights — «Сравнение с похожими» (#276): реальные агрегаты на
Postgres, порог 20, каскад пол+ступень → пол → все, приватность (только агрегаты), 404."""

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.db.models import Gender, User
from app.db.models_program import AssessmentProtocol, AssessmentResult
from tests.test_web._v2_client import v2_get

BASE = "/api/v2/assessments"
NOW = datetime.now(UTC)
# Середина ступени 30–39 (35 лет и ~3 месяца) — не зависит от «сегодня» и часового пояса.
MID_30S = date(NOW.year - 35, 1, 15)
MID_20S = date(NOW.year - 24, 1, 15)
MID_60S = date(NOW.year - 64, 1, 15)
CHILD = date(NOW.year - 12, 1, 15)
_next_tid = [10_000]


async def _pid(session, name: str = "Максимум подтягиваний") -> int:
    return (await session.execute(select(AssessmentProtocol.id).where(AssessmentProtocol.name == name))).scalar_one()


async def _make_user(session, gender: Gender | None, born: date | None) -> User:
    _next_tid[0] += 1
    user = User(telegram_id=_next_tid[0], username=f"peer{_next_tid[0]}", gender=gender, birth_date=born)
    session.add(user)
    await session.flush()
    return user


async def _result(session, user: User, pid: int, value, days_ago: int = 1) -> None:
    session.add(AssessmentResult(
        user_id=user.id, protocol_id=pid, performed_at=NOW - timedelta(days=days_ago), value=Decimal(str(value)), unit="повт.",
    ))
    await session.flush()


async def _cohort(session, pid: int, values, gender: Gender | None, born: date | None) -> list[User]:
    users = []
    for value in values:
        user = await _make_user(session, gender, born)
        await _result(session, user, pid, value)
        users.append(user)
    return users


async def _insights(session, user: User, pid: int) -> dict:
    response = await v2_get(session, user.telegram_id, f"{BASE}/{pid}/peer-insights")
    assert response.status_code == 200, response.text
    return response.json()


async def test_no_own_result_means_no_result_status_even_if_cohort_is_big(session):
    pid = await _pid(session)
    await _cohort(session, pid, range(1, 31), None, None)
    me = await _make_user(session, None, None)
    body = await _insights(session, me, pid)
    assert body["status"] == "no_result" and body["min_cohort_size"] == 20
    assert body["percentile"] is None and body["median"] is None and body["cohort"] is None


async def test_threshold_19_insufficient_20_enough_with_exact_maths(session):
    pid = await _pid(session)
    me = await _make_user(session, None, None)
    await _result(session, me, pid, 15)
    await _cohort(session, pid, [v for v in range(1, 20) if v != 15], None, None)  # 18 других + я = 19
    assert (await _insights(session, me, pid))["status"] == "insufficient"  # 19 — ещё мало
    await _cohort(session, pid, [30], None, None)  # 20-й человек
    body = await _insights(session, me, pid)
    # значения: 1..19 (15 — мой) и 30 → 20 человек
    assert body["status"] == "ok"
    # ниже 15: 1..14 = 14; равных: 1 (я); N=20 → (14 + 0.5)/20 = 72.5% → 73
    assert body["percentile"] == 73
    # отсортировано: 1..14,15,16..19,30 → медиана между 10-м и 11-м = (10 + 11)/2
    assert body["median"] == "10.5"
    assert body["cohort"] == {"level": "all", "label": "Все пользователи", "size_bucket": "20–49"}
    assert body["own_value"] == "15" and body["unit"] == "повт."
    # следующая цель — ближайший порог выше 15 (p75 ≈ 15.25): значение больше моего
    assert body["next_target"]["percentile"] in (75, 90) and Decimal(body["next_target"]["value"]) > 15


async def test_nineteen_people_is_insufficient_and_no_numbers_leak(session):
    pid = await _pid(session)
    me = await _make_user(session, None, None)
    await _result(session, me, pid, 15)
    await _cohort(session, pid, range(1, 19), None, None)  # 18 других + я = 19
    body = await _insights(session, me, pid)
    assert body["status"] == "insufficient"
    assert body["own_value"] == "15"
    for key in ("percentile", "median", "cohort", "next_target"):
        assert body[key] is None, key


async def test_cohort_cascade_gender_age_then_gender_then_all(session):
    pid = await _pid(session)
    me = await _make_user(session, Gender.MALE, MID_30S)
    await _result(session, me, pid, 10)
    # 19 мужчин 30–39 (с собой) → ступень мала; мужчин в целом 19 + 6 из другой ступени = 25
    await _cohort(session, pid, [8] * 18, Gender.MALE, MID_30S)
    await _cohort(session, pid, [12] * 6, Gender.MALE, MID_20S)
    await _cohort(session, pid, [20] * 30, Gender.FEMALE, MID_30S)
    body = await _insights(session, me, pid)
    assert body["status"] == "ok" and body["cohort"]["label"] == "Мужчины" and body["cohort"]["level"] == "gender"
    # мужчины: 18×8, я=10, 6×12 → below 18, equal 1 из 25 → (18.5)/25 = 74%
    assert body["percentile"] == 74 and body["median"] == "8"

    # ещё один мужчина 30–39 → ровно 20 в ступени
    await _cohort(session, pid, [14], Gender.MALE, MID_30S)
    body = await _insights(session, me, pid)
    assert body["cohort"] == {"level": "gender_age", "label": "Мужчины 30–39 лет", "size_bucket": "20–49"}
    assert body["percentile"] == 93  # 20 человек: ниже меня 18 (все по 8), 14 выше → 18.5/20 = 92.5% → 93
    assert body["median"] == "8"


async def test_cascade_falls_back_to_all_users_when_gender_is_small(session):
    pid = await _pid(session)
    me = await _make_user(session, Gender.FEMALE, MID_60S)
    await _result(session, me, pid, 5)
    await _cohort(session, pid, [3, 4, 6, 7, 8], Gender.FEMALE, MID_60S)
    await _cohort(session, pid, [9] * 20, Gender.MALE, MID_30S)
    body = await _insights(session, me, pid)
    assert body["cohort"]["label"] == "Все пользователи"
    assert body["percentile"] == 10  # 26 человек, ниже меня 2 (3, 4), равных 1 → 2.5/26 = 9.6% → 10
    assert body["cohort"]["size_bucket"] == "20–49"


async def test_users_without_gender_or_birth_date_or_minors_skip_levels(session):
    pid = await _pid(session)
    # без пола: даже при дате рождения сравнивается со всеми
    anon = await _make_user(session, None, MID_30S)
    await _result(session, anon, pid, 9)
    await _cohort(session, pid, [5] * 20, Gender.MALE, MID_30S)
    assert (await _insights(session, anon, pid))["cohort"]["label"] == "Все пользователи"
    # пол есть, даты рождения нет → ступени нет, сравнивается с полом
    no_birth = await _make_user(session, Gender.MALE, None)
    await _result(session, no_birth, pid, 9)
    assert (await _insights(session, no_birth, pid))["cohort"]["label"] == "Мужчины"
    # младше 18 — тоже без ступени
    kid = await _make_user(session, Gender.MALE, CHILD)
    await _result(session, kid, pid, 9)
    assert (await _insights(session, kid, pid))["cohort"]["label"] == "Мужчины"


async def test_only_latest_result_per_user_and_only_this_protocol_counts(session):
    pid = await _pid(session)
    other = await _pid(session, "Вис на перекладине, сек")
    me = await _make_user(session, None, None)
    await _result(session, me, pid, 10)
    for value in range(1, 20):
        user = await _make_user(session, None, None)
        await _result(session, user, pid, 100, days_ago=30)  # старый высокий результат — не считается
        await _result(session, user, pid, value, days_ago=2)  # последний — считается
        await _result(session, user, other, 999, days_ago=1)  # чужой протокол — не считается
    body = await _insights(session, me, pid)
    assert body["status"] == "ok"
    # N=20; ниже меня (10) — 1..9 = 9; равных 2 (я и тот, чей последний тоже 10) → (9 + 1)/20 = 50%
    assert body["percentile"] == 50
    assert body["median"] == "10"  # значения 1..19 и мой 10 → 20 штук, середина (10+10)/2


async def test_own_latest_result_is_the_one_compared(session):
    pid = await _pid(session)
    me = await _make_user(session, None, None)
    await _result(session, me, pid, 1, days_ago=30)
    await _result(session, me, pid, 18, days_ago=2)  # последний
    await _cohort(session, pid, range(1, 20), None, None)
    body = await _insights(session, me, pid)
    assert body["own_value"] == "18"
    # ниже 18: 1..17 = 17; равных: 1 (другой с 18) + я = 2; N=20 → (17 + 1)/20 = 90%
    assert body["percentile"] == 90


async def test_response_is_aggregates_only_no_ids_or_foreign_values(session):
    pid = await _pid(session)
    me = await _make_user(session, Gender.MALE, MID_30S)
    await _result(session, me, pid, 10)
    others = await _cohort(session, pid, list(range(40, 70)), Gender.MALE, MID_30S)
    response = await v2_get(session, me.telegram_id, f"{BASE}/{pid}/peer-insights")
    body = response.json()
    assert set(body) == {"status", "min_cohort_size", "unit", "own_value", "cohort", "percentile", "median", "next_target"}
    assert set(body["cohort"]) == {"level", "label", "size_bucket"}
    assert body["cohort"]["size_bucket"] == "20–49"  # не точное число
    raw = response.text
    for other in others:
        assert str(other.telegram_id) not in raw and other.username not in raw
    assert "user_id" not in raw and "telegram" not in raw and "results" not in body
    assert not any(isinstance(v, list) for v in body.values())
    assert len(json.dumps(body)) < 400  # размер не растёт с числом пользователей


async def test_unknown_protocol_and_unknown_user_are_404(session):
    me = await _make_user(session, None, None)
    assert (await v2_get(session, me.telegram_id, f"{BASE}/999999/peer-insights")).status_code == 404
    assert (await v2_get(session, 777_777, f"{BASE}/{await _pid(session)}/peer-insights")).status_code == 404


async def test_next_target_none_when_best_in_cohort(session):
    pid = await _pid(session)
    me = await _make_user(session, None, None)
    await _result(session, me, pid, 50)
    await _cohort(session, pid, range(1, 25), None, None)
    body = await _insights(session, me, pid)
    assert body["percentile"] == 98  # 25 человек, ниже меня 24 → 24.5/25 = 98%
    assert body["next_target"] is None


async def test_cohort_aggregation_is_one_sql_regardless_of_user_count(session):
    from sqlalchemy import event

    from app.db.repositories.assessments import AssessmentRepository

    pid = await _pid(session)
    me = await _make_user(session, Gender.MALE, MID_30S)
    await _result(session, me, pid, 10)
    await _cohort(session, pid, range(1, 60), Gender.MALE, MID_30S)
    statements: list[str] = []
    sync_engine = session.bind.sync_engine if session.bind is not None else session.get_bind()
    def listener(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(sync_engine, "before_cursor_execute", listener)
    try:
        cohorts = await AssessmentRepository(session).peer_cohorts(pid, Decimal(10), "male", "30_39", NOW.date())
    finally:
        event.remove(sync_engine, "before_cursor_execute", listener)
    assert len(statements) == 1
    assert [c.level.value for c in cohorts] == ["gender_age", "gender", "all"] and cohorts[0].size == 60
