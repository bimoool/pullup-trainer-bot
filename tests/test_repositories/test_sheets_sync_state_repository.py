from app.db.models import User
from app.db.repositories.sheets_sync_state import SheetsSyncStateRepository


async def test_get_last_event_id_defaults_to_zero_on_first_call(session, user: User):
    repo = SheetsSyncStateRepository(session)
    assert await repo.get_last_event_id() == 0


async def test_set_then_get_roundtrips(session, user: User):
    repo = SheetsSyncStateRepository(session)
    await repo.set_last_event_id(42)
    assert await repo.get_last_event_id() == 42


async def test_set_last_event_id_overwrites_not_accumulates(session, user: User):
    repo = SheetsSyncStateRepository(session)
    await repo.set_last_event_id(10)
    await repo.set_last_event_id(5)
    assert await repo.get_last_event_id() == 5


async def test_get_after_set_does_not_create_a_second_row(session, user: User):
    """get_last_event_id создаёт строку лениво, только если её ещё нет —
    после явного set она уже есть, второй get не должен пытаться завести
    ещё одну (упёрлось бы в PK id=1)."""
    repo = SheetsSyncStateRepository(session)
    await repo.set_last_event_id(7)
    assert await repo.get_last_event_id() == 7
    assert await repo.get_last_event_id() == 7


async def test_additional_cursors_default_to_zero_and_roundtrip_independently(session, user: User):
    """5 источников делят одну строку (пакет #7) — каждый курсор должен
    жить своей жизнью, не задевая остальные."""
    repo = SheetsSyncStateRepository(session)
    assert await repo.get_last_workout_id() == 0
    assert await repo.get_last_elective_id() == 0
    assert await repo.get_last_subscription_id() == 0
    assert await repo.get_last_coin_id() == 0
    assert await repo.get_last_achievement_id() == 0

    await repo.set_last_workout_id(3)
    await repo.set_last_elective_id(4)
    await repo.set_last_subscription_id(5)
    await repo.set_last_coin_id(6)
    await repo.set_last_achievement_id(7)

    assert await repo.get_last_workout_id() == 3
    assert await repo.get_last_elective_id() == 4
    assert await repo.get_last_subscription_id() == 5
    assert await repo.get_last_coin_id() == 6
    assert await repo.get_last_achievement_id() == 7
    # Событийный курсор не задет соседними изменениями.
    assert await repo.get_last_event_id() == 0
