"""Чтение плана v2 и перенос занятий (issue #304, PROGRAM_PLAN_V2 §4–§7).

PlanViewService — производные состояния занятий (completed / missed / infeasible / available /
too_early), сводка недели «N из M» по занятиям (PL1) и статус отдыха MAIN (K1/K2) для GET /plan.
Ничего не пишет: материализация — только converge_user_plan (PL7).

PlanScheduleService — перенос занятия (PL6): неделя и/или день, любой источник (курс, свой план,
ручное); идентичность занятия (origin_plan_week_id, occurrence_index) не меняется; засчитанное
(историческое) занятие не двигается."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.models_program import (
    CustomPlan,
    PlanItem,
    PlanWeek,
    ProgramInclusion,
    SessionStatus,
    TrainingPlan,
    TrainingSession,
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
    MAIN_SLOT_KEY,
    MAIN_SPACING_GROUP,
    InclusionStatus,
    OccurrenceInput,
    OccurrenceState,
    OccurrenceStateResult,
    PlanItemStatus,
    WeekSummary,
    available_from,
    derive_occurrence_states,
    derive_slots,
    summarize_week,
    weekly_capacity,
)
from app.domain.pullups_v5 import PROGRAM_VERSION, WorkoutRole, is_v5_state
from app.services.plan_spacing import MainSpacingService
from app.services.plan_week import PlanWeekService
from app.services.program_access import ProgramAccessService
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
    # UX-01 (CONTRACT_A_B §1): единственный источник «Начать» — тем же правилом, что проверяет старт.
    start_allowed: bool = False
    blocked_reason: str | None = None
    # UX-08: какое это занятие курса (А/Б по последовательности прогрессии).
    session_variant: str | None = None
    session_variant_basis: str | None = None
    session_ordinal: int | None = None


@dataclass(frozen=True)
class InclusionSchedule:
    """UX-32: фактическое расписание main-слота подключения (что план реально материализует).

    sessions_per_week — занятий main в неделю (derive_slots, тот же вызов, что строит занятия плана и сходимость);
    source — snapshot (в снимке есть замороженные slots) | catalogue (слотов нет: выведены из program_items +
    каталожной частоты); is_legacy — подключение не V5.6 (в снимке нет schedule с программой pullups_v5_6);
    min_days_between_starts — отдых группы main; weekly_capacity — domain.weekly_capacity(min_days): сколько
    стартов main влезает в неделю Пн–Вс при этом отдыхе с чистой недели (3 дня → 3: Пн, Чт, Вс)."""

    sessions_per_week: int
    source: str
    is_legacy: bool
    min_days_between_starts: int
    weekly_capacity: int


@dataclass(frozen=True)
class PlanView:
    items: list[PlanItemView]
    week_summaries: list[tuple[int, WeekSummary]]
    spacing: list[SpacingView]
    custom_plans: list[CustomPlan]
    schedules: dict[int, InclusionSchedule]


def _start_availability(
    item: PlanItem, state: OccurrenceStateResult | None, *, access_allowed: bool, bypass_spacing: bool,
) -> tuple[bool, str | None]:
    """UX-01: можно ли сейчас начать строку и, если нет, почему. Порядок как у старта: доступ (подписка) →
    ожидание замера → отдых K1 (админ обходит, `bypass_spacing`). completed / missed / infeasible не
    стартуются никогда (infeasible — «не успеть на этой неделе»: контракт, не только K1)."""
    if state is not None and state.state in (OccurrenceState.COMPLETED, OccurrenceState.MISSED):
        return False, state.state.value
    if item.legacy_aggregate:
        return False, "missed"  # замороженная агрегатная строка прошлого: старт — 422 «план обновился»
    if not access_allowed:
        return False, "no_access"
    if state is None:
        return True, None
    if state.state == OccurrenceState.AWAITING_ASSESSMENT:
        return False, state.state.value
    if state.state == OccurrenceState.INFEASIBLE:
        return False, state.state.value
    if state.state == OccurrenceState.TOO_EARLY and not bypass_spacing:
        return False, state.state.value
    return True, None


class PlanViewService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._plans = TrainingPlanRepository(session)
        self._sessions = TrainingSessionRepository(session)
        self._programs = ProgramRepository(session)

    async def inclusion_schedule(
        self, inclusion: ProgramInclusion, *, min_days: int | None = None, user_id: int | None = None,
    ) -> InclusionSchedule | None:
        """Расписание main-слота подключения; None — у программы нет main-слота (не курс «Подтягиваний»)."""
        program = await self._programs.get_by_id(inclusion.program_id)
        slots = derive_slots(
            inclusion.snapshot, program_slots=program.slots if program else None,
            program_frequency=program.frequency if program else None,
        )
        main = next((slot for slot in slots if slot.key == MAIN_SLOT_KEY), None)
        if main is None:
            return None
        if min_days is None:
            min_days = await MainSpacingService(self._session).min_days_between_starts(user_id) if user_id else 3
        snapshot = inclusion.snapshot or {}
        frozen = snapshot.get("slots")
        return InclusionSchedule(
            sessions_per_week=main.sessions_per_week,
            source="snapshot" if isinstance(frozen, list) and frozen else "catalogue",
            is_legacy=(snapshot.get("schedule") or {}).get("program_version") != PROGRAM_VERSION,
            min_days_between_starts=min_days, weekly_capacity=weekly_capacity(min_days),
        )

    async def build(
        self, *, plan: TrainingPlan, user: User, today: date, plan_weeks: list[PlanWeek],
        plan_items: list[PlanItem], inclusions: list[ProgramInclusion], now: datetime | None = None,
        bypass_spacing: bool = False,
    ) -> PlanView:
        """now / bypass_spacing — те же входы, что у старта (`_utcnow`, `settings.is_admin`): `start_allowed`
        считается ЕГО правилами, а не копией."""
        now = now or datetime.now(UTC)
        tz = resolve_timezone(user.timezone)
        week_by_id = {week.id: week for week in plan_weeks}
        visible = await self._actionable_rows(plan_items, inclusions, week_by_id, today, user_id=user.id)

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

        # issue #305 (PROGRAM_PLAN_V2 §3): main-занятия инклюзии, ждущей замера, — «Сначала тест на максимум».
        awaiting = {
            inclusion.id for inclusion in inclusions
            if inclusion.is_active and inclusion.status == InclusionStatus.AWAITING_ASSESSMENT.value
        }
        for item in visible:
            if (
                item.program_inclusion_id in awaiting and item.program_slot_key == MAIN_SLOT_KEY
                and item.id not in credited and item.id in states
            ):
                states[item.id] = OccurrenceStateResult(state=OccurrenceState.AWAITING_ASSESSMENT)

        week_id_by_item = {item.id: item.plan_week_id for item in visible}
        summaries = [
            (week.id, summarize_week([occ for occ in inputs if week_id_by_item[occ.item_id] == week.id], states))
            for week in plan_weeks
        ]

        variants = await self._session_variants(visible, inclusions, week_by_id, states, credited)
        access = ProgramAccessService(self._session)
        access_cache: dict[int | None, bool] = {}
        views = []
        for item in visible:
            state = states.get(item.id)
            if item.program_inclusion_id not in access_cache:
                access_cache[item.program_inclusion_id] = await access.training_parts_allowed(
                    user, [item.program_inclusion_id], now=now,
                )
            allowed, reason = _start_availability(
                item, state, access_allowed=access_cache[item.program_inclusion_id], bypass_spacing=bypass_spacing,
            )
            variant, basis, ordinal = variants.get(item.id, (None, None, None))
            views.append(PlanItemView(
                item=item,
                done_count=(1 if item.id in credited else 0) if item.occurrence_index is not None
                else aggregate_done.get(item.id, 0),
                state=state, spacing_group=spacing_group_by_item.get(item.id),
                credited_session_id=credited.get(item.id), start_allowed=allowed, blocked_reason=reason,
                session_variant=variant, session_variant_basis=basis, session_ordinal=ordinal,
            ))
        spacing = [
            SpacingView(
                spacing_group=MAIN_SPACING_GROUP, min_days_between_starts=min_days_by_group[MAIN_SPACING_GROUP],
                last_start_date=last_date, available_from=available_by_group[MAIN_SPACING_GROUP],
            ),
        ]
        schedules: dict[int, InclusionSchedule] = {}
        for inclusion in inclusions:
            schedule = await self.inclusion_schedule(
                inclusion, min_days=min_days_by_group.get(MAIN_SPACING_GROUP, 3),
            )
            if schedule is not None:
                schedules[inclusion.id] = schedule
        return PlanView(
            items=views, week_summaries=summaries, spacing=spacing,
            custom_plans=await self._plans.list_custom_plans(plan.id), schedules=schedules,
        )

    async def _session_variants(
        self, visible: list[PlanItem], inclusions: list[ProgramInclusion], week_by_id: dict[int, PlanWeek],
        states: dict[int, OccurrenceStateResult], credited: dict[int, int],
    ) -> dict[int, tuple[str | None, str | None, int | None]]:
        """UX-08: (session_variant, basis, session_ordinal) занятий main-слота.

        ordinal — место занятия среди main-занятий СВОЕЙ недели своего подключения (по occurrence_index).
        variant — только для V5.6 (state.next_role; в устаревшем подключении у каждого занятия оба блока,
        А/Б там нет): первое открытое занятие (не засчитано, не пропущено, по неделе и индексу) — next_role
        (actual, тот же источник, что «Следующая тренировка B» итога), каждое следующее — чередование от него
        (projected). Засчитанное занятие — роль из рецепта его сессии (actual), если сохранена."""
        by_inclusion = {inclusion.id: inclusion for inclusion in inclusions}
        main_rows: dict[int, list[PlanItem]] = {}
        for item in visible:
            if (
                item.program_slot_key == MAIN_SLOT_KEY and item.program_inclusion_id in by_inclusion
                and item.occurrence_index is not None and item.plan_week_id in week_by_id
            ):
                main_rows.setdefault(item.program_inclusion_id, []).append(item)
        result: dict[int, tuple[str | None, str | None, int | None]] = {}
        session_ids = [credited[item.id] for rows in main_rows.values() for item in rows if item.id in credited]
        roles = await self._credited_roles(session_ids)
        for inclusion_id, rows in main_rows.items():
            inclusion = by_inclusion[inclusion_id]
            ordered = sorted(rows, key=lambda r: (week_by_id[r.plan_week_id].start_date, r.occurrence_index, r.id))
            ordinals: dict[int, int] = {}
            per_week: dict[int, int] = {}
            for item in ordered:
                per_week[item.plan_week_id] = per_week.get(item.plan_week_id, 0) + 1
                ordinals[item.id] = per_week[item.plan_week_id]
            is_v5 = is_v5_state(inclusion.progression_state or {})
            cursor = WorkoutRole(inclusion.progression_state["next_role"]) if is_v5 else None
            first_open = True
            for item in ordered:
                if is_v5 and item.id in credited:
                    role = roles.get(credited[item.id])
                    result[item.id] = (role, "actual" if role else None, ordinals[item.id])
                    continue
                state = states.get(item.id)
                open_row = state is not None and state.state != OccurrenceState.MISSED and item.id not in credited
                if is_v5 and open_row and inclusion.is_active:
                    result[item.id] = (cursor.value, "actual" if first_open else "projected", ordinals[item.id])
                    cursor, first_open = cursor.other, False
                else:
                    result[item.id] = (None, None, ordinals[item.id])
        return result

    async def _credited_roles(self, session_ids: list[int]) -> dict[int, str]:
        if not session_ids:
            return {}
        rows = await self._session.execute(
            select(TrainingSession.id, TrainingSession.prescription_snapshot).where(TrainingSession.id.in_(session_ids)),
        )
        roles: dict[int, str] = {}
        for session_id, snapshot in rows.all():
            program = ((snapshot or {}).get("provenance") or {}).get("course_program") or {}
            if program.get("workout_role") in ("A", "B"):
                roles[session_id] = program["workout_role"]
        return roles

    async def _actionable_rows(
        self, plan_items: list[PlanItem], inclusions: list[ProgramInclusion], week_by_id: dict[int, PlanWeek],
        today: date, *, user_id: int,
    ) -> list[PlanItem]:
        """Строки плана для показа: без снятых (status = removed) и без НЕзасчитанных строк текущей/будущих
        недель, которые сервер не стартует: строки убранного курса (is_active = false, #304 C1) и строки
        своего плана / ручные с удалённой (архивной) тренировкой (#304 F) — «Начать» / available и «0 из 3»
        они не дают. Засчитанные строки и прошлые недели (история) остаются; строки в БД не меняются."""
        inactive = {inclusion.id for inclusion in inclusions if not inclusion.is_active}
        rows = [item for item in plan_items if item.status != PlanItemStatus.REMOVED]
        open_weeks = [
            item for item in rows
            if item.plan_week_id in week_by_id and week_by_id[item.plan_week_id].start_date + timedelta(days=6) >= today
        ]
        workout_rows = [item for item in open_weeks if item.program_inclusion_id is None and item.complex_id is not None]
        live = await self._plans.live_workout_ids([item.complex_id for item in workout_rows], user_id)
        candidates = [item.id for item in open_weeks if item.program_inclusion_id in inactive] + [
            item.id for item in workout_rows if item.complex_id not in live
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

    code = "reschedule_refused"


class PastDayError(RescheduleError):
    """UX-31: день текущей недели уже прошёл — занятие туда не ставится."""

    code = "past_day"


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

        if (
            day_of_week is not None and target.week_number == current_number
            and (target.id != item.plan_week_id or day_of_week != item.day_of_week)
            and day_of_week < (today - target.start_date).days
        ):
            raise PastDayError("Этот день уже прошёл")
        item.plan_week_id = target.id
        item.day_of_week = day_of_week
        item.scheduled_date = target.start_date + timedelta(days=day_of_week) if day_of_week is not None else None
        item.status = PlanItemStatus.RESCHEDULED.value
        await self._plans.flush()
        return item
