from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from init_data_py import InitData
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatting import (
    format_block_result,
    format_equipment_label,
    format_subscription_status,
)
from app.bot.handlers.workout_edit import _is_editable
from app.config import settings
from app.db.models import BlockType
from app.db.repositories.achievements import AchievementRepository
from app.db.repositories.equipment_items import EquipmentItemRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.anomalies import detect_anomalies
from app.domain.constants import STRENGTH_BLOCK, VOLUME_BLOCK, EquipmentType
from app.domain.progression import rollback_target
from app.domain.rules import TrainingReadiness, check_training_readiness
from app.domain.session import BlockLog
from app.services.subscription import SubscriptionService
from app.services.workout_log import WorkoutLogService, ensure_active_workout_set
from app.web.auth import get_validated_init_data
from app.web.db import get_session
from app.web.schemas import (
    AnomalyFlagsResponse,
    BackdateSubmitRequest,
    BandItemInfo,
    EquipmentInfo,
    HelloResponse,
    HistoryBlockDetail,
    HistoryEditDetailResponse,
    HistoryEditRequest,
    HistoryEntryResponse,
    HistoryResponse,
    ProfileResponse,
    ProgressPointResponse,
    ProgressResponse,
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


@router.get("/progress", response_model=ProgressResponse)
async def get_progress(
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> ProgressResponse:
    """Данные для графика вкладки "Прогресс" (issue #50, волна 2) — цель за
    подход по тренировкам во времени, для блока A и Б отдельно.
    WorkoutRepository.list_records_for_user отдаёт те же доменные
    WorkoutRecord, что app.services.reports/app.domain.reports используют
    для отчётов бота — target_after уже посчитан прогрессией
    (app.domain.progression) при записи каждой тренировки, здесь не
    пересчитывается заново, только читается в хронологическом порядке."""
    user = await UserRepository(session).get_by_telegram_id(init_data.user.id)
    if user is None:
        return ProgressResponse(points=[])

    records = await WorkoutRepository(session).list_records_for_user(user.id)
    points = [
        ProgressPointResponse(
            performed_at=record.performed_at.date().isoformat(),
            target_a=record.block_a.target_after,
            target_b=record.block_b.target_after,
            workout_set_id=record.workout_set_id,
        )
        for record in records
    ]
    return ProgressResponse(points=points)


@router.get("/history/{workout_id}", response_model=HistoryEditDetailResponse)
async def get_history_entry(
    workout_id: int,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> HistoryEditDetailResponse:
    """Детали одной тренировки для формы редактирования (issue #52, волна
    1) — сырые working_reps/max_reps, не отформатированная строка
    HistoryEntryResponse.result_a/b (та годится для ленты, не для
    предзаполнения полей ввода). Владение проверяется явно (workout.user_id
    == user.id) — 404, не 403, чтобы не подтверждать существование чужой
    тренировки по id."""
    user = await UserRepository(session).get_by_telegram_id(init_data.user.id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workout not found")

    workout = await WorkoutRepository(session).get_by_id(workout_id)
    if workout is None or workout.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workout not found")

    block_a = next(b for b in workout.blocks if b.block_type == BlockType.A)
    block_b = next(b for b in workout.blocks if b.block_type == BlockType.B)

    band_items: list[BandItemInfo] = []
    if EquipmentType.BAND in (block_a.equipment_type, block_b.equipment_type):
        items = await EquipmentItemRepository(session).list_for_user(user.id)
        band_items = [BandItemInfo(id=item.id, name=item.name, resistance_kg=item.resistance_kg) for item in items]

    return HistoryEditDetailResponse(
        workout_id=workout.id,
        performed_at=workout.performed_at.date().isoformat(),
        comment=workout.comment,
        is_editable=_is_editable(workout),
        block_a=HistoryBlockDetail(
            working_reps=list(block_a.working_reps), max_reps=block_a.max_reps, target_before=block_a.target_before,
            equipment=_equipment_info(block_a.equipment_type, block_a.equipment_value, block_a.equipment_item_id),
        ),
        block_b=HistoryBlockDetail(
            working_reps=list(block_b.working_reps), max_reps=block_b.max_reps, target_before=block_b.target_before,
            equipment=_equipment_info(block_b.equipment_type, block_b.equipment_value, block_b.equipment_item_id),
        ),
        band_items=band_items,
    )


@router.patch("/history/{workout_id}", response_model=WorkoutSubmitResponse)
async def edit_history_entry(
    workout_id: int,
    body: HistoryEditRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> WorkoutSubmitResponse:
    """Применяет правку через WorkoutRepository.edit_workout — тот же
    каскадный пересчёт последующих тренировок (recalculate_cascade), что
    app.bot.handlers.workout_edit._apply_edit_block_b вызывает в конце
    сценария бота, не отдельная копия. Статусы status="not_found"/
    "not_editable" вместо HTTPException 404/400 для "не редактируется" —
    фронтенду нужно отличить "тренировки не существует" (реальный 404,
    формы вообще не должно было быть) от "существует, но каскад её не
    пускает" (ожидаемый статус, GET уже предупредил через is_editable).

    Аномалии — тот же двухшаговый паттерн, что и submit_workout:
    detect_anomalies против previous_avg ДО редактируемой записи (см.
    _previous_avg_for_edit в боте — сравнивать с тем, что было до неё, а
    не с глобально последней тренировкой), без confirm_anomalies ничего не
    пишется. Точечная правка веса/резины (actual_weight/actual_band_item_id)
    — тот же corrected_block_equipment, что использует пост-редакторская
    очередь бота, применяется уже после edit_workout, тем же принципом,
    что и submit_workout (issue #45 часть 2/issue #48)."""
    user = await UserRepository(session).get_by_telegram_id(init_data.user.id)
    if user is None:
        return WorkoutSubmitResponse(status="not_found")

    workouts = WorkoutRepository(session)
    workout = await workouts.get_by_id(workout_id)
    if workout is None or workout.user_id != user.id:
        return WorkoutSubmitResponse(status="not_found")
    if not _is_editable(workout):
        return WorkoutSubmitResponse(status="not_editable")

    block_a_reps = BlockLog(working_reps=tuple(body.block_a_working_reps), max_reps=body.block_a_max_reps)
    block_b_reps = BlockLog(working_reps=tuple(body.block_b_working_reps), max_reps=body.block_b_max_reps)

    block_a_before = next(b for b in workout.blocks if b.block_type == BlockType.A)
    work_sets_a = (
        block_a_before.work_sets_before if block_a_before.work_sets_before is not None else VOLUME_BLOCK.work_sets
    )
    previous_avg_a = await workouts.get_previous_avg_working(user.id, BlockType.A, before=workout.performed_at)
    previous_avg_b = await workouts.get_previous_avg_working(user.id, BlockType.B, before=workout.performed_at)
    anomalies_a = detect_anomalies(block_a_reps, previous_avg_working=previous_avg_a, expected_work_sets=work_sets_a)
    anomalies_b = detect_anomalies(
        block_b_reps, previous_avg_working=previous_avg_b, expected_work_sets=STRENGTH_BLOCK.work_sets,
    )
    if not body.confirm_anomalies and (not anomalies_a.is_empty() or not anomalies_b.is_empty()):
        return WorkoutSubmitResponse(
            status="anomaly_confirm_required",
            anomalies_a=AnomalyFlagsResponse(**asdict(anomalies_a)),
            anomalies_b=AnomalyFlagsResponse(**asdict(anomalies_b)),
        )

    updated = await workouts.edit_workout(
        workout_id=workout_id, block_a_reps=block_a_reps, block_b_reps=block_b_reps, comment=body.comment,
    )
    block_a = next(b for b in updated.blocks if b.block_type == BlockType.A)
    block_b = next(b for b in updated.blocks if b.block_type == BlockType.B)

    if body.block_a_actual_weight is not None and block_a.equipment_type == EquipmentType.WEIGHT:
        updated = await workouts.correct_block_equipment(
            workout_id=workout_id, block_type=BlockType.A, equipment_value=body.block_a_actual_weight,
        )
    if body.block_a_actual_band_item_id is not None and block_a.equipment_type == EquipmentType.BAND:
        item = await EquipmentItemRepository(session).get_by_id(body.block_a_actual_band_item_id)
        if item is None or item.user_id != user.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid band item for block A")
        updated = await workouts.correct_block_equipment(
            workout_id=workout_id, block_type=BlockType.A, equipment_item_id=item.id,
        )
    if body.block_b_actual_weight is not None and block_b.equipment_type == EquipmentType.WEIGHT:
        updated = await workouts.correct_block_equipment(
            workout_id=workout_id, block_type=BlockType.B, equipment_value=body.block_b_actual_weight,
        )
    if body.block_b_actual_band_item_id is not None and block_b.equipment_type == EquipmentType.BAND:
        item = await EquipmentItemRepository(session).get_by_id(body.block_b_actual_band_item_id)
        if item is None or item.user_id != user.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid band item for block B")
        updated = await workouts.correct_block_equipment(
            workout_id=workout_id, block_type=BlockType.B, equipment_item_id=item.id,
        )

    block_a = next(b for b in updated.blocks if b.block_type == BlockType.A)
    block_b = next(b for b in updated.blocks if b.block_type == BlockType.B)
    return WorkoutSubmitResponse(
        status="ok",
        target_a=block_a.target_after, target_b=block_b.target_after,
        equipment_a=_equipment_info(block_a.equipment_type, block_a.equipment_value, block_a.equipment_item_id),
        equipment_b=_equipment_info(block_b.equipment_type, block_b.equipment_value, block_b.equipment_item_id),
        result_a=format_block_result(block_a.working_reps, block_a.max_reps),
        result_b=format_block_result(block_b.working_reps, block_b.max_reps),
    )


@dataclass
class _BackdateContext:
    """Тот же набор полей, что _PlanContext — но без readiness-гейтов
    (too_early/gap_retest_required/deload_due/equipment_setup_required):
    бэкдейт про прошлое, эти статусы описывают, готов ли пользователь к
    СЛЕДУЮЩЕЙ живой тренировке сейчас, к прошлой они не относятся."""

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


async def _resolve_backdate_context(session: AsyncSession, telegram_id: int, *, now: datetime) -> _BackdateContext:
    """Тот же resolve_next_targets, что и _resolve_plan_context — снаряд/
    цель, унаследованные с последней тренировки (используются как значение
    по умолчанию и "пример формата", не как требование: бэкдейт описывает
    уже случившееся, попасть точно в текущую цель необязательно)."""
    user = await UserRepository(session).get_by_telegram_id(telegram_id)
    if user is None:
        return _BackdateContext(status="not_onboarded")
    if not await SubscriptionService(session).has_access(user.id, now=now):
        return _BackdateContext(status="no_access")

    active_set = await ensure_active_workout_set(session, user.id)
    if active_set is None:
        return _BackdateContext(status="no_active_set")

    workouts = WorkoutRepository(session)
    target_a_state, target_b_state = await workouts.resolve_next_targets(user.id)
    return _BackdateContext(
        status="ready",
        user_id=user.id,
        workout_set_id=active_set.id,
        target_a=target_a_state.target,
        target_b=target_b_state.target,
        work_sets_a=target_a_state.work_sets,
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
    """Контекст для формы "Добавить за дату" (issue #52, волна 1) — та же
    форма ответа, что GET /api/workout/plan (поля совпадают один в один),
    но статус "ready" не требует готовности к СЛЕДУЮЩЕЙ живой тренировке,
    см. _resolve_backdate_context."""
    context = await _resolve_backdate_context(session, init_data.user.id, now=datetime.now(UTC))
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
        band_items=band_items,
    )


@router.post("/workout/backdate", response_model=WorkoutSubmitResponse)
async def submit_backdated_workout(
    body: BackdateSubmitRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> WorkoutSubmitResponse:
    """Записывает через WorkoutLogService.record_backdated_workout — тот же
    сервис, что app.bot.handlers.backdate.finalize_backdated_workout
    вызывает в конце сценария бота (не участвует в каскаде, пополняет
    историю/объём, см. докстринг record_backdated_workout в
    WorkoutRepository). Дата — единственная проверка, которой нет у
    обычного submit: не в будущем (та же проверка, что
    handle_backdate_date/handle_calendar_date_picked бота,
    "parsed_date.date() > datetime.now(UTC).date()"). Никакого лимита "не
    старше N дней" в боте нет и здесь не заводится (см. план в issue #52)."""
    now = datetime.now(UTC)
    context = await _resolve_backdate_context(session, init_data.user.id, now=now)
    if context.status != "ready":
        return WorkoutSubmitResponse(status=context.status)

    try:
        performed_date = date.fromisoformat(body.performed_at)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid date") from None
    if performed_date > now.date():
        return WorkoutSubmitResponse(status="future_date")
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
        block_b_reps, previous_avg_working=previous_avg_b, expected_work_sets=STRENGTH_BLOCK.work_sets,
    )
    if not body.confirm_anomalies and (not anomalies_a.is_empty() or not anomalies_b.is_empty()):
        return WorkoutSubmitResponse(
            status="anomaly_confirm_required",
            anomalies_a=AnomalyFlagsResponse(**asdict(anomalies_a)),
            anomalies_b=AnomalyFlagsResponse(**asdict(anomalies_b)),
        )

    equipment_a_value = context.equipment_a_value
    if body.block_a_actual_weight is not None and context.equipment_a_type == EquipmentType.WEIGHT:
        equipment_a_value = body.block_a_actual_weight
    equipment_b_value = context.equipment_b_value
    if body.block_b_actual_weight is not None and context.equipment_b_type == EquipmentType.WEIGHT:
        equipment_b_value = body.block_b_actual_weight

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
    workout = await log_service.record_backdated_workout(
        user_id=context.user_id,
        workout_set_id=context.workout_set_id,
        performed_at=performed_at,
        block_a_reps=block_a_reps,
        block_b_reps=block_b_reps,
        block_a_equipment_type=context.equipment_a_type,
        block_a_equipment_value=equipment_a_value,
        block_b_equipment_type=context.equipment_b_type,
        block_b_equipment_value=equipment_b_value,
        block_a_equipment_item_id=equipment_a_item_id,
        block_b_equipment_item_id=equipment_b_item_id,
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
