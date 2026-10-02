"""POST /api/v2/sessions/live/{id}/phase/back (#292) — «Предыдущий подход»:
фаза возвращается на go предыдущего подхода, SetLog не удаляется, повторный
батч с тем же set_index перезаписывает строку."""

import uuid

from app.db.models import User
from app.domain.live_session import PhaseState, SessionPhaseName, previous_phase
from tests.test_web._v2_client import v2_get, v2_post
from tests.test_web.test_v2_live_session import _setup_step_session


async def _start(session, user: User) -> tuple[int, int]:
    _, roles, plan_item_ids = await _setup_step_session(session, user)
    start = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions/live",
        payload={"client_session_id": str(uuid.uuid4()), "plan_item_ids": [plan_item_ids["block_a"]]},
    )
    return start.json()["id"], roles["block_a"]


async def _next(session, user: User, session_id: int, index: int) -> dict:
    response = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/live/{session_id}/phase/next",
        payload={"expected_phase_index": index},
    )
    assert response.status_code == 200
    return response.json()


async def _back(session, user: User, session_id: int, index: int):
    return await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/live/{session_id}/phase/back",
        payload={"expected_phase_index": index},
    )


async def _log(session, user: User, session_id: int, exercise_id: int, set_index: int, value: str) -> dict:
    response = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/live/{session_id}/sets:batch",
        payload={"sets": [{"set_index": set_index, "exercise_id": exercise_id, "value": value}]},
    )
    assert response.status_code == 200
    return response.json()


async def _to_rest_of_set(session, user: User, session_id: int, exercise_id: int) -> dict:
    """get_ready(1) -> go(1) -> лог подхода 1 -> rest(1)."""
    body = await _next(session, user, session_id, 0)  # go(1)
    await _log(session, user, session_id, exercise_id, 0, "9")
    return await _next(session, user, session_id, body["phase_index"])  # rest(1)


def test_previous_phase_domain_table():
    def state(name, set_number):
        return PhaseState(phase_name=name, block_index=0, set_number=set_number, ends_at_offset_seconds=None)

    assert previous_phase(state(SessionPhaseName.REST, 2)) == state(SessionPhaseName.GO, 2)
    assert previous_phase(state(SessionPhaseName.GET_READY, 3)) == state(SessionPhaseName.GO, 2)
    assert previous_phase(state(SessionPhaseName.GO, 2)) == state(SessionPhaseName.GO, 1)
    assert previous_phase(state(SessionPhaseName.DONE, 3)) == state(SessionPhaseName.GO, 3)
    assert previous_phase(state(SessionPhaseName.GET_READY, 1)) is None
    assert previous_phase(state(SessionPhaseName.GO, 1)) is None


async def test_back_from_rest_reopens_same_set_and_keeps_log(session, user: User):
    session_id, exercise_id = await _start(session, user)
    rest = await _to_rest_of_set(session, user, session_id, exercise_id)
    assert rest["phase"]["name"] == "rest"

    response = await _back(session, user, session_id, rest["phase_index"])

    assert response.status_code == 200
    body = response.json()
    assert body["phase"]["name"] == "go"
    assert body["phase"]["ends_at"] is None
    assert body["current_set_number"] == 1
    assert body["phase_index"] == rest["phase_index"] + 1  # монотонно растёт
    logs = body["blocks"][0]["set_logs"]
    assert [(log["set_number"], log["value"], log["set_index"]) for log in logs] == [(1, "9.00", 0)]


async def test_relog_after_back_overwrites_same_row_no_duplicate(session, user: User):
    session_id, exercise_id = await _start(session, user)
    rest = await _to_rest_of_set(session, user, session_id, exercise_id)
    back = (await _back(session, user, session_id, rest["phase_index"])).json()

    body = await _log(session, user, session_id, exercise_id, 0, "12")  # тот же set_index

    logs = body["blocks"][0]["set_logs"]
    assert [(log["set_number"], log["value"]) for log in logs] == [(1, "12.00")]
    forward = await _next(session, user, session_id, back["phase_index"])
    assert forward["phase"]["name"] == "rest"  # дальше — как обычно


async def test_back_from_get_ready_goes_to_previous_set(session, user: User):
    session_id, exercise_id = await _start(session, user)
    rest = await _to_rest_of_set(session, user, session_id, exercise_id)
    ready = await _next(session, user, session_id, rest["phase_index"])  # get_ready(2)
    assert (ready["phase"]["name"], ready["current_set_number"]) == ("get_ready", 2)

    body = (await _back(session, user, session_id, ready["phase_index"])).json()

    assert (body["phase"]["name"], body["current_set_number"]) == ("go", 1)
    assert len(body["blocks"][0]["set_logs"]) == 1


async def test_back_at_first_set_is_409(session, user: User):
    session_id, _ = await _start(session, user)  # get_ready(1)

    response = await _back(session, user, session_id, 0)

    assert response.status_code == 409
    assert response.json()["detail"] == "no_previous_set"


async def test_back_with_stale_phase_index_is_409_and_changes_nothing(session, user: User):
    session_id, exercise_id = await _start(session, user)
    rest = await _to_rest_of_set(session, user, session_id, exercise_id)

    stale = await _back(session, user, session_id, rest["phase_index"] - 1)
    assert stale.status_code == 409
    assert stale.json()["detail"] == "stale_phase"

    active = (await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/sessions/live/active")).json()
    assert active["session"]["phase"]["name"] == "rest"
    assert active["session"]["phase_index"] == rest["phase_index"]


async def test_back_retry_is_idempotent_second_call_409(session, user: User):
    session_id, exercise_id = await _start(session, user)
    rest = await _to_rest_of_set(session, user, session_id, exercise_id)
    first = await _back(session, user, session_id, rest["phase_index"])
    second = await _back(session, user, session_id, rest["phase_index"])  # ретрай/двойной тап

    assert first.status_code == 200
    assert second.status_code == 409
    active = (await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/sessions/live/active")).json()
    assert active["session"]["phase_index"] == first.json()["phase_index"]


async def test_queued_phase_next_after_back_is_noop(session, user: User):
    """Старый phase/next из офлайн-очереди (индекс до back) не двигает фазу."""
    session_id, exercise_id = await _start(session, user)
    rest = await _to_rest_of_set(session, user, session_id, exercise_id)
    await _back(session, user, session_id, rest["phase_index"])

    body = await _next(session, user, session_id, rest["phase_index"])

    assert body["phase"]["name"] == "go"


async def test_back_foreign_and_unknown_session_is_404(session, user: User):
    other = User(telegram_id=99999981, username="back_other")
    session.add(other)
    await session.flush()
    session_id, exercise_id = await _start(session, user)
    rest = await _to_rest_of_set(session, user, session_id, exercise_id)

    foreign = await _back(session, other, session_id, rest["phase_index"])
    unknown = await _back(session, user, 999999, 0)

    assert foreign.status_code == 404
    assert unknown.status_code == 404


async def test_back_on_completed_session_is_409(session, user: User):
    session_id, exercise_id = await _start(session, user)
    rest = await _to_rest_of_set(session, user, session_id, exercise_id)
    done = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/live/{session_id}/complete",
        payload={"abandoned": True},
    )
    assert done.status_code == 200

    response = await _back(session, user, session_id, rest["phase_index"])

    assert response.status_code == 409
    assert response.json()["detail"] == "not_active"
