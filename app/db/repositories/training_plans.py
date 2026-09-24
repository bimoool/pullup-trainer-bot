from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import (
    ComplexItem,
    PlanItem,
    PlanWeek,
    ProgramInclusion,
    ProgramItem,
    TrainingPlan,
)
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

    async def get_by_id(self, training_plan_id: int) -> TrainingPlan | None:
        return await self._session.get(TrainingPlan, training_plan_id)

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
        initial_progression_state: dict | None = None,
    ) -> ProgramInclusion:
        """initial_progression_state по умолчанию — та же самая переданная
        progression_state (обычный случай: на момент создания инклюзии
        живое и стартовое значение совпадают, живое начинает мутировать
        только с первой сессией). Отдельный параметр — на случай, если
        когда-нибудь понадобится завести инклюзию с уже отличающимися
        значениями (сейчас такого вызывающего кода нет)."""
        inclusion = ProgramInclusion(
            training_plan_id=training_plan_id, program_id=program_id,
            snapshot=snapshot, progression_state=progression_state, is_active=True,
            initial_progression_state=(
                initial_progression_state if initial_progression_state is not None else progression_state
            ),
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

    async def get_plan_item_for_user(self, plan_item_id: int, user_id: int) -> PlanItem | None:
        """Ownership-проверка через join на training_plans — 404, не 403,
        тот же принцип, что get_inclusion_for_user (CLAUDE.md). Нужен
        app.services.live_session при старте живой сессии: каждый
        plan_item_id из запроса должен принадлежать вызывающему
        пользователю, иначе нельзя раскрыть чужой PlanItem как 200/404
        двусмысленно."""
        result = await self._session.execute(
            select(PlanItem)
            .join(TrainingPlan, PlanItem.training_plan_id == TrainingPlan.id)
            .where(PlanItem.id == plan_item_id, TrainingPlan.user_id == user_id),
        )
        return result.scalar_one_or_none()

    async def list_plan_items_by_ids_for_user(self, plan_item_ids: list[int], user_id: int) -> list[PlanItem]:
        """Checkpoint 4C (issue #188) — batch-версия get_plan_item_for_user
        для Журнала: резолв source metadata нескольких сессий одним
        запросом, не по одной на сессию. Тот же ownership-принцип (join на
        training_plans по user_id) — чужой PlanItem никогда не попадёт в
        результат, даже если session_plan_items ссылается на него по
        какой-то причине (не должно происходить, но join не даёт
        просочиться молча)."""
        if not plan_item_ids:
            return []
        result = await self._session.execute(
            select(PlanItem)
            .join(TrainingPlan, PlanItem.training_plan_id == TrainingPlan.id)
            .where(PlanItem.id.in_(plan_item_ids), TrainingPlan.user_id == user_id),
        )
        return list(result.scalars().all())

    async def list_inclusions_by_ids(self, inclusion_ids: list[int]) -> list[ProgramInclusion]:
        """Checkpoint 4C (issue #188) — batch-версия get_inclusion_by_id
        для Журнала. Ownership здесь не нужна отдельно: inclusion_ids
        приходят только из PlanItem, уже отфильтрованных
        list_plan_items_by_ids_for_user выше — транзитивно тот же
        пользователь."""
        if not inclusion_ids:
            return []
        result = await self._session.execute(select(ProgramInclusion).where(ProgramInclusion.id.in_(inclusion_ids)))
        return list(result.scalars().all())

    async def get_plan_week_for_user(self, plan_week_id: int, user_id: int) -> PlanWeek | None:
        """Ownership-проверка через join на training_plans — 404, не 403,
        тот же принцип, что get_plan_item_for_user/get_inclusion_for_user
        (CLAUDE.md). Нужен issue #197 Checkpoint 3B для проверки, что
        plan_week_id в POST /api/v2/plan-items принадлежит вызывающему
        пользователю."""
        result = await self._session.execute(
            select(PlanWeek)
            .join(TrainingPlan, PlanWeek.training_plan_id == TrainingPlan.id)
            .where(PlanWeek.id == plan_week_id, TrainingPlan.user_id == user_id),
        )
        return result.scalar_one_or_none()

    async def create_plan_item(
        self, *, training_plan_id: int, exercise_id: int | None, complex_id: int | None,
        count_per_week: int, day_of_week: int | None, week_phase: WeekPhase | None, program_inclusion_id: int | None,
        plan_week_id: int | None = None,
    ) -> PlanItem:
        """C5b QA-fix (issue #188) — найдено живым 500-error логом: PlanItem
        API-контракт (PlanItemCreateRequest._exactly_one_target) требует
        РОВНО ОДНО из exercise_id/complex_id, но PlanItem.exercise_id — NOT
        NULL на уровне БД (models_program.py). Раньше это никогда не било
        живым HTTP-путём: все Complex-based PlanItem до этого чанка
        создавались только прямой ORM-вставкой в seed/тестовых скриптах,
        где exercise_id подставлялся вручную явно — сам этот repository-
        метод никогда не вызывался с exercise_id=None и complex_id!=None
        через реальный /api/v2/plan-items запрос.

        Тот же принцип, что уже подтверждён в Phase B1/C3 (PlanItem.
        exercise_id — vestigial placeholder, когда complex_id ведёт
        routing, реальный источник упражнения — ComplexItem внутри
        Complex, не это поле): при exercise_id=None и complex_id заданном
        резолвим placeholder из первого ComplexItem этого Complex по
        order_index. Если у Complex вообще нет items — не можем создать
        валидную строку (тот же NOT NULL), поднимаем ValueError с понятным
        текстом, route конвертирует в 422, не 500."""
        resolved_exercise_id = exercise_id
        if resolved_exercise_id is None and complex_id is not None:
            result = await self._session.execute(
                select(ComplexItem.exercise_id)
                .where(ComplexItem.complex_id == complex_id)
                .order_by(ComplexItem.order_index)
                .limit(1),
            )
            resolved_exercise_id = result.scalar_one_or_none()
            if resolved_exercise_id is None:
                raise ValueError("У выбранной тренировки нет упражнений")

        item = PlanItem(
            training_plan_id=training_plan_id, exercise_id=resolved_exercise_id, complex_id=complex_id,
            count_per_week=count_per_week, day_of_week=day_of_week, week_phase=week_phase,
            program_inclusion_id=program_inclusion_id, plan_week_id=plan_week_id,
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

    # --- PlanWeek (Checkpoint 1, issue #188) ---------------------------------------------

    async def get_plan_week(self, *, training_plan_id: int, week_number: int) -> PlanWeek | None:
        result = await self._session.execute(
            select(PlanWeek).where(
                PlanWeek.training_plan_id == training_plan_id, PlanWeek.week_number == week_number,
            ),
        )
        return result.scalar_one_or_none()

    async def create_plan_week(
        self, *, training_plan_id: int, week_number: int, start_date, phase: WeekPhase,
    ) -> PlanWeek:
        """Checkpoint 1.1 (issue #188), п.7 — воспроизведено конкурентным
        тестом (3 параллельных вызова ensure_current_plan_week на одном
        training_plan_id): uq_plan_weeks_plan_week_number (уже существует
        в модели с волны 1, не новый constraint) реально не даёт создать
        дубль на уровне БД, но проигравший запрос без этого падал
        необработанной IntegrityError. INSERT ... ON CONFLICT DO NOTHING
        вместо naive add()+flush() — не session.rollback() специально: этот
        метод вызывается из середины более крупной транзакции (например,
        сразу после bulk_create_plan_items_from_program_items при POST
        /program-inclusions в той же сессии), полный откат стёр бы и её."""
        stmt = (
            pg_insert(PlanWeek)
            .values(training_plan_id=training_plan_id, week_number=week_number, start_date=start_date, phase=phase)
            .on_conflict_do_nothing(constraint="uq_plan_weeks_plan_week_number")
            .returning(PlanWeek)
        )
        result = await self._session.execute(stmt)
        week = result.scalar_one_or_none()
        if week is not None:
            return week
        # Проиграли гонку — победитель уже закоммитил свою строку, читаем её.
        existing = await self.get_plan_week(training_plan_id=training_plan_id, week_number=week_number)
        if existing is None:  # pragma: no cover — теоретически недостижимо
            raise RuntimeError(
                f"plan_week for training_plan_id={training_plan_id} week_number={week_number} "
                "vanished between ON CONFLICT and re-select",
            )
        return existing

    async def list_plan_weeks(self, training_plan_id: int) -> list[PlanWeek]:
        """Все PlanWeek плана, по возрастанию week_number — issue #193
        (WORKER B): GET /api/v2/plan раньше отдавал plan_items/
        program_inclusions, но ни одной PlanWeek, хотя ensure_current_plan_week
        (Checkpoint 1, issue #188) уже материализует их. Последний элемент
        этого списка — всегда текущая неделя (ensure_current_plan_week
        вызывается перед этим методом на каждый GET и никогда не создаёт
        недели наперёд)."""
        result = await self._session.execute(
            select(PlanWeek)
            .where(PlanWeek.training_plan_id == training_plan_id)
            .order_by(PlanWeek.week_number),
        )
        return list(result.scalars().all())

    async def list_unweeked_plan_items(self, *, program_inclusion_id: int) -> list[PlanItem]:
        """PlanItem этой инклюзии, ещё не прошедшие ensure_current_plan_week
        (plan_week_id IS NULL) — свежесозданные bulk_create_plan_items_from_
        program_items (issue #188, checkpoint 1) или строки, мигрированные
        бэкфиллом до этого чекпоинта."""
        result = await self._session.execute(
            select(PlanItem).where(
                PlanItem.program_inclusion_id == program_inclusion_id, PlanItem.plan_week_id.is_(None),
            ),
        )
        return list(result.scalars().all())

    async def list_plan_items_for_week(self, *, program_inclusion_id: int, plan_week_id: int) -> list[PlanItem]:
        result = await self._session.execute(
            select(PlanItem).where(
                PlanItem.program_inclusion_id == program_inclusion_id, PlanItem.plan_week_id == plan_week_id,
            ),
        )
        return list(result.scalars().all())

    async def attach_plan_items_to_week(self, *, plan_items: list[PlanItem], plan_week_id: int) -> None:
        for item in plan_items:
            item.plan_week_id = plan_week_id
        if plan_items:
            await self._session.flush()

    async def create_plan_items_for_week_from_snapshot(
        self, *, training_plan_id: int, program_inclusion_id: int, plan_week_id: int,
        program_items_snapshot: list[dict],
    ) -> list[PlanItem]:
        """Rollover (issue #188, checkpoint 1.1) — источник ТОЛЬКО
        ProgramInclusion.snapshot["program_items"], не live ProgramItem.
        Контрактный баг checkpoint 1: если Program изменится после
        подключения, уже существующий пользователь не должен получить
        другую программу на следующей неделе — snapshot зафиксирован на
        момент подключения (см. ProgramInclusion docstring), program_id
        после подключения — только provenance.

        Та же копирующая логика, что bulk_create_plan_items_from_program_
        items при создании инклюзии, но для НОВОЙ недели — прошлая неделя
        не трогается, здесь всегда создаются новые строки, не апдейт
        старых."""
        items = []
        for program_item in program_items_snapshot:
            exercise_id = program_item.get("exercise_id")
            if exercise_id is None:
                continue
            week_phase_value = program_item.get("week_phase")
            item = PlanItem(
                training_plan_id=training_plan_id, exercise_id=exercise_id,
                complex_id=program_item.get("complex_id"), count_per_week=program_item["count_per_week"],
                day_of_week=program_item.get("day_of_week"),
                week_phase=WeekPhase(week_phase_value) if week_phase_value is not None else None,
                program_inclusion_id=program_inclusion_id, plan_week_id=plan_week_id,
            )
            self._session.add(item)
            items.append(item)
        if items:
            await self._session.flush()
        return items
