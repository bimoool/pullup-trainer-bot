"""#283 — GET /api/v2/plan отдаёт current_week_id (текущая неделя, не «последняя
в списке»), а недельная арифметика плана идёт по часовому поясу пользователя."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.models import User
from app.db.models_program import PlanWeek, TrainingPlan
from app.domain.multi_program import plan_week_number
from app.web import routes_v2
from tests.test_web._v2_client import v2_get, v2_post

TG = 1001

# Воскресенье 22:30 UTC = понедельник 01:30 в Москве (UTC+3).
SUNDAY_NIGHT_UTC = datetime(2026, 10, 4, 22, 30, tzinfo=UTC)
MONDAY = date(2026, 10, 5)
PREVIOUS_MONDAY = date(2026, 9, 28)


@pytest.fixture
def clock(monkeypatch):
    def _set(now: datetime) -> None:
        monkeypatch.setattr(routes_v2, "_utcnow", lambda: now)
    return _set


async def _plan(session, user: User, *, tz: str | None) -> TrainingPlan:
    user.timezone = tz
    plan = TrainingPlan(user_id=user.id, created_at=SUNDAY_NIGHT_UTC - timedelta(days=30))
    session.add(plan)
    await session.commit()
    return plan


def _week(plan_json: dict, week_id: int) -> dict:
    return next(week for week in plan_json["plan_weeks"] if week["id"] == week_id)


async def test_current_week_id_is_not_the_last_week_after_future_weeks(session, user, clock):
    clock(datetime(2026, 10, 7, 12, 0, tzinfo=UTC))  # среда
    await _plan(session, user, tz="UTC")

    first = (await v2_get(session, TG, "/api/v2/plan")).json()["plan"]
    current_id = first["current_week_id"]
    assert current_id is not None
    assert [w["id"] for w in first["plan_weeks"]] == [current_id]
    assert _week(first, current_id)["start_date"] == MONDAY.isoformat()

    future = await v2_post(session, TG, "/api/v2/plan/weeks", {"week_number": first["plan_weeks"][0]["week_number"] + 2})
    assert future.status_code == 200

    plan_json = (await v2_get(session, TG, "/api/v2/plan")).json()["plan"]
    assert plan_json["plan_weeks"][-1]["id"] == future.json()["id"]  # последняя — будущая
    assert plan_json["current_week_id"] == current_id  # а текущая прежняя


async def test_plan_week_math_uses_user_timezone_near_midnight_monday(session, user, clock):
    clock(SUNDAY_NIGHT_UTC)
    plan = await _plan(session, user, tz="Europe/Moscow")  # у пользователя уже понедельник

    plan_json = (await v2_get(session, TG, "/api/v2/plan")).json()["plan"]
    assert _week(plan_json, plan_json["current_week_id"])["start_date"] == MONDAY.isoformat()
    current_number = _week(plan_json, plan_json["current_week_id"])["week_number"]
    assert current_number == plan_week_number(plan.created_at.date(), MONDAY)

    # окно «текущая .. +4» считается от недели пользователя: +4 можно, +5 нельзя, неделя до — нельзя
    assert (await v2_post(session, TG, "/api/v2/plan/weeks", {"week_number": current_number + 4})).status_code == 200
    assert (await v2_post(session, TG, "/api/v2/plan/weeks", {"week_number": current_number + 5})).status_code == 422
    assert (await v2_post(session, TG, "/api/v2/plan/weeks", {"week_number": current_number - 1})).status_code == 422
    starts = sorted(
        (await session.execute(select(PlanWeek.start_date).where(PlanWeek.training_plan_id == plan.id))).scalars(),
    )
    assert starts[0] == MONDAY


async def test_utc_user_still_on_previous_week_at_same_instant(session, user, clock):
    clock(SUNDAY_NIGHT_UTC)
    await _plan(session, user, tz="UTC")  # у UTC-пользователя ещё воскресенье

    plan_json = (await v2_get(session, TG, "/api/v2/plan")).json()["plan"]
    assert _week(plan_json, plan_json["current_week_id"])["start_date"] == PREVIOUS_MONDAY.isoformat()


async def test_no_timezone_falls_back_to_project_default(session, user, clock):
    clock(SUNDAY_NIGHT_UTC)
    await _plan(session, user, tz=None)

    response = await v2_get(session, TG, "/api/v2/plan")
    assert response.status_code == 200
    assert response.json()["plan"]["current_week_id"] is not None


async def test_course_current_week_uses_user_timezone_like_plan_weeks(session, user, clock):
    """#284 C4: current_week курса считался по UTC-дате, а недели плана — по дате пользователя."""
    from app.db.models_program import ProgramInclusion
    from tests.test_web.test_v2_plan_overview import _program

    clock(SUNDAY_NIGHT_UTC)
    program = await _program(session, config={"duration_weeks": 4})

    async def current_week(tz: str) -> int:
        user.timezone = tz
        await session.commit()
        created = await v2_post(session, TG, "/api/v2/program-inclusions", {"program_id": program.id})
        assert created.status_code == 200
        row = await session.get(ProgramInclusion, created.json()["id"])
        row.started_at = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)  # ровно 7 дней до понедельника пользователя в Москве
        await session.commit()
        plan_json = (await v2_get(session, TG, "/api/v2/plan")).json()["plan"]
        return next(i for i in plan_json["program_inclusions"] if i["id"] == row.id)["current_week"]

    assert await current_week("Europe/Moscow") == 2  # у пользователя уже понедельник 5 октября
    assert await current_week("UTC") == 1  # у UTC-пользователя ещё воскресенье 4 октября


async def test_course_current_week_converts_started_at_to_user_timezone(session, user, clock):
    """#285 L1: started_at = понедельник 01:00 Москвы (воскресенье 22:00 UTC) — дата старта курса
    локальная, иначе `.date()` в UTC даёт воскресенье и current_week уходит на неделю вперёд."""
    from app.db.models_program import ProgramInclusion
    from tests.test_web.test_v2_plan_overview import _program

    clock(datetime(2026, 10, 11, 12, 0, tzinfo=UTC))  # воскресенье 11 октября, полдень
    program = await _program(session, config={"duration_weeks": 4})
    user.timezone = "Europe/Moscow"
    await session.commit()
    created = await v2_post(session, TG, "/api/v2/program-inclusions", {"program_id": program.id})
    assert created.status_code == 200
    row = await session.get(ProgramInclusion, created.json()["id"])
    row.started_at = datetime(2026, 10, 4, 22, 0, tzinfo=UTC)  # = пн 5 октября 01:00 в Москве
    await session.commit()

    plan_json = (await v2_get(session, TG, "/api/v2/plan")).json()["plan"]
    inclusion = next(i for i in plan_json["program_inclusions"] if i["id"] == row.id)
    # Локально старт — понедельник 5.10, сегодня — воскресенье 11.10: 6 дней — ещё первая неделя
    # (по UTC-дате старта, 4.10, было бы 7 дней — вторая).
    assert inclusion["current_week"] == 1
