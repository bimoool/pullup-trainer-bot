"""Разовое исправление неверно записанного снаряда в конкретном блоке
конкретной исторической тренировки — правит и БД, и соответствующую
строку в Google Sheets. Не часть постоянной логики воркера.

БД правится через WorkoutRepository.correct_block_equipment (тот же
метод, что и штатная "правка веса/резины" в правке тренировки, см.
app/bot/handlers/workout_edit.py) — не сырой SQL. Каскад/прогрессия не
трогаются: это исправление ошибки ВВОДА исторической записи, не решение
о смене снаряда.

Sheets правится точечным патчем ровно той одной строки листа workouts,
которая соответствует этому (id, block) — не полной регенерацией листа:
для единичной правки это быстрее и не рискует задеть уже корректные
соседние строки (в отличие от бэкфилла username, где нужно было
перегенерировать ВСЕ строки, здесь одна конкретная строка record — просто
находим и переписываем её, тем же кодом форматирования (workout_to_rows),
что и обычный синк.

Использование (внутри контейнера app):
    python fix_workout_block_equipment.py <workout_id> <a|b> <equipment_type> [equipment_value]

Пример (id=16, блок b, тип weight, значение 16.00):
    python fix_workout_block_equipment.py 16 b weight 16.00

equipment_type — одно из bodyweight/band/weight/australian.
equipment_value — опционально, десятичное число (кг); опускается для
bodyweight/australian/band-без-веса."""

import asyncio
import re
import sys
from decimal import Decimal

import gspread

from app.config import settings
from app.db.base import async_session_factory
from app.db.models import BlockType
from app.db.repositories.users import UserRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.services.sheets_export import WORKOUTS_HEADER, WORKOUTS_SHEET_TITLE, workout_to_rows


async def main() -> None:
    if len(sys.argv) not in (4, 5):
        raise SystemExit(__doc__)

    workout_id = int(sys.argv[1])
    block_type = BlockType(sys.argv[2])
    equipment_type = EquipmentType(sys.argv[3])
    equipment_value = Decimal(sys.argv[4]) if len(sys.argv) == 5 else None

    async with async_session_factory() as session:
        workouts = WorkoutRepository(session)
        updated = await workouts.correct_block_equipment(
            workout_id=workout_id, block_type=block_type,
            equipment_type=equipment_type, equipment_value=equipment_value,
        )
        await session.commit()
        print(f"БД: workout id={workout_id} блок {block_type.value} -> {equipment_type.value} {equipment_value}")

        user = await UserRepository(session).get_by_id(updated.user_id)
        corrected_rows = {
            block.block_type.value: row
            for block, row in zip(
                sorted(updated.blocks, key=lambda b: b.block_type.value),
                workout_to_rows(updated, telegram_id=user.telegram_id, username=user.username),
                strict=True,
            )
        }
        corrected_row = corrected_rows[block_type.value]

    client = gspread.service_account(filename=settings.google_sheets_credentials_path)
    spreadsheet = client.open_by_key(settings.google_sheets_spreadsheet_id)
    worksheet = spreadsheet.worksheet(WORKOUTS_SHEET_TITLE)
    values = worksheet.get_all_values()

    matches = [
        i for i, row in enumerate(values)
        if len(row) > 6 and row[0] == str(workout_id) and row[6] == block_type.value
    ]
    if len(matches) != 1:
        raise SystemExit(
            f"Ожидал ровно одну строку в {WORKOUTS_SHEET_TITLE} для id={workout_id} блок={block_type.value}, "
            f"нашёл {len(matches)}. Ничего не патчу — разберись руками.",
        )
    sheet_row_number = matches[0] + 1  # get_all_values() 0-based, строки листа 1-based

    print(f"Sheets: строка {sheet_row_number} листа {WORKOUTS_SHEET_TITLE}")
    print(f"  БЫЛО:   {values[matches[0]]}")
    print(f"  СТАНЕТ: {corrected_row}")

    last_col = re.sub(r"\d+$", "", gspread.utils.rowcol_to_a1(1, len(WORKOUTS_HEADER)))
    worksheet.update(range_name=f"A{sheet_row_number}:{last_col}{sheet_row_number}", values=[corrected_row])
    print("Готово.")


if __name__ == "__main__":
    asyncio.run(main())
