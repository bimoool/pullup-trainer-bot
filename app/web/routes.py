from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from init_data_py import InitData
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatting import (
    format_block_result,
    format_equipment_label,
    format_subscription_status,
)
from app.config import settings
from app.db.models import BlockType
from app.db.repositories.achievements import AchievementRepository
from app.db.repositories.equipment_items import EquipmentItemRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.anomalies import detect_anomalies
from app.domain.constants import STRENGTH_BLOCK, EquipmentType
from app.domain.progression import rollback_target
from app.domain.rules import TrainingReadiness, check_training_readiness
from app.domain.session import BlockLog
from app.services.subscription import SubscriptionService
from app.services.workout_log import WorkoutLogService, ensure_active_workout_set
from app.web.auth import get_validated_init_data
from app.web.db import get_session
from app.web.schemas import (
    AnomalyFlagsResponse,
    BandItemInfo,
    EquipmentInfo,
    HelloResponse,
    ProfileResponse,
    WorkoutPlanResponse,
    WorkoutSubmitRequest,
    WorkoutSubmitResponse,
)

router = APIRouter(prefix="/api")


@router.get("/hello", response_model=HelloResponse)
async def hello(
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> HelloResponse:
    """Единственный эндпойнт Этапа 0 — не содержательная фича, а
    доказательство, что вся цепочка работает целиком: initData (Telegram)
    → HTTPS → FastAPI → validate (app/web/auth.py) → те же
    repositories/domain, что использует бот (app/bot/handlers/workout.py:
    handle_start_workout — тот же check_training_readiness на тех же
    данных, не дублированная копия правила).

    name — из initData.user (Telegram уже подтвердил личность подписью),
    не из БД: у ещё не онбордившегося пользователя в users вообще нет
    строки, а поздороваться нужно в любом случае."""
    telegram_id = init_data.user.id
    name = init_data.user.first_name

    user = await UserRepository(session).get_by_telegram_id(telegram_id)
    if user is None:
        return HelloResponse(
            name=name, is_onboarded=False, readiness_status=None, days_since_last_workout=None,
        )

    history = await WorkoutRepository(session).list_for_user(user.id)
    if not history:
        return HelloResponse(
            name=name, is_onboarded=True, readiness_status=None, days_since_last_workout=None,
        )

    readiness = check_training_readiness(history[-1].performed_at.date(), datetime.now(UTC).date())
    return HelloResponse(
        name=name, is_onboarded=True,
        readiness_status=readiness.status.value,
        days_since_last_workout=readiness.days_since_last_workout,
    )


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> ProfileResponse:
    """Вкладка "Профиль" Mini App (issue #45, часть 3) — сознательно узкий
    срез app.bot.handlers.menu.render_profile: тот же format_subscription_status
    (единый источник представления статуса, не веб-копия), без
    роста/веса/таймзоны/списка ачивок текстом — задел под навигацию,
    наполнить остальным можно по одному полю за раз позже (issue #45,
    план части 3), не всё сразу."""
    user = await UserRepository(session).get_by_telegram_id(init_data.user.id)
    if user is None:
        return ProfileResponse(is_onboarded=False)

    achievements = await AchievementRepository(session).list_for_user(user.id)
    history = await WorkoutRepository(session).list_for_user(user.id)
    days_since_last_workout = (
        (datetime.now(UTC).date() - history[-1].performed_at.date()).days if history else None
    )

    return ProfileResponse(
        is_onboarded=True,
        subscription_status_label=format_subscription_status(user),
        coins_balance=user.coins_balance,
        achievements_count=len(achievements),
        workouts_count=len(history),
        days_since_last_workout=days_since_last_workout,
    )


@dataclass
class _PlanContext:
    """Общий результат для GET /api/workout/plan и POST /api/workout/submit
    (issue #36, Этап 1) — оба эндпойнта должны видеть один и тот же статус
    для одного и того же пользователя в один и тот же момент, submit
    пересчитывает его заново, а не доверяет тому, что клиент прислал из
    предыдущего GET (см. docstring submit_workout).

    status="ready" — единственный случай, когда остальные поля заполнены.
    Любой другой статус — точная копия того, что определило бы ветку в
    handle_start_workout (app/bot/handlers/workout.py): too_early,
    gap_retest_required, deload_due, equipment_setup_required — Mini App их
    не обрабатывает формой (сужение скоупа Этапа 1, см. issue #36), только
    gap_rollback остаётся внутри "ready" (see is_gap_rollback)."""

    status: str
    user_id: int | None = None
    workout_set_id: int | None = None
    target_a: int | None = None
    target_b: int | None = None
    work_sets_a: int | None = None
    equipment_a_type: EquipmentType | None = None
    equipment_a_value: Decimal | None = None
    equipment_a_item_id: int | None = None
    equipment_b_type: EquipmentType | None = None
    equipment_b_value: Decimal | None = None
    equipment_b_item_id: int | None = None
    is_gap_rollback: bool = False


async def _resolve_plan_context(
    session: AsyncSession, telegram_id: int, *, now: datetime,
) -> _PlanContext:
    """Тонкая обвязка вокруг того же пути, что handle_start_workout
    (app/bot/handlers/workout.py) проходит перед показом плана живой
    тренировки — те же репозитории/домен, тот же порядок проверок, не
    копия правил.

    Единственное реальное отличие от бота: needs_new_equipment (для
    любого блока) и is_volume_deload_due здесь тоже останавливают поток —
    Mini App Этапа 1 не переспрашивает снаряд и не показывает
    разгрузочную форму (сужение скоупа, issue #36, согласовано в
    комментарии к issue), эти случаи ведут пользователя обратно в бота.
    ensure_active_workout_set (app/services/workout_log.py, общая с ботом
    функция) вызывается только когда мы точно дошли до "ready" — не
    заводим лишний WorkoutSet ради статуса, который Mini App всё равно не
    покажет формой."""
    user = await UserRepository(session).get_by_telegram_id(telegram_id)
    if user is None:
        return _PlanContext(status="not_onboarded")

    if not await SubscriptionService(session).has_access(user.id, now=now):
        return _PlanContext(status="no_access")

    workouts = WorkoutRepository(session)
    history = await workouts.list_for_user(user.id)
    if not history:
        return _PlanContext(status="first_workout")

    is_admin = settings.is_admin(telegram_id)
    readiness = check_training_readiness(history[-1].performed_at.date(), now.date())
    if readiness.status == TrainingReadiness.TOO_EARLY and not is_admin:
        return _PlanContext(status="too_early")
    if readiness.status == TrainingReadiness.GAP_RETEST_REQUIRED:
        return _PlanContext(status="gap_retest_required")

    if await workouts.is_volume_deload_due(user.id, now=now):
        return _PlanContext(status="deload_due")

    target_a_state, target_b_state = await workouts.resolve_next_targets(
        user.id, bypass_transition_wait=is_admin,
    )
    if target_a_state.needs_new_equipment or target_b_state.needs_new_equipment:
        return _PlanContext(status="equipment_setup_required")

    active_set = await ensure_active_workout_set(session, user.id)
    if active_set is None:
        return _PlanContext(status="no_active_set")

    is_gap_rollback = readiness.status == TrainingReadiness.GAP_ROLLBACK
    target_a = rollback_target(target_a_state.target) if is_gap_rollback else target_a_state.target

    return _PlanContext(
        status="ready",
        user_id=user.id,
        workout_set_id=active_set.id,
        target_a=target_a,
        target_b=target_b_state.target,
        work_sets_a=target_a_state.work_sets,
        equipment_a_type=target_a_state.equipment_type,
        equipment_a_value=target_a_state.equipment_value,
        equipment_a_item_id=target_a_state.equipment_item_id,
        equipment_b_type=target_b_state.equipment_type,
        equipment_b_value=target_b_state.equipment_value,
        equipment_b_item_id=target_b_state.equipment_item_id,
        is_gap_rollback=is_gap_rollback,
    )


def _equipment_info(
    equipment_type: EquipmentType, equipment_value: Decimal | None, equipment_item_id: int | None,
) -> EquipmentInfo:
    return EquipmentInfo(
        type=equipment_type.value,
        value=equipment_value,
        item_id=equipment_item_id,
        label=format_equipment_label(equipment_type, equipment_value),
    )


@router.get("/workout/plan", response_model=WorkoutPlanResponse)
async def get_workout_plan(
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> WorkoutPlanResponse:
    """Экран плана Mini App (issue #36, Этап 1) — та же цель/снаряд, что
    видно в тексте бота (CURRENT_PLAN/WORKOUT_PLAN), тем же путём. Статус
    "ready" уже гарантирует активный WorkoutSet (см. _resolve_plan_context)
    — POST /api/workout/submit пересчитывает его заново на момент отправки,
    не переиспользует workout_set_id из этого ответа."""
    context = await _resolve_plan_context(session, init_data.user.id, now=datetime.now(UTC))
    if context.status != "ready":
        return WorkoutPlanResponse(status=context.status)

    band_items: list[BandItemInfo] = []
    if EquipmentType.BAND in (context.equipment_a_type, context.equipment_b_type):
        items = await EquipmentItemRepository(session).list_for_user(context.user_id)
        band_items = [
            BandItemInfo(id=item.id, name=item.name, resistance_kg=item.resistance_kg) for item in items
        ]

    return WorkoutPlanResponse(
        status="ready",
        workout_set_id=context.workout_set_id,
        target_a=context.target_a,
        target_b=context.target_b,
        work_sets_a=context.work_sets_a,
        work_sets_b=STRENGTH_BLOCK.work_sets,
        equipment_a=_equipment_info(
            context.equipment_a_type, context.equipment_a_value, context.equipment_a_item_id,
        ),
        equipment_b=_equipment_info(
            context.equipment_b_type, context.equipment_b_value, context.equipment_b_item_id,
        ),
        is_gap_rollback=context.is_gap_rollback,
        band_items=band_items,
    )


@router.post("/workout/submit", response_model=WorkoutSubmitResponse)
async def submit_workout(
    body: WorkoutSubmitRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> WorkoutSubmitResponse:
    """Записывает результаты через WorkoutLogService.record_workout — тот же
    сервис, что _finalize_workout бота (app/bot/handlers/workout.py) вызывает
    в конце живой тренировки, не отдельная реализация. Снаряд не
    переспрашивается: он взят из _resolve_plan_context (то же самое
    equipment_type/value/item_id, что унаследовала бы живая тренировка при
    needs_new_equipment=False, см. app/bot/handlers/equipment.py::
    _begin_equipment_setup) — статус "equipment_setup_required" уже отсеян
    контекстом раньше.

    Все проверки статуса повторяются заново на сервере (не доверяем
    клиенту цифры из предыдущего GET /plan — например, если тренировка уже
    записана параллельно из бота, статус здесь изменится сам). Аномалии
    (detect_anomalies — та же функция домена, что использует
    handle_block_a_result/handle_block_b_result бота) не блокируют запись
    жёстко: при первом заходе без confirm_anomalies=True возвращается
    anomaly_confirm_required и ничего не пишется в БД, повторный вызов с
    confirm_anomalies=True дописывает тренировку — тот же двухшаговый
    паттерн, что и anomaly_confirm_keyboard в боте."""
    now = datetime.now(UTC)
    context = await _resolve_plan_context(session, init_data.user.id, now=now)
    if context.status != "ready":
        return WorkoutSubmitResponse(status=context.status)

    block_a_reps = BlockLog(
        working_reps=tuple(body.block_a_working_reps), max_reps=body.block_a_max_reps,
    )
    block_b_reps = BlockLog(
        working_reps=tuple(body.block_b_working_reps), max_reps=body.block_b_max_reps,
    )

    workouts = WorkoutRepository(session)
    previous_avg_a = await workouts.get_previous_avg_working(context.user_id, BlockType.A)
    previous_avg_b = await workouts.get_previous_avg_working(context.user_id, BlockType.B)
    anomalies_a = detect_anomalies(
        block_a_reps, previous_avg_working=previous_avg_a, expected_work_sets=context.work_sets_a,
    )
    anomalies_b = detect_anomalies(
        block_b_reps, previous_avg_working=previous_avg_b,
        expected_work_sets=STRENGTH_BLOCK.work_sets,
    )
    if not body.confirm_anomalies and (not anomalies_a.is_empty() or not anomalies_b.is_empty()):
        return WorkoutSubmitResponse(
            status="anomaly_confirm_required",
            anomalies_a=AnomalyFlagsResponse(**asdict(anomalies_a)),
            anomalies_b=AnomalyFlagsResponse(**asdict(anomalies_b)),
        )

    # Фактический вес (issue #45, часть 2) — та же правка "на месте", что
    # "✏️ Изменить вес/резину" в боте (app/bot/handlers/workout.py::
    # handle_change_block_equipment), только применяется тут, а не отдельным
    # шагом FSM до ввода повторений. Действует только для WEIGHT: снаряд
    # унаследован из _resolve_plan_context (needs_new_equipment=False уже
    # проверен там), а у BAND/BODYWEIGHT/AUSTRALIAN "вес" не имеет смысла —
    # тело/сопротивление резины клиент поправить не может, тот же принцип,
    # что у equipment.py (свободный ввод кг доступен только для WEIGHT).
    equipment_a_value = context.equipment_a_value
    if body.block_a_actual_weight is not None and context.equipment_a_type == EquipmentType.WEIGHT:
        equipment_a_value = body.block_a_actual_weight
    equipment_b_value = context.equipment_b_value
    if body.block_b_actual_weight is not None and context.equipment_b_type == EquipmentType.WEIGHT:
        equipment_b_value = body.block_b_actual_weight

    # Выбор резины (issue #48) — тот же принцип, что actual_weight выше,
    # только для BAND и item_id вместо числа (у BAND equipment_value не
    # заполняется, см. app/db/models.py::EquipmentItem). item должен
    # принадлежать вызывающему пользователю — id из чужого личного списка
    # не должен молча привязаться к этой тренировке.
    equipment_a_item_id = context.equipment_a_item_id
    equipment_b_item_id = context.equipment_b_item_id
    if body.block_a_actual_band_item_id is not None and context.equipment_a_type == EquipmentType.BAND:
        item = await EquipmentItemRepository(session).get_by_id(body.block_a_actual_band_item_id)
        if item is None or item.user_id != context.user_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid band item for block A")
        equipment_a_item_id = item.id
    if body.block_b_actual_band_item_id is not None and context.equipment_b_type == EquipmentType.BAND:
        item = await EquipmentItemRepository(session).get_by_id(body.block_b_actual_band_item_id)
        if item is None or item.user_id != context.user_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid band item for block B")
        equipment_b_item_id = item.id

    log_service = WorkoutLogService(session)
    workout = await log_service.record_workout(
        user_id=context.user_id,
        workout_set_id=context.workout_set_id,
        performed_at=now,
        block_a_reps=block_a_reps,
        block_b_reps=block_b_reps,
        block_a_equipment_type=context.equipment_a_type,
        block_a_equipment_value=equipment_a_value,
        block_b_equipment_type=context.equipment_b_type,
        block_b_equipment_value=equipment_b_value,
        block_a_equipment_item_id=equipment_a_item_id,
        block_b_equipment_item_id=equipment_b_item_id,
        target_a_override=context.target_a if context.is_gap_rollback else None,
        target_b_override=None,
        is_deload_a=False,
        comment=body.comment,
    )

    block_a = next(b for b in workout.blocks if b.block_type == BlockType.A)
    block_b = next(b for b in workout.blocks if b.block_type == BlockType.B)

    return WorkoutSubmitResponse(
        status="ok",
        target_a=block_a.target_after,
        target_b=block_b.target_after,
        equipment_a=_equipment_info(
            block_a.equipment_type, block_a.equipment_value, block_a.equipment_item_id,
        ),
        equipment_b=_equipment_info(
            block_b.equipment_type, block_b.equipment_value, block_b.equipment_item_id,
        ),
        result_a=format_block_result(block_a.working_reps, block_a.max_reps),
        result_b=format_block_result(block_b.working_reps, block_b.max_reps),
    )
