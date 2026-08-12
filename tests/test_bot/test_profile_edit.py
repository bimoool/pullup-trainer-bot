"""«✏️ Изменить профиль» — редактирование по одному полю, тот же паттерн
валидации, что и в анкете (Часть 10)."""

from datetime import UTC, datetime

from aiogram import Bot, Dispatcher
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser

from app.bot.states import ProfileEditStates
from app.db.models import Gender, User
from app.db.repositories.users import UserRepository
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


async def test_edit_weight_updates_only_weight(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await UserRepository(session).update_profile(user.id, weight_kg=70, height_cm=175)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(ProfileEditStates.waiting_for_weight)

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="82"), session=session)

    reloaded = await UserRepository(session).get_by_telegram_id(user.telegram_id)
    assert reloaded.weight_kg == 82
    assert reloaded.height_cm == 175  # не тронуто
    assert await fsm.get_state() is None


async def test_edit_gender_via_buttons(session, user: User, bot: Bot, dispatcher: Dispatcher):
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(ProfileEditStates.waiting_for_gender)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="gender:female"), session=session,
    )

    reloaded = await UserRepository(session).get_by_telegram_id(user.telegram_id)
    assert reloaded.gender == Gender.FEMALE


async def test_edit_invalid_weight_does_not_advance_state(session, user: User, bot: Bot, dispatcher: Dispatcher):
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(ProfileEditStates.waiting_for_weight)

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="не число"), session=session)

    assert await fsm.get_state() == ProfileEditStates.waiting_for_weight.state
