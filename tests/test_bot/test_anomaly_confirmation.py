"""Уточнение по аномалии ввода (пакет #4) во всех точках входа — живая
тренировка (блок A/B), бэкдейт (блок A/B), правка (блок A/B), свободные
подтягивания. Реальным aiogram-роутингом: "Всё верно" должен записать РОВНО
то, что ввели (не то, что стояло бы по умолчанию), "Ввести заново" должен
вернуть к тому же шагу ввода без каких-либо побочных записей."""

from datetime import UTC, datetime, timedelta

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser

from app.bot import texts
from app.bot.states import (
    BackdateStates,
    EditWorkoutStates,
    EquipmentStates,
    FreeWorkoutStates,
    WorkoutStates,
)
from app.db.models import BlockType, User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.session import BlockLog
from tests.test_bot.conftest import make_callback_update as _callback_update


def _message_update(*, telegram_id: int, text: str) -> Update:
    return Update(
        update_id=1,
        message=Message(
            message_id=101, date=datetime.now(UTC),
            chat=Chat(id=telegram_id, type="private"),
            from_user=TgUser(id=telegram_id, is_bot=False, first_name="Tester"),
            text=text,
        ),
    )


async def _seed_workout(
    session, user: User, *, performed_at: datetime, working_reps=(10, 10, 10), max_reps=11,
) -> None:
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=performed_at, reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=performed_at,
        block_a_reps=BlockLog(working_reps=working_reps, max_reps=max_reps),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=4),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.BODYWEIGHT, block_b_equipment_value=None,
    )


# --- Живая тренировка: блок A ------------------------------------------------------


async def _put_user_at_live_block_a(session, user: User, bot: Bot, dispatcher: Dispatcher) -> None:
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(WorkoutStates.waiting_for_block_a)
    await fsm.set_data({
        "workout_set_id": workout_set.id, "target_a": 10, "target_b": 4,
        "target_a_override": None, "target_b_override": None, "is_first_workout": False,
        "equipment_results": {
            "a": {"type": "bodyweight", "value": None, "item_id": None},
            "b": {"type": "bodyweight", "value": None, "item_id": None},
        },
    })


async def test_live_block_a_large_value_asks_for_confirmation(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await _put_user_at_live_block_a(session, user, bot, dispatcher)

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="10 10 55"), session=session)

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == WorkoutStates.waiting_for_block_a_confirm.state
    sent_texts = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]
    assert any("55" in t for t in sent_texts)


async def test_live_block_a_confirm_records_exact_numbers_and_advances(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await _put_user_at_live_block_a(session, user, bot, dispatcher)
    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="10 10 55"), session=session)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="anomaly:confirm"), session=session,
    )

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == WorkoutStates.waiting_for_block_b.state
    data = await fsm.get_data()
    assert data["block_a_working_reps"] == [10, 10]
    assert data["block_a_max_reps"] == 55
    sent_texts = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]
    assert texts.OPTIONAL_EXERCISE_OFFER in sent_texts


async def test_live_block_a_reenter_returns_to_plan_without_saving_anything(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await _put_user_at_live_block_a(session, user, bot, dispatcher)
    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="10 10 55"), session=session)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="anomaly:reenter"), session=session,
    )

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == WorkoutStates.waiting_for_block_a.state
    data = await fsm.get_data()
    assert "block_a_working_reps" not in data


async def test_live_block_a_clean_input_skips_confirmation_entirely(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await _put_user_at_live_block_a(session, user, bot, dispatcher)

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="10 10 10 11"), session=session)

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == WorkoutStates.waiting_for_block_b.state


async def test_live_block_a_jump_vs_history_asks_for_confirmation(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await _seed_workout(session, user, performed_at=datetime.now(UTC) - timedelta(days=3), working_reps=(10, 10, 10))
    workout_set = await WorkoutSetRepository(session).get_active_for_user(user.id)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(WorkoutStates.waiting_for_block_a)
    await fsm.set_data({
        "workout_set_id": workout_set.id, "target_a": 12, "target_b": 4,
        "target_a_override": None, "target_b_override": None, "is_first_workout": False,
        "equipment_results": {
            "a": {"type": "bodyweight", "value": None, "item_id": None},
            "b": {"type": "bodyweight", "value": None, "item_id": None},
        },
    })

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="24 24 24"), session=session)

    assert await fsm.get_state() == WorkoutStates.waiting_for_block_a_confirm.state
    sent_texts = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]
    assert any("заметный рост" in t for t in sent_texts)


# --- Живая тренировка: блок B -------------------------------------------------------


async def _put_user_at_live_block_b(session, user: User, bot: Bot, dispatcher: Dispatcher) -> None:
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(WorkoutStates.waiting_for_block_b)
    await fsm.set_data({
        "workout_set_id": workout_set.id, "target_a": 10, "target_b": 4,
        "target_a_override": None, "target_b_override": None,
        "block_a_working_reps": [10, 10, 10], "block_a_max_reps": 11,
        "equipment_results": {
            "a": {"type": "bodyweight", "value": None, "item_id": None},
            "b": {"type": "bodyweight", "value": None, "item_id": None},
        },
    })


async def test_live_block_b_large_value_confirm_advances_to_comment(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await _put_user_at_live_block_b(session, user, bot, dispatcher)
    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="3 3 3 3 60"), session=session)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == WorkoutStates.waiting_for_block_b_confirm.state

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="anomaly:confirm"), session=session,
    )

    assert await fsm.get_state() == WorkoutStates.waiting_for_comment.state
    data = await fsm.get_data()
    assert data["block_b_max_reps"] == 60


async def test_live_block_b_reenter_resends_block_b_prompt(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await _put_user_at_live_block_b(session, user, bot, dispatcher)
    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="3 3 3 3 60"), session=session)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="anomaly:reenter"), session=session,
    )

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == WorkoutStates.waiting_for_block_b.state
    sent_texts = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]
    assert any(t.startswith("Теперь блок на силу") for t in sent_texts)


# --- Бэкдейт: блок A и B, включая telegram_id-регрессию ----------------------------


async def _start_backdate_at_block_a(session, user: User, bot: Bot, dispatcher: Dispatcher) -> None:
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="backdate_workout"), session=session,
    )
    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="05.01.2026"), session=session,
    )


async def test_backdate_block_a_set_count_mismatch_asks_confirmation(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await _start_backdate_at_block_a(session, user, bot, dispatcher)

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="10 10 11"), session=session)

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == BackdateStates.waiting_for_block_a_confirm.state
    sent_texts = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]
    assert any("Обычно в этом блоке" in t for t in sent_texts)


async def test_backdate_block_a_confirm_advances_to_block_b(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await _start_backdate_at_block_a(session, user, bot, dispatcher)
    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="10 10 11"), session=session)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="anomaly:confirm"), session=session,
    )

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == BackdateStates.waiting_for_block_b.state
    data = await fsm.get_data()
    assert data["block_a_working_reps"] == [10, 10]


async def test_backdate_block_b_confirm_reaches_equipment_queue_with_correct_user(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    """Регрессия (пакет #4): _apply_backdate_block_b раньше рисковала взять
    telegram_id из callback.message.from_user (бот) при вызове из
    anomaly:confirm — тот самый баг, что уже чинили для 'Пропустить'
    (Часть 10). Явный сквозной прогон до записи подтверждает, что
    telegram_id по-прежнему настоящий пользователь."""
    await _start_backdate_at_block_a(session, user, bot, dispatcher)
    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="5 5 5 6"), session=session)
    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="3 3 3 3 60"), session=session)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == BackdateStates.waiting_for_block_b_confirm.state

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="anomaly:confirm"), session=session,
    )
    # Очередь снаряда открыта на реального пользователя — переходим и
    # завершаем её, чтобы убедиться запись реально попадёт этому user.
    assert await fsm.get_state() == EquipmentStates.waiting_for_type.state
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="equip:bodyweight"), session=session,
    )
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="equip:bodyweight"), session=session,
    )

    history = await WorkoutRepository(session).list_for_user(user.id)
    [workout] = history
    block_b = next(b for b in workout.blocks if b.block_type == BlockType.B)
    assert block_b.max_reps == 60


async def test_backdate_block_b_reenter_returns_to_block_b_state(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await _start_backdate_at_block_a(session, user, bot, dispatcher)
    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="5 5 5 6"), session=session)
    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="3 3 3 3 60"), session=session)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="anomaly:reenter"), session=session,
    )

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == BackdateStates.waiting_for_block_b.state


# --- Правка: блок A/B, включая before= из edit_workout_performed_at ----------------


async def test_edit_block_a_jump_uses_before_the_edited_workout_not_the_global_last(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    """Регрессия на _previous_avg_for_edit: правим СТАРУЮ запись — сравнение
    должно идти с тем, что было ДО неё (10), а не с более новой записью
    ПОСЛЕ неё (30), которая иначе замаскировала бы реальный скачок."""
    await _seed_workout(session, user, performed_at=datetime(2026, 1, 1, tzinfo=UTC), working_reps=(10, 10, 10))
    await _seed_workout(session, user, performed_at=datetime(2026, 1, 10, tzinfo=UTC), working_reps=(30, 30, 30))
    workouts = await WorkoutRepository(session).list_for_user(user.id)
    old_workout = workouts[0]

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(EditWorkoutStates.waiting_for_block_a)
    await fsm.set_data({
        "edit_workout_id": old_workout.id, "target_a": 10, "target_b": 4,
        "edit_workout_performed_at": old_workout.performed_at.isoformat(),
    })

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="22 22 22"), session=session)

    assert await fsm.get_state() == EditWorkoutStates.waiting_for_block_a_confirm.state


async def test_edit_block_b_confirm_updates_workout_with_exact_numbers(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await _seed_workout(session, user, performed_at=datetime.now(UTC), working_reps=(10, 10, 10))
    [workout] = await WorkoutRepository(session).list_for_user(user.id)

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(EditWorkoutStates.waiting_for_block_a)
    await fsm.set_data({
        "edit_workout_id": workout.id, "target_a": 10, "target_b": 4,
        "edit_workout_performed_at": workout.performed_at.isoformat(),
    })
    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="10 10 10 11"), session=session)
    assert await fsm.get_state() == EditWorkoutStates.waiting_for_block_b.state

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="3 3 3 3 65"), session=session)
    assert await fsm.get_state() == EditWorkoutStates.waiting_for_block_b_confirm.state

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="anomaly:confirm"), session=session,
    )

    updated = await WorkoutRepository(session).get_by_id(workout.id)
    block_b = next(b for b in updated.blocks if b.block_type == BlockType.B)
    assert block_b.max_reps == 65


# --- Свободные подтягивания ---------------------------------------------------------


async def test_free_workout_large_value_confirm_records_exact_numbers(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_data({"equipment_type": "bodyweight", "equipment_value": None, "equipment_item_id": None})
    await fsm.set_state(FreeWorkoutStates.waiting_for_reps)

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="8 6 60"), session=session)
    assert await fsm.get_state() == FreeWorkoutStates.waiting_for_reps_confirm.state

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="anomaly:confirm"), session=session,
    )

    history = await WorkoutRepository(session).list_for_user(user.id)
    [workout] = history
    block_a = next(b for b in workout.blocks if b.block_type == BlockType.A)
    assert block_a.working_reps == [8, 6]
    assert block_a.max_reps == 60
    assert await fsm.get_state() is None


async def test_free_workout_reenter_returns_to_reps_prompt(session, user: User, bot: Bot, dispatcher: Dispatcher):
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_data({"equipment_type": "bodyweight", "equipment_value": None, "equipment_item_id": None})
    await fsm.set_state(FreeWorkoutStates.waiting_for_reps)
    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="8 6 60"), session=session)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="anomaly:reenter"), session=session,
    )

    assert await fsm.get_state() == FreeWorkoutStates.waiting_for_reps.state
    history = await WorkoutRepository(session).list_for_user(user.id)
    assert history == []


async def test_free_workout_does_not_apply_set_count_check(session, user: User, bot: Bot, dispatcher: Dispatcher):
    """Свободные подтягивания принимают любое количество подходов по
    дизайну (Часть 10, пакет #2, п.21) — проверка "другое количество
    подходов, чем ожидалось" (пакет #4, п.3) здесь неприменима вообще."""
    await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_data({"equipment_type": "bodyweight", "equipment_value": None, "equipment_item_id": None})
    await fsm.set_state(FreeWorkoutStates.waiting_for_reps)

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="8 6 5 4 3"), session=session)

    # Пять подходов — ничего структурно не ожидалось, аномалии нет вовсе.
    assert await fsm.get_state() is None
    history = await WorkoutRepository(session).list_for_user(user.id)
    assert len(history) == 1
