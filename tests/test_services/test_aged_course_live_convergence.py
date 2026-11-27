"""Legacy course completion during the Wave 4 plan cutover (#309)."""

import copy
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.db.models_program import PlanItem, TrainingSession
from app.db.repositories import training_sessions
from app.domain.constants import EquipmentType
from app.services import live_session
from app.services.plan_convergence import PlanConvergenceService
from app.web import routes_v2
from tests.test_services.test_plan_convergence_v2 import _aged_profile, _credits
from tests.test_web import _premium
from tests.test_web._v2_client import v2_get, v2_post
from tests.test_web.test_v2_live_phase_back import _to_rest_of_set
from tests.test_web.test_v2_training_session_v2 import _card


@pytest.mark.parametrize(
    "started_at,expected_week",
    [
        pytest.param(datetime(2026, 10, 31, 23, 59, 55, tzinfo=UTC), 4, id="month-boundary"),
        pytest.param(datetime(2026, 11, 1, 23, 59, 55, tzinfo=UTC), 5, id="week-boundary"),
    ],
)
async def test_legacy_course_start_survives_plan_convergence(
    session, monkeypatch, started_at, expected_week
):
    now = started_at

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz is not None else now.replace(tzinfo=None)

    for module in (live_session, training_sessions, routes_v2, _premium):
        monkeypatch.setattr(module, "datetime", FixedDatetime)

    aged = await _aged_profile(session, plan_created=datetime(2026, 10, 5, 9, tzinfo=UTC))
    user = aged["user"]
    plan = aged["plan"]
    inclusion = aged["inclusion"]
    # The plan-only fixture omits equipment fields required by legacy STEP progression.
    state = copy.deepcopy(inclusion.progression_state)
    for role in ("block_a", "block_b"):
        state[role].update(
            equipment_type=EquipmentType.BODYWEIGHT.value,
            equipment_value=None,
            equipment_item_id=None,
        )
    inclusion.progression_state = state
    revision = inclusion.progression_state_rev
    await session.commit()
    week = aged["weeks"][4]
    aggregate_ids = [item.id for item in aged["aggregates"][4]]
    url = "/api/v2/sessions/live"
    request = {"client_session_id": str(uuid.uuid4()), "plan_item_ids": aggregate_ids}
    response = await v2_post(session, user.telegram_id, url, request)
    assert response.status_code == 200, response.text
    active = response.json()
    assert active["engine_version"] == 1
    assert len(active["blocks"]) == 2
    session_id = active["id"]
    assert (await _credits(session, user.id))[session_id] == aggregate_ids[0]
    first_exercise = active["blocks"][0]["exercise_id"]
    rest = await _to_rest_of_set(session, user, session_id, first_exercise)
    assert rest["phase"]["name"] == "rest"
    row = await session.get(TrainingSession, session_id)
    snapshot = copy.deepcopy(row.prescription_snapshot)
    assert snapshot is not None and row.performed_at == started_at

    now += timedelta(seconds=10)
    convergence = PlanConvergenceService(session)
    week_after, changes = await convergence.converge_user_plan(
        training_plan_id=plan.id, today=now.date()
    )
    assert week_after.week_number == expected_week and changes.mutations > 0
    await session.commit()
    credits = await _credits(session, user.id)
    credit = await session.get(PlanItem, credits[session_id])
    assert credit is not None and credit.program_inclusion_id == inclusion.id
    if expected_week == 4:
        assert (credit.origin_plan_week_id, credit.program_slot_key, credit.occurrence_index) == (
            week.id,
            "main",
            3,
        )
        assert len({credits[x] for x in [*aged["current_sessions"], session_id]}) == 3
    else:
        assert (credit.id, credit.plan_week_id, credit.legacy_aggregate) == (
            aggregate_ids[0],
            week.id,
            True,
        )
    _, again = await convergence.converge_user_plan(training_plan_id=plan.id, today=now.date())
    assert again.mutations == 0, again.as_dict()
    await session.commit()

    replay = await v2_post(session, user.telegram_id, url, request)
    assert replay.status_code == 200 and replay.json()["id"] == session_id, replay.text
    resumed = await v2_get(session, user.telegram_id, f"{url}/active")
    assert resumed.status_code == 200, resumed.text
    for key in ("id", "engine_version", "phase", "phase_index", "blocks"):
        assert resumed.json()["session"][key] == rest[key], key

    targets = [
        (block["exercise_id"], "9" if target["is_max_set"] else target["value"])
        for block in active["blocks"]
        for target in block["targets"]
    ]
    batch = {
        "sets": [
            {"set_index": index, "exercise_id": exercise_id, "value": value}
            for index, (exercise_id, value) in enumerate(targets[1:], start=1)
        ]
    }
    saved = await v2_post(session, user.telegram_id, f"{url}/{session_id}/sets:batch", batch)
    assert saved.status_code == 200, saved.text
    for _ in range(2):
        done = await v2_post(
            session, user.telegram_id, f"{url}/{session_id}/complete", {"abandoned": False}
        )
        assert done.status_code == 200 and done.json()["status"] == "completed", done.text
    await session.refresh(inclusion)
    assert inclusion.progression_state_rev == revision + 1
    card = await _card(session, user, session_id)
    assert card["prescription_snapshot"] == snapshot and card["plan_item_id"] == credit.id
    logs = [log for block in card["blocks"] for log in block["set_logs"]]
    assert [Decimal(log["value"]) for log in logs] == [
        Decimal(9),
        *(Decimal(value) for _, value in targets[1:]),
    ]
    assert await _credits(session, user.id) == credits
