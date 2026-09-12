"""Режим тестирования для админа (Часть 9 респека) — реальным
aiogram-роутингом проверяет, что обход MIN_REST_DAYS и "тихого отката на
старый снаряд после провала перехода" работает ТОЛЬКО для telegram_id из
settings.admin_ids, а обычный пользователь по-прежнему упирается в те же
ограничения, что и раньше. Плюс "🧪 Полный сброс" — доступ и сам эффект."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aiogram import Bot, Dispatcher
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser
from sqlalchemy import text

from app.bot.states import EquipmentStates, WorkoutStates
from app.config import settings
from app.db.models import User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.equipment_items import EquipmentItemRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.session import BlockLog
from app.services.subscription import SubscriptionService
from tests.test_bot.conftest import make_callback_update as _callback_update


def _message_update(*, telegram_id: int, message_text: str) -> Update:
    return Update(
        update_id=1,
        message=Message(
            message_id=101, date=datetime.now(UTC),
            chat=Chat(id=telegram_id, type="private"),
            from_user=TgUser(id=telegram_id, is_bot=False, first_name="Tester"),
            text=message_text,
        ),
    )


async def _make_user_ready_for_workouts(session, user: User) -> None:
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))


async def _seed_one_workout(session, user: User, *, performed_at: datetime, transition_failed_a: bool = False) -> int:
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=performed_at, reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    workout = await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=performed_at,
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=Decimal("20.0"),
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=Decimal("20.0"),
    )
    if transition_failed_a:
        block_a = next(b for b in workout.blocks if b.block_type.value == "a")
        block_a.transition_failed = True
        await session.flush()
    return workout_set.id


# --- MIN_REST_DAYS (TOO_EARLY) ------------------------------------------------------


async def test_too_early_blocks_regular_user(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await _make_user_ready_for_workouts(session, user)
    await _seed_one_workout(session, user, performed_at=datetime.now(UTC))  # только что — days_since=0

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(None)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="start_workout"), session=session,
    )

    # Заблокировано на TOO_EARLY — сценарий даже не начался (ни одного
    # state.set_state в этой ветке handle_start_workout).
    assert await fsm.get_state() is None


async def test_too_early_does_not_block_admin(session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch):
    monkeypatch.setattr(settings, "admin_ids", str(user.telegram_id))
    await _make_user_ready_for_workouts(session, user)
    await _seed_one_workout(session, user, performed_at=datetime.now(UTC))

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(None)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="start_workout"), session=session,
    )

    # Снаряд у обоих блоков не менялся — сценарий доходит сразу до ввода
    # результата (очередь снаряда пустая, needs_new_equipment=False).
    assert await fsm.get_state() == WorkoutStates.waiting_for_block_a.state


async def test_too_early_proactive_status_does_not_show_for_admin(
    session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    """Тот же обход, что и test_too_early_does_not_block_admin — теперь
    ещё и для проактивного статуса при открытии раздела "Тренировка"
    (app/bot/handlers/menu.py::handle_workout_section, issue #94), не
    только для реактивного показа после клика "Начать тренировку"."""
    from aiogram.methods import SendMessage

    monkeypatch.setattr(settings, "admin_ids", str(user.telegram_id))
    await _make_user_ready_for_workouts(session, user)
    await _seed_one_workout(session, user, performed_at=datetime.now(UTC))

    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, message_text="💪 Тренировка"), session=session,
    )

    sent_texts = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]
    assert not [t for t in sent_texts if t and t.startswith("Рано —")]


# --- "тихий откат" после провала перехода на новом снаряде -------------------------


async def test_transition_wait_silently_reverts_for_regular_user(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await _make_user_ready_for_workouts(session, user)
    await _seed_one_workout(
        session, user, performed_at=datetime.now(UTC) - timedelta(days=3), transition_failed_a=True,
    )

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(None)
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="start_workout"), session=session,
    )

    # Снаряд молча остаётся прежним — пользователя не переспрашивают.
    assert await fsm.get_state() == WorkoutStates.waiting_for_block_a.state


async def test_transition_wait_bypassed_for_admin(session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch):
    monkeypatch.setattr(settings, "admin_ids", str(user.telegram_id))
    await _make_user_ready_for_workouts(session, user)
    await _seed_one_workout(
        session, user, performed_at=datetime.now(UTC) - timedelta(days=3), transition_failed_a=True,
    )

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(None)
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="start_workout"), session=session,
    )

    # Для админа снаряд переспрашивается заново, не дожидаясь естественного
    # перетриггера порога.
    assert await fsm.get_state() == EquipmentStates.waiting_for_type.state


# --- "🧪 Полный сброс (админ)" -------------------------------------------------------


async def test_admin_reset_confirm_rejected_for_non_admin(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await _make_user_ready_for_workouts(session, user)
    await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="admin_reset_confirm"), session=session,
    )

    # Доступ отклонён до выполнения reset_user_progress — данные целы.
    assert len(await BaselineRepository(session).list_for_user(user.id)) == 1


async def test_admin_reset_confirm_archives_and_clears_progress_for_admin(
    session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    monkeypatch.setattr(settings, "admin_ids", str(user.telegram_id))
    await _make_user_ready_for_workouts(session, user)
    await _seed_one_workout(session, user, performed_at=datetime.now(UTC))
    await EquipmentItemRepository(session).create(user_id=user.id, name="зелёная")

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="admin_reset_confirm"), session=session,
    )

    assert await BaselineRepository(session).list_for_user(user.id) == []
    assert await WorkoutSetRepository(session).list_for_user(user.id) == []
    assert await EquipmentItemRepository(session).list_for_user(user.id) == []

    # reset_user_progress пишет users через сырой SQL — уже загруженный в
    # identity map объект user не увидит UPDATE без явного refresh().
    await session.refresh(user)
    assert user.onboarding_completed_at is None

    archived_baselines = (
        await session.execute(
            text("SELECT count(*) FROM baselines_archive_admin_reset WHERE user_id = :uid"), {"uid": user.id},
        )
    ).scalar()
    assert archived_baselines == 1
    archived_workouts = (
        await session.execute(
            text("SELECT count(*) FROM workouts_archive_admin_reset WHERE user_id = :uid"), {"uid": user.id},
        )
    ).scalar()
    assert archived_workouts == 1
