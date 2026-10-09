"""converge_user_plan — ЕДИНСТВЕННАЯ идемпотентная функция, которая материализует и сводит план
пользователя к модели «одна строка PlanItem = одно занятие» (issue #304, AD-4, PROGRAM_PLAN_V2 §5
PL7, MIGRATION_V2 §3, §5).

Вызывается из GET /plan (и остальных входов плана через PlanWeekService), из подключения курса,
своего плана и deploy-скрипта `scripts/converge_plan_v2.py` — один код, без второго «ленивого»
пути записи. Повторный вызов без новых событий = 0 изменений (ConvergenceReport.mutations == 0).

Что делает (под локом строки плана):
1. текущая неделя (get-or-create), сироты-ручные строки → текущая неделя, пустые прошлые недели-пропуски;
2. починка старого снимка инклюзии без program_items (#301, тот же код, что раньше);
3. ПРОШЛЫЕ недели: агрегатные строки (occurrence_index IS NULL) замораживаются как история
   (legacy_aggregate = true, показываются своим count_per_week) — новых занятий в прошлом нет;
4. ТЕКУЩАЯ и БУДУЩИЕ существующие недели окна (текущая .. +4):
   * агрегат курса (A+B × count_per_week) → занятия слотов; k сессий старой M2M-связи на этой неделе
     → k засчитанных занятий по порядку performed_at (training_sessions.plan_item_id), агрегат
     выводится из плана (status = removed, legacy_aggregate = true), но НЕ удаляется (на него
     ссылается история M2M);
   * ручная строка с count_per_week = N → N занятий (первое — сама строка, её кредиты сохраняются);
   * у активных инклюзий — недостающие занятия слотов (желаемый объём, ровно sessions_per_week);
   * у активных своих планов — недостающие занятия недели (объём недели, 0 — пусто) только живых
     (не архивных) тренировок, без пересчёта ротации; открытые занятия удалённой тренировки — removed;
     свой план без живых тренировок останавливается (#304 F, PROGRAM_PLAN_V2 §7);
5. кэш инклюзии: status (NULL → по is_active), sequence_cursor (NULL → число засчитанных MAIN),
   completed_main_sessions / last_main_session_at — производные от сессий.

Не делает: не подключает курсы (no auto-enrol), не удаляет и не пересоздаёт инклюзию, не трогает
started_at / progression_state / initial_progression_state / снимок (кроме #301-починки пустого
списка), подписку и доступ, завершённые сессии (кроме проставления явного кредита занятию), не
двигает историю прошлых недель."""

import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import (
    CustomPlan,
    PlanItem,
    PlanWeek,
    ProgramInclusion,
    SessionStatus,
    TrainingPlan,
)
from app.db.repositories.programs import ProgramRepository, program_items_snapshot
from app.db.repositories.training_plans import TrainingPlanRepository
from app.db.repositories.training_sessions import TrainingSessionRepository
from app.db.repositories.users import UserRepository
from app.domain.multi_program import (
    MAX_FUTURE_PLAN_WEEKS,
    ProgramStructureType,
    SnapshotProgramItemsGap,
    WeekPhase,
    plan_week_number,
    plan_week_start_date,
    snapshot_program_items_gap,
)
from app.domain.plan_occurrence import (
    MAIN_SLOT_KEY,
    CustomPlanRepeat,
    InclusionStatus,
    OccurrenceSource,
    PlanItemStatus,
    ProgramSlot,
    assign_aggregate_credits,
    custom_week_occurrences,
    derive_slots,
)
from app.services.plan_removal import retire_open_custom_rows, stop_custom_plan
from app.services.plan_spacing import MainSpacingService
from app.services.training_analytics import resolve_timezone

logger = logging.getLogger(__name__)

_CREDITABLE = (SessionStatus.COMPLETED, SessionStatus.STARTED)


@dataclass(frozen=True)
class SnapshotRepair:
    """Одна выполненная починка снимка (для лога, отчёта repair-скрипта и тестов)."""

    inclusion_id: int
    training_plan_id: int
    program_id: int
    reason: SnapshotProgramItemsGap
    program_items: list[dict]


@dataclass
class ConvergenceReport:
    training_plan_id: int
    weeks_created: int = 0
    orphans_attached: int = 0
    snapshot_repairs: int = 0
    aggregates_frozen: int = 0
    aggregates_expanded: int = 0
    manual_converted: int = 0
    occurrences_created: int = 0
    credits_linked: int = 0
    inclusion_fields_updated: int = 0
    custom_rows_retired: int = 0
    custom_plans_stopped: int = 0
    gaps: list[str] = field(default_factory=list)

    @property
    def mutations(self) -> int:
        return (
            self.weeks_created + self.orphans_attached + self.snapshot_repairs + self.aggregates_frozen
            + self.aggregates_expanded + self.manual_converted + self.occurrences_created + self.credits_linked
            + self.inclusion_fields_updated + self.custom_rows_retired + self.custom_plans_stopped
        )

    def as_dict(self) -> dict:
        return {
            "training_plan_id": self.training_plan_id, "weeks_created": self.weeks_created,
            "orphans_attached": self.orphans_attached, "snapshot_repairs": self.snapshot_repairs,
            "aggregates_frozen": self.aggregates_frozen, "aggregates_expanded": self.aggregates_expanded,
            "manual_converted": self.manual_converted, "occurrences_created": self.occurrences_created,
            "credits_linked": self.credits_linked, "inclusion_fields_updated": self.inclusion_fields_updated,
            "custom_rows_retired": self.custom_rows_retired, "custom_plans_stopped": self.custom_plans_stopped,
            "mutations": self.mutations, "gaps": self.gaps,
        }


def _log_convergence(event: str, **fields) -> None:
    """Громкий структурированный WARNING: исторический пользовательский стейт чинится (или не может
    быть починен) рантаймом. Одна строка JSON — грепается в docker logs по имени события."""
    payload = {"event": event, **fields}
    logger.warning("%s %s", event, json.dumps(payload, ensure_ascii=False, default=str), extra=payload)


def _is_recurring(snapshot: dict, program_structure: str | None) -> bool:
    value = snapshot.get("structure_type") or program_structure
    return value == ProgramStructureType.RECURRING.value


def _scheduled(week: PlanWeek, day_of_week: int | None) -> date | None:
    return week.start_date + timedelta(days=day_of_week) if day_of_week is not None else None


class PlanConvergenceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._plans = TrainingPlanRepository(session)
        self._programs = ProgramRepository(session)
        self._sessions = TrainingSessionRepository(session)

    # --- Публичный вход ------------------------------------------------------------------

    async def converge_user_plan(
        self, *, training_plan_id: int, today: date, create_until_week: int | None = None,
    ) -> tuple[PlanWeek, ConvergenceReport]:
        """Идемпотентная сходимость плана к «сегодня» (дата пользователя). create_until_week —
        дополнительно создать недели текущая .. N (планирование вперёд, только в окне +4)."""
        plan = await self._plans.lock_plan(training_plan_id)
        if plan is None:
            raise ValueError(f"training plan {training_plan_id} not found")
        report = ConvergenceReport(training_plan_id=plan.id)
        created = plan.created_at.date()
        current_number = plan_week_number(created, today)

        current_week = await self._get_or_create_week(plan, current_number, report)
        if create_until_week is not None:
            for number in range(current_number + 1, min(create_until_week, current_number + MAX_FUTURE_PLAN_WEEKS) + 1):
                await self._get_or_create_week(plan, number, report)

        orphans = await self._plans.list_orphan_manual_plan_items(training_plan_id=plan.id)
        if orphans:
            await self._plans.attach_plan_items_to_week(plan_items=orphans, plan_week_id=current_week.id)
            report.orphans_attached += len(orphans)
        await self._fill_past_gap_weeks(plan, current_number, report)

        inclusions = await self._plans.list_inclusions(plan.id)
        slots_by_inclusion: dict[int, list[ProgramSlot]] = {}
        for inclusion in inclusions:
            if not inclusion.is_active:
                continue
            program = await self._programs.get_by_id(inclusion.program_id)
            if not _is_recurring(inclusion.snapshot or {}, program.structure_type.value if program else None):
                continue  # FIXED/SINGLE_LESSON — понедельно не материализуются (как и раньше)
            if await self.converge_inclusion_snapshot(inclusion) is not None:
                report.snapshot_repairs += 1
            slots_by_inclusion[inclusion.id] = derive_slots(
                inclusion.snapshot, program_slots=program.slots if program else None,
                program_frequency=program.frequency if program else None,
            )
            if not slots_by_inclusion[inclusion.id]:
                report.gaps.append(f"inclusion {inclusion.id}: no materializable slots")
                _log_convergence(
                    "plan_convergence_gap", inclusion_id=inclusion.id, training_plan_id=plan.id,
                    program_id=inclusion.program_id, reason="snapshot_has_no_materializable_program_items",
                )
            unweeked = await self._plans.list_unweeked_plan_items(program_inclusion_id=inclusion.id)
            if unweeked:
                # Строки старого кода/бэкфилла без недели — к текущей неделе (как раньше), дальше их
                # разворачивает шаг недели.
                await self._plans.attach_plan_items_to_week(plan_items=unweeked, plan_week_id=current_week.id)
                report.orphans_attached += len(unweeked)

        user = await UserRepository(self._session).get_by_id(plan.user_id)
        tz = resolve_timezone(user.timezone if user is not None else None)
        custom_plans, live_workouts = await self._live_custom_plans(plan, today, report)
        inclusions_by_id = {inclusion.id: inclusion for inclusion in inclusions}
        for week in await self._plans.list_plan_weeks(plan.id):
            if week.week_number > current_number + MAX_FUTURE_PLAN_WEEKS:
                continue
            if week.week_number < current_number:
                await self._freeze_past_week(week, report)
                continue
            await self._converge_open_week(
                week, tz=tz, inclusions_by_id=inclusions_by_id, slots_by_inclusion=slots_by_inclusion,
                custom_plans=custom_plans, live_workouts=live_workouts, plan=plan, today=today, report=report,
            )

        await self._refresh_inclusion_fields(plan, inclusions, slots_by_inclusion, report)
        await self._plans.flush()
        return current_week, report

    # --- Недели ----------------------------------------------------------------------------

    async def _get_or_create_week(self, plan: TrainingPlan, number: int, report: ConvergenceReport) -> PlanWeek:
        week = await self._plans.get_plan_week(training_plan_id=plan.id, week_number=number)
        if week is None:
            week = await self._plans.create_plan_week(
                training_plan_id=plan.id, week_number=number,
                start_date=plan_week_start_date(plan.created_at.date(), number), phase=WeekPhase.BASE,
            )
            report.weeks_created += 1
        return week

    async def _fill_past_gap_weeks(self, plan: TrainingPlan, current_number: int, report: ConvergenceReport) -> None:
        """#301 — непрерывный список недель: пустые PlanWeek между самой ранней и текущей."""
        existing = {week.week_number for week in await self._plans.list_plan_weeks(plan.id)}
        if not existing:
            return
        for number in range(min(existing), current_number):
            if number not in existing:
                await self._get_or_create_week(plan, number, report)

    async def _freeze_past_week(self, week: PlanWeek, report: ConvergenceReport) -> None:
        for row in await self._plans.list_items_in_week(week.id):
            if row.occurrence_index is None and not row.legacy_aggregate and row.status != PlanItemStatus.REMOVED:
                row.legacy_aggregate = True
                report.aggregates_frozen += 1

    async def _converge_open_week(
        self, week: PlanWeek, *, tz, inclusions_by_id: dict[int, ProgramInclusion],
        slots_by_inclusion: dict[int, list[ProgramSlot]], custom_plans: list[CustomPlan],
        live_workouts: dict[int, set[int]], plan: TrainingPlan, today: date, report: ConvergenceReport,
    ) -> None:
        rows = await self._plans.list_items_in_week(week.id)
        aggregates: dict[int, list[PlanItem]] = {}
        for row in rows:
            if row.occurrence_index is not None or row.status == PlanItemStatus.REMOVED or row.legacy_aggregate:
                continue
            if row.program_inclusion_id is None and row.custom_plan_id is None:
                await self._expand_manual(row, week, tz=tz, report=report)
            elif row.program_inclusion_id is not None:
                aggregates.setdefault(row.program_inclusion_id, []).append(row)

        for inclusion_id, slots in slots_by_inclusion.items():
            await self._ensure_program_occurrences(inclusions_by_id[inclusion_id], slots, week, report)

        for inclusion_id, aggregate_rows in aggregates.items():
            if not slots_by_inclusion.get(inclusion_id):
                # Курс без занятий на замену — снят, не повторяющийся (FIXED/SINGLE_LESSON) или без
                # материализуемых слотов: строки текущей/будущей недели остаются как были (стартуются и
                # считаются по-старому). Агрегат выводится из плана ТОЛЬКО вместе с заменой занятиями.
                continue
            await self._expand_program_aggregates(
                inclusions_by_id[inclusion_id], slots_by_inclusion[inclusion_id], aggregate_rows, week,
                tz=tz, report=report,
            )

        for custom_plan in custom_plans:
            await self._ensure_custom_occurrences(
                custom_plan, week, live_workouts[custom_plan.id], plan=plan, today=today, report=report,
            )

    # --- Курс -------------------------------------------------------------------------------

    async def _ensure_program_occurrences(
        self, inclusion: ProgramInclusion, slots: list[ProgramSlot], week: PlanWeek, report: ConvergenceReport,
    ) -> None:
        existing = {
            (row.program_slot_key, row.occurrence_index)
            for row in await self._plans.list_items_by_origin(week.id)
            if row.program_inclusion_id == inclusion.id and row.occurrence_index is not None
        }
        for slot in slots:
            if slot.exercise_id is None:
                continue
            for index in range(1, slot.sessions_per_week + 1):
                if (slot.key, index) in existing:
                    continue
                await self._plans.add_plan_item(PlanItem(
                    training_plan_id=inclusion.training_plan_id, exercise_id=slot.exercise_id,
                    complex_id=slot.complex_id, count_per_week=1, day_of_week=slot.day_of_week,
                    week_phase=WeekPhase.BASE, program_inclusion_id=inclusion.id, plan_week_id=week.id,
                    origin_plan_week_id=week.id, source=OccurrenceSource.PROGRAM.value,
                    workout_definition_id=slot.workout_definition_id, occurrence_index=index,
                    program_slot_key=slot.key, scheduled_date=_scheduled(week, slot.day_of_week),
                    status=PlanItemStatus.OPEN.value,
                ))
                report.occurrences_created += 1

    def _slot_for_row(self, row: PlanItem, inclusion: ProgramInclusion, slots: list[ProgramSlot]) -> str | None:
        """Слот агрегатной строки: тот, чьи members содержат её (exercise_id, complex_id); у main —
        любая роль STEP снимка."""
        roles = {item.get("exercise_id") for item in (inclusion.snapshot or {}).get("exercises") or []}
        for slot in slots:
            if slot.key == MAIN_SLOT_KEY and row.exercise_id in roles:
                return slot.key
        for slot in slots:
            if any(m.exercise_id == row.exercise_id and m.complex_id == row.complex_id for m in slot.members):
                return slot.key
        return None

    async def _sessions_linked_in_week(self, rows: list[PlanItem], week: PlanWeek, tz) -> dict[int, tuple]:
        """session_id → (performed_at, {row_id, ...}, current plan_item_id) для сессий, связанных со
        строками по M2M или уже явно (single-link backfill миграции), STARTED/COMPLETED, с локальной датой
        внутри недели (та же граница, что у старого счётчика «сделано», #258)."""
        row_ids = [row.id for row in rows]
        week_end = week.start_date + timedelta(days=7)
        linked: dict[int, tuple] = {}
        for item_id, session_id, status, performed_at, credit in await self._sessions.legacy_links_for_plan_items(row_ids):
            if status not in _CREDITABLE or not week.start_date <= performed_at.astimezone(tz).date() < week_end:
                continue
            entry = linked.setdefault(session_id, (performed_at, set(), credit))
            entry[1].add(item_id)
        for item_id, session_id, status, performed_at in await self._sessions.credits_for_plan_items(row_ids):
            if status not in _CREDITABLE or not week.start_date <= performed_at.astimezone(tz).date() < week_end:
                continue
            entry = linked.setdefault(session_id, (performed_at, set(), item_id))
            entry[1].add(item_id)
        return linked

    async def _expand_program_aggregates(
        self, inclusion: ProgramInclusion, slots: list[ProgramSlot], aggregate_rows: list[PlanItem], week: PlanWeek,
        *, tz, report: ConvergenceReport,
    ) -> None:
        """MIGRATION_V2 §5 п.2: агрегат с k сессиями → k засчитанных занятий по порядку performed_at.
        Строка, которой не соответствует ни один слот (нет занятия на замену), не выводится из плана."""
        slot_by_row = {row.id: self._slot_for_row(row, inclusion, slots) for row in aggregate_rows}
        aggregate_rows = [row for row in aggregate_rows if slot_by_row[row.id] is not None]
        if not aggregate_rows:
            return
        aggregate_ids = {row.id for row in aggregate_rows}
        occurrences = [
            row for row in await self._plans.list_items_by_origin(week.id)
            if row.program_inclusion_id == inclusion.id and row.occurrence_index is not None
        ]
        already_credited = {item_id for item_id, *_ in await self._sessions.credits_for_plan_items([o.id for o in occurrences])}
        linked = await self._sessions_linked_in_week(aggregate_rows, week, tz)

        sessions_by_slot: dict[str, list[tuple[int, object]]] = {}
        for session_id, (performed_at, row_ids, credit) in linked.items():
            if credit is not None and credit not in aggregate_ids:
                continue  # уже засчитала конкретное занятие — не переносим
            slot_keys = {slot_by_row[row_id] for row_id in row_ids} - {None}
            slot_key = MAIN_SLOT_KEY if MAIN_SLOT_KEY in slot_keys else (min(slot_keys) if slot_keys else None)
            if slot_key is not None:
                sessions_by_slot.setdefault(slot_key, []).append((session_id, performed_at))

        for slot_key, sessions in sessions_by_slot.items():
            free = sorted(
                (o for o in occurrences if o.program_slot_key == slot_key and o.id not in already_credited),
                key=lambda o: o.occurrence_index,
            )
            by_index = {o.occurrence_index: o for o in free}
            for index, session_id in assign_aggregate_credits(list(by_index), sessions).items():
                await self._sessions.set_plan_item_credit(session_id, by_index[index].id)
                report.credits_linked += 1

        for row in aggregate_rows:
            row.status = PlanItemStatus.REMOVED.value
            row.legacy_aggregate = True
            report.aggregates_expanded += 1
        _log_convergence(
            "plan_convergence_expand", inclusion_id=inclusion.id, plan_week_id=week.id,
            week_number=week.week_number, aggregate_row_ids=sorted(aggregate_ids),
            credited_sessions=sum(len(v) for v in sessions_by_slot.values()),
        )

    # --- Ручные строки и свой план ----------------------------------------------------------

    async def _expand_manual(self, row: PlanItem, week: PlanWeek, *, tz, report: ConvergenceReport) -> None:
        """Ручная строка старой формы (count_per_week = N) → N занятий; первая — сама строка."""
        count = max(int(row.count_per_week or 1), 1)
        row.occurrence_index = 1
        row.origin_plan_week_id = week.id
        row.count_per_week = 1
        row.source = row.source or OccurrenceSource.MANUAL.value
        row.workout_definition_id = row.workout_definition_id or row.complex_id
        row.scheduled_date = _scheduled(week, row.day_of_week)
        occurrences = [row]
        for index in range(2, count + 1):
            occurrences.append(await self._plans.add_plan_item(PlanItem(
                training_plan_id=row.training_plan_id, exercise_id=row.exercise_id, complex_id=row.complex_id,
                count_per_week=1, day_of_week=row.day_of_week, week_phase=row.week_phase, program_inclusion_id=None,
                plan_week_id=week.id, origin_plan_week_id=week.id, source=row.source,
                workout_definition_id=row.workout_definition_id, occurrence_index=index,
                scheduled_date=row.scheduled_date, status=PlanItemStatus.OPEN.value,
            )))
            report.occurrences_created += 1
        linked = await self._sessions_linked_in_week([row], week, tz)
        # Сессия засчитывает не более одного занятия (PL2): уже засчитавшая другое занятие (например,
        # смешанная сессия, отданная занятию соседней строки) не переносится.
        sessions = [
            (session_id, performed_at) for session_id, (performed_at, _, credit) in linked.items()
            if credit is None or credit == row.id
        ]
        by_index = {o.occurrence_index: o for o in occurrences}
        for index, session_id in assign_aggregate_credits(list(by_index), sessions).items():
            if linked[session_id][2] != by_index[index].id:
                await self._sessions.set_plan_item_credit(session_id, by_index[index].id)
                report.credits_linked += 1
        report.manual_converted += 1

    async def _live_custom_plans(
        self, plan: TrainingPlan, today: date, report: ConvergenceReport,
    ) -> tuple[list[CustomPlan], dict[int, set[int]]]:
        """Активные свои планы и их ЖИВЫЕ тренировки (#304 F): удалённая (архивная) или чужая тренировка
        не материализуется. План, где живых не осталось ни одной, останавливается (is_active = false,
        открытые занятия текущей/будущих недель — removed; история и засчитанные — как были)."""
        active: list[CustomPlan] = []
        live_workouts: dict[int, set[int]] = {}
        for custom_plan in await self._plans.list_custom_plans(plan.id):
            if not custom_plan.is_active:
                continue
            live = await self._plans.live_workout_ids(list(custom_plan.workouts), plan.user_id)
            if not live:
                report.custom_rows_retired += await stop_custom_plan(self._session, plan, custom_plan, today=today)
                report.custom_plans_stopped += 1
                _log_convergence(
                    "custom_plan_auto_stopped", training_plan_id=plan.id, custom_plan_id=custom_plan.id,
                    reason="no_live_workouts",
                )
                continue
            active.append(custom_plan)
            live_workouts[custom_plan.id] = live
        return active, live_workouts

    async def _ensure_custom_occurrences(
        self, custom_plan: CustomPlan, week: PlanWeek, live: set[int], *, plan: TrainingPlan, today: date,
        report: ConvergenceReport,
    ) -> None:
        """Недостающие занятия недели своего плана. Позиции ротации — из ПОЛНОГО сохранённого списка
        тренировок: позиция удалённой тренировки остаётся дырой (её занятие не создаётся), оставшиеся
        не сдвигаются и её объём не забирают, occurrence_index не перенумеровывается (#304 F). Открытые
        занятия удалённой тренировки в этой (текущей/будущей) неделе снимаются (removed)."""
        rows = [row for row in await self._plans.list_items_by_origin(week.id) if row.custom_plan_id == custom_plan.id]
        stale = [
            row for row in rows
            if row.workout_definition_id not in live and row.status != PlanItemStatus.REMOVED
        ]
        if stale:
            report.custom_rows_retired += await retire_open_custom_rows(self._session, plan, stale, today=today)
        offset = week.week_number - custom_plan.start_week_number
        specs = custom_week_occurrences(
            workout_ids=list(custom_plan.workouts), weeks=list(custom_plan.weeks),
            repeat=CustomPlanRepeat(custom_plan.repeat), week_offset=offset,
            preferred_weekdays=custom_plan.preferred_weekdays,
        )
        if not specs:
            return
        existing = {row.occurrence_index for row in rows}
        for spec in specs:
            if spec.occurrence_index in existing or spec.workout_definition_id not in live:
                continue
            exercise_id = await self._plans.first_complex_exercise_id(spec.workout_definition_id)
            if exercise_id is None:
                report.gaps.append(f"custom plan {custom_plan.id}: workout {spec.workout_definition_id} has no items")
                continue
            await self._plans.add_plan_item(PlanItem(
                training_plan_id=custom_plan.training_plan_id, exercise_id=exercise_id,
                complex_id=spec.workout_definition_id, count_per_week=1, day_of_week=spec.day_of_week,
                week_phase=None, program_inclusion_id=None, plan_week_id=week.id, origin_plan_week_id=week.id,
                source=OccurrenceSource.CUSTOM_PLAN.value, workout_definition_id=spec.workout_definition_id,
                occurrence_index=spec.occurrence_index, custom_plan_id=custom_plan.id,
                scheduled_date=_scheduled(week, spec.day_of_week), status=PlanItemStatus.OPEN.value,
            ))
            report.occurrences_created += 1

    # --- Инклюзия ---------------------------------------------------------------------------

    async def _refresh_inclusion_fields(
        self, plan: TrainingPlan, inclusions: list[ProgramInclusion], slots_by_inclusion: dict[int, list[ProgramSlot]],
        report: ConvergenceReport,
    ) -> None:
        spacing = MainSpacingService(self._session)
        main_count: int | None = None
        last_main = None
        for inclusion in inclusions:
            changed = False
            if inclusion.status is None:
                inclusion.status = (InclusionStatus.ACTIVE if inclusion.is_active else InclusionStatus.REMOVED).value
                changed = True
            has_main = any(slot.key == MAIN_SLOT_KEY for slot in slots_by_inclusion.get(inclusion.id, []))
            if inclusion.is_active and has_main:
                if main_count is None:
                    main_count = await spacing.count_native_main_sessions(plan.user_id)
                    last_main = await spacing.last_main_start_at(plan.user_id)
                if inclusion.sequence_cursor is None:
                    inclusion.sequence_cursor = main_count
                    changed = True
                if inclusion.completed_main_sessions != main_count:
                    inclusion.completed_main_sessions = main_count
                    changed = True
                if inclusion.last_main_session_at != last_main:
                    inclusion.last_main_session_at = last_main
                    changed = True
            report.inclusion_fields_updated += changed

    async def converge_inclusion_snapshot(self, inclusion: ProgramInclusion) -> SnapshotRepair | None:
        """ЕДИНСТВЕННАЯ каноническая починка «старого» снимка инклюзии (#301, aged-state convergence;
        решение владельца 2026-10-06). Чинит ТОЛЬКО активную инклюзию, у снимка которой program_items
        отсутствует или пуст, и ТОЛЬКО если у live Program есть ProgramItem: в снимок дописывается ровно
        один ключ "program_items". Не трогает остальное. Идемпотентно. Громкий WARNING на каждую починку."""
        if not inclusion.is_active:
            return None
        snapshot = inclusion.snapshot or {}
        reason = snapshot_program_items_gap(snapshot)
        if reason is None:
            return None
        live_items = await self._programs.list_program_items(inclusion.program_id)
        if not live_items:
            _log_convergence(
                "plan_convergence_gap", inclusion_id=inclusion.id, training_plan_id=inclusion.training_plan_id,
                program_id=inclusion.program_id, reason=f"{reason.value}; live program has no program_items",
            )
            return None
        items = program_items_snapshot(live_items)
        inclusion.snapshot = {**snapshot, "program_items": items}
        await self._plans.flush()
        repair = SnapshotRepair(
            inclusion_id=inclusion.id, training_plan_id=inclusion.training_plan_id,
            program_id=inclusion.program_id, reason=reason, program_items=items,
        )
        _log_convergence(
            "plan_convergence_repair", inclusion_id=repair.inclusion_id, training_plan_id=repair.training_plan_id,
            program_id=repair.program_id, reason=reason.value, program_items_added=len(items),
            program_item_ids=[item["id"] for item in items],
        )
        return repair
