"""#354: Builder edits preserve active v2 recipes and affect subsequent starts."""

import copy

from sqlalchemy import select

from app.db.models_program import TrainingSession
from tests.test_web import test_v2_live_engine as engine_api
from tests.test_web._v2_client import v2_get, v2_patch, v2_post
from tests.test_web.test_v2_live_session_workout_start import _user

clock = engine_api.clock


async def test_builder_edit_keeps_active_v2_recipe_and_next_start_uses_new_version(session, clock):
    """#354: a template edit affects the next start, never the already issued recipe."""
    user = await _user(session, 306092)

    async def body(response):
        assert response.status_code == 200, response.text
        return response.json()

    async def stored_recipe(session_id):
        # Read actual columns: ORM identity-map caching must not hide a changed stored recipe.
        return copy.deepcopy(
            (
                await session.execute(
                    select(
                        TrainingSession.workout_snapshot,
                        TrainingSession.prescription_snapshot,
                        TrainingSession.engine_plan,
                        TrainingSession.workout_definition_version_id,
                    ).where(TrainingSession.id == session_id)
                )
            ).one()
        )

    old_exercise = await body(
        await v2_post(session, user.telegram_id, "/api/v2/exercises", {"name": "Original"})
    )
    new_exercise = await body(
        await v2_post(session, user.telegram_id, "/api/v2/exercises", {"name": "Replacement"})
    )
    workout = await body(
        await v2_post(session, user.telegram_id, "/api/v2/workouts", {"title": "Original workout"})
    )
    workout_id = workout["id"]
    item = await body(
        await v2_post(
            session,
            user.telegram_id,
            f"/api/v2/workouts/{workout_id}/items",
            {"exercise_id": old_exercise["id"], "protocol": engine_api.REPS_2x8_R30},
        )
    )
    started = await engine_api._start(session, user, clock, workout_id=workout_id)
    before = await stored_recipe(started["id"])
    old_plan = copy.deepcopy(started["engine"]["plan"])
    assert old_plan["blocks"][0]["sets"][0]["target"] == 8
    assert old_plan["blocks"][0]["sets"][0]["rest_after_seconds"] == 30

    changed_protocol = {
        "type": "reps_sets",
        "rest_seconds": 90,
        "prescription": {"source": "static", "sets": 3, "reps": 12},
    }
    await body(
        await v2_patch(
            session,
            user.telegram_id,
            f"/api/v2/workouts/{workout_id}/items/{item['id']}",
            {"exercise_id": new_exercise["id"], "protocol": changed_protocol},
        )
    )
    await body(
        await v2_patch(
            session, user.telegram_id, f"/api/v2/workouts/{workout_id}", {"title": "Edited workout"}
        )
    )
    current = await body(await v2_get(session, user.telegram_id, f"/api/v2/workouts/{workout_id}"))
    assert current["title"] == "Edited workout" and current["current_version"]["version_no"] == 3
    assert current["items"][0]["exercise_id"] == new_exercise["id"]

    reopened = await engine_api._active(session, user)
    assert reopened["id"] == started["id"] and reopened["title"] == "Original workout"
    assert reopened["blocks"][0]["exercise_id"] == old_exercise["id"]
    assert reopened["engine"]["plan"] == old_plan
    assert await stored_recipe(started["id"]) == before

    await engine_api._post_events(session, user, started["id"], engine_api._event("cancel"))
    assert await engine_api._active(session, user) is None
    again = await engine_api._start(session, user, clock, workout_id=workout_id)
    assert again["id"] != started["id"] and again["title"] == "Edited workout"
    assert again["blocks"][0]["exercise_id"] == new_exercise["id"]
    new_sets = again["engine"]["plan"]["blocks"][0]["sets"]
    assert len(new_sets) == 3 and [set_["target"] for set_ in new_sets] == [12, 12, 12]
    assert new_sets[0]["rest_after_seconds"] == 90
    assert await stored_recipe(started["id"]) == before
