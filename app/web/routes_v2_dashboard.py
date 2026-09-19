"""GET /api/v2/dashboard/status (issue #167, волна 4) — pull-up-специфичная
read-only витрина статуса поверх общей многокурсовой схемы. Намеренно
отдельный файл от app/web/routes_v2.py: докстринг того модуля прямо
заявляет "не pull-up-специфичные" эндпоинты — общий CRUD-слой волны 3 под
будущие произвольные программы. Статус-логика Dashboard (день отдыха, "какой
блок А/Б", допущение "ровно один активный STEP-курс") — pull-up/wave-4-
специфичная обвязка для конкретного экрана, смешивать её в routes_v2.py
значило бы испортить чистоту общего слоя.

Единственное место этой волны, где /api/v2/* подключается к
webapp-frontend/ (DashboardScreen.tsx, apiV2.ts) — см. сужение инварианта в
tests/test_web/test_v2_not_wired_to_ui.py (allowlist вместо полного запрета).

GET /api/v2/plan (routes_v2.py) остаётся как есть — чистое CRUD-чтение
ресурсов 1:1 со схемой, не аналог _resolve_plan_context старой схемы.
progression_state там непрозрачный dict, статус-логика по нему здесь, не
там (issue #167, план, подтверждено Кириллом)."""

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from init_data_py import InitData
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatting import format_equipment_label
from app.config import settings
from app.db.repositories.training_plans import TrainingPlanRepository
from app.db.repositories.training_sessions import TrainingSessionRepository
from app.db.repositories.users import UserRepository
from app.domain.constants import STRENGTH_BLOCK, EquipmentType
from app.domain.progression import rollback_target
from app.domain.rules import TrainingReadiness, check_training_readiness
from app.web.auth import get_validated_init_data
from app.web.db import get_session
from app.web.schemas_v2_dashboard import (
    DashboardBlockResponse,
    DashboardEquipmentResponse,
    DashboardStatusResponse,
)

router_v2_dashboard = APIRouter(prefix="/api/v2/dashboard")


def _equipment_response(block_state: dict) -> DashboardEquipmentResponse:
    equipment_type = EquipmentType(block_state["equipment_type"])
    raw_value = block_state.get("equipment_value")
    equipment_value = Decimal(raw_value) if raw_value is not None else None
    return DashboardEquipmentResponse(
        type=equipment_type.value,
        value=str(equipment_value) if equipment_value is not None else None,
        item_id=block_state.get("equipment_item_id"),
        label=format_equipment_label(equipment_type, equipment_value),
        needs_new_equipment=bool(block_state.get("needs_new_equipment", False)),
    )


@router_v2_dashboard.get("/status", response_model=DashboardStatusResponse)
async def get_dashboard_status(
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> DashboardStatusResponse:
    """404 для неизвестного telegram_id — тот же принцип, что
    _require_user в routes_v2.py (не молчаливое "not_migrated": в этом
    случае у нас вообще нет User, а не просто нет TrainingPlan)."""
    user = await UserRepository(session).get_by_telegram_id(init_data.user.id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    plans = TrainingPlanRepository(session)
    plan = await plans.get_for_user(user.id)
    if plan is None:
        return DashboardStatusResponse(status="not_migrated")

    active_inclusions = [inclusion for inclusion in await plans.list_inclusions(plan.id) if inclusion.is_active]
    if not active_inclusions:
        return DashboardStatusResponse(status="not_migrated")
    if len(active_inclusions) > 1:
        return DashboardStatusResponse(status="multiple_active_inclusions")
    inclusion = active_inclusions[0]

    progression_state = inclusion.progression_state
    if not progression_state or progression_state.get("strategy_type") != "step":
        return DashboardStatusResponse(status="not_migrated")

    is_gap_rollback = False
    last_sessions = await TrainingSessionRepository(session).list_for_user(user.id, limit=1)
    if last_sessions:
        is_admin = settings.is_admin(init_data.user.id)
        readiness = check_training_readiness(last_sessions[0].performed_at.date(), datetime.now(UTC).date())
        if readiness.status == TrainingReadiness.TOO_EARLY and not is_admin:
            return DashboardStatusResponse(status="too_early")
        if readiness.status == TrainingReadiness.GAP_RETEST_REQUIRED:
            return DashboardStatusResponse(status="gap_retest_required")
        is_gap_rollback = readiness.status == TrainingReadiness.GAP_ROLLBACK

    block_a_state, block_b_state = progression_state["block_a"], progression_state["block_b"]
    target_a = rollback_target(block_a_state["target"]) if is_gap_rollback else block_a_state["target"]

    return DashboardStatusResponse(
        status="ready",
        program_name=inclusion.snapshot.get("program_name"),
        is_gap_rollback=is_gap_rollback,
        work_sets_growth_reason=block_a_state.get("work_sets_growth_reason"),
        block_a=DashboardBlockResponse(
            target=target_a, work_sets=block_a_state["work_sets"], equipment=_equipment_response(block_a_state),
        ),
        block_b=DashboardBlockResponse(
            target=block_b_state["target"], work_sets=STRENGTH_BLOCK.work_sets,
            equipment=_equipment_response(block_b_state),
        ),
    )
