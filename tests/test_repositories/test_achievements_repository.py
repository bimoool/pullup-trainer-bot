from app.db.models import User
from app.db.repositories.achievements import AchievementRepository


async def test_unlock_creates_achievement(session, user: User):
    repo = AchievementRepository(session)
    achievement = await repo.unlock(user_id=user.id, code="first_baseline")

    assert achievement is not None
    assert achievement.code == "first_baseline"


async def test_unlock_is_idempotent(session, user: User):
    repo = AchievementRepository(session)
    first = await repo.unlock(user_id=user.id, code="ten_workouts_streak")
    second = await repo.unlock(user_id=user.id, code="ten_workouts_streak")

    assert first is not None
    assert second is None  # уже разблокирована — тихо игнорируем, не роняем сессию


async def test_unlock_is_idempotent_does_not_poison_session(session, user: User):
    """После неудачной (дублирующей) разблокировки сессия должна оставаться
    рабочей — savepoint в unlock() не должен утаскивать за собой внешнюю
    транзакцию."""
    repo = AchievementRepository(session)
    await repo.unlock(user_id=user.id, code="equipment_changed")
    await repo.unlock(user_id=user.id, code="equipment_changed")  # дубликат, поглощается

    # сессия всё ещё живая и пригодна для дальнейших операций
    another = await repo.unlock(user_id=user.id, code="set_completed")
    assert another is not None


async def test_has_unlocked(session, user: User):
    repo = AchievementRepository(session)
    assert await repo.has_unlocked(user.id, "first_baseline") is False

    await repo.unlock(user_id=user.id, code="first_baseline")
    assert await repo.has_unlocked(user.id, "first_baseline") is True


async def test_list_for_user(session, user: User):
    repo = AchievementRepository(session)
    await repo.unlock(user_id=user.id, code="first_baseline")
    await repo.unlock(user_id=user.id, code="equipment_changed", context={"new_equipment_value": 18.0})

    achievements = await repo.list_for_user(user.id)
    assert {a.code for a in achievements} == {"first_baseline", "equipment_changed"}
    equipment_changed = next(a for a in achievements if a.code == "equipment_changed")
    assert equipment_changed.context == {"new_equipment_value": 18.0}
