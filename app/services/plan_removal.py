"""Снятие занятий плана без потери кредита (issue #304 B1/B3, PROGRAM_PLAN_V2 §5 PL8–PL10).

Три пользовательских действия, один набор правил:

* «Убрать из плана» одно занятие (DELETE /api/v2/plan-items/{id});
* удаление своей тренировки (DELETE /api/v2/workouts/{id}) — её строки плана;
* «Остановить план» своего плана (POST /api/v2/custom-plans/{id}/deactivate).

Правила:

1. Засчитанное занятие (на строку ссылается хоть одна сессия — явный кредит
   training_sessions.plan_item_id или старая M2M) НЕ удаляется и НЕ снимается: строка, её статус и
   session.plan_item_id не меняются. Явное «Убрать» такого занятия — CreditedPlanItemError (422).
2. Незасчитанное занятие своего плана снимается МЯГКО: status = removed. Строка остаётся и занимает
   свою идентичность (origin_plan_week_id, custom_plan_id, occurrence_index), поэтому
   converge_user_plan её не пересоздаёт.
3. Незасчитанная ручная строка (без курса и своего плана) удаляется жёстко, как и раньше: её
   повторно не материализует никто.
4. Занятия курса этим путём не снимаются (404, как раньше): курс снимается целиком («Убрать курс»).

Конкурентность: до проверки кредита берётся advisory-лок стартов пользователя
(app.services.live_session.lock_user_starts — старт, засчитывающий занятие, сериализован с ним), затем
строка плана (lock_plan — сериализует с converge_user_plan). Строки читаются ПОСЛЕ локов."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import CustomPlan, PlanItem, TrainingPlan
from app.db.repositories.training_plans import TrainingPlanRepository
from app.db.repositories.training_sessions import TrainingSessionRepository
from app.domain.multi_program import plan_week_number
from app.domain.plan_occurrence import PlanItemStatus
from app.services.live_session import lock_user_starts

CREDITED_PLAN_ITEM_CODE = "credited_plan_item"
CREDITED_PLAN_ITEM_MESSAGE = "Засчитанную тренировку удалить нельзя"


class CreditedPlanItemError(Exception):
    """Явное удаление засчитанного занятия (роут → 422 {code: credited_plan_item})."""


class PlanItemRemoval(StrEnum):
    DELETED = "deleted"  # ручная незасчитанная строка удалена
    REMOVED = "removed"  # занятие своего плана снято мягко (status = removed)


@dataclass(frozen=True)
class WorkoutItemsRemoval:
    deleted: int
    removed: int
    kept_credited: int


@dataclass(frozen=True)
class CustomPlanDeactivation:
    custom_plan: CustomPlan
    removed: int


class PlanRemovalService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._plans = TrainingPlanRepository(session)
        self._sessions = TrainingSessionRepository(session)

    async def _lock(self, user_id: int) -> TrainingPlan | None:
        plan = await self._plans.get_for_user(user_id)
        if plan is None:
            return None
        await lock_user_starts(self._session, user_id)
        return await self._plans.lock_plan(plan.id)

    async def _refresh(self, items: list[PlanItem]) -> None:
        # Строки могли быть загружены до локов (identity map) — статус читаем заново.
        for item in items:
            await self._session.refresh(item)

    async def _disposal(self, items: list[PlanItem]) -> tuple[list[PlanItem], list[PlanItem], int]:
        """(жёстко удалить, снять мягко, оставить засчитанными) — правила 1–3."""
        credited = await self._sessions.credited_plan_item_ids([item.id for item in items])
        delete: list[PlanItem] = []
        soft: list[PlanItem] = []
        kept = 0
        for item in items:
            if item.id in credited:
                kept += 1
            elif item.custom_plan_id is not None:
                if item.status != PlanItemStatus.REMOVED:
                    soft.append(item)
            else:
                delete.append(item)
        return delete, soft, kept

    async def _apply(self, delete: list[PlanItem], soft: list[PlanItem]) -> None:
        for item in soft:
            item.status = PlanItemStatus.REMOVED.value
        for item in delete:
            await self._plans.delete_plan_item(item)
        await self._plans.flush()

    async def remove_plan_item(self, *, user_id: int, plan_item_id: int) -> PlanItemRemoval | None:
        """None — нет / чужое / уже снятое / занятие курса (404). CreditedPlanItemError — засчитано."""
        plan = await self._lock(user_id)
        if plan is None:
            return None
        item = await self._plans.get_plan_item_for_user(plan_item_id, user_id)
        if item is None:
            return None
        await self._refresh([item])
        if item.status == PlanItemStatus.REMOVED or item.program_inclusion_id is not None:
            return None
        delete, soft, kept = await self._disposal([item])
        if kept:
            raise CreditedPlanItemError(CREDITED_PLAN_ITEM_MESSAGE)
        await self._apply(delete, soft)
        return PlanItemRemoval.REMOVED if soft else PlanItemRemoval.DELETED

    async def remove_workout_items(self, *, user_id: int, complex_id: int) -> WorkoutItemsRemoval:
        """Удаление своей тренировки: незасчитанные ручные строки — удалить, занятия своего плана —
        снять, засчитанные (любой источник) — оставить как есть (история кредита)."""
        plan = await self._lock(user_id)
        if plan is None:
            return WorkoutItemsRemoval(deleted=0, removed=0, kept_credited=0)
        items = await self._plans.list_workout_plan_items(plan.id, complex_id)
        await self._refresh(items)
        delete, soft, kept = await self._disposal(items)
        await self._apply(delete, soft)
        return WorkoutItemsRemoval(deleted=len(delete), removed=len(soft), kept_credited=kept)

    async def deactivate_custom_plan(
        self, *, user_id: int, custom_plan_id: int, today: date,
    ) -> CustomPlanDeactivation | None:
        """«Остановить план»: is_active = false (converge_user_plan больше не материализует его
        занятия); незасчитанные занятия текущей и будущих недель снимаются мягко; засчитанные и
        прошлые недели (история, «пропущено») не меняются. Повтор — 0 изменений. Чужой — None (404)."""
        plan = await self._lock(user_id)
        if plan is None:
            return None
        custom_plan = await self._plans.get_custom_plan_for_user(custom_plan_id, user_id)
        if custom_plan is None or custom_plan.training_plan_id != plan.id:
            return None
        await self._session.refresh(custom_plan)
        custom_plan.is_active = False
        current_number = plan_week_number(plan.created_at.date(), today)
        week_number_by_id = {week.id: week.week_number for week in await self._plans.list_plan_weeks(plan.id)}
        items = await self._plans.list_custom_plan_items(custom_plan.id)
        await self._refresh(items)
        open_items = [
            item for item in items
            if item.status != PlanItemStatus.REMOVED
            and week_number_by_id.get(item.plan_week_id, current_number) >= current_number
        ]
        _, soft, _ = await self._disposal(open_items)
        await self._apply([], soft)
        return CustomPlanDeactivation(custom_plan=custom_plan, removed=len(soft))
