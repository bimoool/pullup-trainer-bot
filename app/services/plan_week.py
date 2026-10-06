import json
import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import PlanItem, PlanWeek, ProgramInclusion, TrainingPlan
from app.db.repositories.programs import ProgramRepository, program_items_snapshot
from app.db.repositories.training_plans import TrainingPlanRepository
from app.domain.multi_program import (
    ProgramStructureType,
    SnapshotProgramItemsGap,
    WeekPhase,
    is_plannable_week_number,
    plan_week_number,
    plan_week_start_date,
    snapshot_program_items_gap,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SnapshotRepair:
    """Одна выполненная починка снимка (для лога, отчёта repair-скрипта и тестов)."""

    inclusion_id: int
    training_plan_id: int
    program_id: int
    reason: SnapshotProgramItemsGap
    program_items: list[dict]


def _log_convergence(event: str, **fields) -> None:
    """Громкий структурированный WARNING: исторический пользовательский стейт чинится (или не может
    быть починен) рантаймом. Одна строка JSON — грепается в docker logs по имени события."""
    payload = {"event": event, **fields}
    logger.warning("%s %s", event, json.dumps(payload, ensure_ascii=False, default=str), extra=payload)


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

        # #297 — самовосстановление «сирот»: ручные строки без недели (старый
        # POST /plan-items у пользователя без плана) привязываем к текущей неделе.
        # Идемпотентно (после первого вызова выборка пуста), ничего не удаляем.
        orphans = await self._plans.list_orphan_manual_plan_items(training_plan_id=training_plan_id)
        if orphans:
            await self._plans.attach_plan_items_to_week(plan_items=orphans, plan_week_id=week.id)

        # #301 — недели, которые ни разу не были текущими (пользователь не заходил),
        # заполняем пустыми PlanWeek: степпер «Планов» не должен молча перепрыгивать
        # с недели 1 на 3. Строк в прошлые недели НЕ материализуем (они только для чтения).
        await self._fill_past_gap_weeks(plan, current_week_number=week_number)

        inclusions = await self._plans.list_inclusions(training_plan_id)
        if any(inclusion.is_active for inclusion in inclusions):
            # Материализация «проверить — вставить»: две конкурентные
            # транзакции (две вкладки, GET + POST) не должны оба вставить строки
            # недели. Лок плана до конца транзакции; перепроверки ниже читают
            # уже закоммиченное победителем (READ COMMITTED).
            await self._plans.lock_plan(training_plan_id)
        await self._materialize_inclusions_into_week(plan, week, inclusions, attach_unweeked=True)

        # #301 — будущие недели окна «текущая .. +4», которые уже существуют (создала
        # пользователь, › в «Планах», или прошлый вызов), тоже получают строки курса:
        # продолжающаяся программа не должна выглядеть пустой после недели 1. Недели
        # здесь НЕ создаются (их создаёт ensure_plannable_week) — только дополняются.
        for future in await self._plans.list_plan_weeks(training_plan_id):
            if future.week_number > week_number and is_plannable_week_number(future.week_number, week_number):
                await self._materialize_inclusions_into_week(plan, future, inclusions, attach_unweeked=False)

        return week

    async def _fill_past_gap_weeks(self, plan: TrainingPlan, *, current_week_number: int) -> None:
        """Создаёт недостающие пустые PlanWeek между самой ранней существующей и текущей
        неделей (get-or-create, идемпотентно). Ничего не удаляет и не наполняет строками."""
        existing = {week.week_number for week in await self._plans.list_plan_weeks(plan.id)}
        if not existing:
            return
        created = plan.created_at.date()
        for number in range(min(existing), current_week_number):
            if number not in existing:
                await self._plans.create_plan_week(
                    training_plan_id=plan.id, week_number=number,
                    start_date=plan_week_start_date(created, number), phase=WeekPhase.BASE,
                )

    async def _materialize_inclusions_into_week(
        self, plan: TrainingPlan, week: PlanWeek, inclusions: list[ProgramInclusion], *, attach_unweeked: bool,
    ) -> None:
        """Единый путь «курс -> строки конкретной недели» (текущей и будущих, #301).
        Источник — СНИМОК инклюзии (не live Program), идемпотентность по
        (инклюзия, неделя): если в неделе уже есть строки этой инклюзии, ничего не
        вставляется. Вызывать под локом плана (см. ensure_current_plan_week /
        ensure_plannable_week). attach_unweeked — только для ТЕКУЩЕЙ недели: свежесозданные
        строки инклюзии без недели привязываются к ней, а не клонируются заново."""
        for inclusion in inclusions:
            if not inclusion.is_active:
                continue

            # Checkpoint 1.1 (issue #188): structure_type и program_items читаются из snapshot,
            # не из live Program/ProgramItem. Live Program — только фолбэк: за structure_type,
            # если его нет в legacy-снимке, и за program_items ТОЛЬКО когда их в снимке нет или
            # список пуст (converge_inclusion_snapshot ниже, #301, решение владельца 2026-10-06).
            # Непустой список снимка — исторический факт подключения и не переписывается.
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

            # Aged-state convergence (#301, решение владельца 2026-10-06): снимок без/с пустым
            # program_items дополняется из live Program — один раз, персистентно, громко в лог.
            # Непустой исторический снимок не переписывается никогда (snapshot immutability).
            await self.converge_inclusion_snapshot(inclusion)
            snapshot = inclusion.snapshot or {}

            if attach_unweeked:
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

            snapshot_items = snapshot.get("program_items")
            if not snapshot_items:
                # После convergence сюда попадает только то, что починить нельзя (у live Program
                # нет ProgramItem, или значение не список) — не тихий continue, а громкий лог.
                _log_convergence(
                    "plan_convergence_gap", inclusion_id=inclusion.id, training_plan_id=plan.id,
                    program_id=inclusion.program_id, plan_week_id=week.id, week_number=week.week_number,
                    reason="snapshot_has_no_materializable_program_items",
                )
                continue

            # Rollover (раздел 7 preflight) и недели наперёд (#301): клонируем ИЗ
            # SNAPSHOT заново, чужие недели не трогаем. Live Program могла измениться с
            # момента подключения — это не должно повлиять на уже
            # подключённого пользователя (snapshot immutability, issue #188
            # checkpoint 1.1, см. tests/test_services/test_plan_week_service
            # .py::test_rollover_uses_snapshot_not_live_program).
            await self._plans.create_plan_items_for_week_from_snapshot(
                training_plan_id=plan.id, program_inclusion_id=inclusion.id,
                plan_week_id=week.id, program_items_snapshot=snapshot_items,
            )

    async def converge_inclusion_snapshot(self, inclusion: ProgramInclusion) -> SnapshotRepair | None:
        """ЕДИНСТВЕННАЯ каноническая починка «старого» снимка инклюзии (#301, aged-state convergence;
        решение владельца 2026-10-06). Вызывается рантаймом (материализация недели на GET /plan и
        остальных входах) и targeted-скриптом scripts/repair_plan_convergence.py — один код.

        Чинит ТОЛЬКО активную инклюзию, у снимка которой program_items отсутствует или пуст
        (domain.snapshot_program_items_gap), и ТОЛЬКО если у live Program есть ProgramItem: в снимок
        дописывается ровно один ключ "program_items" (та же сериализация, что при подключении курса).
        Не трогает: непустой исторический снимок, остальные ключи снимка, progression_state,
        started_at, is_active, PlanItem/PlanWeek/сессии, подписку. Идемпотентно: после починки
        предикат возвращает None. Каждая починка — громкий структурированный WARNING."""
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
        await self._session.flush()
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
        """issue #275 — get-or-create PlanWeek для планирования вперёд.
        None — неделя вне окна «текущая .. +4» (прошлая/слишком далёкая).
        Недостающие промежуточные недели создаются тоже, чтобы список недель
        оставался непрерывным. #301: строки активных RECURRING-курсов материализуются
        в каждую неделю окна до week_number (из снимка инклюзии, идемпотентно) — будущая
        неделя продолжающейся программы не пустая. Недели до текущей не трогаются."""
        plan = await self._plans.get_by_id(training_plan_id)
        if plan is None:
            raise ValueError(f"training plan {training_plan_id} not found")
        created = plan.created_at.date()
        current_number = plan_week_number(created, today)
        if not is_plannable_week_number(week_number, current_number):
            return None
        inclusions = await self._plans.list_inclusions(training_plan_id)
        if any(inclusion.is_active for inclusion in inclusions):
            await self._plans.lock_plan(training_plan_id)
        week = None
        for number in range(current_number, week_number + 1):
            week = await self._plans.get_plan_week(training_plan_id=training_plan_id, week_number=number)
            if week is None:
                week = await self._plans.create_plan_week(
                    training_plan_id=training_plan_id, week_number=number,
                    start_date=plan_week_start_date(created, number), phase=WeekPhase.BASE,
                )
            # Текущую неделю целиком (сироты, unweeked) ведёт ensure_current_plan_week; здесь —
            # только будущие, у текущей строки уже материализованы GET /plan.
            await self._materialize_inclusions_into_week(
                plan, week, inclusions, attach_unweeked=number == current_number,
            )
        return week

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
                program_inclusion_id=None, plan_week_id=target.id,
            ))
            copied += 1
        await self._session.flush()
        return copied, skipped
