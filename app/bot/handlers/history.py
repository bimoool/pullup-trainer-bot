from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.keyboards import after_history_keyboard
from app.db.models import Block, BlockType, EquipmentType
from app.db.repositories.users import UserRepository
from app.db.repositories.workouts import WorkoutRepository

router = Router()

HISTORY_LIMIT = 10

_EQUIPMENT_LABELS = {
    EquipmentType.BAND: "рез.",
    EquipmentType.BODYWEIGHT: "св.вес",
    EquipmentType.WEIGHT: "отягощ.",
    EquipmentType.AUSTRALIAN: "австрал.",
}


def _format_equipment(block: Block) -> str:
    label = _EQUIPMENT_LABELS[block.equipment_type]
    if block.equipment_value is None:
        return label
    return f"{label} {block.equipment_value}кг"


@router.callback_query(F.data == "show_history")
async def handle_show_history(callback: CallbackQuery, session: AsyncSession) -> None:
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)

    workouts = WorkoutRepository(session)
    history = await workouts.list_for_user(user.id)

    if not history:
        await callback.message.answer(texts.HISTORY_EMPTY, reply_markup=after_history_keyboard())
        await callback.answer()
        return

    lines = []
    for workout in history[-HISTORY_LIMIT:]:
        block_a = next(b for b in workout.blocks if b.block_type == BlockType.A)
        block_b = next(b for b in workout.blocks if b.block_type == BlockType.B)
        date_str = workout.performed_at.strftime("%d.%m.%Y")
        backdated_mark = " (задним числом)" if not workout.participates_in_cascade else ""
        lines.append(
            f"{date_str}{backdated_mark}: объём {_format_equipment(block_a)} макс {block_a.max_reps}→цель "
            f"{block_a.target_after}, сила {_format_equipment(block_b)} макс {block_b.max_reps}→цель "
            f"{block_b.target_after}",
        )

    await callback.message.answer("\n".join(lines), reply_markup=after_history_keyboard())
    await callback.answer()
