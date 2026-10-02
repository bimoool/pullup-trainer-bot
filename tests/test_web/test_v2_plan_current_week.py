"""#283 — GET /api/v2/plan отдаёт current_week_id (текущая неделя, не «последняя
в списке»): после #275 в списке плана есть будущие недели."""

from tests.test_web._v2_client import v2_get, v2_post

TG = 1001


async def test_current_week_id_is_not_the_last_week_after_future_weeks(session, user):
    from datetime import UTC, datetime

    from app.db.models_program import TrainingPlan

    session.add(TrainingPlan(user_id=user.id, created_at=datetime.now(UTC)))
    await session.commit()

    first = (await v2_get(session, TG, "/api/v2/plan")).json()["plan"]
    current_id = first["current_week_id"]
    assert current_id is not None
    assert [w["id"] for w in first["plan_weeks"]] == [current_id]

    future = await v2_post(session, TG, "/api/v2/plan/weeks", {"week_number": first["plan_weeks"][0]["week_number"] + 2})
    assert future.status_code == 200

    plan_json = (await v2_get(session, TG, "/api/v2/plan")).json()["plan"]
    assert plan_json["plan_weeks"][-1]["id"] == future.json()["id"]  # последняя — будущая
    assert plan_json["current_week_id"] == current_id  # а текущая прежняя
