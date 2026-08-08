from app.db.models import User
from app.db.repositories.events import EventRepository


async def test_create_and_list_for_user(session, user: User):
    repo = EventRepository(session)
    await repo.create(user_id=user.id, event_type="start_command")
    await repo.create(user_id=user.id, event_type="button_click", payload={"button": "begin_workout"})

    events = await repo.list_for_user(user.id)

    assert len(events) == 2
    assert {e.event_type for e in events} == {"start_command", "button_click"}


async def test_create_defaults_payload_to_empty_dict(session, user: User):
    repo = EventRepository(session)
    event = await repo.create(user_id=user.id, event_type="validation_error")
    assert event.payload == {}


async def test_list_for_user_respects_limit(session, user: User):
    repo = EventRepository(session)
    for i in range(5):
        await repo.create(user_id=user.id, event_type=f"event_{i}")

    events = await repo.list_for_user(user.id, limit=2)
    assert len(events) == 2
