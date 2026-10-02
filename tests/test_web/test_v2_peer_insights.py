"""/api/v2/assessments/{id}/peer-insights — «Сравнение с похожими» (#276): реальные агрегаты на
Postgres, порог 20, каскад пол+ступень → пол → все, приватность (только агрегаты), 404."""

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.models import Gender, User
from app.db.models_program import AssessmentProtocol, AssessmentResult
from app.web.routes_v2_assessments import PEER_RATE_CAPACITY, peer_insights_limiter
from tests.test_web._v2_client import v2_get

BASE = "/api/v2/assessments"
NOW = datetime.now(UTC)
# Середина ступени 30–39 (35 лет и ~3 месяца) — не зависит от «сегодня» и часового пояса.
MID_30S = date(NOW.year - 35, 1, 15)
MID_20S = date(NOW.year - 24, 1, 15)
MID_60S = date(NOW.year - 64, 1, 15)
CHILD = date(NOW.year - 12, 1, 15)
_next_tid = [10_000]


@pytest.fixture(autouse=True)
def _fresh_limiter():
    peer_insights_limiter.reset()
    yield
    peer_insights_limiter.reset()


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
    assert body["percentile"] == 70  # точный 73 → полоса 70 («~70 %»)
    # отсортировано: 1..14,15,16..19,30 → медиана между 10-м и 11-м = (10 + 11)/2
    assert body["median"] == "11"  # повторения — целые: 10.5 → 11
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
    assert body["percentile"] == 70 and body["median"] == "8"  # точный 74 → полоса 70

    # ещё один мужчина 30–39 → ровно 20 в ступени, но остаток «мужчины − ступень» = 6 → ступень подавлена
    await _cohort(session, pid, [14], Gender.MALE, MID_30S)
    assert (await _insights(session, me, pid))["cohort"]["level"] == "gender"
    # +14 мужчин 20–29 → остаток 20: ступень показывается
    await _cohort(session, pid, [12] * 14, Gender.MALE, MID_20S)
    body = await _insights(session, me, pid)
    assert body["cohort"] == {"level": "gender_age", "label": "Мужчины 30–39 лет", "size_bucket": "20–49"}
    assert body["percentile"] == 90  # точный 93; 20 человек: ниже меня 18 (все по 8), 14 выше → 18.5/20 = 92.5% → 93
    assert body["median"] == "8"


async def test_cascade_falls_back_to_all_users_when_gender_is_small(session):
    pid = await _pid(session)
    me = await _make_user(session, Gender.FEMALE, MID_60S)
    await _result(session, me, pid, 8)
    await _cohort(session, pid, [3, 4, 6, 7, 8], Gender.FEMALE, MID_60S)
    await _cohort(session, pid, [9] * 14, Gender.MALE, MID_30S)
    await _cohort(session, pid, [9] * 10, None, None)
    body = await _insights(session, me, pid)
    assert body["cohort"]["label"] == "Все пользователи"
    # 30 человек, ниже меня 4 (3, 4, 6, 7), равных 2 → 5/30 = 16.7% → 17 → полоса 10
    assert body["percentile"] == 10
    assert body["cohort"]["size_bucket"] == "20–49"


async def test_users_without_gender_or_birth_date_or_minors_skip_levels(session):
    pid = await _pid(session)
    # по 20 мужчин в двух ступенях и 20 без пола: остатки вычитания ≥ 20, защита не мешает
    await _cohort(session, pid, [5] * 20, Gender.MALE, MID_30S)
    await _cohort(session, pid, [5] * 20, Gender.MALE, MID_20S)
    await _cohort(session, pid, [6] * 20, None, None)
    # без пола: даже при дате рождения сравнивается со всеми
    anon = await _make_user(session, None, MID_30S)
    await _result(session, anon, pid, 9)
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
    assert body["percentile"] == 90  # 25 человек, ниже меня 24 → 98% → полоса 90
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
        cohorts = await AssessmentRepository(session).peer_cohorts(pid, Decimal(10), NOW.date())
    finally:
        event.remove(sync_engine, "before_cursor_execute", listener)
    assert len(statements) <= 2  # сейчас ровно один (GROUPING SETS)
    assert {c.level.value for c in cohorts.values()} == {"gender_age", "gender", "all"}
    assert next(c for c in cohorts.values() if c.level.value == "gender_age").size == 60


async def test_percentile_is_a_ten_point_band_sweeping_own_value_cannot_resolve_individuals(session):
    """Развёртка: пользователь ставит своё значение 1..30 против одной и той же когорты (30 чужих
    значений 1..30). Ответов с точным процентилем было бы ~30 разных (по 1 % на человека), с
    полосами — не больше 10 значений, кратных 10."""
    pid = await _pid(session)
    me = await _make_user(session, None, None)
    await _cohort(session, pid, range(1, 31), None, None)
    seen = set()
    for value in range(1, 31):
        peer_insights_limiter.reset()
        await _result(session, me, pid, value, days_ago=0)
        body = await _insights(session, me, pid)
        seen.add(body["percentile"])
        assert body["percentile"] % 10 == 0 and 0 <= body["percentile"] <= 90
    assert len(seen) <= 10


async def test_non_reps_median_and_next_target_use_one_decimal(session):
    pid = await _pid(session, "Подтягивания с весом, кг")
    me = await _make_user(session, None, None)
    await _result(session, me, pid, 10)
    values = ["5.25", "5.5", "6.25", "7.75", "8.5", "9.25", "11.25", "12.75", "14.5", "15.25"] * 2
    await _cohort(session, pid, values, None, None)
    body = await _insights(session, me, pid)
    for number in (body["median"], body["next_target"]["value"]):
        assert len(number.partition(".")[2]) <= 1, number
    assert Decimal(body["next_target"]["value"]) > 10


async def test_gender_level_hidden_when_age_remainder_is_small_everyone_still_gets_a_cohort(session):
    """Мужчина без даты рождения: «мужчины» = 25 (30–39) + 10 (20–29) + он сам = 36; ступень 30–39
    (25) оставляла бы остаток 11. Подавляется узкая ступень, а не «мужчины»: без даты рождения —
    «мужчины» (остаток от «все» 25 женщин ≥ 20), мужчина 30–39 тоже видит «мужчин» (ступень скрыта)."""
    pid = await _pid(session)
    await _cohort(session, pid, [5] * 25, Gender.MALE, MID_30S)
    await _cohort(session, pid, [6] * 10, Gender.MALE, MID_20S)
    await _cohort(session, pid, [7] * 25, Gender.FEMALE, MID_30S)
    me = await _make_user(session, Gender.MALE, None)
    await _result(session, me, pid, 9)
    body = await _insights(session, me, pid)
    assert body["status"] == "ok" and body["cohort"]["level"] == "gender"
    viewer = await _make_user(session, Gender.MALE, MID_30S)
    await _result(session, viewer, pid, 9)
    assert (await _insights(session, viewer, pid))["cohort"]["level"] == "gender"  # ступень 30–39 подавлена
    # ещё 9 мужчин 20–29 → остаток 20 → ступень 30–39 снова показывается (26 с viewer'ом)
    await _cohort(session, pid, [6] * 9, Gender.MALE, MID_20S)
    assert (await _insights(session, viewer, pid))["cohort"]["level"] == "gender_age"


async def test_small_minority_does_not_suppress_all_for_everyone(session):
    """Ревью #284 (B2): 25 мужчин + 8 женщин. Раньше «все» скрывалось для женщин и пользователей без
    пола. Теперь «все» (33) доступно им; узкие «мужчины»/ступень, чья разность с «все» раскрыла бы
    8 женщин, подавляются — мужчины тоже получают «все»."""
    pid = await _pid(session)
    await _cohort(session, pid, [5] * 25, Gender.MALE, MID_30S)
    await _cohort(session, pid, [6] * 7, Gender.FEMALE, MID_30S)
    woman = await _make_user(session, Gender.FEMALE, MID_30S)
    await _result(session, woman, pid, 9)
    nobody = await _make_user(session, None, None)
    await _result(session, nobody, pid, 9)
    man = await _make_user(session, Gender.MALE, MID_30S)
    await _result(session, man, pid, 9)  # теперь мужчин 26, женщин 8: ALL = 35 (с nobody)
    for user in (woman, nobody, man):
        body = await _insights(session, user, pid)
        assert body["status"] == "ok" and body["cohort"]["level"] == "all", body


async def test_review_scenario_male_only_protocol_cannot_be_differenced_through_birth_date(session):
    """Ревью #284 (B1): 35 мужчин (25 в 18–29, 10 в 30–39), женщин нет. «все» ≡ «мужчины»; смена
    даты рождения не должна давать другой ответ — ступень 18–29 скрыта, все видят одни цифры."""
    pid = await _pid(session)
    await _cohort(session, pid, [5] * 24, Gender.MALE, MID_20S)
    await _cohort(session, pid, [7] * 9, Gender.MALE, MID_30S)
    old = await _make_user(session, Gender.MALE, MID_30S)
    young = await _make_user(session, Gender.MALE, MID_20S)
    for user in (old, young):
        await _result(session, user, pid, 6)
    bodies = []
    for user in (old, young):
        peer_insights_limiter.reset()
        bodies.append(await _insights(session, user, pid))
    assert bodies[0] == bodies[1]
    assert bodies[0]["cohort"]["level"] == "gender"
    nobody = await _make_user(session, None, None)  # без пола: «все» — это те же 35 + он сам (остаток 1)
    await _result(session, nobody, pid, 6)
    body = await _insights(session, nobody, pid)
    # остаток «все» − «мужчины» = 1 → «мужчины» скрыты; «все» (36) для него; «мужчины» не отличимы
    # от «все» по разности, потому что их больше нет
    assert body["status"] == "ok" and body["cohort"]["level"] == "all"
    peer_insights_limiter.reset()
    assert (await _insights(session, old, pid))["cohort"]["level"] == "all"


async def test_all_level_with_single_gender_less_than_twenty_is_insufficient_until_enough(session):
    """Без пола: 19 мужчин + он сам = 20 в «все»; ни одна узкая когорта не показывается (мужчин 19)."""
    pid = await _pid(session)
    await _cohort(session, pid, [5] * 19, Gender.MALE, MID_30S)
    me = await _make_user(session, None, None)
    await _result(session, me, pid, 9)
    assert (await _insights(session, me, pid))["cohort"]["level"] == "all"
    await _cohort(session, pid, [5], Gender.MALE, MID_30S)  # мужчин 20, «все» 21: остаток 1 → мужчины скрыты
    body = await _insights(session, me, pid)
    assert body["cohort"]["level"] == "all"


async def test_peer_cohorts_returns_all_candidates_from_one_grouped_sql(session):
    from sqlalchemy import event

    from app.db.repositories.assessments import AssessmentRepository
    from app.domain.peer_insights import ALL_COHORT, cell_cohort, gender_cohort

    pid = await _pid(session)
    me = await _make_user(session, Gender.MALE, MID_30S)
    await _result(session, me, pid, 10)
    await _cohort(session, pid, [5] * 25, Gender.MALE, MID_20S)
    await _cohort(session, pid, [5] * 3, Gender.FEMALE, MID_20S)
    await _cohort(session, pid, [5] * 2, None, None)
    statements: list[str] = []
    sync_engine = session.bind.sync_engine if session.bind is not None else session.get_bind()

    def listener(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(sync_engine, "before_cursor_execute", listener)
    try:
        cohorts = await AssessmentRepository(session).peer_cohorts(pid, Decimal(10), NOW.date())
    finally:
        event.remove(sync_engine, "before_cursor_execute", listener)
    assert len(statements) == 1  # ≤ 2 по ТЗ; сейчас ровно один (GROUPING SETS)
    # меньше 20 в выдачу не попадает (30–39 мужчин: 1, женщины: 3); без пола — только в «все»
    assert set(cohorts) == {ALL_COHORT, gender_cohort("male"), cell_cohort("male", "18_29")}
    assert cohorts[ALL_COHORT].size == 31 and cohorts[gender_cohort("male")].size == 26
    assert cohorts[cell_cohort("male", "18_29")].size == 25 and cohorts[cell_cohort("male", "18_29")].below == 25


async def test_peer_insights_endpoint_is_rate_limited_per_user_with_friendly_429(session):
    pid = await _pid(session)
    me = await _make_user(session, None, None)
    other = await _make_user(session, None, None)
    for _ in range(PEER_RATE_CAPACITY):
        assert (await v2_get(session, me.telegram_id, f"{BASE}/{pid}/peer-insights")).status_code == 200
    blocked = await v2_get(session, me.telegram_id, f"{BASE}/{pid}/peer-insights")
    assert blocked.status_code == 429
    assert "Слишком много" in blocked.json()["detail"] and int(blocked.headers["retry-after"]) >= 1
    # лимит per-user: другой пользователь не затронут
    assert (await v2_get(session, other.telegram_id, f"{BASE}/{pid}/peer-insights")).status_code == 200
