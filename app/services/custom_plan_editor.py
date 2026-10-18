"""Редактор своего плана: количество тренировок по неделям, фазы, вставка/удаление недель, размещение по
дням (UX-EDITOR; контракт checkpoints/UX-EDITOR-contract.md).

Все правки идут под локом плана (как PlanRemovalService), меняют custom_plans.spec (+ weeks = недельные
суммы, workouts), переносят занятия при сдвиге недель и затем зовут ту же converge_user_plan — она сверяет
занятия окна «текущая .. +4» по количеству (PlanConvergenceService._reconcile_spec_week). История, сессии и
кредиты не затрагиваются: засчитанные занятия не снимаются и не двигаются; операции, которым пришлось бы их
двигать, отклоняются целиком с машинным кодом."""

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import Complex, CustomPlan, PlanItem, PlanWeek, TrainingPlan
from app.db.repositories.training_plans import TrainingPlanRepository
from app.db.repositories.training_sessions import TrainingSessionRepository
from app.domain.multi_program import MAX_FUTURE_PLAN_WEEKS, plan_week_number, plan_week_start_date
from app.domain.plan_occurrence import CustomPlanRepeat, PlanItemStatus
from app.domain.plan_spec import (
    PlanSpec,
    PlanSpecError,
    add_workout,
    delete_week,
    derive_spec_from_legacy,
    insert_week,
    remove_workout,
    spec_from_json,
    validate_matrix,
    with_phase,
    with_quantities,
)
from app.services.live_session import lock_user_starts
from app.services.plan_removal import retire_open_custom_rows
from app.services.plan_view import PlanScheduleService, RescheduleError
from app.services.plan_week import PlanWeekService


class EditorError(Exception):
    """Отказ с машинным кодом (роут → 422 {code, message, ...extra})."""

    def __init__(self, code: str, message: str, **extra) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra


@dataclass
class _Ctx:
    plan: TrainingPlan
    custom_plan: CustomPlan
    spec: PlanSpec
    converted: bool
    today: date
    current_number: int
    weeks_by_number: dict[int, PlanWeek]
    weeks_by_id: dict[int, PlanWeek]
    rows: list[PlanItem]  # занятия этого плана, status != removed
    credited: set[int]
    titles: dict[int, str] = field(default_factory=dict)

    @property
    def start(self) -> int:
        return self.custom_plan.start_week_number

    def origin_number(self, row: PlanItem) -> int | None:
        week = self.weeks_by_id.get(row.origin_plan_week_id) if row.origin_plan_week_id else None
        return week.week_number if week else None

    def placed_number(self, row: PlanItem) -> int | None:
        week = self.weeks_by_id.get(row.plan_week_id) if row.plan_week_id else None
        return week.week_number if week else None


@dataclass
class EditorResult:
    ctx: _Ctx
    removed_sessions: int = 0


def _validate_plan_error(exc: PlanSpecError) -> EditorError:
    return EditorError(exc.code, exc.message)


class CustomPlanEditorService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._plans = TrainingPlanRepository(session)
        self._sessions = TrainingSessionRepository(session)

    # --- Контекст ----------------------------------------------------------------------------

    async def load(self, *, user_id: int, custom_plan_id: int, today: date, lock: bool) -> _Ctx | None:
        plan = await self._plans.get_for_user(user_id)
        if plan is None:
            return None
        if lock:
            await lock_user_starts(self._session, user_id)
            plan = await self._plans.lock_plan(plan.id)
        custom_plan = await self._plans.get_custom_plan_for_user(custom_plan_id, user_id)
        if custom_plan is None or custom_plan.training_plan_id != plan.id:
            return None
        await self._session.refresh(custom_plan)
        return await self._context(plan, custom_plan, today)

    async def _context(self, plan: TrainingPlan, custom_plan: CustomPlan, today: date) -> _Ctx:
        if custom_plan.spec is not None:
            spec, converted = spec_from_json(custom_plan.workouts, custom_plan.spec, custom_plan.repeat), True
        else:
            spec = derive_spec_from_legacy(
                list(custom_plan.workouts), list(custom_plan.weeks), CustomPlanRepeat(custom_plan.repeat),
            )
            converted = False
        weeks = await self._plans.list_plan_weeks(plan.id)
        items = await self._plans.list_custom_plan_items(custom_plan.id)
        for item in items:
            await self._session.refresh(item)
        rows = [item for item in items if item.status != PlanItemStatus.REMOVED]
        credited = await self._sessions.credited_plan_item_ids([row.id for row in rows])
        ids = set(spec.workouts) | {row.workout_definition_id for row in rows if row.workout_definition_id}
        titles: dict[int, str] = {}
        if ids:
            result = await self._session.execute(select(Complex.id, Complex.name).where(Complex.id.in_(ids)))
            titles = {cid: name for cid, name in result.all()}
        return _Ctx(
            plan=plan, custom_plan=custom_plan, spec=spec, converted=converted, today=today,
            current_number=plan_week_number(plan.created_at.date(), today),
            weeks_by_number={w.week_number: w for w in weeks}, weeks_by_id={w.id: w for w in weeks},
            rows=rows, credited=credited, titles=titles,
        )

    def _persist(self, ctx: _Ctx, spec: PlanSpec) -> None:
        cp = ctx.custom_plan
        cp.spec = spec.to_json()
        cp.weeks = spec.totals()
        cp.workouts = list(spec.workouts)
        cp.repeat = spec.repeat.value

    async def _converge(self, ctx: _Ctx, spec: PlanSpec) -> _Ctx:
        """Недели окна, которые покрывает план, создаются и сверяются единственной converge_user_plan."""
        last = min(ctx.start + spec.week_count - 1, ctx.current_number + MAX_FUTURE_PLAN_WEEKS)
        await PlanWeekService(self._session).ensure_plannable_week(
            training_plan_id=ctx.plan.id, week_number=max(last, ctx.current_number), today=ctx.today,
        )
        await self._session.flush()
        return await self._context(ctx.plan, ctx.custom_plan, ctx.today)

    # --- Правки ------------------------------------------------------------------------------

    def _week_state(self, ctx: _Ctx, calendar_week: int) -> str:
        if calendar_week < ctx.current_number:
            return "past"
        return "current" if calendar_week == ctx.current_number else "future"

    def _done_in_week(self, ctx: _Ctx, calendar_week: int, workout_id: int) -> int:
        return sum(
            1 for row in ctx.rows
            if row.id in ctx.credited and row.workout_definition_id == workout_id
            and ctx.origin_number(row) == calendar_week
        )

    async def set_quantities(self, ctx: _Ctx, index: int, quantities: dict[int, int]) -> EditorResult:
        calendar_week = ctx.start + index - 1
        if index < 1 or index > ctx.spec.week_count:
            raise EditorError("week_not_found", "Нет такой недели")
        if calendar_week < ctx.current_number:
            raise EditorError("week_not_editable", "Прошедшую неделю изменить нельзя", reason="past")
        for workout_id, count in quantities.items():
            done = self._done_in_week(ctx, calendar_week, workout_id)
            if count < done:
                raise EditorError(
                    "below_done", f"Уже выполнено занятий: {done} — меньше поставить нельзя", min=done,
                    workout_id=workout_id,
                )
        try:
            spec = with_quantities(ctx.spec, index - 1, quantities)
        except PlanSpecError as exc:
            raise _validate_plan_error(exc) from exc
        self._persist(ctx, spec)
        return EditorResult(await self._converge(ctx, spec))

    async def set_phase(self, ctx: _Ctx, index: int, phase: str) -> EditorResult:
        if index < 1 or index > ctx.spec.week_count:
            raise EditorError("week_not_found", "Нет такой недели")
        if ctx.start + index - 1 < ctx.current_number:
            raise EditorError("week_not_editable", "Прошедшую неделю изменить нельзя", reason="past")
        try:
            spec = with_phase(ctx.spec, index - 1, phase)
        except PlanSpecError as exc:
            raise _validate_plan_error(exc) from exc
        self._persist(ctx, spec)
        return EditorResult(ctx=await self._context(ctx.plan, ctx.custom_plan, ctx.today))

    async def add_workout(self, ctx: _Ctx, workout_id: int) -> EditorResult:
        try:
            spec = add_workout(ctx.spec, workout_id)
        except PlanSpecError as exc:
            raise _validate_plan_error(exc) from exc
        self._persist(ctx, spec)
        return EditorResult(await self._converge(ctx, spec))

    async def remove_workout(self, ctx: _Ctx, workout_id: int) -> EditorResult:
        try:
            spec = remove_workout(ctx.spec, workout_id)
        except PlanSpecError as exc:
            raise _validate_plan_error(exc) from exc
        mine = [row for row in ctx.rows if row.workout_definition_id == workout_id]
        removed = await retire_open_custom_rows(self._session, ctx.plan, mine, today=ctx.today)
        self._persist(ctx, spec)
        result = await self._converge(ctx, spec)
        return EditorResult(result, removed_sessions=removed)

    async def insert_week(self, ctx: _Ctx, after_index: int) -> EditorResult:
        if not 0 <= after_index <= ctx.spec.week_count:
            raise EditorError("week_not_found", "Нет такой недели")
        boundary = ctx.start + after_index  # календарная неделя новой пустой недели
        if boundary <= ctx.current_number:
            raise EditorError(
                "week_not_editable", "Вставить неделю можно только в будущее",
                reason="current" if boundary == ctx.current_number else "past",
            )
        try:
            spec = insert_week(ctx.spec, after_index)
        except PlanSpecError as exc:
            raise _validate_plan_error(exc) from exc
        await self._refuse_if_done_from(ctx, boundary)
        await self._shift_rows(ctx, boundary, +1)
        self._persist(ctx, spec)
        return EditorResult(await self._converge(ctx, spec))

    async def delete_week(self, ctx: _Ctx, index: int) -> EditorResult:
        if index < 1 or index > ctx.spec.week_count:
            raise EditorError("week_not_found", "Нет такой недели")
        boundary = ctx.start + index - 1
        if boundary <= ctx.current_number:
            raise EditorError(
                "week_not_editable", "Удалить можно только будущую неделю",
                reason="current" if boundary == ctx.current_number else "past",
            )
        try:
            spec = delete_week(ctx.spec, index - 1)
        except PlanSpecError as exc:
            raise _validate_plan_error(exc) from exc
        done_here = [row for row in ctx.rows if row.id in ctx.credited and ctx.origin_number(row) == boundary]
        open_here = [
            row for row in ctx.rows
            if row.id not in ctx.credited and ctx.origin_number(row) == boundary
        ]
        if done_here:
            raise EditorError(
                "week_has_done_sessions", "В этой неделе есть выполненное занятие — удалить её нельзя",
                done=len(done_here), open=len(open_here),
            )
        await self._refuse_if_done_from(ctx, boundary + 1)
        removed = await retire_open_custom_rows(self._session, ctx.plan, open_here, today=ctx.today)
        await self._shift_rows(ctx, boundary + 1, -1)
        self._persist(ctx, spec)
        result = await self._converge(ctx, spec)
        return EditorResult(result, removed_sessions=removed)

    async def _refuse_if_done_from(self, ctx: _Ctx, first_week: int) -> None:
        done = [
            row for row in ctx.rows if row.id in ctx.credited
            and ((ctx.origin_number(row) or 0) >= first_week or (ctx.placed_number(row) or 0) >= first_week)
        ]
        if done:
            raise EditorError(
                "week_has_done_sessions", "В следующих неделях есть выполненные занятия — сдвинуть их нельзя",
                done=len(done),
            )

    async def _shift_rows(self, ctx: _Ctx, first_week: int, delta: int) -> None:
        """Занятия недель >= first_week сдвигаются на delta календарных недель (идентичность строки,
        occurrence_index, день и статус сохраняются). Цель вне окна планирования — занятие снимается
        (пересоздастся, когда неделя войдёт в окно)."""
        rows = [
            row for row in ctx.rows
            if (ctx.origin_number(row) or 0) >= first_week or (ctx.placed_number(row) or 0) >= first_week
        ]
        window_end = ctx.current_number + MAX_FUTURE_PLAN_WEEKS
        weeks_service = PlanWeekService(self._session)
        needed = {
            n + delta
            for row in rows
            for n in (ctx.origin_number(row), ctx.placed_number(row))
            if n is not None and n >= first_week
        }
        targets: dict[int, PlanWeek] = {}
        # Недели-цели создаём при остановленном плане: сходимость не должна материализовать в них занятия
        # ДО переноса (иначе уникальный индекс origin+plan+occurrence_index и дубли).
        ctx.custom_plan.is_active = False
        try:
            for number in sorted(needed):
                if ctx.current_number <= number <= window_end:
                    week = await weeks_service.ensure_plannable_week(
                        training_plan_id=ctx.plan.id, week_number=number, today=ctx.today,
                    )
                    if week is not None:
                        targets[number] = week
        finally:
            ctx.custom_plan.is_active = True
        ctx.weeks_by_number.update(targets)
        everything = await self._plans.list_custom_plan_items(ctx.custom_plan.id)  # включая снятые
        max_index: dict[int, int] = {}
        for item in everything:
            if item.origin_plan_week_id is not None:
                max_index[item.origin_plan_week_id] = max(
                    max_index.get(item.origin_plan_week_id, 0), item.occurrence_index or 0,
                )
        for row in sorted(rows, key=lambda r: r.id):
            origin, placed = ctx.origin_number(row), ctx.placed_number(row)
            new_origin = origin + delta if origin is not None and origin >= first_week else origin
            new_placed = placed + delta if placed is not None and placed >= first_week else placed
            if (new_origin != origin and new_origin not in targets) or (
                new_placed != placed and new_placed not in targets
            ):
                row.status = PlanItemStatus.REMOVED.value
                continue
            if new_origin != origin and new_origin is not None:
                week = targets[new_origin]
                row.origin_plan_week_id = week.id
                # Идентичность занятия — id строки; индекс внутри новой origin-недели выдаётся заново
                # (уникальный индекс, снятые строки тоже занимают свои индексы).
                max_index[week.id] = max_index.get(week.id, 0) + 1
                row.occurrence_index = max_index[week.id]
            if new_placed != placed and new_placed is not None:
                week = targets[new_placed]
                row.plan_week_id = week.id
                if row.day_of_week is not None:
                    row.scheduled_date = week.start_date + timedelta(days=row.day_of_week)
        await self._plans.flush()

    # --- Расписание недели -------------------------------------------------------------------

    def _week_rows(self, ctx: _Ctx, calendar_week: int) -> list[PlanItem]:
        return [row for row in ctx.rows if ctx.placed_number(row) == calendar_week]

    async def place(self, ctx: _Ctx, index: int, workout_id: int, day: int, *, user_id: int, unplace: bool) -> _Ctx:
        calendar_week = ctx.start + index - 1
        if not 0 <= day <= 6:
            raise EditorError("invalid_day", "День недели: 0..6")
        if calendar_week < ctx.current_number:
            raise EditorError("week_not_editable", "Прошедшую неделю изменить нельзя", reason="past")
        if calendar_week == ctx.current_number and not unplace and day < (ctx.today - self._monday(ctx, calendar_week)).days:
            raise EditorError("past_day", "Этот день уже прошёл")
        rows = [row for row in self._week_rows(ctx, calendar_week) if row.workout_definition_id == workout_id]
        service = PlanScheduleService(self._session)
        if unplace:
            placed = sorted(
                (row for row in rows if row.day_of_week == day and row.id not in ctx.credited),
                key=lambda r: -(r.occurrence_index or 0),
            )
            if not placed:
                raise EditorError("nothing_to_unplace", "На этот день нечего снимать")
            target, new_day = placed[0], None
        else:
            free = sorted(
                (row for row in rows if row.day_of_week is None and row.id not in ctx.credited),
                key=lambda r: r.occurrence_index or 0,
            )
            if not free:
                raise EditorError("quota_exhausted", "Все занятия размещены")
            target, new_day = free[0], day
        try:
            await service.reschedule(
                user_id=user_id, plan_item_id=target.id, today=ctx.today, day_of_week=new_day,
                plan_week_id=None, scheduled_date=None,
            )
        except RescheduleError as exc:
            raise EditorError(getattr(exc, "code", "reschedule_refused"), str(exc)) from exc
        return await self._context(ctx.plan, ctx.custom_plan, ctx.today)

    def _monday(self, ctx: _Ctx, calendar_week: int) -> date:
        week = ctx.weeks_by_number.get(calendar_week)
        return week.start_date if week else plan_week_start_date(ctx.plan.created_at.date(), calendar_week)


# --- Модели ответа (dict-ы; роут оборачивает в pydantic) ------------------------------------


def editor_view(ctx: _Ctx) -> dict:
    spec = ctx.spec
    weeks = []
    for i in range(spec.week_count):
        number = ctx.start + i
        by_workout: dict[int, int] = {}
        done: dict[int, int] = {}
        for position, workout_id in enumerate(spec.workouts):
            by_workout[workout_id] = by_workout.get(workout_id, 0) + spec.quantities[position][i]
        for row in ctx.rows:
            if row.id in ctx.credited and ctx.origin_number(row) == number and row.workout_definition_id:
                done[row.workout_definition_id] = done.get(row.workout_definition_id, 0) + 1
        placed = sum(1 for row in ctx.rows if ctx.placed_number(row) == number and row.day_of_week is not None)
        state = "past" if number < ctx.current_number else ("current" if number == ctx.current_number else "future")
        weeks.append({
            "index": i + 1, "week_number": number,
            "start_date": plan_week_start_date(ctx.plan.created_at.date(), number), "state": state,
            "phase": spec.phases[i], "total": spec.totals()[i],
            "quantities": {str(k): v for k, v in by_workout.items()},
            "done": {str(k): v for k, v in done.items()}, "placed": placed,
        })
    current_index = ctx.current_number - ctx.start + 1
    return {
        "id": ctx.custom_plan.id, "display_name": ctx.custom_plan.display_name,
        "repeat": spec.repeat.value, "start_week_number": ctx.start, "is_active": ctx.custom_plan.is_active,
        "current_week_index": current_index if 1 <= current_index <= spec.week_count else None,
        "converted": ctx.converted, "notice": spec.notice if not ctx.converted else None,
        "workouts": [
            {"workout_id": wid, "title": ctx.titles.get(wid, "Тренировка")} for wid in dict.fromkeys(spec.workouts)
        ],
        "weeks": weeks,
    }


def schedule_view(ctx: _Ctx, index: int) -> dict | None:
    if index < 1 or index > ctx.spec.week_count:
        return None
    number = ctx.start + index - 1
    monday = ctx.weeks_by_number[number].start_date if number in ctx.weeks_by_number else plan_week_start_date(
        ctx.plan.created_at.date(), number,
    )
    rows = [row for row in ctx.rows if ctx.placed_number(row) == number]
    days = []
    for day in range(7):
        date_ = monday + timedelta(days=day)
        days.append({
            "day": day, "date": date_,
            "state": "past" if date_ < ctx.today else ("today" if date_ == ctx.today else "future"),
            "total": sum(1 for row in rows if row.day_of_week == day),
        })
    workouts = []
    ordered = list(dict.fromkeys([*ctx.spec.workouts, *(r.workout_definition_id for r in rows if r.workout_definition_id)]))
    for wid in ordered:
        mine = sorted((r for r in rows if r.workout_definition_id == wid), key=lambda r: r.occurrence_index or 0)
        if not mine and wid not in ctx.spec.workouts:
            continue
        by_day = [sum(1 for r in mine if r.day_of_week == d) for d in range(7)]
        workouts.append({
            "workout_id": wid, "title": ctx.titles.get(wid, "Тренировка"), "quantity": len(mine),
            "placed_by_day": by_day, "remaining": sum(1 for r in mine if r.day_of_week is None),
            "items": [
                {
                    "plan_item_id": r.id, "day": r.day_of_week, "done": r.id in ctx.credited,
                    "missed": r.id not in ctx.credited and r.day_of_week is not None
                    and monday + timedelta(days=r.day_of_week) < ctx.today,
                }
                for r in mine
            ],
        })
    return {
        "index": index, "week_number": number, "start_date": monday,
        "state": "past" if number < ctx.current_number else ("current" if number == ctx.current_number else "future"),
        "days": days, "workouts": workouts,
    }


__all__ = [
    "CustomPlanEditorService", "EditorError", "EditorResult", "editor_view", "schedule_view", "validate_matrix",
]
