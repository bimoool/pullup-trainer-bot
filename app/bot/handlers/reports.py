from datetime import UTC, datetime, timedelta

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.formatting import format_progress_report
from app.bot.keyboards import progress_section_keyboard
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.reports import current_equipment_progress, weekly_summary
from app.services.export import build_export_workbook

router = Router()


@router.callback_query(F.data == "show_progress_report")
async def handle_show_progress_report(callback: CallbackQuery, session: AsyncSession) -> None:
    """"По запросу — раздел «Прогресс»" (Часть 5 респека) — те же данные,
    что в еженедельной рассылке (app/workers/weekly_report.py), плюс
    динамика на текущем снаряде, доступные в любой момент по кнопке."""
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)

    workouts = WorkoutRepository(session)
    records = await workouts.list_records_for_user(user.id)
    if not records:
        await callback.message.answer(texts.HISTORY_EMPTY, reply_markup=progress_section_keyboard())
        await callback.answer()
        return

    now = datetime.now(UTC)
    week_ago = now - timedelta(days=7)
    two_weeks_ago = now - timedelta(days=14)
    this_week = [r for r in records if r.performed_at >= week_ago]
    previous_week = [r for r in records if two_weeks_ago <= r.performed_at < week_ago]
    previous_week_volume = sum(r.block_a.log.volume + r.block_b.log.volume for r in previous_week)

    summary = weekly_summary(this_week, previous_week_volume)
    progress_a = current_equipment_progress(records, "a")
    progress_b = current_equipment_progress(records, "b")

    await callback.message.answer(
        format_progress_report(summary, progress_a, progress_b), reply_markup=progress_section_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "export_xlsx")
async def handle_export_xlsx(callback: CallbackQuery, session: AsyncSession) -> None:
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)

    workouts = WorkoutRepository(session)
    records = await workouts.list_records_for_user(user.id)
    baselines = await BaselineRepository(session).list_for_user(user.id)

    buffer = build_export_workbook(records, baselines)
    filename = f"pullup-trainer-{datetime.now(UTC):%Y-%m-%d}.xlsx"
    await callback.message.answer_document(
        BufferedInputFile(buffer.read(), filename=filename), caption=texts.EXPORT_READY,
    )
    await callback.answer()
