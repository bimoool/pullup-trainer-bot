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
