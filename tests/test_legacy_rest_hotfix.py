"""P0 regression: legacy STEP's real snapshot -> engine conversion retains A/B rest."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.domain.multi_program import MetricType
from app.services.live_session import LiveSessionService, engine_plan_for


async def _patch_for(user, inclusion):
    service = object.__new__(LiveSessionService)
    service._plans = SimpleNamespace(get_inclusion_by_id=AsyncMock(return_value=inclusion))
    return await service._legacy_step_rest_patch(2, user)


@pytest.mark.parametrize("preferences,expected", [
    ({}, (240, 180, 900)),
    ({"rest_seconds_block_a": 300, "rest_seconds_block_b": 210, "big_break_seconds": 600}, (300, 210, 600)),
])
async def test_new_legacy_start_freezes_preferences_in_engine_recipe(preferences, expected):
    prefs = preferences
    user = SimpleNamespace(**{key: prefs.get(key) for key in ('rest_seconds_block_a', 'rest_seconds_block_b', 'big_break_seconds')})
    inclusion = SimpleNamespace(snapshot={'progression_strategy_type': 'step', 'exercises': [
        {'exercise_id': 10, 'role': 'block_a'}, {'exercise_id': 20, 'role': 'block_b'}]}, progression_state={})
    snapshot = {'synthesized': True, 'blocks': [
        {'exercise_id': exercise_id, 'sets': [{'rest_after_seconds': None}] * 2}
        for exercise_id in (10, 20)
    ]}
    # independent sets, like the actual serialized synthesized prescription
    snapshot = deepcopy(snapshot)
    for block in snapshot['blocks']:
        block['sets'] = [dict(item) for item in block['sets']]
    patch = await _patch_for(user, inclusion)
    assert patch is not None
    patch(snapshot)
    detail = SimpleNamespace(prescription_snapshot=snapshot, workout_snapshot=None, blocks=[
        SimpleNamespace(exercise_id=exercise_id, set_targets=[SimpleNamespace(metric_type=MetricType.REPS, value=5, is_max_set=False)] * 2)
        for exercise_id in (10, 20)
    ])
    plan = engine_plan_for(detail)
    a, b, gap = expected
    assert plan['blocks'][0]['sets'][0]['rest_after_seconds'] == a
    assert plan['blocks'][1]['sets'][0]['rest_after_seconds'] == b
    assert plan['blocks'][0]['rest_after_block_seconds'] == gap
    assert plan['blocks'][1]['rest_after_block_seconds'] is None
    assert all(block['sets'][-1]['rest_after_seconds'] is None for block in plan['blocks'])


async def test_v5_recipe_is_not_changed():
    inclusion = SimpleNamespace(progression_state={'program_version': 'pullups_v5_6'}, snapshot={})
    assert await _patch_for(SimpleNamespace(), inclusion) is None
