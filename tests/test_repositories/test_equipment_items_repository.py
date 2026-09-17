from decimal import Decimal

from app.db.models import User
from app.db.repositories.equipment_items import EquipmentItemRepository
from app.db.repositories.users import UserRepository


async def test_create_assigns_incrementing_positions(session, user: User):
    repo = EquipmentItemRepository(session)

    first = await repo.create(user_id=user.id, name="зелёная")
    second = await repo.create(user_id=user.id, name="широкая фиолетовая", resistance_kg=Decimal("25.0"))

    assert first.position == 0
    assert second.position == 1
    assert first.resistance_kg is None
    assert second.resistance_kg == Decimal("25.0")


async def test_list_for_user_ordered_by_position(session, user: User):
    repo = EquipmentItemRepository(session)
    await repo.create(user_id=user.id, name="первая")
    await repo.create(user_id=user.id, name="вторая")
    await repo.create(user_id=user.id, name="третья")

    items = await repo.list_for_user(user.id)

    assert [item.name for item in items] == ["первая", "вторая", "третья"]


async def test_list_for_user_scoped_to_owner(session, user: User):
    other_user = await _make_other_user(session)
    repo = EquipmentItemRepository(session)
    await repo.create(user_id=user.id, name="моя резина")
    await repo.create(user_id=other_user.id, name="чужая резина")

    items = await repo.list_for_user(user.id)

    assert [item.name for item in items] == ["моя резина"]


async def test_get_by_id_returns_none_for_missing(session, user: User):
    repo = EquipmentItemRepository(session)
    assert await repo.get_by_id(999999) is None


async def test_reorder_swaps_positions_and_persists(session, user: User):
    repo = EquipmentItemRepository(session)
    first = await repo.create(user_id=user.id, name="первая")
    second = await repo.create(user_id=user.id, name="вторая")
    third = await repo.create(user_id=user.id, name="третья")

    # Пользователь двигает "третья" на самый верх.
    reordered = await repo.reorder(user.id, [third.id, first.id, second.id])

    assert [item.name for item in reordered] == ["третья", "первая", "вторая"]
    # Порядок должен пережить повторное чтение из БД, не только вернуться
    # из самого reorder() — проверяем через свежий list_for_user.
    persisted = await repo.list_for_user(user.id)
    assert [item.name for item in persisted] == ["третья", "первая", "вторая"]


async def test_list_all_spans_every_user_ordered_by_user_then_position(session, user: User):
    other_user = await _make_other_user(session)
    repo = EquipmentItemRepository(session)
    await repo.create(user_id=user.id, name="моя первая")
    await repo.create(user_id=other_user.id, name="чужая первая")
    await repo.create(user_id=user.id, name="моя вторая")

    items = await repo.list_all()

    assert [(item.user_id, item.name) for item in items] == [
        (user.id, "моя первая"),
        (user.id, "моя вторая"),
        (other_user.id, "чужая первая"),
    ]


async def test_rename_updates_name(session, user: User):
    repo = EquipmentItemRepository(session)
    item = await repo.create(user_id=user.id, name="старое имя")

    renamed = await repo.rename(item_id=item.id, user_id=user.id, name="новое имя")

    assert renamed is not None
    assert renamed.name == "новое имя"
    persisted = await repo.get_by_id(item.id)
    assert persisted.name == "новое имя"


async def test_rename_returns_none_for_missing_item(session, user: User):
    repo = EquipmentItemRepository(session)
    assert await repo.rename(item_id=999999, user_id=user.id, name="x") is None


async def test_rename_returns_none_for_foreign_item(session, user: User):
    other_user = await _make_other_user(session)
    repo = EquipmentItemRepository(session)
    item = await repo.create(user_id=other_user.id, name="чужая")

    assert await repo.rename(item_id=item.id, user_id=user.id, name="перехват") is None
    persisted = await repo.get_by_id(item.id)
    assert persisted.name == "чужая"


async def test_delete_removes_item(session, user: User):
    repo = EquipmentItemRepository(session)
    item = await repo.create(user_id=user.id, name="удаляемая")

    assert await repo.delete(item_id=item.id, user_id=user.id) is True
    assert await repo.get_by_id(item.id) is None


async def test_delete_returns_false_for_missing_item(session, user: User):
    repo = EquipmentItemRepository(session)
    assert await repo.delete(item_id=999999, user_id=user.id) is False


async def test_delete_returns_false_for_foreign_item(session, user: User):
    other_user = await _make_other_user(session)
    repo = EquipmentItemRepository(session)
    item = await repo.create(user_id=other_user.id, name="чужая")

    assert await repo.delete(item_id=item.id, user_id=user.id) is False
    assert await repo.get_by_id(item.id) is not None


async def _make_other_user(session):
    return await UserRepository(session).create(telegram_id=2002, username="other")
