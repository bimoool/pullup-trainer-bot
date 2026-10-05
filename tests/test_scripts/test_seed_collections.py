from app.db.models_program import Program, ProgramStructureType
from app.db.repositories.collections import CollectionRepository
from scripts.seed_collections import START_SLUG, seed_collections


async def _program(session, name: str, category: str | None) -> Program:
    program = Program(name=name, goal="цель", structure_type=ProgramStructureType.RECURRING, category=category, config={})
    session.add(program)
    await session.flush()
    return program


async def test_seed_builds_start_collection_from_pull_up_programs_idempotently(session):
    first = await _program(session, "Подтягивания", "pull_ups")
    await _program(session, "Другая", "mobility")

    assert await CollectionRepository(session).list_visible() == []
    dry = await seed_collections(session, dry_run=True)
    assert "1 программ" in dry[0]
    assert await CollectionRepository(session).list_visible() == []

    for _ in range(2):
        await seed_collections(session)
    visible = await CollectionRepository(session).list_visible()

    assert [v.collection.slug for v in visible] == [START_SLUG]
    assert [(i.item_type, i.target_id) for i in visible[0].items] == [("program", first.id)]
    assert visible[0].collection.author_label == "Турникмэн"


async def test_seed_without_programs_yields_nothing_visible(session):
    await seed_collections(session)
    assert await CollectionRepository(session).list_visible() == []
