from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import PlanWeek
from app.db.repositories.programs import ProgramRepository
from app.db.repositories.training_plans import TrainingPlanRepository
from app.domain.multi_program import (
    ProgramStructureType,
    WeekPhase,
    plan_week_number,
    plan_week_start_date,
)


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
        self._programs = ProgramRepository(session)

    async def ensure_current_plan_week(self, *, training_plan_id: int, today: date) -> PlanWeek:
        """Идемпотентно: get-or-create текущая PlanWeek + материализация
        активных RECURRING ProgramInclusion в неё. Безопасно вызывать
        многократно (routes_v2.py на каждый GET /plan) и повторно
        (backfill) — ни разу не создаёт дублей, см. tests/test_services/
        test_plan_week_service.py."""
        plan = await self._plans.get_by_id(training_plan_id)
        if plan is None:
            raise ValueError(f"training plan {training_plan_id} not found")

        plan_created_date = plan.created_at.date()
        week_number = plan_week_number(plan_created_date, today)

        week = await self._plans.get_plan_week(training_plan_id=training_plan_id, week_number=week_number)
        if week is None:
            week = await self._plans.create_plan_week(
                training_plan_id=training_plan_id, week_number=week_number,
                start_date=plan_week_start_date(plan_created_date, week_number), phase=WeekPhase.BASE,
            )

        inclusions = await self._plans.list_inclusions(training_plan_id)
        for inclusion in inclusions:
            if not inclusion.is_active:
                continue

            # Checkpoint 1.1 (issue #188) — контрактный баг checkpoint 1:
            # structure_type и program_items читаются из snapshot, не из
            # live Program/ProgramItem. program_id используется ТОЛЬКО как
            # provenance-фолбэк — legacy-снимок до нормализации (см.
            # scripts/backfill_multi_program.py::normalize_legacy_snapshots)
            # может не иметь structure_type, тогда и только тогда идём в
            # живую Program за ним, за program_items — никогда (нет
            # безопасного фолбэка на "актуальную" структуру курса без
            # искажения snapshot semantics, поэтому пустой snapshot
            # ["program_items"] просто не материализуется, до нормализации).
            snapshot = inclusion.snapshot or {}
            structure_type_value = snapshot.get("structure_type")
            if structure_type_value is None:
                program = await self._programs.get_by_id(inclusion.program_id)
                structure_type_value = program.structure_type.value if program is not None else None
            if structure_type_value != ProgramStructureType.RECURRING.value:
                # FIXED/SINGLE_LESSON не материализуются понедельно этим
                # сервисом в этом чекпоинте — ни одной такой программы в
                # каталоге пока нет (read-only-аудит, раздел C), решать
                # семантику при появлении первой, не заранее.
                continue

            unweeked = await self._plans.list_unweeked_plan_items(program_inclusion_id=inclusion.id)
            if unweeked:
                # Первая материализация этой инклюзии (только что создана
                # bulk_create_plan_items_from_program_items при POST
                # /program-inclusions — см. ProgramInclusionService — либо
                # это старые строки из бэкфилла до checkpoint 1). Дублей не
                # создаём, привязываем то, что уже есть.
                await self._plans.attach_plan_items_to_week(plan_items=unweeked, plan_week_id=week.id)
                continue

            existing_this_week = await self._plans.list_plan_items_for_week(
                program_inclusion_id=inclusion.id, plan_week_id=week.id,
            )
            if existing_this_week:
                continue  # уже материализовано в эту неделю — идемпотентность

            program_items_snapshot = snapshot.get("program_items")
            if not program_items_snapshot:
                continue  # legacy-снимок без program_items — нормализуется отдельно, не здесь

            # Rollover (раздел 7 preflight): предыдущая неделя(и) уже имеют
            # свои PlanItem, наступила новая — клонируем ИЗ SNAPSHOT заново,
            # прошлые недели не трогаем. Live Program могла измениться с
            # момента подключения — это не должно повлиять на уже
            # подключённого пользователя (snapshot immutability, issue #188
            # checkpoint 1.1, см. tests/test_services/test_plan_week_service
            # .py::test_rollover_uses_snapshot_not_live_program).
            await self._plans.create_plan_items_for_week_from_snapshot(
                training_plan_id=training_plan_id, program_inclusion_id=inclusion.id,
                plan_week_id=week.id, program_items_snapshot=program_items_snapshot,
            )

        return week
