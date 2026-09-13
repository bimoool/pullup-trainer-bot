"""Редактирование внесённых не в цепочку записей (бэкдейт/свободные,
issue #106) через тот же календарь "Изменить тренировку", что и обычные
тренировки (см. test_edit_calendar.py) — реальным aiogram-роутингом.

Раньше такие записи вообще не подхватывались этим сценарием (_is_editable
исключал их) — теперь _start_editing ветвится на WorkoutRepository.
edit_noncascade_workout (без пересчёта цели/каскада, тот же инвариант,
что и при первом вводе таких записей, issue #88) вместо edit_workout.
Отдельно проверяется формат "только итог" блока Б (issue #88) — он
сохраняется при правке, без переключения на раскладку по подходам."""

from datetime import UTC, datetime
from decimal import Decimal

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser

from app.bot import texts
from app.bot.states import EditWorkoutStates
from app.db.models import BlockType, User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.session import BlockLog
from tests.test_bot.conftest import make_callback_update as _callback_update

BAND_VALUE = Decimal("15.0")


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


async def _make_backdated_workout(
    session, user: User, *, performed_at: datetime, workout_set_id: int, block_b_reps: BlockLog,
) -> int:
    workout = await WorkoutRepository(session).record_backdated_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=performed_at,
        block_a_reps=BlockLog(working_reps=(9, 9, 9), max_reps=10),
        block_b_reps=block_b_reps,
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BODYWEIGHT, block_b_equipment_value=None,
    )
    return workout.id


async def _enter_edit_via_calendar(session, user: User, bot: Bot, dispatcher: Dispatcher, *, day: str) -> None:
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data=f"cal_day:edit:{day}"), session=session,
    )


async def test_editing_backdated_workout_breakdown_format_does_not_change_target(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    from app.db.repositories.users import UserRepository

    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    workout_id = await _make_backdated_workout(
        session, user, performed_at=datetime(2026, 8, 5, tzinfo=UTC), workout_set_id=workout_set.id,
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
    )
    before = await WorkoutRepository(session).get_by_id(workout_id)
    target_before_a = next(b for b in before.blocks if b.block_type == BlockType.A).target_after
    target_before_b = next(b for b in before.blocks if b.block_type == BlockType.B).target_after

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.clear()
    await _enter_edit_via_calendar(session, user, bot, dispatcher, day="2026-08-05")
    assert await fsm.get_state() == EditWorkoutStates.waiting_for_block_a.state

    # Аномально большое число специально — если бы edit_noncascade_workout
    # пересчитывал цель, это было бы видно по резко изменившемуся target.
    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="20 20 20 21"), session=session)
    assert await fsm.get_state() == EditWorkoutStates.waiting_for_block_b.state
    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="9 9 9 9 10"), session=session)

    assert await fsm.get_state() is None
    after = await WorkoutRepository(session).get_by_id(workout_id)
    block_a = next(b for b in after.blocks if b.block_type == BlockType.A)
    block_b = next(b for b in after.blocks if b.block_type == BlockType.B)
    assert block_a.working_reps == [20, 20, 20]
    assert block_a.max_reps == 21
    assert block_b.working_reps == [9, 9, 9, 9]
    assert block_b.max_reps == 10
    # Цель заморожена — тот же инвариант, что при первом вводе (issue #88).
    assert block_a.target_after == target_before_a
    assert block_b.target_after == target_before_b

    [done] = [
        m.text for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text and m.text.startswith(texts.EDIT_DONE_NONCASCADE.split("{")[0])
    ]
    assert "20, 20, 20, максимум 21" in done
    assert "9, 9, 9, 9, максимум 10" in done


async def test_editing_backdated_workout_total_format_keeps_total_format(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    from app.db.repositories.users import UserRepository

    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    workout_id = await _make_backdated_workout(
        session, user, performed_at=datetime(2026, 8, 6, tzinfo=UTC), workout_set_id=workout_set.id,
        block_b_reps=BlockLog(working_reps=(), max_reps=0, reported_volume=50),
    )

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.clear()
    await _enter_edit_via_calendar(session, user, bot, dispatcher, day="2026-08-06")
    assert await fsm.get_state() == EditWorkoutStates.waiting_for_block_a.state

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="9 9 9 10"), session=session)
    # Формат "только итог" сохраняется — не обычный BLOCK_B_PROMPT по подходам.
    assert await fsm.get_state() == EditWorkoutStates.waiting_for_block_b_total.state
    [total_prompt] = [
        m.text for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text == texts.BACKDATE_BLOCK_B_TOTAL_PROMPT
    ]
    assert total_prompt

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="65"), session=session)
    assert await fsm.get_state() == EditWorkoutStates.waiting_for_block_b_total_max.state

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="edit_skip_block_b_total_max"), session=session,
    )

    assert await fsm.get_state() is None
    workout = await WorkoutRepository(session).get_by_id(workout_id)
    block_b = next(b for b in workout.blocks if b.block_type == BlockType.B)
    assert block_b.working_reps == []
    assert block_b.max_reps == 0
    assert block_b.reported_volume == 65
