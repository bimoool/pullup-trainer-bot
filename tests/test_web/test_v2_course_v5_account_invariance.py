"""Ordinary accounts with equal V5.6 inputs/history have equal calculations.

Legacy versions and administrator access exemptions are separate contracts: this
trace deliberately uses two non-admin accounts on the same explicit V5.6 rule.
HTTP helpers mutate global dependency overrides, so every request is sequential.
"""

import uuid
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.config import settings
from app.db.models_program import TrainingSession
from app.services import live_engine, live_session, program_inclusion
from app.web import routes_v2, routes_v2_course
from tests.test_web import test_v2_live_session_workout_start as account_helpers
from tests.test_web._v2_client import v2_get, v2_post
from tests.test_web.test_v2_course_v5 import (
    MON,
    WEIGHTED_INPUTS,
    _enrol,
    _main_occurrences,
    _pullups,
)
from tests.test_web.test_v2_course_v5_engine import LIVE, VALID, _events, _run, _start
from tests.test_web.test_v2_live_session_workout_start import _user


@pytest.fixture
def fixed_clock(monkeypatch):
    class Clock(datetime):
        current = MON

        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz) if tz else cls.current.replace(tzinfo=None)

    for module in (live_session, program_inclusion, routes_v2, routes_v2_course, account_helpers):
        monkeypatch.setattr(module, "datetime", Clock)
    for module in (live_session, live_engine, routes_v2):
        monkeypatch.setattr(module, "_utcnow", lambda: Clock.current)

    def advance(now):
        Clock.current = now

    return advance


async def _course(session, user, inclusion):
    response = await v2_get(
        session, user.telegram_id, f"/api/v2/program-inclusions/{inclusion.id}/course"
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _state(session, inclusion):
    await session.refresh(inclusion)
    return deepcopy(
        (inclusion.progression_state, inclusion.progression_state_rev, inclusion.sequence_cursor)
    )


async def _frozen(session, body, inclusion):
    row = await session.get(TrainingSession, body["id"])
    await session.refresh(row)
    snapshot = deepcopy(row.prescription_snapshot)
    # These are the only account-local references in the frozen prescription.
    # Keep all inputs, weights, versions, revisions, and resolved timestamps.
    provenance = snapshot["provenance"]
    assert provenance["program_inclusion_id"] == inclusion.id
    provenance["program_inclusion_id"] = "account-inclusion"
    return snapshot, deepcopy(row.engine_plan)


async def _finish(session, user, body):
    confirm = await _run(session, user, body, [[17, 17, 17, 19], [5] * 5])
    assert confirm["engine"]["state"]["phase"] == "CONFIRM"
    event = {
        "client_event_id": str(uuid.uuid4()),
        "type": "confirm_blocks",
        "payload": {"checks": VALID},
    }
    done = await _events(session, user, body["id"], [event])
    assert done["status"] == "completed"
    duplicate = await _events(session, user, body["id"], [event])
    assert duplicate["status"] == "completed"
    again = await v2_post(
        session, user.telegram_id, f"{LIVE}/{body['id']}/complete", {"abandoned": False}
    )
    assert again.status_code == 200, again.text
    assert again.json()["progression_skipped_reason"] == "already_completed"
    return done["course_progression"]


async def test_equal_accounts_calculate_equally_and_progress_in_isolation(session, fixed_clock):
    program = await _pullups(session)
    accounts = [await _user(session, telegram_id) for telegram_id in (383001, 383002, 383003)]
    assert len({user.id for user in accounts}) == 3
    assert all(not settings.is_admin(user.telegram_id) for user in accounts)
    inclusions = [
        await _enrol(
            session, user, program, program_version="pullups_v5_6", course_inputs=WEIGHTED_INPUTS
        )
        for user in accounts
    ]
    a, b, _observer = accounts
    ia, ib, io = inclusions
    initial = await _state(session, ib)
    observer_state = await _state(session, io)
    assert await _state(session, ia) == initial
    course_a, course_b = await _course(session, a, ia), await _course(session, b, ib)
    assert course_a == course_b
    assert course_a["next_workout"]["blocks"][0]["display"] == "17/17/17/17+"
    occurrences_a = await _main_occurrences(session, a)
    occurrences_b = await _main_occurrences(session, b)
    started_a = await _start(session, a, occurrences_a[0]["id"])
    frozen_a = await _frozen(session, started_a, ia)
    progression_a = await _finish(session, a, started_a)
    # A's entire trace (including duplicate confirmations/completion) cannot
    # advance B, alter B's prescription, or touch an unrelated third account.
    assert await _state(session, ib) == initial
    assert await _course(session, b, ib) == course_b
    assert await _state(session, io) == observer_state
    after_a = await _state(session, ia)
    assert after_a[1] == initial[1] + 1
    assert after_a[0]["volume_a"]["targets"] == [18, 17, 17, 17]
    assert after_a[0]["strength_a"]["load_kg"] == "6.5"
    assert progression_a["blocks"][0]["fact_volume"] == 70

    started_b = await _start(session, b, occurrences_b[0]["id"])
    assert started_a["course_program"] == started_b["course_program"]
    assert frozen_a == await _frozen(session, started_b, ib)
    assert await _finish(session, b, started_b) == progression_a
    assert await _state(session, ib) == after_a
    assert await _state(session, ia) == after_a
    assert await _frozen(session, started_a, ia) == frozen_a
    assert await _state(session, io) == observer_state

    fixed_clock(MON + timedelta(days=3))
    next_a = await _start(session, a, occurrences_a[1]["id"])
    next_b = await _start(session, b, occurrences_b[1]["id"])
    assert next_a["course_program"] == next_b["course_program"]
    assert await _frozen(session, next_a, ia) == await _frozen(session, next_b, ib)
    volume, strength = next_a["blocks"]
    assert len(volume["targets"]) == 15
    assert {Decimal(target["value"]) for target in volume["targets"]} == {5}
    assert [Decimal(target["value"]) for target in strength["targets"]] == [3] * 5
    assert strength["course_block"]["external_load_kg"] == "10"
    assert await _state(session, io) == observer_state
