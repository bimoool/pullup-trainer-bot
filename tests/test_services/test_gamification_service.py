import pytest

from app.db.models import CoinReason, User
from app.db.repositories.coins import CoinRepository
from app.db.repositories.users import UserRepository
from app.domain.achievements import AchievementCode
from app.services.gamification import GamificationService


async def test_unlock_achievement_awards_coins(session, user: User):
    service = GamificationService(session)
    achievement = await service.unlock_achievement(
        user_id=user.id, code=AchievementCode.FIRST_BASELINE, coins_reward=20,
    )

    assert achievement is not None
    updated_user = await UserRepository(session).get_by_id(user.id)
    assert updated_user.coins_balance == 20

    transactions = await CoinRepository(session).list_for_user(user.id)
    assert transactions[0].reason == CoinReason.ACHIEVEMENT_UNLOCKED
    assert transactions[0].related_achievement_id == achievement.id


async def test_unlock_achievement_is_idempotent_no_double_reward(session, user: User):
    service = GamificationService(session)
    await service.unlock_achievement(user_id=user.id, code=AchievementCode.EQUIPMENT_CHANGED, coins_reward=15)
    second = await service.unlock_achievement(user_id=user.id, code=AchievementCode.EQUIPMENT_CHANGED, coins_reward=15)

    assert second is None
    updated_user = await UserRepository(session).get_by_id(user.id)
    assert updated_user.coins_balance == 15  # не 30


async def test_unlock_achievement_zero_reward_creates_no_transaction(session, user: User):
    service = GamificationService(session)
    await service.unlock_achievement(user_id=user.id, code=AchievementCode.SET_COMPLETED, coins_reward=0)

    transactions = await CoinRepository(session).list_for_user(user.id)
    assert transactions == []


async def test_award_workout_coins(session, user: User):
    service = GamificationService(session)
    await service.award_workout_coins(user.id, 3)

    updated_user = await UserRepository(session).get_by_id(user.id)
    assert updated_user.coins_balance == 3


async def test_spend_coins_reduces_balance(session, user: User):
    service = GamificationService(session)
    await service.award_workout_coins(user.id, 10)

    await service.spend_coins(user.id, 4)

    updated_user = await UserRepository(session).get_by_id(user.id)
    assert updated_user.coins_balance == 6
    transactions = await CoinRepository(session).list_for_user(user.id)
    assert transactions[-1].amount == -4
    assert transactions[-1].reason == CoinReason.SUBSCRIPTION_EXTENSION


async def test_spend_coins_rejects_non_positive_amount(session, user: User):
    service = GamificationService(session)
    with pytest.raises(ValueError, match="must be positive"):
        await service.spend_coins(user.id, 0)


async def test_spend_coins_rejects_insufficient_balance(session, user: User):
    service = GamificationService(session)
    await service.award_workout_coins(user.id, 5)

    with pytest.raises(ValueError, match="insufficient balance"):
        await service.spend_coins(user.id, 10)


async def test_grant_coins_by_admin_allows_negative_correction(session, user: User):
    service = GamificationService(session)
    await service.award_workout_coins(user.id, 5)

    await service.grant_coins_by_admin(user.id, -3)

    updated_user = await UserRepository(session).get_by_id(user.id)
    assert updated_user.coins_balance == 2
    transactions = await CoinRepository(session).list_for_user(user.id)
    assert transactions[-1].reason == CoinReason.ADMIN_ADJUSTMENT
    assert transactions[-1].amount == -3


async def test_grant_coins_by_admin_zero_creates_no_transaction(session, user: User):
    service = GamificationService(session)
    await service.grant_coins_by_admin(user.id, 0)

    transactions = await CoinRepository(session).list_for_user(user.id)
    assert transactions == []
