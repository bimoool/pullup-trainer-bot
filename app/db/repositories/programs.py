from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import (
    Complex,
    ComplexItem,
    Exercise,
    Program,
    ProgramItem,
    ProgressionStrategyProfile,
)
from app.domain.multi_program import MetricType


class ProgramRepository:
    """Read-only на этой волне (issue #165, волна 3) — администрирование
    каталога (создание/правка Program/ProgramItem/Exercise) не запрошено,
    единственный писатель каталога пока scripts/backfill_multi_program.py.

    Phase A1 (issue #214, Worker B) добавляет минимальные write-методы для
    Complex/ComplexItem — только под protocol storage, не полноценное CRUD.

    Phase C1 (issue #188) добавляет create_user_exercise — минимальный
    write-метод под пользовательский Exercise (Workout Builder foundation),
    тот же принцип: узкая capability, не полноценное CRUD (update/delete/
    rename Exercise — явно вне scope этой волны).

    Phase C2 (issue #188) добавляет Workout core (list/visibility/edit-
    guard/update title) — тот же get_X_for_user-паттерн, только title
    editing, без WorkoutItem CRUD/reorder/delete (следующая волна).

    Phase C3 (issue #188) добавляет WorkoutItem CRUD (add/update/delete/
    move) — order_index управляется автоматически (append/compact/swap),
    никогда не задаётся напрямую вызывающим кодом извне репозитория."""

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

    async def list_complexes_by_ids(self, complex_ids: list[int]) -> list[Complex]:
        """Phase B1 gate fix (issue #215) — batch-версия get_complex для
        резолва Workout title (Complex.name) в Журнале/списке сессий, тот
        же batch-принцип, что list_exercises_by_ids выше. Нужна, потому
        что _resolve_session_titles до этого фикса вообще не знал про
        complex_id-based PlanItem — резолвил title только через
        program_inclusion_id/exercise_id, никогда не проверяя complex_id,
        и потому мог случайно взять несвязанный exercise_id вместо
        настоящего названия Workout."""
        if not complex_ids:
            return []
        result = await self._session.execute(select(Complex).where(Complex.id.in_(complex_ids)))
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

    # --- Complex/ComplexItem write methods (Phase A1, issue #214) ---

    async def get_visible_exercise_for_user(self, exercise_id: int, user_id: int) -> Exercise | None:
        """Phase C1 (issue #188) — тот же get_X_for_user-паттерн, что уже
        системно используется в проекте (app.db.repositories.training_plans).
        Возвращает Exercise только если он system (видим всем) или user
        exercise, принадлежащий именно этому user_id — иначе None. Route-
        уровень конвертирует None -> 404, не 403 (существующая конвенция
        проекта — не раскрывать существование чужого ресурса)."""
        exercise = await self._session.get(Exercise, exercise_id)
        if exercise is None:
            return None
        if exercise.source_type == "system" or exercise.owner_user_id == user_id:
            return exercise
        return None

    async def create_user_exercise(self, *, name: str, owner_user_id: int) -> Exercise:
        """Phase C1 (issue #188) — создание пользовательского Exercise через
        Workout Builder. Всегда source_type='user' — system Exercise через
        этот путь создать нельзя (тот же принцип, что create_complex не
        принимает source_type снаружи для пользовательского пути). Минимум
        обязательных полей модели — metric_type/category нужны схемой,
        значения по умолчанию для нового пользовательского упражнения без
        дополнительного UI на этой волне (Builder ещё не выбирает тип
        метрики отдельно от самого упражнения на этом шаге)."""
        exercise = Exercise(
            name=name, metric_type=MetricType.REPS, category="user",
            source_type="user", owner_user_id=owner_user_id,
        )
        self._session.add(exercise)
        await self._session.flush()
        return exercise

    async def get_complex(self, complex_id: int) -> Complex | None:
        """Read Complex с новыми полями source_type/owner_user_id (Phase A1)."""
        return await self._session.get(Complex, complex_id)

    async def list_user_workouts(self, user_id: int) -> list[Complex]:
        """Phase C2 (issue #188) — только user Workout текущего владельца,
        не system и не чужие. Для экрана "Мои тренировки" — не каталог
        (system Workout здесь намеренно не включается, отдельный endpoint
        для каталога не проектируется на этой волне)."""
        result = await self._session.execute(
            select(Complex).where(Complex.owner_user_id == user_id).order_by(Complex.id),
        )
        return list(result.scalars().all())

    async def get_visible_workout_for_user(self, complex_id: int, user_id: int) -> Complex | None:
        """Тот же get_X_for_user-паттерн, что уже системно используется в
        проекте (training_plans.py, и C1's get_visible_exercise_for_user).
        Видим: system (любому) или свой user Workout. Иначе None — route
        конвертирует в 404, не 403."""
        complex_ = await self._session.get(Complex, complex_id)
        if complex_ is None:
            return None
        if complex_.source_type == "system" or complex_.owner_user_id == user_id:
            return complex_
        return None

    async def get_editable_workout_for_user(self, complex_id: int, user_id: int) -> Complex | None:
        """Строже, чем get_visible_workout_for_user — system Workout
        НЕ редактируем никем через этот путь (read-only для всех
        обычных пользователей), только свой user Workout."""
        complex_ = await self._session.get(Complex, complex_id)
        if complex_ is None:
            return None
        if complex_.source_type == "user" and complex_.owner_user_id == user_id:
            return complex_
        return None

    async def update_complex_title(self, complex_id: int, title: str) -> None:
        """Минимальное обновление названия — ownership уже проверен
        вызывающим кодом через get_editable_workout_for_user, здесь только
        сам UPDATE."""
        complex_ = await self._session.get(Complex, complex_id)
        if complex_ is not None:
            complex_.name = title
            await self._session.flush()

    async def create_complex(
        self,
        *,
        name: str,
        source_type: str = "system",
        owner_user_id: int | None = None,
    ) -> Complex:
        """Минимальный create для Complex с новыми полями (Phase A1).
        Инвариант (system → owner_user_id IS NULL, user → owner_user_id IS NOT NULL)
        проверяется вызывающим сервисным слоем, не здесь."""
        complex = Complex(name=name, source_type=source_type, owner_user_id=owner_user_id)
        self._session.add(complex)
        await self._session.flush()
        return complex

    async def create_complex_item(
        self,
        *,
        complex_id: int,
        exercise_id: int,
        order_index: int,
        sets: int,
        target_value: float | None = None,
        target_unit: str | None = None,
        rest_seconds: int | None = None,
        protocol: dict | None = None,
    ) -> ComplexItem:
        """Минимальный create для ComplexItem с новым полем protocol (Phase A1).
        Старые поля sets/target_value/target_unit/rest_seconds остаются
        для backward compatibility."""
        item = ComplexItem(
            complex_id=complex_id,
            exercise_id=exercise_id,
            order_index=order_index,
            sets=sets,
            target_value=target_value,
            target_unit=target_unit,
            rest_seconds=rest_seconds,
            protocol=protocol,
        )
        self._session.add(item)
        await self._session.flush()
        return item

    async def get_complex_item(self, item_id: int) -> ComplexItem | None:
        """Phase C3 (issue #188) — read одного ComplexItem по id, для
        ownership-проверки (item принадлежит editable Workout) перед
        update/delete/move."""
        return await self._session.get(ComplexItem, item_id)

    async def add_workout_item(self, *, complex_id: int, exercise_id: int, protocol: dict) -> ComplexItem:
        """Phase C3 — order_index автоматически: max(existing)+1, 0 для
        первого item (тот же 0-based convention, что уже используют
        create_complex_item's вызывающие места и workout_snapshot.py's
        сортировка). sets=0 — тот же placeholder, что Phase B1 уже
        использует для protocol-JSONB-driven items (legacy-поле, реальный
        источник правды — protocol)."""
        existing = await self.list_complex_items(complex_id)
        next_order_index = (max((item.order_index for item in existing), default=-1)) + 1
        return await self.create_complex_item(
            complex_id=complex_id, exercise_id=exercise_id, order_index=next_order_index,
            sets=0, protocol=protocol,
        )

    async def update_workout_item(
        self, item_id: int, *, exercise_id: int | None = None, protocol: dict | None = None,
    ) -> ComplexItem | None:
        """Phase C3 — оба поля опциональны на уровне repository (route
        уже требует хотя бы одно через схему), order_index этим методом
        никогда не меняется (раздел 4 задачи)."""
        item = await self._session.get(ComplexItem, item_id)
        if item is None:
            return None
        if exercise_id is not None:
            item.exercise_id = exercise_id
        if protocol is not None:
            item.protocol = protocol
        await self._session.flush()
        return item

    async def delete_workout_item(self, item_id: int) -> None:
        """Phase C3 — удаляет item и нормализует order_index оставшихся
        (0, 1, 2, ... без дырок), тот же принцип, что и раньше — порядок
        item'ов внутри Workout всегда плотный 0-based."""
        item = await self._session.get(ComplexItem, item_id)
        if item is None:
            return
        complex_id = item.complex_id
        await self._session.delete(item)
        await self._session.flush()

        remaining = await self.list_complex_items(complex_id)
        for index, remaining_item in enumerate(remaining):
            if remaining_item.order_index != index:
                remaining_item.order_index = index
        await self._session.flush()

    async def move_workout_item(self, item_id: int, *, direction: str) -> bool:
        """Phase C3 — простой swap с соседом по order_index, не
        произвольный target index (drag-and-drop явно вне scope MVP).
        Возвращает False (idempotent no-op) на границе — первый item +
        "up", последний + "down" — не ошибка, просто нечего двигать; это
        решение, не 409/422, потому что попытка подвинуть первый элемент
        ещё выше — не некорректный запрос пользователя (кнопка ↑ на
        первой позиции по UX-контракту уже disabled, но backend не должен
        падать, если фронт всё же вызовет её по гонке/багу)."""
        item = await self._session.get(ComplexItem, item_id)
        if item is None:
            return False
        siblings = await self.list_complex_items(item.complex_id)
        position = next((i for i, sibling in enumerate(siblings) if sibling.id == item_id), None)
        if position is None:
            return False

        swap_position = position - 1 if direction == "up" else position + 1
        if swap_position < 0 or swap_position >= len(siblings):
            return False  # граница — idempotent no-op, не ошибка

        neighbor = siblings[swap_position]
        item.order_index, neighbor.order_index = neighbor.order_index, item.order_index
        await self._session.flush()
        return True


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
