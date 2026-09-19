"""GET /api/v2/plan (issue #165, волна 3)."""

from app.db.models import User
from tests.test_web._v2_client import v2_get


async def test_get_plan_for_unknown_telegram_id_is_404(session):
    response = await v2_get(session, telegram_id=60101, path="/api/v2/plan")
    assert response.status_code == 404


async def test_get_plan_before_any_inclusion_is_null_not_autocreated(session, user: User):
    """GET не создаёт TrainingPlan молча (побочный эффект на чтении) —
    план появляется только после POST /program-inclusions или
    POST /plan-items, см. докстринг PlanResponse."""
    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/plan")

    assert response.status_code == 200
    assert response.json()["plan"] is None
