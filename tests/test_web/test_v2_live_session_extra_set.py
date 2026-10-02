"""«+ Ещё подход» (issue #264): подход сверх плана хранится с is_extra, батч
остаётся идемпотентным по (session_id, set_index), прогрессия его игнорирует."""

import uuid
from decimal import Decimal

from app.db.models import User
from app.db.repositories.training_sessions import SessionBlockDetail, SessionSetLogDetail
from app.domain.multi_program import MetricType
from app.services.session_log import _session_block_input_from_detail
from tests.test_web._v2_client import v2_post
from tests.test_web.test_v2_live_session import _setup_step_session


async def _start(session, user: User, plan_item_ids: list[int]) -> int:
    start = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions/live",
        payload={"client_session_id": str(uuid.uuid4()), "plan_item_ids": plan_item_ids},
    )
    return start.json()["id"]


async def test_extra_set_is_persisted_flagged_and_idempotent(session, user: User):
    _, roles, plan_item_ids = await _setup_step_session(session, user)
    session_id = await _start(session, user, [plan_item_ids["block_a"]])
    exercise_id = roles["block_a"]
    path = f"/api/v2/sessions/live/{session_id}/sets:batch"
    payload = {"sets": [
        {"set_index": 0, "exercise_id": exercise_id, "value": "10"},
        {"set_index": 1, "exercise_id": exercise_id, "value": "9", "is_extra": True},
    ]}

    first = await v2_post(session, telegram_id=user.telegram_id, path=path, payload=payload)
    again = await v2_post(session, telegram_id=user.telegram_id, path=path, payload=payload)

    assert first.status_code == 200
    assert again.status_code == 200
    logs = again.json()["blocks"][0]["set_logs"]
    assert [(log["set_number"], log["is_extra"]) for log in logs] == [(1, False), (2, True)]
    assert len(logs) == 2  # повтор батча не дублирует строку


async def test_old_client_batch_defaults_to_non_extra(session, user: User):
    _, roles, plan_item_ids = await _setup_step_session(session, user)
    session_id = await _start(session, user, [plan_item_ids["block_a"]])

    response = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/live/{session_id}/sets:batch",
        payload={"sets": [{"set_index": 0, "exercise_id": roles["block_a"], "value": "10"}]},
    )

    assert response.json()["blocks"][0]["set_logs"][0]["is_extra"] is False


def test_progression_input_excludes_extra_sets():
    """Вход прогрессии (live complete и каскад правки) строится из этого
    преобразования — extra-подходы в него не попадают."""
    block = SessionBlockDetail(
        id=1, order_index=0, exercise_id=1, complex_id=None,
        set_logs=[
            SessionSetLogDetail(
                set_number=n, is_max_set=False, metric_type=MetricType.REPS, value=Decimal(v), unit="reps",
                effort=None, note=None, is_extra=extra,
            )
            for n, v, extra in [(1, 11, False), (2, 11, False), (3, 30, True)]
        ],
    )

    sets = _session_block_input_from_detail(block).sets

    assert [s.set_number for s in sets] == [1, 2]
