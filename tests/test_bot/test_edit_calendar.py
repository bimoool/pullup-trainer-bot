""""Изменить тренировку" через календарь вместо плоского списка кнопок-дат
(Часть 10, пакет #2, п.17). Реальным aiogram-роутингом."""

from datetime import UTC, datetime

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage

from app.bot.states import EditWorkoutStates
from app.db.models import User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.session import BlockLog
from tests.test_bot.conftest import make_callback_update as _callback_update


async def _make_live_workout(session, user: User, *, performed_at: datetime, workout_set_id: int) -> None:
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=performed_at,
        block_a_reps=BlockLog(working_reps=(10, 10, 10), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.BODYWEIGHT, block_b_equipment_value=None,
    )


async def _make_backdated_workout(session, user: User, *, performed_at: datetime, workout_set_id: int) -> None:
    await WorkoutRepository(session).record_backdated_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=performed_at,
        block_a_reps=BlockLog(working_reps=(9, 9, 9), max_reps=10),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.BODYWEIGHT, block_b_equipment_value=None,
    )


async def test_edit_workout_menu_opens_calendar_not_flat_list(session, user: User, bot: Bot, dispatcher: Dispatcher):
    # Календарь по умолчанию открывается на ТЕКУЩЕМ месяце (см.
    # handle_edit_workout_menu: now = datetime.now(UTC)) — тренировка
    # должна быть в нём же, не в захардкоженном прошлом месяце, иначе тест
    # ломается при каждой смене месяца (issue #44).
    performed_at = datetime.now(UTC)
    await UserRepository(session).complete_onboarding(user.id, performed_at)
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=performed_at, reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await _make_live_workout(session, user, performed_at=performed_at, workout_set_id=workout_set.id)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="edit_workout_menu"), session=session,
    )

    [calendar_message] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.reply_markup and any(
            b.callback_data.startswith("cal_close:edit")
            for row in m.reply_markup.inline_keyboard for b in row
        )
    ]
    day_buttons = [
        b.callback_data for row in calendar_message.reply_markup.inline_keyboard for b in row
        if b.callback_data.startswith("cal_day:")
    ]
    assert f"cal_day:edit:{performed_at.date().isoformat()}" in day_buttons


async def test_edit_workout_menu_alerts_when_nothing_editable(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="edit_workout_menu"), session=session,
    )

    # ни одного календарного сообщения не ушло — только alert через callback.answer
    assert not any(isinstance(m, SendMessage) for m in bot.session.sent_methods)


async def test_tapping_day_with_one_editable_workout_starts_editing(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await _make_live_workout(session, user, performed_at=datetime(2026, 8, 5, tzinfo=UTC), workout_set_id=workout_set.id)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="cal_day:edit:2026-08-05"), session=session,
    )

    assert await fsm.get_state() == EditWorkoutStates.waiting_for_block_a.state


async def test_tapping_day_with_only_backdated_workout_starts_editing(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    # Внесённые задним числом не в цепочке каскада, но теперь тоже
    # редактируются (issue #106) — просто через edit_noncascade_workout
    # вместо edit_workout (см. _is_history_editable), без пересчёта цели.
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await _make_backdated_workout(
        session, user, performed_at=datetime(2026, 8, 5, tzinfo=UTC), workout_set_id=workout_set.id,
    )
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.clear()  # dispatcher session-scoped — тот же telegram_id между тестами файла

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="cal_day:edit:2026-08-05"), session=session,
    )

    assert await fsm.get_state() == EditWorkoutStates.waiting_for_block_a.state


async def test_tapping_day_with_two_editable_workouts_shows_sub_picker(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await _make_live_workout(
        session, user, performed_at=datetime(2026, 8, 5, 9, 0, tzinfo=UTC), workout_set_id=workout_set.id,
    )
    await _make_live_workout(
        session, user, performed_at=datetime(2026, 8, 5, 18, 0, tzinfo=UTC), workout_set_id=workout_set.id,
    )
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.clear()  # dispatcher session-scoped — тот же telegram_id между тестами файла

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="cal_day:edit:2026-08-05"), session=session,
    )

    # редкий случай — не сразу в редактирование, а короткий саб-список
    assert await fsm.get_state() is None
    [sub_picker] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.reply_markup and any(
            b.callback_data.startswith("edit_pick:") for row in m.reply_markup.inline_keyboard for b in row
        )
    ]
    labels = [
        b.text for row in sub_picker.reply_markup.inline_keyboard for b in row
        if b.callback_data.startswith("edit_pick:")
    ]
    assert set(labels) == {"09:00", "18:00"}
