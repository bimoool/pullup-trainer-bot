from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import (
    ComplexItem,
    Exercise,
    Program,
    ProgramItem,
    ProgressionStrategyProfile,
)


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

    async def get_exercise(self, exercise_id: int) -> Exercise | None:
        """Read-only — Exercise ещё каталожная сущность на этой волне, не
        трогается сервисом. Нужен app.services.live_session, чтобы узнать
        metric_type упражнения при резолве блоков живой сессии."""
        return await self._session.get(Exercise, exercise_id)

    async def list_exercises_by_ids(self, exercise_ids: list[int]) -> list[Exercise]:
        """Checkpoint 4C (issue #188) — batch-версия get_exercise для
        резолва названий manual-сессий в Журнале одним запросом на
        страницу, не по одному на сессию (раздел 5 задачи — 'не делать
        N+1 на фронте'; здесь тот же принцип и на бэкенде)."""
        if not exercise_ids:
            return []
        result = await self._session.execute(select(Exercise).where(Exercise.id.in_(exercise_ids)))
        return list(result.scalars().all())

    async def list_complex_items(self, complex_id: int) -> list[ComplexItem]:
        """Состав комплекса по order_index — тот же порядок, в котором
        app.services.live_session разворачивает Complex в SessionBlock'и
        живой сессии (issue #165, продолжение волны 3)."""
        result = await self._session.execute(
            select(ComplexItem).where(ComplexItem.complex_id == complex_id).order_by(ComplexItem.order_index),
        )
        return list(result.scalars().all())

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


def program_items_snapshot(program_items: list[ProgramItem]) -> list[dict]:
    """Единственная точка сериализации ProgramItem в форму
    ProgramInclusion.snapshot["program_items"] (checkpoint 1.1, issue #188
    — контрактный баг: до этого исправления app.services.program_inclusion
    ._build_snapshot и scripts/backfill_multi_program.py::seed_catalog
    строили ДВА разных снимка, второй без program_items вообще, хотя
    докстринг первого ложно утверждал обратное).

    Вызывается и обычным путём подключения курса, и бэкфиллом, и
    нормализацией легаси-снимков — ни один из них не должен собирать этот
    список заново вручную."""
    return [
        {
            "id": item.id, "exercise_id": item.exercise_id, "complex_id": item.complex_id,
            "count_per_week": item.count_per_week, "day_of_week": item.day_of_week,
            "week_phase": item.week_phase.value,
        }
        for item in program_items
    ]
