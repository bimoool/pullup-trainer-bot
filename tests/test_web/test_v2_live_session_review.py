"""#257 — оценка тренировки целиком при завершении живой сессии:
POST /sessions/live/{id}/complete принимает необязательные effort (1–5) и
comment (≤1000), хранит их на TrainingSession, не затирает повтором без них."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import User
from app.db.models_program import TrainingSession
from app.db.repositories.training_sessions import TrainingSessionRepository
from app.domain.multi_program import SessionSource
from tests.test_web._v2_client import v2_get, v2_post
from tests.test_web.test_v2_live_session import _setup_step_session


async def _start(session, user: User) -> int:
    _, _, plan_item_ids = await _setup_step_session(session, user)
    start = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions/live",
        payload={
            "client_session_id": str(uuid.uuid4()),
            "plan_item_ids": [plan_item_ids["block_a"], plan_item_ids["block_b"]],
        },
    )
    return start.json()["id"]


async def _complete(session, user: User, session_id: int, **payload):
    return await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/live/{session_id}/complete", payload=payload,
    )


async def _journal_card(session, user: User, session_id: int) -> dict:
    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/sessions?status=completed")
    return next(card for card in response.json()["sessions"] if card["id"] == session_id)


async def test_complete_stores_workout_effort_and_comment(session, user: User):
    session_id = await _start(session, user)

    response = await _complete(session, user, session_id, effort="4", comment="  Тяжело, но ок  ")

    assert response.status_code == 200
    card = await _journal_card(session, user, session_id)
    assert float(card["effort"]) == 4.0
    assert card["comment"] == "Тяжело, но ок"


async def test_complete_sets_completed_at_once(session, user: User):
    """#259: completed_at ставится при завершении и не двигается повтором."""
    session_id = await _start(session, user)
    row = await session.get(TrainingSession, session_id)
    assert row.completed_at is None

    await _complete(session, user, session_id)
    await session.refresh(row)
    first = row.completed_at
    assert first is not None and abs((datetime.now(UTC) - first).total_seconds()) < 60

    await _complete(session, user, session_id)
    await session.refresh(row)
    assert row.completed_at == first


async def test_manual_session_create_sets_completed_at(session, user: User):
    row = await TrainingSessionRepository(session).create_session(
        user_id=user.id, source=SessionSource.PLAN, performed_at=datetime.now(UTC) - timedelta(days=2),
        effort=None, comment=None, blocks=[],
    )
    assert row.completed_at is not None


async def test_complete_without_review_fields_still_works(session, user: User):
    session_id = await _start(session, user)

    response = await _complete(session, user, session_id)

    assert response.status_code == 200
    card = await _journal_card(session, user, session_id)
    assert card["effort"] is None and card["comment"] is None


@pytest.mark.parametrize("payload", [
    {"effort": "0"}, {"effort": "6"}, {"effort": "-1"}, {"comment": "x" * 1001},
])
async def test_complete_rejects_invalid_review_fields(session, user: User, payload):
    session_id = await _start(session, user)

    response = await _complete(session, user, session_id, **payload)

    assert response.status_code == 422
    # сессия не завершена невалидным запросом
    ok = await _complete(session, user, session_id)
    assert ok.status_code == 200 and ok.json()["progression_skipped_reason"] != "already_completed"


async def test_comment_of_exactly_1000_chars_is_accepted(session, user: User):
    session_id = await _start(session, user)

    response = await _complete(session, user, session_id, comment="x" * 1000)

    assert response.status_code == 200


async def test_repeat_complete_without_fields_does_not_overwrite_with_nulls(session, user: User):
    session_id = await _start(session, user)
    await _complete(session, user, session_id, effort="3", comment="Нормально")

    repeat = await _complete(session, user, session_id)

    assert repeat.status_code == 200
    card = await _journal_card(session, user, session_id)
    assert float(card["effort"]) == 3.0
    assert card["comment"] == "Нормально"


async def test_repeat_complete_with_other_values_keeps_first_review(session, user: User):
    session_id = await _start(session, user)
    await _complete(session, user, session_id, effort="3", comment="Первая")

    await _complete(session, user, session_id, effort="5", comment="Вторая")

    card = await _journal_card(session, user, session_id)
    assert float(card["effort"]) == 3.0
    assert card["comment"] == "Первая"


async def test_repeat_complete_fills_only_missing_review(session, user: User):
    """Первый (потерянный) complete ушёл без оценки, повтор из офлайн-очереди — с ней."""
    session_id = await _start(session, user)
    await _complete(session, user, session_id)

    await _complete(session, user, session_id, effort="2", comment="Лёгкая")

    card = await _journal_card(session, user, session_id)
    assert float(card["effort"]) == 2.0
    assert card["comment"] == "Лёгкая"
