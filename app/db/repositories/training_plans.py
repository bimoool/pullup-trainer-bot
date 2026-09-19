from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import PlanItem, ProgramInclusion, ProgramItem, TrainingPlan
from app.domain.multi_program import WeekPhase


class TrainingPlanRepository:
    """Агрегат TrainingPlan + ProgramInclusion + PlanItem (issue #165, волна
    3) — один репозиторий на агрегат, тот же принцип, что в разделе
    "Архитектура" CLAUDE.md. Не переиспользует WorkoutRepository (старая
    схема) — параллельная новая схема, ничем с ней не связанная кроме
    users.id."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_user(self, user_id: int) -> TrainingPlan | None:
        result = await self._session.execute(select(TrainingPlan).where(TrainingPlan.user_id == user_id))
        return result.scalar_one_or_none()

    async def get_or_create_for_user(self, user_id: int) -> TrainingPlan:
        plan = await self.get_for_user(user_id)
        if plan is not None:
            return plan
        plan = TrainingPlan(user_id=user_id)
        self._session.add(plan)
        await self._session.flush()
        return plan

    async def list_inclusions(self, training_plan_id: int) -> list[ProgramInclusion]:
        result = await self._session.execute(
            select(ProgramInclusion)
            .where(ProgramInclusion.training_plan_id == training_plan_id)
            .order_by(ProgramInclusion.id),
        )
        return list(result.scalars().all())

    async def get_inclusion_by_id(self, inclusion_id: int) -> ProgramInclusion | None:
        return await self._session.get(ProgramInclusion, inclusion_id)

    async def get_inclusion_for_user(self, inclusion_id: int, user_id: int) -> ProgramInclusion | None:
        """Ownership-проверка через join на training_plans — 404, не 403,
        тем же принципом, что EquipmentItemRepository.rename/.delete (см.
        CLAUDE.md: не подтверждать чужому пользователю сам факт
        существования id)."""
        result = await self._session.execute(
            select(ProgramInclusion)
            .join(TrainingPlan, ProgramInclusion.training_plan_id == TrainingPlan.id)
            .where(ProgramInclusion.id == inclusion_id, TrainingPlan.user_id == user_id),
        )
        return result.scalar_one_or_none()

    async def create_inclusion(
        self, *, training_plan_id: int, program_id: int, snapshot: dict, progression_state: dict,
    ) -> ProgramInclusion:
        inclusion = ProgramInclusion(
            training_plan_id=training_plan_id, program_id=program_id,
            snapshot=snapshot, progression_state=progression_state, is_active=True,
        )
        self._session.add(inclusion)
        await self._session.flush()
        return inclusion

    async def update_progression_state(self, inclusion_id: int, progression_state: dict) -> None:
        """Присваивание нового dict целиком (не мутация существующего
        inclusion.progression_state на месте) — SQLAlchemy отслеживает
        изменение JSONB-колонки надёжно только на замену атрибута, не на
        мутацию словаря по ссылке."""
        inclusion = await self.get_inclusion_by_id(inclusion_id)
        inclusion.progression_state = progression_state
        await self._session.flush()

    async def list_plan_items(
        self, training_plan_id: int, *, program_inclusion_id: int | None = None,
    ) -> list[PlanItem]:
        query = select(PlanItem).where(PlanItem.training_plan_id == training_plan_id)
        if program_inclusion_id is not None:
            query = query.where(PlanItem.program_inclusion_id == program_inclusion_id)
        result = await self._session.execute(query.order_by(PlanItem.id))
        return list(result.scalars().all())

    async def create_plan_item(
        self, *, training_plan_id: int, exercise_id: int, complex_id: int | None,
        count_per_week: int, day_of_week: int | None, week_phase: WeekPhase | None, program_inclusion_id: int | None,
    ) -> PlanItem:
        item = PlanItem(
            training_plan_id=training_plan_id, exercise_id=exercise_id, complex_id=complex_id,
            count_per_week=count_per_week, day_of_week=day_of_week, week_phase=week_phase,
            program_inclusion_id=program_inclusion_id,
        )
        self._session.add(item)
        await self._session.flush()
        return item

    async def bulk_create_plan_items_from_program_items(
        self, *, training_plan_id: int, program_inclusion_id: int, program_items: list[ProgramItem],
    ) -> list[PlanItem]:
        """Копирование ProgramItem -> PlanItem при инклюзии (докстринг
        ProgramItem.program_inclusion_id в app/db/models_program.py: "форма,
        которую при ProgramInclusion копируют строки PlanItem"). ProgramItem
        с exercise_id=None (комплекс без отдельного упражнения) пропускается
        — PlanItem.exercise_id NOT NULL в схеме волны 1 (models_program.py),
        а Program.complex_id-only ProgramItem скопировать туда без потери
        NOT NULL было бы нельзя; ни одна программа на этой волне (семя
        «Подтягивания» — пустой ProgramItem, тестовая синтетика — только
        exercise_id) этот случай не создаёт, задокументировано как известный
        пробел схемы на будущее, не решается здесь."""
        items = []
        for program_item in program_items:
            if program_item.exercise_id is None:
                continue
            item = PlanItem(
                training_plan_id=training_plan_id, exercise_id=program_item.exercise_id,
                complex_id=program_item.complex_id, count_per_week=program_item.count_per_week,
                day_of_week=program_item.day_of_week, week_phase=program_item.week_phase,
                program_inclusion_id=program_inclusion_id,
            )
            self._session.add(item)
            items.append(item)
        if items:
            await self._session.flush()
        return items
