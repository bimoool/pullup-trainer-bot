from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import PlanItem, PlanWeek, ProgramInclusion
from app.db.repositories.training_plans import TrainingPlanRepository
from app.domain.multi_program import is_plannable_week_number, plan_week_number
from app.domain.plan_occurrence import OccurrenceSource, PlanItemStatus
from app.services.plan_convergence import ConvergenceReport, PlanConvergenceService, SnapshotRepair

__all__ = ["ConvergenceReport", "PlanWeekService", "SnapshotRepair"]


class PlanWeekService:
    """Единственный канонический путь материализации Program в PlanWeek/
    PlanItem (issue #188, checkpoint 1 — read-only-аудит подтвердил: FK
    plan_items -> plan_weeks не было ни в одной миграции волны 1, PlanWeek
    существовала мёртвой таблицей). Вызывается и из routes_v2.py (новые
    пользователи), и из scripts/backfill_multi_program.py (существующие) —
    один и тот же метод, не две параллельные реализации недели.

    Не меняет ProgressionStrategy/target'ы/снаряд/каскад — те живут в
    ProgramInclusion.progression_state и ProgressionCascadeService, этот
    сервис только размещает уже посчитанную работу во времени."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._plans = TrainingPlanRepository(session)
        self._convergence = PlanConvergenceService(session)

    async def ensure_current_plan_week(self, *, training_plan_id: int, today: date) -> PlanWeek:
        """Идемпотентно: текущая PlanWeek + сходимость плана (issue #304: одна строка = одно занятие).
        Вся логика — в единственной converge_user_plan (app.services.plan_convergence); этот метод —
        прежняя точка входа для GET /plan, подключения курса, бэкфилла и repair-скрипта."""
        week, _ = await self._convergence.converge_user_plan(training_plan_id=training_plan_id, today=today)
        return week

    async def converge_user_plan(self, *, training_plan_id: int, today: date) -> ConvergenceReport:
        _, report = await self._convergence.converge_user_plan(training_plan_id=training_plan_id, today=today)
        return report

    async def converge_inclusion_snapshot(self, inclusion: ProgramInclusion) -> SnapshotRepair | None:
        """#301 — каноническая починка снимка без program_items (см. PlanConvergenceService)."""
        return await self._convergence.converge_inclusion_snapshot(inclusion)

    async def release_future_weeks_of_inclusion(self, *, inclusion: ProgramInclusion, today: date) -> int:
        """#301 — «Убрать курс»: строки этого курса в БУДУЩИХ неделях (после текущей) — это
        ещё не выполнявшиеся плановые слоты, не история; убираем те, на которые нет ни одной
        сессии (SessionPlanItem). Текущая и прошлые недели не трогаются (как и раньше), строки
        с сессиями — тоже. Возвращает число удалённых строк."""
        plan = await self._plans.get_by_id(inclusion.training_plan_id)
        if plan is None:
            return 0
        current_number = plan_week_number(plan.created_at.date(), today)
        return await self._plans.delete_unperformed_inclusion_items_after_week(
            program_inclusion_id=inclusion.id, after_week_number=current_number,
        )

    async def ensure_plannable_week(self, *, training_plan_id: int, week_number: int, today: date) -> PlanWeek | None:
        """issue #275 — get-or-create PlanWeek для планирования вперёд. None — неделя вне окна
        «текущая .. +4» (прошлая/слишком далёкая). Недостающие промежуточные недели создаются тоже;
        занятия курсов и своих планов материализует та же converge_user_plan (#304)."""
        plan = await self._plans.get_by_id(training_plan_id)
        if plan is None:
            raise ValueError(f"training plan {training_plan_id} not found")
        current_number = plan_week_number(plan.created_at.date(), today)
        if not is_plannable_week_number(week_number, current_number):
            return None
        await self._convergence.converge_user_plan(
            training_plan_id=training_plan_id, today=today, create_until_week=week_number,
        )
        return await self._plans.get_plan_week(training_plan_id=training_plan_id, week_number=week_number)

    async def copy_manual_items(self, *, source: PlanWeek, target: PlanWeek) -> tuple[int, int]:
        """Копирует ручные PlanItem недели source в target. Источник переносится без потерь:
        одинаковые (exercise, complex, день) строки внутри source — отдельные строки со своим
        count. Идемпотентность повторного копирования — по мультимножеству: сколько строк с
        таким ключом уже есть в target, столько строк источника пропускается как дубли.
        Программные строки не копируются. Возвращает (скопировано, пропущено).

        Два конкурентных вызова на один план сериализуются локом строки плана
        (иначе оба прочитают пустую target и продублируют строки); второй
        увидит строки, закоммиченные первым, и пропустит их как дубликаты."""
        await self._plans.lock_plan(source.training_plan_id)
        existing = await self._plans.list_manual_plan_items_for_week(target.id)
        remaining: dict[tuple, int] = {}
        for item in existing:
            key = (item.exercise_id, item.complex_id, item.day_of_week)
            remaining[key] = remaining.get(key, 0) + 1
        copied = skipped = 0
        for item in await self._plans.list_manual_plan_items_for_week(source.id):
            key = (item.exercise_id, item.complex_id, item.day_of_week)
            if remaining.get(key, 0) > 0:
                remaining[key] -= 1
                skipped += 1
                continue
            self._session.add(PlanItem(
                training_plan_id=item.training_plan_id, exercise_id=item.exercise_id, complex_id=item.complex_id,
                count_per_week=item.count_per_week, day_of_week=item.day_of_week, week_phase=item.week_phase,
                program_inclusion_id=None, plan_week_id=target.id, origin_plan_week_id=target.id,
                source=OccurrenceSource.MANUAL.value, workout_definition_id=item.workout_definition_id,
                occurrence_index=1 if item.occurrence_index is not None else None,
                scheduled_date=(
                    target.start_date + timedelta(days=item.day_of_week) if item.day_of_week is not None else None
                ),
                status=PlanItemStatus.OPEN.value,
            ))
            copied += 1
        await self._session.flush()
        return copied, skipped
