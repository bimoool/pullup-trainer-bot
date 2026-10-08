"""WorkoutDefinition v2 через API (issue #303): Detail/каталог показывают рецепт текущей версии
одним describe(); Builder-правки создают версии идемпотентно; превью — 422 на невалидное;
подписи упражнений и категорий — никогда не slug (E1, E3)."""

import re

from sqlalchemy import text

from app.db.migrations._frozen.b7d2e9f4a1c3_backfill import run_backfill
from tests.test_web._v2_client import v2_delete, v2_get, v2_patch, v2_post
from tests.test_web.test_v2_system_content import _user, ship_system_content

SLUG = re.compile(r"^[a-z_]+$")
W_SEQUENCE = "5-4-3-2-1-2-3-4-5-4-3-2-1-2-3-4-5"


async def _ship_v2(session) -> None:
    """Сид a4c8e1f7b2d9 + бэкфилл b7d2e9f4a1c3 — тот же код, что `alembic upgrade head`."""
    await ship_system_content(session)
    await session.run_sync(lambda sync_session: run_backfill(sync_session.connection()))


async def _catalog(session, user) -> dict[str, dict]:
    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/workouts/catalog")
    assert response.status_code == 200
    return {w["title"]: w for w in response.json()["workouts"]}


async def test_w_ladder_detail_and_catalog_show_explicit_sequence(session):
    await _ship_v2(session)
    user = await _user(session)
    ladder = (await _catalog(session, user))["W-лесенка"]
    assert ladder["current_version"]["version_no"] == 2
    (block,) = ladder["prescription"]
    assert block["description"] == W_SEQUENCE
    assert block["description"] != "17 × 3"
    assert block["rest_description"] == "отдых 0:10"
    assert block["total_target_reps"] == 53
    assert [s["target_reps"] for s in block["sets"]] == [5, 4, 3, 2, 1, 2, 3, 4, 5, 4, 3, 2, 1, 2, 3, 4, 5]
    assert block["exercise"]["display_name"] == "Подтягивания"

    detail = await v2_get(session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{ladder['id']}")
    assert detail.status_code == 200
    assert detail.json()["prescription"][0]["description"] == W_SEQUENCE
    # V1-голова не изменена (legacy-представление читаемо как прежде)
    assert detail.json()["items"][0]["protocol"]["prescription"] == {"source": "static", "sets": 17, "reps": 3}


async def test_maximum_and_three_minutes_reauthored(session):
    await _ship_v2(session)
    user = await _user(session)
    catalog = await _catalog(session, user)
    (maximum,) = catalog["Максимум подтягиваний"]["prescription"]
    assert maximum["description"] == "Максимум × 4"
    assert maximum["rest_description"] == "отдых 3:00 → 2:00 → 1:00"
    assert [s["target_reps"] for s in maximum["sets"]] == [None, None, None, None]
    assert [s["rest_after_seconds"] for s in maximum["sets"]] == [180, 120, 60, None]
    (interval,) = catalog["3 минуты подтягиваний"]["prescription"]
    assert interval["interval"] == {"work_seconds": 10, "rest_seconds": 20, "rounds": 6, "record_reps_per_round": True}
    assert interval["description"] == "6 × (0:10 работа / 0:20 отдых)"
    (volume,) = catalog["Объём ×5"]["prescription"]
    assert volume["description"] == "5 × 8"
    assert catalog["Объём ×5"]["current_version"]["version_no"] == 1


async def test_builder_edits_version_idempotently(session, user):
    created = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/workouts", payload={"title": "Моя"})
    workout_id = created.json()["id"]
    assert created.json()["current_version"] is None  # пустая тренировка — версии нет

    exercise = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/exercises", payload={"name": "Узкий хват"})
    protocol = {"type": "reps_sets", "prescription": {"source": "static", "sets": 3, "reps": 10}, "rest_seconds": 90}
    item = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}/items",
        payload={"exercise_id": exercise.json()["id"], "protocol": protocol},
    )
    assert item.status_code == 200
    detail = (await v2_get(session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}")).json()
    assert detail["current_version"]["version_no"] == 1
    assert detail["prescription"][0]["description"] == "3 × 10"
    assert detail["prescription"][0]["exercise"]["display_name"] == "Узкий хват"
    first_hash = detail["current_version"]["content_hash"]

    # тот же протокол ещё раз — содержимое не изменилось, версии нет
    await v2_patch(
        session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}/items/{item.json()['id']}",
        payload={"protocol": protocol},
    )
    same = (await v2_get(session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}")).json()
    assert same["current_version"]["version_no"] == 1 and same["current_version"]["content_hash"] == first_hash

    changed_protocol = {**protocol, "prescription": {"source": "static", "sets": 4, "reps": 3}}
    await v2_patch(
        session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}/items/{item.json()['id']}",
        payload={"protocol": changed_protocol},
    )
    changed = (await v2_get(session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}")).json()
    assert changed["current_version"]["version_no"] == 2
    assert changed["prescription"][0]["description"] == "4 × 3"
    versions = (await session.execute(
        text("SELECT version_no FROM workout_definition_versions WHERE workout_definition_id = :id ORDER BY 1"),
        {"id": workout_id},
    )).scalars().all()
    assert versions == [1, 2]

    renamed = await v2_patch(
        session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}", payload={"title": "Новая"},
    )
    assert renamed.status_code == 200
    after_rename = (await v2_get(session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}")).json()
    assert after_rename["current_version"]["version_no"] == 3

    deleted = await v2_delete(
        session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}/items/{item.json()['id']}",
    )
    assert deleted.status_code == 204
    emptied = (await v2_get(session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}")).json()
    assert emptied["current_version"] is None and emptied["prescription"] is None


async def test_preview_normalizes_describes_and_rejects_with_422(session, user):
    exercise = (await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/exercises", payload={"name": "Моё"},
    )).json()
    ladder = [{"kind": "reps", "target_reps": r, "rest_after_seconds": 10} for r in [5, 4, 3, 2, 1, 2, 3, 4, 5, 4, 3, 2, 1, 2, 3, 4, 5]]
    del ladder[-1]["rest_after_seconds"]
    ok = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/workouts/preview", payload={"content": {
        "title": "W", "blocks": [{"key": "A", "exercise_id": exercise["id"], "sets": ladder}],
    }})
    assert ok.status_code == 200
    assert ok.json()["prescription"][0]["description"] == W_SEQUENCE
    assert len(ok.json()["content"]["blocks"][0]["sets"]) == 17

    flat = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/workouts/preview", payload={"content": {
        "title": "W", "blocks": [{"key": "A", "exercise_id": exercise["id"], "sets": 17, "reps": 3, "rest_seconds": 10}],
    }})
    assert flat.json()["prescription"][0]["description"] == "17 × 3"
    assert flat.json()["content_hash"] != ok.json()["content_hash"]

    for content, code in (
        ({"title": "T", "blocks": [{"key": "A", "exercise_id": exercise["id"], "sets": [{"kind": "max_reps", "target_reps": 0}]}]}, "W2"),
        ({"title": "T", "sets": 3, "blocks": []}, "W1"),
        ({"title": "T", "blocks": [{"key": "A", "exercise_id": 999999, "sets": 1, "reps": 1}]}, "W6"),
        ({"title": "T", "blocks": [{"key": "A", "exercise_id": exercise["id"], "sets": [
            {"kind": "reps", "target_reps": 3, "rest_after_seconds": 60}]}]}, "W4"),
    ):
        bad = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/workouts/preview", payload={"content": content})
        assert bad.status_code == 422, content
        assert bad.json()["detail"]["code"] == code


async def test_exercise_labels_are_never_slugs(session, user):
    await _ship_v2(session)
    created = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/exercises", payload={"name": "Моё упр"})
    assert created.status_code == 200
    body = created.json()
    assert body["category"] == "Мои упражнения"
    assert body["category_ref"]["display_name"] == "Мои упражнения"
    assert body["display_name"] == "Моё упр"

    listed = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/exercises")
    assert listed.status_code == 200
    for exercise in listed.json()["exercises"]:
        for label in (exercise["name"], exercise["display_name"], exercise["category"], exercise["subcategory"]):
            assert label is None or not SLUG.match(label), exercise
        if exercise["category_ref"] is not None:
            assert not SLUG.match(exercise["category_ref"]["display_name"])

    catalog = await _catalog(session, user)
    for workout in catalog.values():
        for block in workout["prescription"]:
            assert not SLUG.match(block["exercise"]["display_name"])
        for item in workout["items"]:
            assert not SLUG.match(item["exercise_name"])


# --- #303 review C1: кривой exercise_id — 422 {code, path, message}, никогда не 500 ----------------


async def test_preview_malformed_exercise_id_is_422_never_500(session, user):
    for bad in ([1, 2], {"id": 1}, "1", 1.5, True, None, 0, -3, 2**63, 10**30):
        response = await v2_post(
            session, telegram_id=user.telegram_id, path="/api/v2/workouts/preview",
            payload={"content": {"title": "T", "blocks": [{"key": "A", "exercise_id": bad, "sets": 1, "reps": 1}]}},
        )
        assert response.status_code == 422, (bad, response.text)
        detail = response.json()["detail"]
        assert set(detail) == {"code", "path", "message"}, (bad, detail)
        assert detail["path"] == "$.blocks[0].exercise_id", (bad, detail)
        assert detail["code"] in ("invalid_type", "out_of_range"), (bad, detail)

    # blocks не списком / блок не объектом — тоже 422 канонического вида, не TypeError
    for content in ({"title": "T", "blocks": 5}, {"title": "T", "blocks": [[{"exercise_id": [1]}]]}):
        response = await v2_post(
            session, telegram_id=user.telegram_id, path="/api/v2/workouts/preview", payload={"content": content},
        )
        assert response.status_code == 422, (content, response.text)
        assert set(response.json()["detail"]) == {"code", "path", "message"}


# --- #303 review B3: ключ блока V1 = i<item>e<exercise> ----------------------------------------------


async def _builder_workout(session, user, *exercise_names: str) -> tuple[int, list[int]]:
    workout_id = (await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/workouts", payload={"title": "Ключи"},
    )).json()["id"]
    exercise_ids = [
        (await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/exercises", payload={"name": name})).json()["id"]
        for name in exercise_names
    ]
    return workout_id, exercise_ids


async def _version_keys(session, workout_id: int) -> list[tuple[int, list[tuple[str, int]]]]:
    rows = (await session.execute(
        text("SELECT version_no, content FROM workout_definition_versions WHERE workout_definition_id = :id ORDER BY 1"),
        {"id": workout_id},
    )).all()
    return [(row.version_no, [(b["key"], b["exercise_id"]) for b in row.content["blocks"]]) for row in rows]


def _assert_no_key_collision(history: list[tuple[int, list[tuple[str, int]]]]) -> None:
    exercises_by_key: dict[str, set[int]] = {}
    for _, pairs in history:
        for key, exercise_id in pairs:
            exercises_by_key.setdefault(key, set()).add(exercise_id)
    assert all(len(ids) == 1 for ids in exercises_by_key.values()), exercises_by_key


PROTOCOL_3X10 = {"type": "reps_sets", "prescription": {"source": "static", "sets": 3, "reps": 10}, "rest_seconds": 90}


async def test_builder_item_exercise_change_gets_new_block_key(session, user):
    workout_id, (first, second) = await _builder_workout(session, user, "Первое", "Второе")
    item = (await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}/items",
        payload={"exercise_id": first, "protocol": PROTOCOL_3X10},
    )).json()
    changed = await v2_patch(
        session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}/items/{item['id']}",
        payload={"exercise_id": second},
    )
    assert changed.status_code == 200

    history = await _version_keys(session, workout_id)
    assert history == [
        (1, [(f"i{item['id']}e{first}", first)]),
        (2, [(f"i{item['id']}e{second}", second)]),
    ]
    _assert_no_key_collision(history)

    # и обратно на первое упражнение: прежний ключ снова означает то же упражнение — v3, без коллизии
    await v2_patch(
        session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}/items/{item['id']}",
        payload={"exercise_id": first},
    )
    history = await _version_keys(session, workout_id)
    assert [no for no, _ in history] == [1, 2, 3]
    assert history[2][1] == [(f"i{item['id']}e{first}", first)]
    _assert_no_key_collision(history)


async def test_builder_ordinary_edits_keep_block_keys_stable(session, user):
    workout_id, (first, second) = await _builder_workout(session, user, "Первое", "Второе")
    items = [
        (await v2_post(
            session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}/items",
            payload={"exercise_id": exercise_id, "protocol": PROTOCOL_3X10},
        )).json()
        for exercise_id in (first, second)
    ]
    expected = {f"i{items[0]['id']}e{first}", f"i{items[1]['id']}e{second}"}
    await v2_patch(
        session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}/items/{items[0]['id']}",
        payload={"protocol": {**PROTOCOL_3X10, "prescription": {"source": "static", "sets": 5, "reps": 2}, "rest_seconds": 60}},
    )
    await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}/items/{items[1]['id']}/move",
        payload={"direction": "up"},
    )
    await v2_patch(session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}", payload={"title": "Новое"})

    history = await _version_keys(session, workout_id)
    assert len(history) >= 4  # добавление ×2, правка, перестановка, переименование — каждое по версии
    for _, pairs in history[1:]:
        assert {key for key, _ in pairs} == expected
    assert [key for key, _ in history[-1][1]] == [f"i{items[1]['id']}e{second}", f"i{items[0]['id']}e{first}"]
    _assert_no_key_collision(history)
