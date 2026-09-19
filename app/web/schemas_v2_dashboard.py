"""Pydantic-схемы для app/web/routes_v2_dashboard.py (issue #167, волна 4) —
pull-up-специфичная обвязка статуса Dashboard поверх общего
app/web/routes_v2.py: PlanResponse там — сырой CRUD-снимок ресурсов
(TrainingPlan/ProgramInclusion/PlanItem), эти схемы — уже посчитанный
пользовательский статус экрана, тот же водораздел, что _PlanContext/
WorkoutPlanResponse у старой схемы в app/web/schemas.py."""

from typing import Literal

from pydantic import BaseModel


class DashboardEquipmentResponse(BaseModel):
    type: str
    value: str | None
    item_id: int | None
    label: str
    # Смена снаряда сигнализируется StepProgressionStrategy
    # (needs_new_equipment в progression_state), но выбор конкретного нового
    # снаряда в v2 пока не автоматизирован — нет UI/эндпоинта выбора (см.
    # app/services/session_log.py). Dashboard показывает это read-only
    # текстом, а не отдельным блокирующим статусом (issue #167, план,
    # подтверждено Кириллом).
    needs_new_equipment: bool


class DashboardBlockResponse(BaseModel):
    target: int
    work_sets: int
    equipment: DashboardEquipmentResponse


class DashboardStatusResponse(BaseModel):
    """GET /api/v2/dashboard/status — статус read-only витрины Dashboard
    (issue #167, волна 4). Читает ProgramInclusion.progression_state, не
    отдаёт сырой /api/v2/plan напрямую (см. докстринг
    app/web/routes_v2_dashboard.py про то, где проведена граница между
    "данные" и "статус экрана").

    "not_migrated" — нет TrainingPlan, ни одной активной ProgramInclusion,
    или активная инклюзия не STEP-стратегии (замена first_workout/
    not_onboarded старой схемы на этом этапе — Dashboard видит только STEP,
    см. докстринг routes_v2_dashboard.py).
    "multiple_active_inclusions" — больше одного активного курса; Dashboard
    пока не умеет выбирать между ними, не угадывает.
    "too_early"/"gap_retest_required" — тот же расчёт, что старая схема
    (app.domain.rules.check_training_readiness), от даты последней
    TrainingSession пользователя (не последней сессии именно этого курса —
    TrainingSession не хранит program_inclusion_id, известное ограничение
    схемы волны 3, см. CLAUDE.md/issue #167).

    Тест на максимум блока A (is_deload_a) и чередование тяжёлой блока Б
    (is_heavy_b) старой схемы сознательно НЕ перенесены в этой волне — в
    progression_state v2 нет ни якорной даты последнего теста, ни расчёта
    чётности (подтверждено Кириллом как честный, задокументированный
    пробел). Dashboard всегда показывает блок Б как обычную тренировку,
    фронтенд поясняет это статичной сноской, не пытается угадать."""

    status: Literal["not_migrated", "too_early", "gap_retest_required", "multiple_active_inclusions", "ready"]
    program_name: str | None = None
    is_gap_rollback: bool = False
    work_sets_growth_reason: Literal["stall", "ceiling"] | None = None
    block_a: DashboardBlockResponse | None = None
    block_b: DashboardBlockResponse | None = None
