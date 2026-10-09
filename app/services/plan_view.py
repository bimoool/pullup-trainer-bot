"""Чтение плана v2 и перенос занятий (issue #304, PROGRAM_PLAN_V2 §4–§7).

PlanViewService — производные состояния занятий (completed / missed / infeasible / available /
too_early), сводка недели «N из M» по занятиям (PL1) и статус отдыха MAIN (K1/K2) для GET /plan.
Ничего не пишет: материализация — только converge_user_plan (PL7).

PlanScheduleService — перенос занятия (PL6): неделя и/или день, любой источник (курс, свой план,
ручное); идентичность занятия (origin_plan_week_id, occurrence_index) не меняется; засчитанное
(историческое) занятие не двигается."""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.models_program import (
    CustomPlan,
    PlanItem,
    PlanWeek,
    ProgramInclusion,
    SessionStatus,
    TrainingPlan,
)
from app.db.repositories.programs import ProgramRepository
from app.db.repositories.training_plans import TrainingPlanRepository
from app.db.repositories.training_sessions import TrainingSessionRepository
from app.domain.multi_program import (
    count_done_per_plan_item,
    is_plannable_week_number,
    plan_week_number,
)
from app.domain.plan_occurrence import (
    MAIN_SPACING_GROUP,
    OccurrenceInput,
    OccurrenceStateResult,
    PlanItemStatus,
    WeekSummary,
    available_from,
    derive_occurrence_states,
    derive_slots,
    summarize_week,
)
from app.services.plan_spacing import MainSpacingService
from app.services.plan_week import PlanWeekService
from app.services.training_analytics import resolve_timezone


@dataclass(frozen=True)
class SpacingView:
    spacing_group: str
    min_days_between_starts: int
    last_start_date: date | None
    available_from: date | None


@dataclass(frozen=True)
class PlanItemView:
    item: PlanItem
    done_count: int
    state: OccurrenceStateResult | None
    spacing_group: str | None
    credited_session_id: int | None


@dataclass(frozen=True)
class PlanView:
    items: list[PlanItemView]
    week_summaries: list[tuple[int, WeekSummary]]
    spacing: list[SpacingView]
    custom_plans: list[CustomPlan]


class PlanViewService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._plans = TrainingPlanRepository(session)
        self._sessions = TrainingSessionRepository(session)
        self._programs = ProgramRepository(session)

    async def build(
        self, *, plan: TrainingPlan, user: User, today: date, plan_weeks: list[PlanWeek],
        plan_items: list[PlanItem], inclusions: list[ProgramInclusion],
    ) -> PlanView:
        tz = resolve_timezone(user.timezone)
        week_by_id = {week.id: week for week in plan_weeks}
        visible = await self._actionable_rows(plan_items, inclusions, week_by_id, today)

        # Старые агрегатные строки — прежний счётчик «сделано на своей неделе» по M2M (#258).
        aggregates = [item for item in visible if item.occurrence_index is None]
        week_start_by_item = {
            item.id: week_by_id[item.plan_week_id].start_date for item in aggregates if item.plan_week_id in week_by_id
        }
        performed = await self._plans.list_completed_session_times_by_plan_item(
            user_id=user.id, plan_item_ids=list(week_start_by_item),
        )
        aggregate_done = count_done_per_plan_item(
            week_start_by_item, [(item_id, at.astimezone(tz).date()) for item_id, at in performed],
        )

        # Занятия — явный кредит завершённой сессией (PL2/PL4), в любой неделе.
        occurrences = [item for item in visible if item.occurrence_index is not None]
        credited: dict[int, int] = {}
        for item_id, session_id, status, _ in await self._sessions.credits_for_plan_items([o.id for o in occurrences]):
            if status == SessionStatus.COMPLETED and item_id not in credited:
                credited[item_id] = session_id

        spacing_group_by_item = await self._spacing_groups(occurrences, inclusions)
        spacing_service = MainSpacingService(self._session)
        min_days_by_group = await spacing_service.spacing_by_group(user.id)
        last = await spacing_service.last_main_start_at(user.id)
        last_date = last.astimezone(tz).date() if last is not None else None
        available_by_group = {group: available_from(last_date, days) for group, days in min_days_by_group.items()}

        inputs: list[OccurrenceInput] = []
        for item in visible:
            week = week_by_id.get(item.plan_week_id)
            if week is None:
                continue
            inputs.append(OccurrenceInput(
                item_id=item.id, week_start=week.start_date, occurrence_index=item.occurrence_index,
                spacing_group=spacing_group_by_item.get(item.id), completed=item.id in credited,
                scheduled_date=item.scheduled_date, legacy_aggregate=item.occurrence_index is None,
                planned_count=item.count_per_week, done_count=aggregate_done.get(item.id, 0),
            ))
        states = derive_occurrence_states(
            inputs, today=today, available_from_by_group=available_by_group, min_days_by_group=min_days_by_group,
        )

        week_id_by_item = {item.id: item.plan_week_id for item in visible}
        summaries = [
            (week.id, summarize_week([occ for occ in inputs if week_id_by_item[occ.item_id] == week.id], states))
            for week in plan_weeks
        ]

        views = [
            PlanItemView(
                item=item,
                done_count=(1 if item.id in credited else 0) if item.occurrence_index is not None
                else aggregate_done.get(item.id, 0),
                state=states.get(item.id), spacing_group=spacing_group_by_item.get(item.id),
                credited_session_id=credited.get(item.id),
            )
            for item in visible
        ]
        spacing = [
            SpacingView(
                spacing_group=MAIN_SPACING_GROUP, min_days_between_starts=min_days_by_group[MAIN_SPACING_GROUP],
                last_start_date=last_date, available_from=available_by_group[MAIN_SPACING_GROUP],
            ),
        ]
        return PlanView(
            items=views, week_summaries=summaries, spacing=spacing,
            custom_plans=await self._plans.list_custom_plans(plan.id),
        )

    async def _actionable_rows(
        self, plan_items: list[PlanItem], inclusions: list[ProgramInclusion], week_by_id: dict[int, PlanWeek],
        today: date,
    ) -> list[PlanItem]:
        """Строки плана для показа: без снятых (status = removed) и без НЕзасчитанных строк убранного
        курса (is_active = false) в текущей/будущих неделях (#304 C1) — их старт сервер отклоняет, поэтому
        «Начать» / available и «0 из 3» они не дают. Засчитанные строки убранного курса и прошлые недели
        (история) остаются; строки в БД не меняются (повторное «Добавить» курса вернёт их как были)."""
        inactive = {inclusion.id for inclusion in inclusions if not inclusion.is_active}
        rows = [item for item in plan_items if item.status != PlanItemStatus.REMOVED]
        candidates = [
            item.id for item in rows
            if item.program_inclusion_id in inactive and item.plan_week_id in week_by_id
            and week_by_id[item.plan_week_id].start_date + timedelta(days=6) >= today
        ]
        if not candidates:
            return rows
        hidden = set(candidates) - await self._sessions.credited_plan_item_ids(candidates)
        return [item for item in rows if item.id not in hidden]

    async def _spacing_groups(self, occurrences: list[PlanItem], inclusions: list[ProgramInclusion]) -> dict[int, str]:
        """Группа отдыха занятия курса — из слотов его инклюзии (свой план/ручные — без группы, K4)."""
        slots_by_inclusion: dict[int, dict[str, str | None]] = {}
        for inclusion in inclusions:
            program = await self._programs.get_by_id(inclusion.program_id)
            slots = derive_slots(
                inclusion.snapshot, program_slots=program.slots if program else None,
                program_frequency=program.frequency if program else None,
            )
            slots_by_inclusion[inclusion.id] = {slot.key: slot.spacing_group for slot in slots}
        result: dict[int, str] = {}
        for item in occurrences:
            if item.program_inclusion_id is None or item.program_slot_key is None:
                continue
            group = slots_by_inclusion.get(item.program_inclusion_id, {}).get(item.program_slot_key)
            if group is not None:
                result[item.id] = group
        return result


class RescheduleError(ValueError):
    """Перенос невозможен (роут → 422 с текстом)."""


class PlanScheduleService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._plans = TrainingPlanRepository(session)
        self._sessions = TrainingSessionRepository(session)

    async def reschedule(
        self, *, user_id: int, plan_item_id: int, today: date, day_of_week: int | None,
        plan_week_id: int | None, scheduled_date: date | None,
    ) -> PlanItem | None:
        """None — занятие не найдено / чужое (404). RescheduleError — нельзя (422)."""
        plan = await self._plans.get_for_user(user_id)
        item = await self._plans.get_plan_item_for_user(plan_item_id, user_id)
        if plan is None or item is None or item.status == PlanItemStatus.REMOVED:
            return None
        if item.occurrence_index is None and not item.legacy_aggregate and item.program_inclusion_id is not None:
            # Строка курса старой формы, которую converge_user_plan не заменил занятиями (курс снят / не
            # повторяющийся / без слотов): как и раньше (#188 D2), программные строки не переносятся — 404.
            return None
        if item.legacy_aggregate or item.occurrence_index is None:
            raise RescheduleError("Это историческая строка плана — её нельзя перенести")
        if await self._sessions.credits_for_plan_items([item.id]):
            raise RescheduleError("Засчитанную тренировку перенести нельзя")
        current_number = plan_week_number(plan.created_at.date(), today)
        source = await self._plans.get_plan_week_for_user(item.plan_week_id, user_id) if item.plan_week_id else None
        if source is not None and source.week_number < current_number:
            raise RescheduleError("Неделя недоступна для планирования")

        target = source
        if scheduled_date is not None:
            number = plan_week_number(plan.created_at.date(), scheduled_date)
            if not is_plannable_week_number(number, current_number):
                raise RescheduleError("Неделя недоступна для планирования")
            target = await PlanWeekService(self._session).ensure_plannable_week(
                training_plan_id=plan.id, week_number=number, today=today,
            )
            if plan_week_id is not None and target is not None and target.id != plan_week_id:
                raise RescheduleError("Дата не попадает в выбранную неделю")
            day_of_week = (scheduled_date - target.start_date).days
        elif plan_week_id is not None:
            target = await self._plans.get_plan_week_for_user(plan_week_id, user_id)
            if target is None:
                return None
            if not is_plannable_week_number(target.week_number, current_number):
                raise RescheduleError("Неделя недоступна для планирования")
        if target is None:
            raise RescheduleError("Неделя недоступна для планирования")

        item.plan_week_id = target.id
        item.day_of_week = day_of_week
        item.scheduled_date = target.start_date + timedelta(days=day_of_week) if day_of_week is not None else None
        item.status = PlanItemStatus.RESCHEDULED.value
        await self._plans.flush()
        return item
