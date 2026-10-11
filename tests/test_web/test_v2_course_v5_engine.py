"""Программа V5.6 (#305) исполняется Live Engine v2 (#306): интеграционные пути на реальном Postgres.

План движка берёт явный отдых рецепта из снимка сессии (240/30 → 900 → 180, решение владельца #306 п. 5),
завершение движка — канонический complete_session #307 (одна прогрессия V5.6, история #308 канонична),
повторное завершение и копия — без второй прогрессии; подтверждения техники/отдыха, пришедшие с явным
завершением POST …/complete, сохраняются до серверного finish_early.

Известные швы V5.6 × #306 (docs/domain/PULLUPS_V5_6.md §13) — динамический стоп B в самом движке, потолок
контрольного подхода, подтверждения после автозавершения движка — здесь не закрепляются как поведение."""

import uuid
from datetime import timedelta

from sqlalchemy import update

from app.db.models_program import TrainingSession
from app.db.repositories.training_sessions import TrainingSessionRepository
from tests.test_web._v2_client import v2_get, v2_post
from tests.test_web.test_v2_course_v5 import (  # noqa: F401 — clock — фикстура
    CONFIRMED,
    MON,
    _enrol,
    _main_occurrences,
    _pullups,
    clock,
)
from tests.test_web.test_v2_live_session_workout_start import _user

LIVE = "/api/v2/sessions/live"
WEIGHTED_INPUTS = {"e1rm_kg": "30", "load_step_kg": "0.5"}


async def _start(session, user, plan_item_id: int) -> dict:
    response = await v2_post(session, user.telegram_id, LIVE, {
        "client_session_id": str(uuid.uuid4()), "plan_item_ids": [plan_item_id], "engine_version": 2,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["engine_version"] == 2
    return body


async def _event(session, user, session_id: int, type_: str, payload: dict) -> dict:
    response = await v2_post(session, user.telegram_id, f"{LIVE}/{session_id}/events", {
        "events": [{"client_event_id": str(uuid.uuid4()), "type": type_, "payload": payload}],
    })
    assert response.status_code == 200, response.text
    return response.json()


async def _run(session, user, body: dict, values_by_block: list[list[int]], *, stop_before_last: bool = False) -> dict:
    """Ожидания — «Начать сейчас» (skip_wait), подходы — submit_result; stop_before_last — без последнего."""
    queues = [list(values) for values in values_by_block]
    total = sum(len(q) for q in queues)
    sent, response = 0, body
    while response["engine"]["state"]["status"] == "active":
        state = response["engine"]["state"]
        cursor = state["cursor"]
        if state["phase"] in ("PREP", "REST"):
            response = await _event(session, user, body["id"], "skip_wait", {"phase_seq": state["phase_seq"]})
            continue
        if stop_before_last and sent == total - 1:
            return response
        response = await _event(session, user, body["id"], "submit_result", {
            "block_index": cursor["block_index"], "set_index": cursor["set_index"], "round_index": cursor["round_index"],
            "value": queues[cursor["block_index"]].pop(0),
        })
        sent += 1
    return response


def _rests(plan: dict) -> tuple[list[list[int | None]], list[int | None]]:
    return (
        [[s["rest_after_seconds"] for s in block["sets"]] for block in plan["blocks"]],
        [block["rest_after_block_seconds"] for block in plan["blocks"]],
    )


async def _backdate(session, session_id: int, at) -> None:
    await session.execute(update(TrainingSession).where(TrainingSession.id == session_id).values(
        performed_at=at, started_at=at, completed_at=at + timedelta(minutes=50), ended_at=at + timedelta(minutes=50),
    ))
    await session.flush()


async def test_engine_plan_executes_the_prescribed_rests_240_30_900_180(session, clock):  # noqa: F811
    user = await _user(session, 305601)
    program = await _pullups(session)
    await _enrol(session, user, program, course_inputs=WEIGHTED_INPUTS)
    occurrences = await _main_occurrences(session, user)
    a_day = await _start(session, user, occurrences[0]["id"])
    a_sets, a_blocks = _rests(a_day["engine"]["plan"])
    assert a_sets == [[240, 240, 240, None], [180, 180, 180, 180, None]]  # объём A 240, сила 180
    assert a_blocks == [900, None]  # объём → сила 900, не умолчание движка 90
    assert [t["marker"] for t in a_day["blocks"][0]["targets"]] == ["working"] * 3 + ["amrap"]
    a_done = await _run(session, user, a_day, [[17, 17, 17, 18], [5] * 5])
    assert a_done["status"] == "completed"
    await _backdate(session, a_day["id"], MON)

    clock(MON + timedelta(days=3))
    b_day = await _start(session, user, occurrences[1]["id"])
    b_sets, b_blocks = _rests(b_day["engine"]["plan"])
    assert set(b_sets[0][:-1]) == {30} and b_sets[0][-1] is None  # объём B: 30 с между подходами
    assert b_sets[1] == [180, 180, 180, 180, None] and b_blocks == [900, None]


async def test_engine_completion_is_canonical_progresses_once_and_repeat_or_clone_do_not(session, clock):  # noqa: F811
    user = await _user(session, 305602)
    program = await _pullups(session)
    inclusion = await _enrol(session, user, program, course_inputs=WEIGHTED_INPUTS)
    occurrences = await _main_occurrences(session, user)
    body = await _start(session, user, occurrences[0]["id"])
    done = await _run(session, user, body, [[17, 17, 17, 18], [5] * 5])
    # Автозавершение движка — канонический complete_session #307: прогрессия V5.6 ровно одна.
    assert done["status"] == "completed" and done["engine_status"] == "completed"
    assert done["course_progression"]["program_version"] == "pullups_v5_6"
    assert [b["block_role"] for b in done["course_progression"]["blocks"]] == ["a_volume", "a_weighted_strength"]
    await session.refresh(inclusion)
    assert (inclusion.progression_state_rev, inclusion.sequence_cursor) == (1, 1)
    row = await session.get(TrainingSession, body["id"])
    await session.refresh(row)
    assert row.status.value == "completed" and row.superseded_at is None and row.engine_version == 2  # #308

    again = await v2_post(session, user.telegram_id, f"{LIVE}/{body['id']}/complete", {"abandoned": False})
    assert again.status_code == 200 and again.json()["progression_skipped_reason"] == "already_completed"
    clone = await v2_post(session, user.telegram_id, f"/api/v2/sessions/{body['id']}/clone", {
        "performed_at": (MON + timedelta(days=1)).isoformat(),
    })
    assert clone.status_code == 201, clone.text
    await session.refresh(inclusion)
    assert (inclusion.progression_state_rev, inclusion.sequence_cursor) == (1, 1)  # ни повтор, ни копия

    journal = (await v2_get(session, user.telegram_id, "/api/v2/sessions?status=completed")).json()["sessions"]
    assert sorted(c["id"] for c in journal) == sorted([body["id"], clone.json()["id"]])  # #308: по одному разу


async def test_explicit_finish_with_block_checks_saves_them_before_the_engine_finishes(session, clock):  # noqa: F811
    """POST …/complete сессии движка v2 с подтверждениями: они записаны ДО серверного finish_early (как у движка
    v1, где complete_session пишет их до прогрессии) — прогрессия завершения видит их, а не NULL."""
    user = await _user(session, 305603)
    program = await _pullups(session)
    await _enrol(session, user, program, course_inputs=WEIGHTED_INPUTS)
    occurrences = await _main_occurrences(session, user)
    body = await _start(session, user, occurrences[0]["id"])
    await _run(session, user, body, [[17, 17, 17, 18], [5] * 5], stop_before_last=True)
    response = await v2_post(session, user.telegram_id, f"{LIVE}/{body['id']}/complete", {
        "abandoned": False, "block_checks": CONFIRMED,
    })
    assert response.status_code == 200, response.text
    detail = await TrainingSessionRepository(session).get_for_user(body["id"], user.id)
    assert detail.status.value == "completed"
    assert [(b.technique_valid, b.rest_within_limit) for b in detail.blocks] == [(True, True), (True, True)]
