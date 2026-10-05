"""Ревью wave 13: у пользователя западнее UTC план создан по UTC-дате «завтра» — его локальная неделя
раньше недели создания плана (week_number <= 0). Планы/копирование/перенос не должны ломаться."""

from datetime import UTC, date, datetime

from app.db.models_program import TrainingPlan
from app.web import routes_v2
from tests.test_web._v2_client import v2_get, v2_post

TG = 1001
NOW = datetime(2026, 10, 5, 2, 0, tzinfo=UTC)  # понедельник 02:00 UTC = воскресенье 19:00 в Лос-Анджелесе


async def test_plan_for_user_whose_local_week_precedes_plan_creation(session, user, monkeypatch):
    monkeypatch.setattr(routes_v2, "_utcnow", lambda: NOW)
    user.timezone = "America/Los_Angeles"
    session.add(TrainingPlan(user_id=user.id, created_at=NOW))
    await session.commit()

    plan = await v2_get(session, TG, "/api/v2/plan")
    assert plan.status_code == 200, plan.text
    body = plan.json()["plan"]
    assert body["today"] == date(2026, 10, 4).isoformat()
    week = next(w for w in body["plan_weeks"] if w["id"] == body["current_week_id"])
    assert week["start_date"] == "2026-09-28"

    nxt = await v2_post(session, TG, "/api/v2/plan/weeks", {"week_number": week["week_number"] + 1})
    assert nxt.status_code == 200, nxt.text
    copied = await v2_post(session, TG, f"/api/v2/plan/weeks/{week['id']}/copy-to-next", {})
    assert copied.status_code == 200, copied.text
    assert copied.json()["target_week"]["id"] == nxt.json()["id"]
