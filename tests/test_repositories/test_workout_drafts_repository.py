"""WorkoutDraftRepository (issue #61) — один черновик тренировки в реальном
времени на пользователя, upsert на месте при повторном сохранении, как и
ActiveTimerRepository — здесь проверяется только хранение/замена."""

from decimal import Decimal

from app.db.models import User
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_drafts import WorkoutDraftRepository


async def test_save_creates_new_draft(session, user: User):
    repo = WorkoutDraftRepository(session)

    draft = await repo.save(
        user_id=user.id,
        step_index=1,
        block_a_working_reps=[8],
        block_a_max_reps=None,
        block_b_working_reps=[],
        block_b_max_reps=None,
        block_a_actual_weight=None,
        block_b_actual_weight=None,
        block_a_actual_band_item_id=None,
        block_b_actual_band_item_id=None,
        comment=None,
    )

    assert draft.step_index == 1
    assert draft.block_a_working_reps == [8]
    assert draft.block_b_working_reps == []


async def test_save_replaces_existing_draft_for_same_user(session, user: User):
    repo = WorkoutDraftRepository(session)
    await repo.save(
        user_id=user.id, step_index=1, block_a_working_reps=[8], block_a_max_reps=None,
        block_b_working_reps=[], block_b_max_reps=None, block_a_actual_weight=None,
        block_b_actual_weight=None, block_a_actual_band_item_id=None,
        block_b_actual_band_item_id=None, comment=None,
    )

    updated = await repo.save(
        user_id=user.id, step_index=3, block_a_working_reps=[8, 9], block_a_max_reps=12,
        block_b_working_reps=[], block_b_max_reps=None,
        block_a_actual_weight=Decimal("82.50"), block_b_actual_weight=None,
        block_a_actual_band_item_id=None, block_b_actual_band_item_id=None,
        comment="норм",
    )

    fetched = await repo.get_for_user(user.id)
    assert fetched is not None
    assert fetched.id == updated.id
    assert fetched.step_index == 3
    assert fetched.block_a_working_reps == [8, 9]
    assert fetched.block_a_max_reps == 12
    assert fetched.block_a_actual_weight == Decimal("82.50")
    assert fetched.comment == "норм"


async def test_get_for_user_returns_none_when_no_draft(session, user: User):
    repo = WorkoutDraftRepository(session)
    assert await repo.get_for_user(user.id) is None


async def test_delete_for_user_removes_draft(session, user: User):
    repo = WorkoutDraftRepository(session)
    await repo.save(
        user_id=user.id, step_index=0, block_a_working_reps=[], block_a_max_reps=None,
        block_b_working_reps=[], block_b_max_reps=None, block_a_actual_weight=None,
        block_b_actual_weight=None, block_a_actual_band_item_id=None,
        block_b_actual_band_item_id=None, comment=None,
    )

    await repo.delete_for_user(user.id)

    assert await repo.get_for_user(user.id) is None


async def test_delete_for_user_is_idempotent_when_no_draft(session, user: User):
    repo = WorkoutDraftRepository(session)
    await repo.delete_for_user(user.id)  # не должно бросить исключение


async def test_drafts_are_scoped_per_user(session, user: User):
    other_user = await _make_other_user(session)
    repo = WorkoutDraftRepository(session)
    await repo.save(
        user_id=user.id, step_index=0, block_a_working_reps=[], block_a_max_reps=None,
        block_b_working_reps=[], block_b_max_reps=None, block_a_actual_weight=None,
        block_b_actual_weight=None, block_a_actual_band_item_id=None,
        block_b_actual_band_item_id=None, comment=None,
    )

    assert await repo.get_for_user(other_user.id) is None


async def _make_other_user(session) -> User:
    return await UserRepository(session).create(telegram_id=6101, username="other")
