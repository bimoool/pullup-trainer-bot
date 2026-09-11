from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from init_data_py import InitData
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.formatting import (
    format_block_result,
    format_equipment_label,
    format_subscription_status,
)
from app.bot.handlers.menu import OFERTA_PDF_PATH
from app.bot.handlers.subscription import _robokassa_available
from app.bot.handlers.workout_edit import _is_editable
from app.config import settings
from app.db.models import ActiveTimerType, BlockType, SubscriptionStatus
from app.db.repositories.achievements import AchievementRepository
from app.db.repositories.active_timers import ActiveTimerRepository
from app.db.repositories.equipment_items import EquipmentItemRepository
from app.db.repositories.leaderboard import LeaderboardRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_drafts import WorkoutDraftRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.achievements import ACHIEVEMENT_LABELS, AchievementCode
from app.domain.anomalies import detect_anomalies
from app.domain.constants import (
    DEFAULT_BIG_BREAK_SECONDS,
    DEFAULT_REST_SECONDS_BLOCK_A,
    DEFAULT_REST_SECONDS_BLOCK_B,
    DEFAULT_TIMER_SOUND_VOLUME_PERCENT,
    STRENGTH_BLOCK,
    SUBSCRIPTION_DAYS,
    SUBSCRIPTION_PRICE_RUB,
    VOLUME_BLOCK,
    EquipmentType,
    VolumeGrowthReason,
    to_signed_load,
)
from app.domain.gto import calculate_gto_status
from app.domain.leaderboard import AGE_BUCKETS, LEADERBOARD_TOP_LIMIT, LeaderboardMetric
from app.domain.progression import rollback_target
from app.domain.reports import (
    EquipmentProgress,
    all_cycles_analytics,
    current_equipment_progress,
    weekly_summary,
)
from app.domain.rules import TrainingReadiness, check_training_readiness
from app.domain.session import BlockAssignment, BlockLog
from app.services.robokassa import RobokassaClient, RobokassaService
from app.services.subscription import SubscriptionService
from app.services.workout_log import WorkoutLogService, ensure_active_workout_set
from app.web.auth import get_validated_init_data
from app.web.db import get_session
from app.web.schemas import (
    AchievementItem,
    AnalyticsResponse,
    AnomalyFlagsResponse,
    BackdateSubmitRequest,
    BandItemInfo,
    CycleVolumeResponse,
    EquipmentInfo,
    EquipmentProgressResponse,
    GtoResponse,
    HelloResponse,
    HistoryBlockDetail,
    HistoryEditDetailResponse,
    HistoryEditRequest,
    HistoryEntryResponse,
    HistoryResponse,
    LeaderboardDisplayNameResponse,
    LeaderboardDisplayNameUpdateRequest,
    LeaderboardEntryResponse,
    LeaderboardResponse,
    PaymentLinkResponse,
    ProfileResponse,
    ProgressPointResponse,
    ProgressResponse,
    SubscriptionResponse,
    TimerPreferencesResponse,
    TimerPreferencesUpdateRequest,
    TimerStartRequest,
    TimerStatusResponse,
    WeeklySummaryResponse,
    WorkoutDraftRequest,
    WorkoutDraftResponse,
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

    # Список ачивок с датами (issue #66, п.1) — тот же ACHIEVEMENT_LABELS,
    # что render_profile бота, list_for_user уже отдаёт по возрастанию
    # unlocked_at (см. AchievementRepository), тот же порядок, что в тексте
    # бота, здесь не пересортировывается.
    achievement_items = [
        AchievementItem(
            code=a.code,
            label=ACHIEVEMENT_LABELS.get(AchievementCode(a.code), a.code),
            unlocked_at=a.unlocked_at.date().isoformat(),
        )
        for a in achievements
    ]

    return ProfileResponse(
        is_onboarded=True,
        subscription_status_label=format_subscription_status(user),
        coins_balance=user.coins_balance,
        achievements_count=len(achievements),
        achievements=achievement_items,
        workouts_count=len(history),
        days_since_last_workout=days_since_last_workout,
    )


@router.get("/gto", response_model=GtoResponse)
async def get_gto(
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> GtoResponse:
    """Разряд ГТО по подтягиванию (issue #71) — отдельная концепция от
    обычных ачивок (app.domain.gto, не AchievementRepository): статус
    пересчитывается на лету при каждом запросе из текущего пола/возраста
    (app.db.models.User) и лучшего max_reps за всю историю, ничего не
    пишется в БД (обратимый статус — снижение результата или смена
    возрастной ступени меняют его в обе стороны, см. докстринг домена).

    best_max_reps — тот же способ агрегации, что
    app.services.achievement_checks.unlock_history_achievements уже
    использует для MAX_REPS_PLUS_TEN: максимум по обоим блокам за всю
    историю, не только блок A."""
    user = await UserRepository(session).get_by_telegram_id(init_data.user.id)
    if user is None:
        return GtoResponse(applicable=False, reason="not_onboarded")

    records = await WorkoutRepository(session).list_records_for_user(user.id)
    best_max_reps = (
        max(max(r.block_a.log.max_reps, r.block_b.log.max_reps) for r in records) if records else None
    )

    status_ = calculate_gto_status(
        gender=user.gender.value if user.gender is not None else None,
        birth_date=user.birth_date,
        best_max_reps=best_max_reps,
        today=datetime.now(UTC).date(),
    )
    return GtoResponse(
        applicable=status_.applicable,
        reason=status_.reason,
        age=status_.age,
        step_number=status_.step_number,
        rank=status_.rank.value if status_.rank is not None else None,
        best_max_reps=status_.best_max_reps,
        bronze_threshold=status_.bronze_threshold,
        silver_threshold=status_.silver_threshold,
        gold_threshold=status_.gold_threshold,
        next_rank=status_.next_rank.value if status_.next_rank is not None else None,
        reps_to_next_rank=status_.reps_to_next_rank,
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
    work_sets_growth_reason: VolumeGrowthReason | None = None


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
        work_sets_growth_reason=target_a_state.work_sets_growth_reason,
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
        work_sets_growth_reason=(
            context.work_sets_growth_reason.value if context.work_sets_growth_reason is not None else None
        ),
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

    # Черновик живой тренировки (issue #61), если был — удаляется здесь, в
    # той же обработке, что и запись blocks/workouts, а не отдельным
    # вызовом DELETE с клиента после успеха: сеть могла оборваться уже
    # после успешного submit, оставив черновик висеть и указывать на уже
    # записанную тренировку.
    await WorkoutDraftRepository(session).delete_for_user(context.user_id)

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


# --- Черновик тренировки в реальном времени (issue #61) ---------------------------------


def _draft_response(draft) -> WorkoutDraftResponse:
    if draft is None:
        return WorkoutDraftResponse(active=False)
    return WorkoutDraftResponse(
        active=True,
        step_index=draft.step_index,
        block_a_working_reps=draft.block_a_working_reps,
        block_a_max_reps=draft.block_a_max_reps,
        block_b_working_reps=draft.block_b_working_reps,
        block_b_max_reps=draft.block_b_max_reps,
        block_a_actual_weight=draft.block_a_actual_weight,
        block_b_actual_weight=draft.block_b_actual_weight,
        block_a_actual_band_item_id=draft.block_a_actual_band_item_id,
        block_b_actual_band_item_id=draft.block_b_actual_band_item_id,
        comment=draft.comment,
    )


@router.put("/workout/draft", response_model=WorkoutDraftResponse)
async def save_workout_draft(
    body: WorkoutDraftRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> WorkoutDraftResponse:
    """Сохраняет накопленный прогресс живой тренировки (issue #61) — по
    завершении каждого подхода (LiveWorkoutScreen.tsx), не только при
    финальной отправке через submit_workout выше. Апсертит целиком (тот же
    приём, что start_timer ниже) — клиент шлёт весь накопленный массив, а
    не один подход."""
    user = await UserRepository(session).get_by_telegram_id(init_data.user.id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not onboarded")

    draft = await WorkoutDraftRepository(session).save(
        user_id=user.id,
        step_index=body.step_index,
        block_a_working_reps=body.block_a_working_reps,
        block_a_max_reps=body.block_a_max_reps,
        block_b_working_reps=body.block_b_working_reps,
        block_b_max_reps=body.block_b_max_reps,
        block_a_actual_weight=body.block_a_actual_weight,
        block_b_actual_weight=body.block_b_actual_weight,
        block_a_actual_band_item_id=body.block_a_actual_band_item_id,
        block_b_actual_band_item_id=body.block_b_actual_band_item_id,
        comment=body.comment,
    )
    return _draft_response(draft)


@router.get("/workout/draft", response_model=WorkoutDraftResponse)
async def get_workout_draft(
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> WorkoutDraftResponse:
    """Опрашивается при заходе на LiveWorkoutScreen вместе с планом (issue
    #61) — если есть незавершённый черновик, экран восстанавливается на
    том же шаге, а не начинается заново с "intro"."""
    user = await UserRepository(session).get_by_telegram_id(init_data.user.id)
    if user is None:
        return WorkoutDraftResponse(active=False)
    draft = await WorkoutDraftRepository(session).get_for_user(user.id)
    return _draft_response(draft)


@router.delete("/workout/draft", response_model=WorkoutDraftResponse)
async def delete_workout_draft(
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> WorkoutDraftResponse:
    """Явная отмена тренировки ("Отмена" на LiveWorkoutScreen, issue #61) —
    идемпотентна, тот же принцип, что cancel_timer ниже."""
    user = await UserRepository(session).get_by_telegram_id(init_data.user.id)
    if user is not None:
        await WorkoutDraftRepository(session).delete_for_user(user.id)
    return WorkoutDraftResponse(active=False)


@router.get("/history", response_model=HistoryResponse)
async def get_history(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> HistoryResponse:
    """Вкладка "История" Mini App (issue #50, волна 1) — те же факты, что
    печатает app.bot.handlers.history.handle_show_history (тот же
    WorkoutRepository.list_for_user, тот же format_block_result), только
    структурированные под карточки, а не единый текстовый блок бота.

    Пагинация — offset/limit-срез уже загруженного списка (тот же приём,
    что HISTORY_LIMIT-срез в handle_show_history), не отдельный SQL-запрос
    с LIMIT/OFFSET: list_for_user и так остаётся единственным источником
    истории пользователя во всём проекте (профиль/план/аномалии читают его
    же), заводить вторую версию с БД-пагинацией ради одного экрана — лишняя
    развилка без выигрыша при типичном объёме истории одного пользователя.
    Новейшие тренировки — первыми (естественный порядок для ленты)."""
    user = await UserRepository(session).get_by_telegram_id(init_data.user.id)
    if user is None:
        return HistoryResponse(items=[], has_more=False)

    history = await WorkoutRepository(session).list_for_user(user.id)
    newest_first = list(reversed(history))
    page = newest_first[offset : offset + limit]

    items = []
    for workout in page:
        block_a = next(b for b in workout.blocks if b.block_type == BlockType.A)
        block_b = next(b for b in workout.blocks if b.block_type == BlockType.B)
        is_latest = workout is newest_first[0]
        items.append(
            HistoryEntryResponse(
                workout_id=workout.id,
                performed_at=workout.performed_at.date().isoformat(),
                is_backdated=not workout.participates_in_cascade,
                comment=workout.comment,
                equipment_a=_equipment_info(
                    block_a.equipment_type, block_a.equipment_value, block_a.equipment_item_id,
                ),
                equipment_b=_equipment_info(
                    block_b.equipment_type, block_b.equipment_value, block_b.equipment_item_id,
                ),
                result_a=format_block_result(block_a.working_reps, block_a.max_reps),
                result_b=format_block_result(block_b.working_reps, block_b.max_reps),
                target_a=block_a.target_after if is_latest else None,
                target_b=block_b.target_after if is_latest else None,
            ),
        )
    return HistoryResponse(items=items, has_more=offset + limit < len(newest_first))


def _progress_value(block: BlockAssignment, metric: str, *, block_letter: str) -> Decimal | None:
    """Факт по выбранной метрике (issue #82) — см. докстринг
    ProgressPointResponse для смысла каждой ветки. strength скоуплена на
    блок Б (block_letter == "b") — для A возвращает None всегда, не
    придумывает число для метрики, которая для этого блока не определена."""
    if metric == "max_reps":
        return Decimal(block.log.best_set)
    if metric == "volume":
        return Decimal(block.log.volume)
    # metric == "strength"
    if block_letter != "b" or block.equipment_type == EquipmentType.AUSTRALIAN:
        return None
    return to_signed_load(block.equipment_type, block.equipment_value)


@router.get("/progress", response_model=ProgressResponse)
async def get_progress(
    metric: Literal["max_reps", "volume", "strength"] = Query(default="max_reps"),
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> ProgressResponse:
    """Данные для графика вкладки "Прогресс" (issue #82: переделано с плана
    на факт — см. история issue #50, волна 2, там строился по target_after).
    WorkoutRepository.list_records_for_user отдаёт те же доменные
    WorkoutRecord, что app.services.reports/app.domain.reports используют
    для отчётов бота — value_a/value_b читаются из уже записанного факта
    (BlockLog), не из плановой цели прогрессии."""
    user = await UserRepository(session).get_by_telegram_id(init_data.user.id)
    if user is None:
        return ProgressResponse(metric=metric, points=[])

    records = await WorkoutRepository(session).list_records_for_user(user.id)
    points = [
        ProgressPointResponse(
            performed_at=record.performed_at.date().isoformat(),
            value_a=_progress_value(record.block_a, metric, block_letter="a"),
            value_b=_progress_value(record.block_b, metric, block_letter="b"),
            workout_set_id=record.workout_set_id,
        )
        for record in records
    ]
    return ProgressResponse(metric=metric, points=points)


def _equipment_progress_response(progress: EquipmentProgress | None) -> EquipmentProgressResponse | None:
    if progress is None:
        return None
    return EquipmentProgressResponse(
        equipment=_equipment_info(progress.equipment_type, progress.equipment_value, progress.equipment_item_id),
        first_volume=progress.first_volume,
        current_volume=progress.current_volume,
        change_pct=progress.change_pct,
    )


@router.get("/analytics", response_model=AnalyticsResponse)
async def get_analytics(
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> AnalyticsResponse:
    """Аналитический блок вкладки "Прогресс" Mini App (issue #66, п.2) —
    те же вызовы app.domain.reports с теми же входными данными, что кнопки
    "📊 Прогресс"/"📈 Аналитика по всем циклам" бота
    (app/bot/handlers/reports.py::handle_show_progress_report/
    handle_show_all_cycles_analytics), только в JSON вместо готового
    текста — не отдельная копия вычислений. Недельная сводка скоупится по
    текущему (или только что закрытому) циклу, тем же способом, что и
    еженедельная рассылка (app/workers/weekly_report.py); прогресс на
    снаряде намеренно остаётся на полной истории — динамика "на одном и
    том же снаряде", а не "за цикл"."""
    user = await UserRepository(session).get_by_telegram_id(init_data.user.id)
    if user is None:
        return AnalyticsResponse(has_data=False)

    workouts = WorkoutRepository(session)
    records = await workouts.list_records_for_user(user.id)
    if not records:
        return AnalyticsResponse(has_data=False)

    all_sets = await WorkoutSetRepository(session).list_for_user(user.id)
    current_set_records = await workouts.list_records_for_set(all_sets[-1].id)

    now = datetime.now(UTC)
    week_ago = now - timedelta(days=7)
    two_weeks_ago = now - timedelta(days=14)
    this_week = [r for r in current_set_records if r.performed_at >= week_ago]
    previous_week = [r for r in current_set_records if two_weeks_ago <= r.performed_at < week_ago]
    previous_week_volume = sum(r.block_a.log.volume + r.block_b.log.volume for r in previous_week)

    summary = weekly_summary(this_week, previous_week_volume)
    analytics = all_cycles_analytics(records)

    return AnalyticsResponse(
        has_data=True,
        weekly=WeeklySummaryResponse(**asdict(summary)),
        equipment_progress_a=_equipment_progress_response(current_equipment_progress(records, "a")),
        equipment_progress_b=_equipment_progress_response(current_equipment_progress(records, "b")),
        total_volume=analytics.total_volume,
        cycle_count=analytics.cycle_count,
        cycles=[CycleVolumeResponse(**asdict(c)) for c in analytics.cycles],
    )


@router.get("/subscription", response_model=SubscriptionResponse)
async def get_subscription(
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> SubscriptionResponse:
    """Раздел подписки/оплаты Mini App (issue #53, волна 1) — расширяет
    статус, уже частично показанный во вкладке "Профиль" (get_profile
    выше), тем же format_subscription_status (не отдельный веб-текст).
    price_rub/days/pricing_text_html/robokassa_available не зависят от
    пользователя — те же SUBSCRIPTION_PRICE_RUB/SUBSCRIPTION_DAYS/
    texts.PRICING_TEXT/_robokassa_available(), что паивелл бота
    (app/bot/handlers/subscription.py), отдаются даже неонбордившемуся
    (фронтенд может показать реквизиты/условия ещё до первой тренировки)."""
    user = await UserRepository(session).get_by_telegram_id(init_data.user.id)

    status_value = None
    status_label = None
    expires_at = None
    if user is not None:
        status_value = user.subscription_status.value
        status_label = format_subscription_status(user)
        if user.subscription_status in (SubscriptionStatus.TRIAL, SubscriptionStatus.ACTIVE):
            expires_at = (
                user.subscription_expires_at.date().isoformat()
                if user.subscription_expires_at is not None
                else None
            )

    return SubscriptionResponse(
        is_onboarded=user is not None,
        status=status_value,
        status_label=status_label,
        expires_at=expires_at,
        price_rub=SUBSCRIPTION_PRICE_RUB,
        days=SUBSCRIPTION_DAYS,
        pricing_text_html=texts.PRICING_TEXT,
        robokassa_available=_robokassa_available(),
    )


@router.post("/subscription/pay", response_model=PaymentLinkResponse)
async def pay_subscription(
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> PaymentLinkResponse:
    """Создаёт ссылку на оплату обычной подписки — тот же
    RobokassaService.create_payment_link, что handle_pay_robokassa бота
    (app/bot/handlers/subscription.py), без параметров amount_rub/
    description (диагностический платёж на 1₽ остаётся только в /admin
    бота, см. CLAUDE.md). Подтверждение — тем же воркером
    sync_robokassa_payments, отдельного пути опроса для Mini App нет.

    404 у неонбордившегося (в Mini App недостижимо вживую — экран
    подписки виден только после онбординга — но дешевле проверить на
    сервере, чем гадать). 503 при незаданных robokassa_* — тот же смысл,
    что скрытая кнопка pay_robokassa в paywall_keyboard бота, только с
    явным кодом ошибки для фронтенда вместо молча пропавшей кнопки."""
    user = await UserRepository(session).get_by_telegram_id(init_data.user.id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not onboarded")
    if not _robokassa_available():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Robokassa is not configured")

    client = RobokassaClient(
        merchant_login=settings.robokassa_merchant_login,
        password_1=settings.robokassa_password_1,
        password_2=settings.robokassa_password_2,
    )
    payment_url = await RobokassaService(session, client).create_payment_link(user.id)
    return PaymentLinkResponse(payment_url=payment_url)


@router.get("/oferta.pdf")
async def get_oferta_pdf() -> FileResponse:
    """Тот же файл, что бот отправляет по кнопке "Тарифы и реквизиты"
    (app/bot/handlers/menu.py::OFERTA_PDF_PATH) — раздаётся напрямую с
    диска, не дублируется (issue #57, п.2). Публичный, без initData:
    тот же уровень доступа, что у текста PRICING_TEXT в /api/subscription,
    которое тоже отдаётся без проверки подписки/онбординга."""
    return FileResponse(OFERTA_PDF_PATH, media_type="application/pdf", filename="oferta.pdf")


# --- Редактирование истории (issue #52) ---------------------------------------------


def _history_block_detail(block) -> HistoryBlockDetail:
    return HistoryBlockDetail(
        working_reps=list(block.working_reps),
        max_reps=block.max_reps,
        target_before=block.target_before,
        equipment=_equipment_info(block.equipment_type, block.equipment_value, block.equipment_item_id),
    )


@router.get("/history/{workout_id}", response_model=HistoryEditDetailResponse)
async def get_history_workout(
    workout_id: int,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> HistoryEditDetailResponse:
    """Детали одной тренировки для формы редактирования (issue #52) — те же
    факты, что app.bot.handlers.workout_edit::_start_editing кладёт в FSM
    перед переспросом блока A. Чужая/несуществующая тренировка — 404, не
    палим сам факт существования чужой записи отдельным статусом."""
    user = await UserRepository(session).get_by_telegram_id(init_data.user.id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workout not found")

    workout = await WorkoutRepository(session).get_by_id(workout_id)
    if workout is None or workout.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workout not found")

    block_a = next(b for b in workout.blocks if b.block_type == BlockType.A)
    block_b = next(b for b in workout.blocks if b.block_type == BlockType.B)
    return HistoryEditDetailResponse(
        workout_id=workout.id,
        performed_at=workout.performed_at.date().isoformat(),
        is_editable=_is_editable(workout),
        comment=workout.comment,
        block_a=_history_block_detail(block_a),
        block_b=_history_block_detail(block_b),
    )


@router.patch("/history/{workout_id}", response_model=WorkoutSubmitResponse)
async def edit_history_workout(
    workout_id: int,
    body: HistoryEditRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> WorkoutSubmitResponse:
    """Правит уже введённые повторения прошлой тренировки через
    WorkoutRepository.edit_workout — тот же каскадный пересчёт
    (recalculate_cascade) последующих тренировок цепочки, что и
    app.bot.handlers.workout_edit, не отдельная веб-копия. Аномалии — тот
    же двухшаговый паттерн, что и submit_workout/submit_backdated_workout
    (anomaly_confirm_required без confirm_anomalies=True ничего не пишет).
    Правка веса/резины "на месте" — тот же приём, что submit_workout,
    применяется отдельным correct_block_equipment ПОСЛЕ edit_workout."""
    user = await UserRepository(session).get_by_telegram_id(init_data.user.id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workout not found")

    workouts = WorkoutRepository(session)
    workout = await workouts.get_by_id(workout_id)
    if workout is None or workout.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workout not found")
    if not _is_editable(workout):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Workout is not editable")

    block_a_orig = next(b for b in workout.blocks if b.block_type == BlockType.A)
    expected_work_sets_a = (
        block_a_orig.work_sets_before
        if block_a_orig.work_sets_before is not None
        else VOLUME_BLOCK.work_sets
    )

    block_a_reps = BlockLog(working_reps=tuple(body.block_a_working_reps), max_reps=body.block_a_max_reps)
    block_b_reps = BlockLog(working_reps=tuple(body.block_b_working_reps), max_reps=body.block_b_max_reps)

    previous_avg_a = await workouts.get_previous_avg_working(
        user.id, BlockType.A, before=workout.performed_at,
    )
    previous_avg_b = await workouts.get_previous_avg_working(
        user.id, BlockType.B, before=workout.performed_at,
    )
    anomalies_a = detect_anomalies(
        block_a_reps, previous_avg_working=previous_avg_a, expected_work_sets=expected_work_sets_a,
    )
    anomalies_b = detect_anomalies(
        block_b_reps, previous_avg_working=previous_avg_b, expected_work_sets=STRENGTH_BLOCK.work_sets,
    )
    if not body.confirm_anomalies and (not anomalies_a.is_empty() or not anomalies_b.is_empty()):
        return WorkoutSubmitResponse(
            status="anomaly_confirm_required",
            anomalies_a=AnomalyFlagsResponse(**asdict(anomalies_a)),
            anomalies_b=AnomalyFlagsResponse(**asdict(anomalies_b)),
        )

    # Резина валидируется ДО edit_workout (equipment_type блока сам
    # edit_workout не трогает, читать его можно и из workout ДО правки) —
    # иначе неверный item_id откатывал бы уже применённую правку повторений
    # наполовину (edit_workout закоммичен, correct_block_equipment — нет).
    block_b_orig = next(b for b in workout.blocks if b.block_type == BlockType.B)
    band_item_a = None
    band_item_b = None
    if body.block_a_actual_band_item_id is not None and block_a_orig.equipment_type == EquipmentType.BAND:
        band_item_a = await EquipmentItemRepository(session).get_by_id(body.block_a_actual_band_item_id)
        if band_item_a is None or band_item_a.user_id != user.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid band item for block A")
    if body.block_b_actual_band_item_id is not None and block_b_orig.equipment_type == EquipmentType.BAND:
        band_item_b = await EquipmentItemRepository(session).get_by_id(body.block_b_actual_band_item_id)
        if band_item_b is None or band_item_b.user_id != user.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid band item for block B")

    workout = await workouts.edit_workout(
        workout_id=workout_id, block_a_reps=block_a_reps, block_b_reps=block_b_reps, comment=body.comment,
    )
    block_a = next(b for b in workout.blocks if b.block_type == BlockType.A)
    block_b = next(b for b in workout.blocks if b.block_type == BlockType.B)

    if body.block_a_actual_weight is not None and block_a.equipment_type == EquipmentType.WEIGHT:
        workout = await workouts.correct_block_equipment(
            workout_id=workout_id, block_type=BlockType.A, equipment_value=body.block_a_actual_weight,
        )
    if body.block_b_actual_weight is not None and block_b.equipment_type == EquipmentType.WEIGHT:
        workout = await workouts.correct_block_equipment(
            workout_id=workout_id, block_type=BlockType.B, equipment_value=body.block_b_actual_weight,
        )
    if band_item_a is not None:
        workout = await workouts.correct_block_equipment(
            workout_id=workout_id, block_type=BlockType.A, equipment_item_id=band_item_a.id,
        )
    if band_item_b is not None:
        workout = await workouts.correct_block_equipment(
            workout_id=workout_id, block_type=BlockType.B, equipment_item_id=band_item_b.id,
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


# --- Внесение задним числом (issue #52) -----------------------------------------------


@dataclass
class _BackdateContext:
    """Контекст для "Внести пропущенную тренировку" — тот же
    resolve_next_targets, что и _PlanContext, но БЕЗ гейтов too_early/
    gap_retest_required/deload_due/equipment_setup_required: бэкдейт про
    прошлое, эти статусы про готовность к СЛЕДУЮЩЕЙ живой тренировке, не
    про него (согласовано в issue #52). target/equipment здесь — только
    пример/подсказка для формы, не авторитетное значение, которое просто
    наследуется, как в _PlanContext: реальный тип/значение снаряда всегда
    приходят явно от клиента (BackdateSubmitRequest) — тот же принцип, что
    _begin_equipment_setup(target_a_state=None, ...) у бота для бэкдейта."""

    status: str
    user_id: int | None = None
    workout_set_id: int | None = None
    target_a: int | None = None
    target_b: int | None = None
    work_sets_a: int | None = None
    work_sets_b: int | None = None
    equipment_a_type: EquipmentType | None = None
    equipment_a_value: Decimal | None = None
    equipment_a_item_id: int | None = None
    equipment_b_type: EquipmentType | None = None
    equipment_b_value: Decimal | None = None
    equipment_b_item_id: int | None = None


async def _resolve_backdate_context(session: AsyncSession, telegram_id: int, *, now: datetime) -> _BackdateContext:
    user = await UserRepository(session).get_by_telegram_id(telegram_id)
    if user is None:
        return _BackdateContext(status="not_onboarded")

    if not await SubscriptionService(session).has_access(user.id, now=now):
        return _BackdateContext(status="no_access")

    workouts = WorkoutRepository(session)
    target_a_state, target_b_state = await workouts.resolve_next_targets(user.id)

    active_set = await ensure_active_workout_set(session, user.id)
    if active_set is None:
        return _BackdateContext(status="no_active_set")

    return _BackdateContext(
        status="ready",
        user_id=user.id,
        workout_set_id=active_set.id,
        target_a=target_a_state.target,
        target_b=target_b_state.target,
        work_sets_a=target_a_state.work_sets,
        work_sets_b=STRENGTH_BLOCK.work_sets,
        equipment_a_type=target_a_state.equipment_type,
        equipment_a_value=target_a_state.equipment_value,
        equipment_a_item_id=target_a_state.equipment_item_id,
        equipment_b_type=target_b_state.equipment_type,
        equipment_b_value=target_b_state.equipment_value,
        equipment_b_item_id=target_b_state.equipment_item_id,
    )


@router.get("/workout/backdate/plan", response_model=WorkoutPlanResponse)
async def get_backdate_plan(
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> WorkoutPlanResponse:
    """Контекст для формы "Добавить за дату" — те же цель/снаряд-пример, что
    GET /api/workout/plan, но band_items отдаётся всегда (не только когда
    текущий снаряд — BAND), потому что снаряд для бэкдейта выбирается явно
    и может отличаться от того, что унаследовала бы живая тренировка."""
    context = await _resolve_backdate_context(session, init_data.user.id, now=datetime.now(UTC))
    if context.status != "ready":
        return WorkoutPlanResponse(status=context.status)

    items = await EquipmentItemRepository(session).list_for_user(context.user_id)
    band_items = [BandItemInfo(id=item.id, name=item.name, resistance_kg=item.resistance_kg) for item in items]

    return WorkoutPlanResponse(
        status="ready",
        workout_set_id=context.workout_set_id,
        target_a=context.target_a,
        target_b=context.target_b,
        work_sets_a=context.work_sets_a,
        work_sets_b=context.work_sets_b,
        equipment_a=_equipment_info(
            context.equipment_a_type, context.equipment_a_value, context.equipment_a_item_id,
        ),
        equipment_b=_equipment_info(
            context.equipment_b_type, context.equipment_b_value, context.equipment_b_item_id,
        ),
        is_gap_rollback=False,
        band_items=band_items,
    )


def _parse_backdate_equipment_type(raw: str, *, field: str) -> EquipmentType:
    try:
        return EquipmentType(raw)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid equipment type for {field}") from None


async def _resolve_backdate_equipment(
    session: AsyncSession,
    user_id: int,
    equipment_type: EquipmentType,
    equipment_value: Decimal | None,
    equipment_item_id: int | None,
    *,
    field: str,
) -> tuple[Decimal | None, int | None]:
    if equipment_type == EquipmentType.WEIGHT:
        if equipment_value is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Missing weight for {field}")
        return equipment_value, None
    if equipment_type == EquipmentType.BAND:
        if equipment_item_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Missing band item for {field}")
        item = await EquipmentItemRepository(session).get_by_id(equipment_item_id)
        if item is None or item.user_id != user_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid band item for {field}")
        return None, item.id
    return None, None


@router.post("/workout/backdate", response_model=WorkoutSubmitResponse)
async def submit_backdated_workout(
    body: BackdateSubmitRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> WorkoutSubmitResponse:
    """Записывает тренировку задним числом через
    WorkoutLogService.record_backdated_workout — тот же сервис, что
    finalize_backdated_workout бота (app/bot/handlers/backdate.py), не
    отдельная реализация. Единственная проверка даты — "не в будущем" (тот
    же `parsed_date.date() > now.date()`, что и handle_backdate_date/
    handle_calendar_date_picked бота): никакого лимита на глубину бэкдейта
    в реальном коде бота нет (issue #52, согласовано в комментарии — более
    раннее упоминание "7 дней" было ошибкой по памяти, не переносом
    существующей логики)."""
    try:
        performed_date = date.fromisoformat(body.performed_at)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid date") from None

    now = datetime.now(UTC)
    if performed_date > now.date():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Date cannot be in the future")

    context = await _resolve_backdate_context(session, init_data.user.id, now=now)
    if context.status != "ready":
        return WorkoutSubmitResponse(status=context.status)

    block_a_equipment_type = _parse_backdate_equipment_type(body.block_a_equipment_type, field="block A")
    block_b_equipment_type = _parse_backdate_equipment_type(body.block_b_equipment_type, field="block B")
    block_a_equipment_value, block_a_equipment_item_id = await _resolve_backdate_equipment(
        session, context.user_id, block_a_equipment_type,
        body.block_a_equipment_value, body.block_a_equipment_item_id, field="block A",
    )
    block_b_equipment_value, block_b_equipment_item_id = await _resolve_backdate_equipment(
        session, context.user_id, block_b_equipment_type,
        body.block_b_equipment_value, body.block_b_equipment_item_id, field="block B",
    )

    performed_at = datetime(performed_date.year, performed_date.month, performed_date.day, tzinfo=UTC)
    block_a_reps = BlockLog(working_reps=tuple(body.block_a_working_reps), max_reps=body.block_a_max_reps)
    block_b_reps = BlockLog(working_reps=tuple(body.block_b_working_reps), max_reps=body.block_b_max_reps)

    workouts = WorkoutRepository(session)
    previous_avg_a = await workouts.get_previous_avg_working(context.user_id, BlockType.A, before=performed_at)
    previous_avg_b = await workouts.get_previous_avg_working(context.user_id, BlockType.B, before=performed_at)
    anomalies_a = detect_anomalies(
        block_a_reps, previous_avg_working=previous_avg_a, expected_work_sets=context.work_sets_a,
    )
    anomalies_b = detect_anomalies(
        block_b_reps, previous_avg_working=previous_avg_b, expected_work_sets=context.work_sets_b,
    )
    if not body.confirm_anomalies and (not anomalies_a.is_empty() or not anomalies_b.is_empty()):
        return WorkoutSubmitResponse(
            status="anomaly_confirm_required",
            anomalies_a=AnomalyFlagsResponse(**asdict(anomalies_a)),
            anomalies_b=AnomalyFlagsResponse(**asdict(anomalies_b)),
        )

    log_service = WorkoutLogService(session)
    workout = await log_service.record_backdated_workout(
        user_id=context.user_id,
        workout_set_id=context.workout_set_id,
        performed_at=performed_at,
        block_a_reps=block_a_reps,
        block_b_reps=block_b_reps,
        block_a_equipment_type=block_a_equipment_type,
        block_a_equipment_value=block_a_equipment_value,
        block_b_equipment_type=block_b_equipment_type,
        block_b_equipment_value=block_b_equipment_value,
        block_a_equipment_item_id=block_a_equipment_item_id,
        block_b_equipment_item_id=block_b_equipment_item_id,
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


# --- Персистентный таймер (issue #59, волна 1) ------------------------------------------


def _parse_timer_type(raw: str) -> ActiveTimerType:
    try:
        return ActiveTimerType(raw)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid timer_type") from None


def _timer_status_response(timer, *, now: datetime) -> TimerStatusResponse:
    """Источник правды — сервер: остаток всегда считается заново из
    started_at/duration_seconds, никогда не читается из клиента (issue #59:
    "клиент просто спрашивает "сколько осталось" по факту открытия, а не
    ведёт свой независимый отсчёт"). Истёкшая запись не удаляется здесь —
    только следующий POST /api/timer/start (замена) или DELETE /api/timer
    её уберёт, поэтому active=False уже при remaining_seconds=0, хотя
    строка в БД физически ещё существует."""
    elapsed = (now - timer.started_at).total_seconds()
    remaining = max(0, timer.duration_seconds - int(elapsed))
    return TimerStatusResponse(
        active=remaining > 0,
        timer_type=timer.timer_type.value,
        duration_seconds=timer.duration_seconds,
        remaining_seconds=remaining,
        block_letter=timer.block_letter,
        set_number=timer.set_number,
    )


@router.post("/timer/start", response_model=TimerStatusResponse)
async def start_timer(
    body: TimerStartRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> TimerStatusResponse:
    """Стартует (или заменяет уже идущий, см. ActiveTimerRepository.start)
    персистентный таймер отдыха/большого перерыва режима тренировки в
    реальном времени (issue #59, Волна 2). started_at всегда серверное
    время — тело запроса его не содержит, чтобы рассинхрон часов клиента
    не мог сдвинуть момент, от которого считается остаток."""
    user = await UserRepository(session).get_by_telegram_id(init_data.user.id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not onboarded")

    timer_type = _parse_timer_type(body.timer_type)
    now = datetime.now(UTC)
    timer = await ActiveTimerRepository(session).start(
        user_id=user.id,
        timer_type=timer_type,
        started_at=now,
        duration_seconds=body.duration_seconds,
        block_letter=body.block_letter,
        set_number=body.set_number,
    )
    return _timer_status_response(timer, now=now)


@router.get("/timer/status", response_model=TimerStatusResponse)
async def get_timer_status(
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> TimerStatusResponse:
    """Опрашивается фронтендом при каждом открытии/возврате в приложение
    (visibilitychange/focus, issue #59, Волна 2) — не полагается на
    локальный setInterval как источник правды, только как визуальный тик
    между опросами."""
    user = await UserRepository(session).get_by_telegram_id(init_data.user.id)
    if user is None:
        return TimerStatusResponse(active=False)

    timer = await ActiveTimerRepository(session).get_for_user(user.id)
    if timer is None:
        return TimerStatusResponse(active=False)
    return _timer_status_response(timer, now=datetime.now(UTC))


@router.delete("/timer", response_model=TimerStatusResponse)
async def cancel_timer(
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> TimerStatusResponse:
    """Досрочная отмена — идемпотентна: отсутствие активного таймера (или
    неонбордившийся пользователь) не считается ошибкой, просто нечего
    отменять."""
    user = await UserRepository(session).get_by_telegram_id(init_data.user.id)
    if user is not None:
        await ActiveTimerRepository(session).delete_for_user(user.id)
    return TimerStatusResponse(active=False)


# --- Персистентные настройки длительности таймера (issue #59, волна 2) ------------------


def _resolve_timer_preferences(user) -> TimerPreferencesResponse:
    return TimerPreferencesResponse(
        rest_seconds_block_a=user.rest_seconds_block_a or DEFAULT_REST_SECONDS_BLOCK_A,
        rest_seconds_block_b=user.rest_seconds_block_b or DEFAULT_REST_SECONDS_BLOCK_B,
        big_break_seconds=user.big_break_seconds or DEFAULT_BIG_BREAK_SECONDS,
        # `or` не годится здесь как для трёх полей выше — 0 (звук выключен)
        # валидное значение, но falsy, "or" молча подменил бы его дефолтом.
        sound_volume_percent=(
            user.sound_volume_percent
            if user.sound_volume_percent is not None
            else DEFAULT_TIMER_SOUND_VOLUME_PERCENT
        ),
    )


@router.get("/timer/preferences", response_model=TimerPreferencesResponse)
async def get_timer_preferences(
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> TimerPreferencesResponse:
    """Значения уже резолвлены дефолтом — NULL на users (никогда не
    настраивал) отдаётся как DEFAULT_REST_SECONDS_BLOCK_A/B/
    DEFAULT_BIG_BREAK_SECONDS, фронтенду не нужно знать про дефолты
    отдельно (issue #59, волна 2)."""
    user = await UserRepository(session).get_by_telegram_id(init_data.user.id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not onboarded")
    return _resolve_timer_preferences(user)


@router.put("/timer/preferences", response_model=TimerPreferencesResponse)
async def update_timer_preferences(
    body: TimerPreferencesUpdateRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> TimerPreferencesResponse:
    """Сохраняет ровно одну настройку за раз (issue #59, волна 2: "для
    единообразия" — все настройки персистентны одинаково). Либо одну из трёх
    длительностей (block_letter="A"/"B" — отдых между подходами
    соответствующего блока, None — большой перерыв между блоками), либо
    громкость звука таймера (issue #90) — ровно одно из двух гарантировано
    схемой (TimerPreferencesUpdateRequest._check_exactly_one_value)."""
    user = await UserRepository(session).get_by_telegram_id(init_data.user.id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not onboarded")

    if body.sound_volume_percent is not None:
        field, value = "sound_volume_percent", body.sound_volume_percent
    else:
        field = {
            "A": "rest_seconds_block_a",
            "B": "rest_seconds_block_b",
            None: "big_break_seconds",
        }[body.block_letter]
        value = body.duration_seconds
    updated = await UserRepository(session).update_timer_preference(user.id, field=field, value=value)
    return _resolve_timer_preferences(updated)


# Текст для NULL leaderboard_display_name — форматирование, не доменное
# правило (issue #67), поэтому константа здесь, а не в app/domain/leaderboard.py.
_ANONYMOUS_LABEL = "Аноним"


@router.get("/leaderboard", response_model=LeaderboardResponse)
async def get_leaderboard(
    metric: Literal["max_reps", "max_weight", "total_volume"] = Query(...),
    gender: Literal["all", "male", "female"] = Query(default="all"),
    age_bucket: str = Query(default="all"),
    period: Literal["week", "month", "all"] = Query(default="all"),
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> LeaderboardResponse:
    """Вкладка "Лидерборд" Mini App (issue #67) — три метрики (переключаются
    значением metric на одном и том же экране, не отдельными эндпойнтами),
    с необязательным фильтром по полу/возрастной категории (ступени ГТО,
    см. app.domain.leaderboard.AGE_BUCKETS). Своя строка (is_current_user)
    отдаётся LeaderboardRepository.top() одним проходом, даже если
    пользователь вне топ-N — см. докстринг репозитория.

    period (issue #74, волна 2) имеет эффект только при metric=total_volume
    (см. LeaderboardRepository.top) — для остальных метрик игнорируется
    молча, а не отклоняется 400: фронтенд просто не показывает переключатель
    периода на других вкладках, отдельный запрет здесь избыточен."""
    if age_bucket != "all" and age_bucket not in AGE_BUCKETS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid age_bucket")

    user = await UserRepository(session).get_by_telegram_id(init_data.user.id)
    requesting_user_id = user.id if user is not None else None

    entries = await LeaderboardRepository(session).top(
        metric=LeaderboardMetric(metric),
        gender=None if gender == "all" else gender,
        age_bucket=None if age_bucket == "all" else age_bucket,
        requesting_user_id=requesting_user_id,
        period=None if period == "all" else period,
        limit=LEADERBOARD_TOP_LIMIT,
    )
    my_rank = next((entry.rank for entry in entries if entry.is_current_user), None)

    return LeaderboardResponse(
        metric=metric,
        entries=[
            LeaderboardEntryResponse(
                rank=entry.rank,
                display_name=entry.display_name or _ANONYMOUS_LABEL,
                value=entry.value,
                is_current_user=entry.is_current_user,
            )
            for entry in entries
        ],
        my_display_name=user.leaderboard_display_name if user is not None else None,
        my_rank=my_rank,
    )


@router.put("/leaderboard/display-name", response_model=LeaderboardDisplayNameResponse)
async def update_leaderboard_display_name(
    body: LeaderboardDisplayNameUpdateRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> LeaderboardDisplayNameResponse:
    """Пустая строка нормализуется в None здесь же — тот же результат, что
    явный null от клиента: "анонимно" (issue #67)."""
    user = await UserRepository(session).get_by_telegram_id(init_data.user.id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not onboarded")

    display_name = body.display_name.strip() if body.display_name else None
    updated = await UserRepository(session).set_leaderboard_display_name(user.id, display_name or None)
    return LeaderboardDisplayNameResponse(display_name=updated.leaderboard_display_name)
