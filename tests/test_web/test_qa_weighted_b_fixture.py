"""Reserved synthetic B-incident fixtures must produce the shipped course through real services."""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.models_program import ProgramInclusion, TrainingPlan, TrainingSession
from app.db.repositories.users import UserRepository
from scripts.qa.identities import QA_IDENTITIES
from scripts.qa.provision_staging_identities import RefusedError, provision_weighted_b
from tests.test_web._v2_client import v2_get, v2_post


@pytest.mark.parametrize("identity", ["qa_weighted_b", "qa_weighted_b_stop"])
async def test_reserved_fixture_starts_ten_by_five_b_with_weighted_strength(session, identity):
    telegram_id = QA_IDENTITIES[identity]
    await provision_weighted_b(session, telegram_id)
    user = await UserRepository(session).get_by_telegram_id(telegram_id)
    inclusion = (
        await session.execute(
            select(ProgramInclusion).join(TrainingPlan).where(TrainingPlan.user_id == user.id)
        )
    ).scalar_one()
    assert inclusion.progression_state["next_role"] == "B"
    assert inclusion.progression_state["sessions_completed"] == 1

    plan_response = await v2_get(session, telegram_id, "/api/v2/plan")
    assert plan_response.status_code == 200, plan_response.text
    items = plan_response.json()["plan"]["plan_items"]
    occurrence = next(row for row in items if row.get("program_slot_key") == "main")
    import uuid

    response = await v2_post(
        session,
        telegram_id,
        "/api/v2/sessions/live",
        {
            "client_session_id": str(uuid.uuid4()),
            "plan_item_ids": [occurrence["id"]],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    blocks = body["blocks"]
    assert body["course_program"]["workout_role"] == "B"
    assert body["course_program"]["inter_block_rest_seconds"] == 900
    assert blocks[0]["course_block"]["rest_seconds"] == 60
    assert blocks[1]["course_block"]["rest_seconds"] == 180
    assert Decimal(blocks[1]["course_block"]["external_load_kg"]) == Decimal(10)
    row = await session.get(TrainingSession, body["id"])
    snapshot = row.prescription_snapshot
    assert snapshot["blocks"][0]["rest_after_block_seconds"] == 900
    assert [target["rest_after_seconds"] for target in snapshot["blocks"][0]["sets"]] == [
        60
    ] * 9 + [None]
    assert [target["rest_after_seconds"] for target in snapshot["blocks"][1]["sets"]] == [
        180
    ] * 4 + [None]
    assert len(blocks[0]["targets"]) == 10
    assert [Decimal(str(t["value"])) for t in blocks[0]["targets"]] == [Decimal(5)] * 10
    assert len(blocks[1]["targets"]) == 5
    assert [Decimal(str(t["value"])) for t in blocks[1]["targets"]] == [Decimal(3)] * 5


@pytest.mark.parametrize("telegram_id", [123, 900_001, QA_IDENTITIES["qa_fresh_active"]])
async def test_incident_fixture_refuses_any_other_identity_before_io(telegram_id):
    with pytest.raises(RefusedError):
        await provision_weighted_b(None, telegram_id)
