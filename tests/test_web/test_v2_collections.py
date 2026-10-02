"""/api/v2/collections — редакционные подборки (CRIMPD #271): видимость и 404."""

from app.db.models import User
from app.db.models_program import (
    Collection,
    CollectionItem,
    Exercise,
    MetricType,
    Program,
    ProgramStructureType,
)
from app.db.repositories.collections import CollectionRepository
from tests.test_web._v2_client import v2_get


async def _program(session, name: str = "Курс", category: str | None = "pull_ups") -> Program:
    program = Program(
        name=name, goal=f"цель {name}", structure_type=ProgramStructureType.RECURRING, category=category, config={},
    )
    session.add(program)
    await session.flush()
    return program


async def _exercise(session, name: str, *, source_type: str = "system", subcategory: str | None = None,
                    owner_user_id: int | None = None) -> Exercise:
    exercise = Exercise(
        name=name, metric_type=MetricType.REPS, category="strength", subcategory=subcategory,
        source_type=source_type, owner_user_id=owner_user_id,
    )
    session.add(exercise)
    await session.flush()
    return exercise


async def _collection(session, slug: str, *, published: bool = True, sort_order: int = 0,
                      programs: list[Program] | None = None, exercises: list[Exercise] | None = None,
                      title: str | None = None) -> Collection:
    return await CollectionRepository(session).upsert_collection(
        slug=slug, title=title or f"Подборка {slug}", description=f"Описание {slug}", sort_order=sort_order,
        is_published=published, program_ids=[p.id for p in programs or []],
        exercise_ids=[e.id for e in exercises or []],
    )


async def _list(session, user: User) -> list[dict]:
    response = await v2_get(session, user.telegram_id, "/api/v2/collections")
    assert response.status_code == 200
    return response.json()["collections"]


async def test_empty_by_default(session, user: User):
    assert await _list(session, user) == []


async def test_lists_published_collection_with_counts_author_and_order(session, user: User):
    first, second = await _program(session, "Первая"), await _program(session, "Вторая")
    exercise = await _exercise(session, "Подтягивания")
    await _collection(session, "later", sort_order=5, programs=[first], title="Позже")
    await _collection(session, "sooner", sort_order=1, programs=[second, first], exercises=[exercise], title="Раньше")

    collections = await _list(session, user)

    assert [c["title"] for c in collections] == ["Раньше", "Позже"]
    sooner = collections[0]
    assert sooner["author"] == "Турникмэн"
    assert sooner["description"] == "Описание sooner"
    assert (sooner["items_count"], sooner["programs_count"], sooner["exercises_count"]) == (3, 2, 1)


async def test_unpublished_and_empty_collections_are_hidden(session, user: User):
    program = await _program(session)
    await _collection(session, "draft", published=False, programs=[program])
    await _collection(session, "empty", programs=[])
    await _collection(session, "visible", programs=[program])

    assert [c["title"] for c in await _list(session, user)] == ["Подборка visible"]


async def test_detail_lists_items_in_order_with_types(session, user: User):
    first, second = await _program(session, "Первая"), await _program(session, "Вторая")
    exercise = await _exercise(session, "Отжимания")
    collection = await _collection(session, "main", programs=[second, first], exercises=[exercise])

    response = await v2_get(session, user.telegram_id, f"/api/v2/collections/{collection.id}")

    assert response.status_code == 200
    body = response.json()
    assert (body["title"], body["author"], body["items_count"]) == ("Подборка main", "Турникмэн", 3)
    assert [(i["item_type"], i["target_id"], i["title"]) for i in body["items"]] == [
        ("program", second.id, "Вторая"), ("program", first.id, "Первая"), ("exercise", exercise.id, "Отжимания"),
    ]
    assert body["items"][0]["subtitle"] == "цель Вторая"


async def test_hidden_and_private_items_are_excluded(session, user: User):
    """Приватное/внутреннее содержимое в подборке не раскрывается (PROJECT_SPEC §5):
    чужое user-упражнение и внутренние step-роли отфильтрованы, видимое — остаётся."""
    program = await _program(session)
    public = await _exercise(session, "Публичное")
    private = await _exercise(session, "Чужое приватное", source_type="user", owner_user_id=user.id)
    internal = await _exercise(session, "Подтягивания — объём", subcategory="block_a")
    collection = await _collection(session, "mix", programs=[program], exercises=[public, private, internal])

    body = (await v2_get(session, user.telegram_id, f"/api/v2/collections/{collection.id}")).json()

    assert [i["title"] for i in body["items"]] == [program.name, "Публичное"]
    assert body["items_count"] == 2
    summary = (await _list(session, user))[0]
    assert summary["items_count"] == 2


async def test_collection_with_only_hidden_items_is_absent(session, user: User):
    private = await _exercise(session, "Приватное", source_type="user", owner_user_id=user.id)
    collection = await _collection(session, "only-hidden", exercises=[private])

    assert await _list(session, user) == []
    response = await v2_get(session, user.telegram_id, f"/api/v2/collections/{collection.id}")
    assert response.status_code == 404


async def test_unknown_and_unpublished_ids_are_404(session, user: User):
    program = await _program(session)
    draft = await _collection(session, "draft", published=False, programs=[program])

    assert (await v2_get(session, user.telegram_id, "/api/v2/collections/999999")).status_code == 404
    assert (await v2_get(session, user.telegram_id, f"/api/v2/collections/{draft.id}")).status_code == 404
    assert (await v2_get(session, user.telegram_id, "/api/v2/collections/abc")).status_code == 422


async def test_dangling_program_row_is_ignored_and_unknown_user_is_404(session, user: User):
    program = await _program(session)
    collection = await _collection(session, "dangling", programs=[program])
    session.add(CollectionItem(collection_id=collection.id, program_id=None, exercise_id=None, position=9))
    await session.flush()

    body = (await v2_get(session, user.telegram_id, f"/api/v2/collections/{collection.id}")).json()
    assert body["items_count"] == 1

    assert (await v2_get(session, 424242, "/api/v2/collections")).status_code == 404
