from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BlockType
from app.db.repositories.users import UserRepository
from app.db.repositories.workouts import WorkoutRepository

router = Router()

HISTORY_EMPTY = "Пока нет ни одной тренировки."
HISTORY_LIMIT = 10


@router.callback_query(F.data == "show_history")
async def handle_show_history(callback: CallbackQuery, session: AsyncSession) -> None:
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)

    workouts = WorkoutRepository(session)
    history = await workouts.list_for_user(user.id)

    if not history:
        await callback.message.answer(HISTORY_EMPTY)
        await callback.answer()
        return

    lines = []
    for workout in history[-HISTORY_LIMIT:]:
        block_a = next(b for b in workout.blocks if b.block_type == BlockType.A)
        block_b = next(b for b in workout.blocks if b.block_type == BlockType.B)
        date_str = workout.performed_at.strftime("%d.%m.%Y")
        lines.append(
            f"{date_str}: A макс {block_a.max_reps}→цель {block_a.target_after}, "
            f"B макс {block_b.max_reps}→цель {block_b.target_after}",
        )

    await callback.message.answer("\n".join(lines))
    await callback.answer()
