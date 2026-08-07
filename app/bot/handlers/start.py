from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.bot import texts

router = Router()


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    await message.answer(texts.START_STUB)
