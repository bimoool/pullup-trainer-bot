"""Проверяет реальным движком aiogram-роутинга (не по описанию в коммите),
что /cancel перехватывает апдейт раньше любого хендлера, завязанного на
FSM-состояние ожидания ввода — баг, который был в старой (не-v2) версии:
`/cancel` посреди ввода результата блока парсился как число и падал с
ошибкой разбора вместо отмены сценария (см. очерёдность include_router в
app/bot/handlers/__init__.py и комментарии в start.py/menu.py)."""

from datetime import UTC, datetime

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import TelegramMethod
from aiogram.types import Chat, Message, TelegramObject, Update
from aiogram.types import User as TgUser

from app.bot.handlers import router as app_router
from app.bot.states import (
    BackdateStates,
    EditWorkoutStates,
    EquipmentStates,
    RetestStates,
    WorkoutStates,
)
from app.db.models import User
from app.db.repositories.users import UserRepository

# Токен формально валиден для Bot(...) (цифры:остальное), реальных запросов
# не делает — все исходящие вызовы перехватывает _StubSession ниже.
_FAKE_TOKEN = "123456789:AAFakeTokenForRoutingTestsOnly0000000000"


class _StubSession(BaseSession):
    """Ни одного реального обращения к api.telegram.org — только чтобы
    message.answer()/callback.answer() внутри хендлеров не падали."""

    async def close(self) -> None:
        return None

    async def make_request(
        self, bot: Bot, method: TelegramMethod[TelegramObject], timeout: int | None = None,
    ) -> TelegramObject:
        if isinstance(method.__returning__, bool | type(None)):  # answerCallbackQuery и т.п.
            return True
        return Message(
            message_id=1, date=datetime.now(UTC), chat=Chat(id=1, type="private"), text="stub",
        )

    async def stream_content(self, *args, **kwargs):  # pragma: no cover - не используется в этих тестах
        yield b""


def _cancel_update(*, telegram_id: int) -> Update:
    return Update(
        update_id=1,
        message=Message(
            message_id=100, date=datetime.now(UTC),
            chat=Chat(id=telegram_id, type="private"),
            from_user=TgUser(id=telegram_id, is_bot=False, first_name="Tester"),
            text="/cancel",
        ),
    )


# Все состояния ожидания числового/текстового ввода, где раньше "/cancel"
# рисковал уйти в парсер вместо команды — по одному на каждый StatesGroup,
# который реально ждёт свободный текст в чат.
WAITING_FOR_INPUT_STATES = [
    WorkoutStates.waiting_for_block_a,
    WorkoutStates.waiting_for_block_b,
    WorkoutStates.waiting_for_comment,
    EquipmentStates.waiting_for_value,
    EditWorkoutStates.waiting_for_block_a,
    EditWorkoutStates.waiting_for_block_b,
    BackdateStates.waiting_for_block_a,
    BackdateStates.waiting_for_block_b,
    RetestStates.waiting_for_baseline_reps,
]


@pytest.fixture(scope="module")
def bot() -> Bot:
    return Bot(token=_FAKE_TOKEN, session=_StubSession())


@pytest.fixture(scope="module")
def dispatcher() -> Dispatcher:
    # Router можно include_router() только один раз за время жизни объекта
    # (aiogram запрещает повторное присоединение) — Dispatcher строится
    # один раз на модуль и переиспользуется между параметризованными
    # прогонами; общее MemoryStorage это не портит, каждый тест сам
    # выставляет своё состояние перед feed_update и проверяет после.
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(app_router)
    return dp


@pytest.mark.parametrize("state_to_set", WAITING_FOR_INPUT_STATES, ids=lambda s: s.state)
async def test_cancel_interrupts_any_input_waiting_state(
    session, user: User, state_to_set, bot: Bot, dispatcher: Dispatcher,
):
    # Онбординг обязателен: у пользователя, который его не прошёл,
    # _go_home() после /cancel сознательно возвращает в
    # OnboardingStates.waiting_for_baseline_reps, а не очищает состояние —
    # это отдельная (верная) ветка, не то, что здесь проверяется.
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(state_to_set)
    await fsm.update_data(block_a_working_reps=[1, 1, 1], block_a_max_reps=1)  # мусорные данные сценария

    await dispatcher.feed_update(bot, _cancel_update(telegram_id=user.telegram_id), session=session)

    # Если бы "/cancel" перехватил хендлер состояния (старый баг), он бы
    # вернул ParseError и НЕ тронул состояние — оно осталось бы прежним.
    assert await fsm.get_state() is None
    assert await fsm.get_data() == {}
