from app.db.models import CoinReason, User
from app.db.repositories.coins import CoinRepository


async def test_create_transaction_and_list(session, user: User):
    repo = CoinRepository(session)
    await repo.create_transaction(user_id=user.id, amount=5, reason=CoinReason.WORKOUT_COMPLETED)
    await repo.create_transaction(user_id=user.id, amount=-3, reason=CoinReason.SUBSCRIPTION_EXTENSION)

    transactions = await repo.list_for_user(user.id)
    assert [t.amount for t in transactions] == [5, -3]


async def test_get_balance_sums_transactions(session, user: User):
    repo = CoinRepository(session)
    await repo.create_transaction(user_id=user.id, amount=10, reason=CoinReason.WORKOUT_COMPLETED)
    await repo.create_transaction(user_id=user.id, amount=20, reason=CoinReason.ACHIEVEMENT_UNLOCKED)
    await repo.create_transaction(user_id=user.id, amount=-15, reason=CoinReason.SUBSCRIPTION_EXTENSION)

    assert await repo.get_balance(user.id) == 15


async def test_get_balance_with_no_transactions_is_zero(session, user: User):
    repo = CoinRepository(session)
    assert await repo.get_balance(user.id) == 0


async def test_list_since_returns_only_newer_ids_in_order(session, user: User):
    repo = CoinRepository(session)
    first = await repo.create_transaction(user_id=user.id, amount=5, reason=CoinReason.WORKOUT_COMPLETED)
    second = await repo.create_transaction(user_id=user.id, amount=-3, reason=CoinReason.SUBSCRIPTION_EXTENSION)

    assert [c.id for c in await repo.list_since(0, limit=10)] == [first.id, second.id]
    assert [c.id for c in await repo.list_since(first.id, limit=10)] == [second.id]
