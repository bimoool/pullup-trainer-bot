from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import Exercise, Program, ProgramItem, ProgressionStrategyProfile


class ProgramRepository:
    """Read-only на этой волне (issue #165, волна 3) — администрирование
    каталога (создание/правка Program/ProgramItem/Exercise) не запрошено,
    единственный писатель каталога пока scripts/backfill_multi_program.py."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> list[Program]:
        result = await self._session.execute(select(Program).order_by(Program.id))
        return list(result.scalars().all())

    async def get_by_id(self, program_id: int) -> Program | None:
        return await self._session.get(Program, program_id)

    async def get_strategy_profile(self, profile_id: int) -> ProgressionStrategyProfile | None:
        return await self._session.get(ProgressionStrategyProfile, profile_id)

    async def list_program_items(self, program_id: int) -> list[ProgramItem]:
        result = await self._session.execute(
            select(ProgramItem).where(ProgramItem.program_id == program_id).order_by(ProgramItem.id),
        )
        return list(result.scalars().all())

    async def find_step_role_exercises(self, *, category: str | None) -> dict[str, Exercise]:
        """Роль "какой Exercise — блок A/Б" для StepProgressionStrategy —
        по конвенции category+subcategory ("block_a"/"block_b"), которую уже
        использует scripts/backfill_multi_program.py::_get_or_create_exercise
        (подтверждено Кириллом в issue #165 как достаточное для этой волны,
        без новой колонки/миграции). Пустой словарь, если category не задана
        у Program или подходящих Exercise не нашлось — вызывающий код решает,
        что с этим делать (для STEP это 400, для программ без прогрессии —
        ожидаемый случай)."""
        if category is None:
            return {}
        result = await self._session.execute(
            select(Exercise).where(Exercise.category == category, Exercise.subcategory.in_(["block_a", "block_b"])),
        )
        return {exercise.subcategory: exercise for exercise in result.scalars().all()}
