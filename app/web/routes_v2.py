"""Эндпоинты новой многокурсовой схемы (issue #165, волна 3) — параллельно
app/web/routes.py (старая pull-up-специфичная схема, не трогается), под
префиксом /api/v2, НЕ подключены к текущему UI. Критерий готовности волны:
ничего из webapp-frontend/src не импортирует эти пути — держать инвариантом
(проверяется тестом, см. tests/test_web/test_v2_not_wired_to_ui.py), тем же
принципом, что app/domain/ проверяется на отсутствие aiogram/sqlalchemy
(CLAUDE.md)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from init_data_py import InitData
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import (
    Complex,
    ComplexItem,
    Exercise,
    PlanItem,
    PlanWeek,
    Program,
    ProgramInclusion,
    SessionStatus,
)
from app.db.repositories.favorites import FavoriteRepository
from app.db.repositories.programs import ProgramRepository
from app.db.repositories.training_plans import TrainingPlanRepository
from app.db.repositories.training_sessions import (
    BatchSetLogInput,
    SessionBlockInput,
    SessionDetail,
    SetLogInput,
    TrainingSessionRepository,
)
from app.db.repositories.users import UserRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.activity_types import activity_label
from app.domain.block_execution import interval_protocol, rest_seconds_for_protocol
from app.domain.electives import format_elective_set_note
from app.domain.journal_calendar import (
    local_day_counts,
    local_range_bounds_utc,
    month_date_range,
    parse_month,
)
from app.domain.multi_program import (
    MetricType,
    SessionSource,
    WeekPhase,
    count_done_per_plan_item,
    is_plannable_week_number,
    plan_week_number,
)
from app.domain.program_schedule import (
    block_role_title,
    block_target_label,
    count_per_week_label,
    course_week_number,
    duration_weeks,
)
from app.domain.workout_protocol import UserWorkoutProtocol
from app.domain.workout_snapshot import positional_snapshot_items
from app.services.live_session import (
    ActiveSessionConflictError,
    CompleteResult,
    LiveSessionService,
    awaiting_block_start,
    block_started_at,
    current_interval_timing,
)
from app.services.plan_week import PlanWeekService
from app.services.program_inclusion import ProgramInclusionRequest, ProgramInclusionService
from app.services.progression_cascade import ProgressionCascadeService
from app.services.session_deletion import SessionDeletionService
from app.services.session_editing import EditOutcome, EditStatus, SessionEditingService, SetEdit
from app.services.session_log import TrainingSessionLogService
from app.services.training_analytics import resolve_timezone
from app.web.auth import get_validated_init_data
from app.web.db import get_session
from app.web.schemas_v2 import (
    BlockProgressionResponse,
    ExerciseCreateRequest,
    ExerciseListResponse,
    ExerciseResponse,
    FavoriteListResponse,
    FavoriteResponse,
    JournalDayResponse,
    JournalDaysResponse,
    PlanItemCreateRequest,
    PlanItemListResponse,
    PlanItemMoveRequest,
    PlanItemResponse,
    PlanResponse,
    PlanWeekCopyResponse,
    PlanWeekCreateRequest,
    PlanWeekResponse,
    ProgramInclusionCreateRequest,
    ProgramInclusionResponse,
    ProgramListResponse,
    ProgramResponse,
    ProgramScheduleItemResponse,
    ProgramScheduleResponse,
    SessionBlockInputSchema,
    SessionBlockResponse,
    SessionCreateRequest,
    SessionListResponse,
    SessionProgressionResponse,
    SessionResponse,
    SessionSetTargetResponse,
    SetLogInputSchema,
    SetLogResponse,
    TrainingPlanResponse,
    WorkoutCreateRequest,
    WorkoutItemCreateRequest,
    WorkoutItemMoveRequest,
    WorkoutItemResponse,
    WorkoutItemUpdateRequest,
    WorkoutListResponse,
    WorkoutResponse,
    WorkoutSessionsResponse,
    WorkoutSessionSummaryResponse,
    WorkoutUpdateRequest,
)
from app.web.schemas_v2_session import (
    IntervalConfigResponse,
    IntervalStateResponse,
    LiveSessionActiveResponse,
    LiveSessionBlockRequest,
    LiveSessionBlockResponse,
    LiveSessionCompleteRequest,
    LiveSessionCompleteResponse,
    LiveSessionPhaseNextRequest,
    LiveSessionPhaseResponse,
    LiveSessionResponse,
    LiveSessionStartRequest,
    LiveSetBatchRequest,
    LiveSetTargetResponse,
    PlanItemDeltaResponse,
    ProgressionPreviewRequest,
    ProgressionPreviewResponse,
    SessionCloneRequest,
    SessionEditRequest,
)

router_v2 = APIRouter(prefix="/api/v2")


async def _require_user(session: AsyncSession, init_data: InitData):
    user = await UserRepository(session).get_by_telegram_id(init_data.user.id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


def _program_response(program: Program, strategy_type_value: str | None) -> ProgramResponse:
    return ProgramResponse(
        id=program.id, name=program.name, goal=program.goal,
        structure_type=program.structure_type.value, category=program.category,
        progression_strategy_type=strategy_type_value,
    )


def _program_inclusion_response(inclusion: ProgramInclusion, user) -> ProgramInclusionResponse:
    """current_week считается в поясе пользователя, как недели плана (#285 L1): и «сегодня»
    (_plan_today), и дата старта курса — локальные (started_at хранится в UTC, `.date()` без
    перевода дал бы другой день около полуночи)."""
    total_weeks = duration_weeks((inclusion.snapshot or {}).get("config"))
    started_on = inclusion.started_at.astimezone(resolve_timezone(user.timezone)).date()
    return ProgramInclusionResponse(
        duration_weeks=total_weeks,
        current_week=course_week_number(started_on, _plan_today(user), total_weeks),
        id=inclusion.id, program_id=inclusion.program_id,
        program_name=inclusion.snapshot.get("program_name", ""),
        is_active=inclusion.is_active, started_at=inclusion.started_at, expires_at=inclusion.expires_at,
        snapshot=inclusion.snapshot, progression_state=inclusion.progression_state,
    )


def _plan_item_response(
    item: PlanItem, complex_name_by_id: dict[int, str] | None = None,
    complex_source_type_by_id: dict[int, str] | None = None, done_count: int = 0,
) -> PlanItemResponse:
    return PlanItemResponse(
        id=item.id, exercise_id=item.exercise_id, complex_id=item.complex_id,
        count_per_week=item.count_per_week, day_of_week=item.day_of_week,
        week_phase=item.week_phase.value if item.week_phase is not None else None,
        program_inclusion_id=item.program_inclusion_id, plan_week_id=item.plan_week_id,
        complex_name=(complex_name_by_id or {}).get(item.complex_id) if item.complex_id is not None else None,
        complex_source_type=(
            (complex_source_type_by_id or {}).get(item.complex_id) if item.complex_id is not None else None
        ),
        done_count=done_count,
    )


def _plan_week_response(week: PlanWeek) -> PlanWeekResponse:
    return PlanWeekResponse(
        id=week.id, week_number=week.week_number, start_date=week.start_date, phase=week.phase.value,
    )


def _set_log_note(source: SessionSource, note: str | None, value: Decimal | None = None) -> str | None:
    """SetLog.note факультатива — упакованный backfill-ом JSON, не пользовательский текст: в API
    уходит читаемая строка «Подходы: 4 · 3 · 2» (или None), сырой JSON наружу не отдаётся (#279);
    разбивка скрыта, если значение подхода правили и оно ≠ сумме (#283) — см.
    `app.domain.electives.format_elective_set_note` (общий с CSV-экспортом)."""
    if source != SessionSource.ELECTIVE or note is None:
        return note
    return format_elective_set_note(note, value)


def _session_response(
    detail: SessionDetail, *, progression: SessionProgressionResponse | None, skipped_reason: str | None,
    title: str | None = None, exercise_names: dict[int, str] | None = None, can_delete: bool = False,
    workout_id: int | None = None,
) -> SessionResponse:
    """exercise_names — имена из каталога для блоков без замороженного снимка
    (manual/STEP); внутренние STEP-роли в него не попадают, поэтому у их
    блоков имени нет (None), а не техническое "Блок A"."""
    snapshot_items = positional_snapshot_items(detail.workout_snapshot, len(detail.blocks))

    def _block(block, item) -> SessionBlockResponse:
        name = item.exercise_name if item is not None else (exercise_names or {}).get(block.exercise_id)
        protocol = interval_protocol(item.protocol) if item is not None else None
        return SessionBlockResponse(
            order_index=block.order_index, exercise_id=block.exercise_id, complex_id=block.complex_id,
            result=block.result, protocol_type=item.protocol.type.value if item is not None else None,
            exercise_name=name, started_at=block_started_at(detail, block.order_index) if item is not None else None,
            set_targets=[
                SessionSetTargetResponse(
                    set_number=t.set_number, is_max_set=t.is_max_set, metric_type=t.metric_type.value,
                    value=str(t.value), unit=t.unit,
                )
                for t in block.set_targets
            ],
            interval_config=(
                IntervalConfigResponse(
                    total_duration_seconds=protocol.total_duration_seconds,
                    work_seconds=protocol.work_seconds, rest_seconds=protocol.rest_seconds,
                )
                if protocol is not None else None
            ),
            set_logs=[
                SetLogResponse(
                    set_number=log.set_number, is_max_set=log.is_max_set, metric_type=log.metric_type.value,
                    value=str(log.value), unit=log.unit,
                    effort=str(log.effort) if log.effort is not None else None,
                    note=_set_log_note(detail.source, log.note, log.value), is_extra=log.is_extra,
                )
                for log in block.set_logs
            ],
        )

    return SessionResponse(
        id=detail.id, source=detail.source.value, status=detail.status.value,
        performed_at=detail.performed_at, effort=str(detail.effort) if detail.effort is not None else None,
        comment=detail.comment, title=activity_label(detail.activity_type) or title, can_delete=can_delete,
        can_edit=can_delete, activity_type=detail.activity_type, duration_seconds=detail.duration_seconds,
        blocks=[_block(block, item) for block, item in zip(detail.blocks, snapshot_items, strict=True)],
        progression_result=progression, progression_skipped_reason=skipped_reason, workout_id=workout_id,
    )


async def _openable_workout_ids(
    session: AsyncSession, details: list[SessionDetail], user_id: int,
) -> dict[int, int]:
    """session_id -> workout_id для сессий, чей замороженный снимок ссылается на ЖИВУЮ
    свою тренировку пользователя (Журнал «Открыть тренировку», #281). Удалённая
    (архивная) или чужая тренировка — ссылки нет, а не мёртвая кнопка."""
    referenced: dict[int, int] = {}
    for detail in details:
        raw = (detail.workout_snapshot or {}).get("workout_id")
        if isinstance(raw, int) and not isinstance(raw, bool):
            referenced[detail.id] = raw
    own = await ProgramRepository(session).list_own_workout_ids(sorted(set(referenced.values())), user_id)
    return {session_id: workout_id for session_id, workout_id in referenced.items() if workout_id in own}


async def _catalog_exercise_names(session: AsyncSession, details: list[SessionDetail]) -> dict[int, str]:
    """Имена упражнений блоков одним запросом. Внутренние STEP-роли
    (subcategory block_a/block_b — тот же фильтр, что GET /exercises) не
    получают имени: человекочитаемого у них нет."""
    exercise_ids = sorted({
        block.exercise_id for detail in details for block in detail.blocks if block.exercise_id is not None
    })
    exercises = await ProgramRepository(session).list_exercises_by_ids(exercise_ids)
    return {ex.id: ex.name for ex in exercises if ex.subcategory not in ("block_a", "block_b")}


# --- Каталог ---------------------------------------------------------------------------


@router_v2.get("/programs", response_model=ProgramListResponse)
async def list_programs(
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> ProgramListResponse:
    await _require_user(session, init_data)
    programs_repo = ProgramRepository(session)
    programs = await programs_repo.list_all()
    responses = []
    for program in programs:
        strategy_profile = (
            await programs_repo.get_strategy_profile(program.progression_strategy_id)
            if program.progression_strategy_id is not None else None
        )
        strategy_type_value = strategy_profile.strategy_type.value if strategy_profile is not None else None
        responses.append(_program_response(program, strategy_type_value))
    return ProgramListResponse(programs=responses)


@router_v2.get("/programs/{program_id}/schedule", response_model=ProgramScheduleResponse)
async def get_program_schedule(
    program_id: int,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> ProgramScheduleResponse:
    """Превью структуры программы до добавления в план (issue #266). Каталог виден
    всем; только реальные ProgramItem/config — у программы без строк items пуст."""
    await _require_user(session, init_data)
    programs = ProgramRepository(session)
    program = await programs.get_by_id(program_id)
    if program is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Program not found")
    program_items = await programs.list_program_items(program.id)
    exercises = {
        ex.id: ex for ex in await programs.list_exercises_by_ids(
            sorted({i.exercise_id for i in program_items if i.exercise_id is not None}),
        )
    }
    complexes = {
        c.id: c for c in await programs.list_complexes_by_ids(
            sorted({i.complex_id for i in program_items if i.complex_id is not None}),
        )
    }
    items: list[ProgramScheduleItemResponse] = []
    for item in sorted(program_items, key=lambda i: (i.week_phase.value, i.day_of_week is None, i.day_of_week or 0, i.id)):
        exercise = exercises.get(item.exercise_id) if item.exercise_id is not None else None
        complex_ = complexes.get(item.complex_id) if item.complex_id is not None else None
        subcategory = exercise.subcategory if exercise is not None else None
        if complex_ is not None and complex_.owner_user_id is None:
            title = complex_.name
        elif exercise is not None:
            title = block_role_title(subcategory) or exercise.name
        else:
            continue  # ни упражнения, ни публичного комплекса — нечего показать
        items.append(ProgramScheduleItemResponse(
            week_phase=item.week_phase.value, day_of_week=item.day_of_week,
            count_per_week=item.count_per_week, title=title,
            count_label=count_per_week_label(item.count_per_week),
            target_label=block_target_label(program.config, subcategory),
        ))
    phases = list(dict.fromkeys(i.week_phase for i in items))
    return ProgramScheduleResponse(
        program_id=program.id, duration_weeks=duration_weeks(program.config), phases=phases, items=items,
    )


# --- Избранное (issue #272) -------------------------------------------------------------


async def _favorite_target_exists(session: AsyncSession, user_id: int, target_type: str, target_id: int) -> bool:
    """Избранное — только видимое пользователю: свои user-тренировки и программы
    каталога (у Program нет флага публикации — каталог виден всем). Остальное — нет."""
    programs = ProgramRepository(session)
    if target_type == "workout":
        return await programs.get_editable_workout_for_user(target_id, user_id) is not None
    if target_type == "program":
        return await programs.get_by_id(target_id) is not None
    return False


@router_v2.get("/favorites", response_model=FavoriteListResponse)
async def list_favorites(
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> FavoriteListResponse:
    """Избранное, новые первыми. Удалённые/ставшие недоступными цели в список
    не попадают (строки не удаляются — просто фильтруются)."""
    user = await _require_user(session, init_data)
    programs = ProgramRepository(session)
    rows = await FavoriteRepository(session).list_for_user(user.id)
    workouts = {w.id: w for w in await programs.list_user_workouts(user.id)}
    program_by_id = {p.id: p for p in await programs.list_all()}
    favorites: list[FavoriteResponse] = []
    for row in rows:
        if row.target_type == "workout" and row.target_id in workouts:
            favorites.append(FavoriteResponse(
                target_type="workout", target_id=row.target_id, title=workouts[row.target_id].name,
                subtitle="Своя тренировка",
            ))
        elif row.target_type == "program" and row.target_id in program_by_id:
            program = program_by_id[row.target_id]
            favorites.append(FavoriteResponse(
                target_type="program", target_id=row.target_id, title=program.name, subtitle=program.goal,
            ))
    return FavoriteListResponse(favorites=favorites)


@router_v2.put("/favorites/{target_type}/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def add_favorite(
    target_type: str,
    target_id: int,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Идемпотентно. Недоступная/несуществующая цель или неизвестный тип — 404."""
    user = await _require_user(session, init_data)
    if not await _favorite_target_exists(session, user.id, target_type, target_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Favorite target not found")
    await FavoriteRepository(session).add(user.id, target_type, target_id)
    await session.commit()


@router_v2.delete("/favorites/{target_type}/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_favorite(
    target_type: str,
    target_id: int,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Идемпотентно: снять можно и то, чего нет. Неизвестный тип — 404."""
    user = await _require_user(session, init_data)
    if target_type not in ("workout", "program"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Favorite target not found")
    await FavoriteRepository(session).remove(user.id, target_type, target_id)
    await session.commit()


@router_v2.get("/exercises", response_model=ExerciseListResponse)
async def list_exercises(
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> ExerciseListResponse:
    """Checkpoint 3A (issue #196) — минимальная Exercise Library без UI.
    Не требует admin-доступа (обычный пользователь должен пользоваться
    библиотекой). Отдаёт только поля, реально существующие в Exercise
    model — не equipment/difficulty/duration/muscles.

    Product-contract gap, найден живым Playwright-прогоном Checkpoint 3
    (не в исходном issue #196): без фильтра сюда попадали и внутренние
    step-роли программ (subcategory="block_a"/"block_b" — "Подтягивания —
    объём/сила"), позволяя пользователю добавить чужой строительный блок
    программы как самостоятельное упражнение. Исключение — по УЖЕ
    существующей конвенции, не новой эвристике: та же пара значений
    subcategory, которую ProgramRepository.find_step_role_exercises()
    использует для резолва StepProgressionStrategy (подтверждено Кириллом
    в issue #165 как достаточное, без новой колонки). Exercise с
    subcategory=NULL (обычные библиотечные упражнения) — не задет, явный
    OR по IS NULL, потому что NOT IN(...) в SQL сам по себе отбрасывает
    NULL-строки (three-valued logic), не включает их.

    Phase C1 (issue #188) — добавлена visibility-фильтрация: обычный
    пользователь видит все system Exercise и только свои user Exercise, не
    чужие. Тот же принцип, что get_X_for_user-семейство методов уже
    применяет системно (app.db.repositories.training_plans) — не новая
    эвристика."""
    user = await _require_user(session, init_data)
    result = await session.execute(
        select(Exercise)
        .where(Exercise.subcategory.is_(None) | Exercise.subcategory.not_in(["block_a", "block_b"]))
        .where((Exercise.source_type == "system") | (Exercise.owner_user_id == user.id))
        .order_by(Exercise.id),
    )
    exercises = result.scalars().all()
    return ExerciseListResponse(
        exercises=[
            ExerciseResponse(
                id=ex.id,
                name=ex.name,
                metric_type=ex.metric_type.value,
                category=ex.category,
                subcategory=ex.subcategory,
            )
            for ex in exercises
        ],
    )


@router_v2.post("/exercises", response_model=ExerciseResponse)
async def create_exercise(
    body: ExerciseCreateRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> ExerciseResponse:
    """Phase C1 (issue #188) — минимальный CREATE для пользовательского
    Exercise (Workout Builder foundation). System Exercise через этот путь
    создать нельзя — source_type всегда "user", owner_user_id всегда
    текущий пользователь (ProgramRepository.create_user_exercise не
    принимает эти значения снаружи). rename/delete/update — явно вне
    scope этой волны (см. issue #188, Phase C1)."""
    user = await _require_user(session, init_data)
    exercise = await ProgramRepository(session).create_user_exercise(name=body.name, owner_user_id=user.id)
    await session.commit()
    return ExerciseResponse(
        id=exercise.id, name=exercise.name, metric_type=exercise.metric_type.value,
        category=exercise.category, subcategory=exercise.subcategory,
    )


def _workout_response(complex_: Complex, items: list[WorkoutItemResponse] | None = None) -> WorkoutResponse:
    return WorkoutResponse(
        id=complex_.id, title=complex_.name, source_type=complex_.source_type,
        owner_user_id=complex_.owner_user_id, items=items,
    )


async def _build_workout_item_responses(
    session: AsyncSession, items: list[ComplexItem], name_by_id: dict[int, str] | None = None,
) -> list[WorkoutItemResponse]:
    """Phase C3 (issue #188) — batch-резолвинг exercise_name, не по
    одному на item (тот же принцип, что list_exercises_by_ids уже
    применяется везде в проекте для этой цели)."""
    if name_by_id is None:
        exercises = await ProgramRepository(session).list_exercises_by_ids(sorted({item.exercise_id for item in items}))
        name_by_id = {exercise.id: exercise.name for exercise in exercises}
    return [
        WorkoutItemResponse(
            id=item.id, exercise_id=item.exercise_id,
            exercise_name=name_by_id.get(item.exercise_id, f"Упражнение #{item.exercise_id}"),
            order_index=item.order_index, protocol=item.protocol or {},
        )
        for item in items
    ]


@router_v2.post("/workouts", response_model=WorkoutResponse)
async def create_workout(
    body: WorkoutCreateRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> WorkoutResponse:
    """Phase C2 (issue #188) — минимальный CREATE для Workout (продуктовое
    имя; техническое хранилище — Complex, без rename, см. ADR
    docs/adr/WORKOUT_PROTOCOL_V1.md). Всегда source_type='user',
    owner_user_id=текущий пользователь — system Workout через этот путь
    создать нельзя (create_complex не получает эти значения снаружи)."""
    user = await _require_user(session, init_data)
    workout = await ProgramRepository(session).create_complex(
        name=body.title, source_type="user", owner_user_id=user.id,
    )
    await session.commit()
    return _workout_response(workout)


@router_v2.get("/workouts", response_model=WorkoutListResponse)
async def list_my_workouts(
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> WorkoutListResponse:
    """Phase C2 (issue #188) — только user Workout текущего владельца
    (source_type == user AND owner_user_id == текущий пользователь), для
    экрана "Мои тренировки" и карточек Главной (items включены). System
    Workout сюда намеренно не входит — публичного каталога нет."""
    user = await _require_user(session, init_data)
    programs = ProgramRepository(session)
    workouts = await programs.list_user_workouts(user.id)
    # Состав всех тренировок — двумя запросами на весь список (items и имена
    # упражнений), не по запросу на каждую: карточкам Главной нужны items.
    items_by_workout = await programs.list_complex_items_by_complex_ids([w.id for w in workouts])
    exercise_ids = sorted({item.exercise_id for items in items_by_workout.values() for item in items})
    name_by_id = {ex.id: ex.name for ex in await programs.list_exercises_by_ids(exercise_ids)}
    return WorkoutListResponse(
        workouts=[
            _workout_response(
                w, items=await _build_workout_item_responses(session, items_by_workout[w.id], name_by_id),
            )
            for w in workouts
        ],
    )


@router_v2.get("/workouts/{workout_id}", response_model=WorkoutResponse)
async def get_workout_detail(
    workout_id: int,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> WorkoutResponse:
    """Видим: system (любому) или свой user Workout. Чужой user Workout —
    404, не 403 (существующая конвенция проекта). Phase C3 — теперь
    включает ordered items (order_index ASC, тот же порядок, что
    list_complex_items уже гарантирует)."""
    user = await _require_user(session, init_data)
    program_repo = ProgramRepository(session)
    workout = await program_repo.get_visible_workout_for_user(workout_id, user.id)
    if workout is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workout not found")
    complex_items = await program_repo.list_complex_items(workout_id)
    items = await _build_workout_item_responses(session, complex_items)
    return _workout_response(workout, items=items)


@router_v2.get("/workouts/{workout_id}/sessions", response_model=WorkoutSessionsResponse)
async def list_workout_sessions(
    workout_id: int,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> WorkoutSessionsResponse:
    """История одной тренировки: завершённые v2-сессии текущего пользователя,
    чей замороженный workout_snapshot ссылается на этот Workout, новые первыми.
    Видимость — как у GET /workouts/{id} (чужой user Workout — 404)."""
    user = await _require_user(session, init_data)
    if await ProgramRepository(session).get_visible_workout_for_user(workout_id, user.id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workout not found")
    details = await TrainingSessionRepository(session).list_completed_for_workout(user.id, workout_id)
    return WorkoutSessionsResponse(
        sessions=[
            WorkoutSessionSummaryResponse(
                id=detail.id, performed_at=detail.performed_at, exercises_count=len(detail.blocks),
                sets_done=sum(len(block.set_logs) for block in detail.blocks),
            )
            for detail in details
        ],
    )


@router_v2.post("/workouts/{workout_id}/items", response_model=WorkoutItemResponse)
async def add_workout_item(
    workout_id: int,
    body: WorkoutItemCreateRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> WorkoutItemResponse:
    """Phase C3 (issue #188) — только editable (свой user) Workout, не
    system, не чужой. Exercise должен быть visible current_user (system
    или свой user Exercise) — тот же get_visible_exercise_for_user, что
    C1 уже определил. protocol валидируется через UserWorkoutProtocol
    (без progression-вариантов — обычный Workout Builder не должен
    протолкнуть prescription.source='progression' через сырой JSON)."""
    user = await _require_user(session, init_data)
    program_repo = ProgramRepository(session)
    workout = await program_repo.get_editable_workout_for_user(workout_id, user.id)
    if workout is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workout not found")
    exercise = await program_repo.get_visible_exercise_for_user(body.exercise_id, user.id)
    if exercise is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Exercise not found")
    try:
        validated_protocol = TypeAdapter(UserWorkoutProtocol).validate_python(body.protocol)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    item = await program_repo.add_workout_item(
        complex_id=workout_id, exercise_id=body.exercise_id,
        protocol=validated_protocol.model_dump(mode="json"),
    )
    await session.commit()
    return (await _build_workout_item_responses(session, [item]))[0]


@router_v2.patch("/workouts/{workout_id}/items/{item_id}", response_model=WorkoutItemResponse)
async def update_workout_item(
    workout_id: int,
    item_id: int,
    body: WorkoutItemUpdateRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> WorkoutItemResponse:
    """order_index через этот endpoint никогда не меняется (см. move)."""
    user = await _require_user(session, init_data)
    program_repo = ProgramRepository(session)
    workout = await program_repo.get_editable_workout_for_user(workout_id, user.id)
    if workout is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workout not found")
    item = await program_repo.get_complex_item(item_id)
    if item is None or item.complex_id != workout_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workout item not found")

    new_exercise_id = body.exercise_id
    if new_exercise_id is not None:
        exercise = await program_repo.get_visible_exercise_for_user(new_exercise_id, user.id)
        if exercise is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Exercise not found")

    new_protocol = None
    if body.protocol is not None:
        try:
            validated_protocol = TypeAdapter(UserWorkoutProtocol).validate_python(body.protocol)
        except ValidationError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        new_protocol = validated_protocol.model_dump(mode="json")

    updated = await program_repo.update_workout_item(item_id, exercise_id=new_exercise_id, protocol=new_protocol)
    await session.commit()
    return (await _build_workout_item_responses(session, [updated]))[0]


@router_v2.delete("/workouts/{workout_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workout_item(
    workout_id: int,
    item_id: int,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Удаляет item из editable Workout, нормализует order_index
    оставшихся (0, 1, 2, ... без дырок)."""
    user = await _require_user(session, init_data)
    program_repo = ProgramRepository(session)
    workout = await program_repo.get_editable_workout_for_user(workout_id, user.id)
    if workout is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workout not found")
    item = await program_repo.get_complex_item(item_id)
    if item is None or item.complex_id != workout_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workout item not found")
    await program_repo.delete_workout_item(item_id)
    await session.commit()


@router_v2.post("/workouts/{workout_id}/items/{item_id}/move", response_model=WorkoutResponse)
async def move_workout_item(
    workout_id: int,
    item_id: int,
    body: WorkoutItemMoveRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> WorkoutResponse:
    """Простой swap с соседом. На границе (первый+up, последний+down) —
    idempotent no-op, не ошибка (см. репозиторный докстринг)."""
    user = await _require_user(session, init_data)
    program_repo = ProgramRepository(session)
    workout = await program_repo.get_editable_workout_for_user(workout_id, user.id)
    if workout is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workout not found")
    item = await program_repo.get_complex_item(item_id)
    if item is None or item.complex_id != workout_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workout item not found")
    await program_repo.move_workout_item(item_id, direction=body.direction)
    await session.commit()
    refreshed_complex_items = await program_repo.list_complex_items(workout_id)
    items = await _build_workout_item_responses(session, refreshed_complex_items)
    return _workout_response(workout, items=items)


@router_v2.patch("/workouts/{workout_id}", response_model=WorkoutResponse)
async def update_workout_title(
    workout_id: int,
    body: WorkoutUpdateRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> WorkoutResponse:
    """Редактируем: только свой user Workout. System Workout — read-only
    для всех обычных пользователей, тоже 404 при попытке PATCH (не
    раскрывает пользователю, что Workout вообще существует под чужим/
    системным владением — та же 404-конвенция, что и всюду в проекте)."""
    user = await _require_user(session, init_data)
    workout = await ProgramRepository(session).get_editable_workout_for_user(workout_id, user.id)
    if workout is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workout not found")
    await ProgramRepository(session).update_complex_title(workout_id, body.title)
    await session.commit()
    refreshed = await ProgramRepository(session).get_complex(workout_id)
    return _workout_response(refreshed)


@router_v2.delete("/workouts/{workout_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workout(
    workout_id: int,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Issue #261 — мягкое удаление своего user Workout (чужой/system/уже
    удалённый — 404). Определение Complex/ComplexItem не уничтожается: на него
    ссылаются замороженные снимки завершённых сессий, они остаются в Журнале.
    Ручные PlanItem этой тренировки убираются из плана, избранное — тоже."""
    user = await _require_user(session, init_data)
    program_repo = ProgramRepository(session)
    workout = await program_repo.get_editable_workout_for_user(workout_id, user.id)
    if workout is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workout not found")
    await TrainingPlanRepository(session).delete_plan_items_for_workout(user.id, workout_id)
    await FavoriteRepository(session).remove(user.id, "workout", workout_id)
    await program_repo.archive_workout(workout)
    await session.commit()


@router_v2.post("/workouts/{workout_id}/duplicate", response_model=WorkoutResponse)
async def duplicate_workout(
    workout_id: int,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> WorkoutResponse:
    """Issue #261 — «<название> (копия)» со скопированным составом и протоколами,
    тот же владелец. Только свой user Workout (иначе 404)."""
    user = await _require_user(session, init_data)
    program_repo = ProgramRepository(session)
    workout = await program_repo.get_editable_workout_for_user(workout_id, user.id)
    if workout is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workout not found")
    name = f"{workout.name} (копия)"[:255]
    copy = await program_repo.duplicate_workout(workout, owner_user_id=user.id, name=name)
    await session.commit()
    items = await _build_workout_item_responses(session, await program_repo.list_complex_items(copy.id))
    return _workout_response(copy, items=items)


# --- План ------------------------------------------------------------------------------


def _utcnow() -> datetime:
    """Единая точка «сейчас» для недельной арифметики плана (подменяется в тестах)."""
    return datetime.now(UTC)


def _plan_today(user) -> date:
    """Сегодняшняя дата в часовом поясе пользователя: по ней считается вся
    недельная арифметика плана (текущая неделя, окно «текущая .. +4»), как и
    на клиенте; в UTC у UTC+N около полуночи понедельника неделя не совпадала."""
    return _utcnow().astimezone(resolve_timezone(user.timezone)).date()


@router_v2.get("/plan", response_model=PlanResponse)
async def get_plan(
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> PlanResponse:
    user = await _require_user(session, init_data)
    plans = TrainingPlanRepository(session)
    plan = await plans.get_for_user(user.id)
    if plan is None:
        return PlanResponse(plan=None)

    # Checkpoint 1 (issue #188), раздел "Rollover": единственная точка,
    # где новая календарная неделя должна материализоваться сама, без
    # действия пользователя — "пользователь не может открыть Планы и
    # остаться на прошлой неделе" (Поправка 4). Тонкий вызов, вся логика —
    # в PlanWeekService, идемпотентно на каждый GET.
    current_week = await PlanWeekService(session).ensure_current_plan_week(
        training_plan_id=plan.id, today=_plan_today(user),
    )

    inclusions = await plans.list_inclusions(plan.id)
    plan_items = await plans.list_plan_items(plan.id)
    plan_weeks = await plans.list_plan_weeks(plan.id)
    # Phase B2 gate fix (issue #215) — batch, не по одному на PlanItem.
    complex_ids = sorted({item.complex_id for item in plan_items if item.complex_id is not None})
    complexes = await ProgramRepository(session).list_complexes_by_ids(complex_ids)
    complex_name_by_id = {complex_.id: complex_.name for complex_ in complexes}
    # Phase D2 (issue #188) — тот же уже полученный complexes список, ни
    # одного дополнительного запроса.
    complex_source_type_by_id = {complex_.id: complex_.source_type for complex_ in complexes}
    # issue #258 — счётчики «сделано» на неделю каждого item, в часовом поясе
    # пользователя; не хранимый статус, считается из SessionPlanItem.
    tz = resolve_timezone(user.timezone)
    week_start_by_id = {week.id: week.start_date for week in plan_weeks}
    week_start_by_item = {
        item.id: week_start_by_id[item.plan_week_id]
        for item in plan_items if item.plan_week_id in week_start_by_id
    }
    performed = await plans.list_completed_session_times_by_plan_item(
        user_id=user.id, plan_item_ids=list(week_start_by_item),
    )
    done_by_item = count_done_per_plan_item(
        week_start_by_item, [(item_id, at.astimezone(tz).date()) for item_id, at in performed],
    )
    return PlanResponse(
        plan=TrainingPlanResponse(
            id=plan.id, created_at=plan.created_at,
            program_inclusions=[_program_inclusion_response(inclusion, user) for inclusion in inclusions],
            plan_items=[
                _plan_item_response(
                    item, complex_name_by_id, complex_source_type_by_id, done_by_item.get(item.id, 0),
                )
                for item in plan_items
            ],
            plan_weeks=[_plan_week_response(week) for week in plan_weeks],
            current_week_id=current_week.id,
        ),
    )


@router_v2.post("/program-inclusions", response_model=ProgramInclusionResponse)
async def create_program_inclusion(
    body: ProgramInclusionCreateRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> ProgramInclusionResponse:
    user = await _require_user(session, init_data)
    inclusion = await ProgramInclusionService(session).create_inclusion(
        user_id=user.id,
        request=ProgramInclusionRequest(
            program_id=body.program_id, initial_target_a=body.initial_target_a,
            initial_target_b=body.initial_target_b, initial_volume_a=body.initial_volume_a,
            initial_volume_b=body.initial_volume_b,
        ),
    )
    if inclusion is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Program not found")
    # Checkpoint 1 (issue #188) — тонкий вызов канонического сервиса, вся
    # логика материализации в PlanWeekService, не здесь (раздел 4 preflight:
    # "не помещать бизнес-логику materialization непосредственно в route").
    await PlanWeekService(session).ensure_current_plan_week(
        training_plan_id=inclusion.training_plan_id, today=_plan_today(user),
    )
    return _program_inclusion_response(inclusion, user)


@router_v2.post("/program-inclusions/{inclusion_id}/deactivate", response_model=ProgramInclusionResponse)
async def deactivate_program_inclusion(
    inclusion_id: int,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> ProgramInclusionResponse:
    """«Убрать курс из плана» (issue #266): is_active=false, строки истории
    (PlanItem/сессии/снимок) не удаляются; expires_at фиксирует дату окончания.
    Идемпотентно. Чужой/несуществующий id — 404."""
    user = await _require_user(session, init_data)
    inclusion = await TrainingPlanRepository(session).get_inclusion_for_user(inclusion_id, user.id)
    if inclusion is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Program inclusion not found")
    if inclusion.is_active:
        inclusion.is_active = False
        if inclusion.expires_at is None:
            inclusion.expires_at = datetime.now(UTC)
        await session.commit()
    return _program_inclusion_response(inclusion, user)


# --- Строки недельной матрицы -----------------------------------------------------------


@router_v2.post("/plan/weeks", response_model=PlanWeekResponse)
async def create_plan_week(
    body: PlanWeekCreateRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> PlanWeekResponse:
    """issue #275 — идемпотентно создаёт неделю плана вперёд (текущая .. +4).
    Вне окна — 422. Программные PlanItem сюда не материализуются."""
    user = await _require_user(session, init_data)
    plan = await TrainingPlanRepository(session).get_or_create_for_user(user.id)
    week = await PlanWeekService(session).ensure_plannable_week(
        training_plan_id=plan.id, week_number=body.week_number, today=_plan_today(user),
    )
    if week is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Неделя недоступна для планирования")
    await session.commit()
    return _plan_week_response(week)


@router_v2.post("/plan/weeks/{plan_week_id}/copy-to-next", response_model=PlanWeekCopyResponse)
async def copy_plan_week_to_next(
    plan_week_id: int,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> PlanWeekCopyResponse:
    """issue #275 — копирует ручные PlanItem недели в следующую (дубликаты
    пропускаются, программные строки не копируются). Чужая неделя — 404;
    следующая неделя вне окна планирования — 422."""
    user = await _require_user(session, init_data)
    plans = TrainingPlanRepository(session)
    source = await plans.get_plan_week_for_user(plan_week_id, user.id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "PlanWeek not found")
    service = PlanWeekService(session)
    target = await service.ensure_plannable_week(
        training_plan_id=source.training_plan_id, week_number=source.week_number + 1,
        today=_plan_today(user),
    )
    if target is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Неделя недоступна для планирования")
    copied, skipped = await service.copy_manual_items(source=source, target=target)
    await session.commit()
    return PlanWeekCopyResponse(target_week=_plan_week_response(target), copied=copied, skipped=skipped)


@router_v2.get("/plan-items", response_model=PlanItemListResponse)
async def list_plan_items(
    program_inclusion_id: int | None = Query(default=None),
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> PlanItemListResponse:
    user = await _require_user(session, init_data)
    plans = TrainingPlanRepository(session)
    plan = await plans.get_for_user(user.id)
    if plan is None:
        return PlanItemListResponse(items=[])
    items = await plans.list_plan_items(plan.id, program_inclusion_id=program_inclusion_id)
    return PlanItemListResponse(items=[_plan_item_response(item) for item in items])


@router_v2.post("/plan-items", response_model=PlanItemResponse)
async def create_plan_item(
    body: PlanItemCreateRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> PlanItemResponse:
    """program_inclusion_id всегда NULL на этом пути — по докстрингу
    PlanItem "добавлено вручную" (app/db/models_program.py). Строки из
    инклюзии заводит только POST /program-inclusions (копирование
    ProgramItem -> PlanItem), не этот эндпоинт."""
    user = await _require_user(session, init_data)
    plans = TrainingPlanRepository(session)
    programs = ProgramRepository(session)
    plan = await plans.get_or_create_for_user(user.id)

    # G2 (REBUILD-1, R4) — публичный путь не должен привязывать к плану
    # произвольный объект по id. ВСЕ проверки — до создания PlanItem (при
    # отказе строка не создаётся; пустой TrainingPlan — обычное состояние
    # любого пользователя, не утечка). Недоступное и несуществующее
    # неразличимы: одинаковый 404.
    #   * exercise_id — system Exercise из публичной библиотеки или СВОЙ
    #     user Exercise; не чужой и не внутренняя STEP-роль;
    #   * complex_id — только СВОЙ user Workout; system/программные Complex и
    #     чужие Workout — отказ. Внутренние пути материализации
    #     (ProgramInclusion/STEP) эту проверку не проходят: они не идут через
    #     публичный эндпоинт.
    if body.exercise_id is not None and (
        await programs.get_publicly_attachable_exercise_for_user(body.exercise_id, user.id) is None
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Exercise not found")
    if body.complex_id is not None and (
        await programs.get_editable_workout_for_user(body.complex_id, user.id) is None
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workout not found")

    # Checkpoint 3B (issue #197): ownership-проверка plan_week_id, если передан
    if body.plan_week_id is not None:
        week = await plans.get_plan_week_for_user(body.plan_week_id, user.id)
        if week is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "PlanWeek not found")

    try:
        item = await plans.create_plan_item(
            training_plan_id=plan.id, exercise_id=body.exercise_id, complex_id=body.complex_id,
            count_per_week=body.count_per_week, day_of_week=body.day_of_week,
            week_phase=WeekPhase(body.week_phase) if body.week_phase is not None else None,
            program_inclusion_id=None, plan_week_id=body.plan_week_id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return _plan_item_response(item)


@router_v2.patch("/plan-items/{plan_item_id}", response_model=PlanItemResponse)
async def move_plan_item(
    plan_item_id: int,
    body: PlanItemMoveRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> PlanItemResponse:
    """Phase D2 (issue #188) — Move. plan_week_id не меняется в этой волне
    (PlanItem остаётся в той же current PlanWeek). STEP/program-backed
    (program_inclusion_id IS NOT NULL) и чужой PlanItem — оба дают 404,
    не раскрывая пользователю причину (существующая 404-конвенция
    проекта)."""
    user = await _require_user(session, init_data)
    plans = TrainingPlanRepository(session)
    if body.plan_week_id is not None:
        # issue #275 — перенос между неделями: целевая неделя своя и в окне
        # «текущая .. +4»; ручной item из прошлой недели не двигаем.
        plan = await plans.get_for_user(user.id)
        target = await plans.get_plan_week_for_user(body.plan_week_id, user.id)
        current = await plans.get_plan_item_for_user(plan_item_id, user.id)
        if plan is None or target is None or current is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "PlanItem not found")
        current_number = plan_week_number(plan.created_at.date(), _plan_today(user))
        source = (
            await plans.get_plan_week_for_user(current.plan_week_id, user.id) if current.plan_week_id else None
        )
        if not is_plannable_week_number(target.week_number, current_number) or (
            source is not None and source.week_number < current_number
        ):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Неделя недоступна для планирования")
    item = await plans.update_mutable_plan_item_day(
        plan_item_id, user.id, body.day_of_week, plan_week_id=body.plan_week_id,
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "PlanItem not found")
    return _plan_item_response(item)


@router_v2.delete("/plan-items/{plan_item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_plan_item(
    plan_item_id: int,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Phase D2 (issue #188) — Remove. Удаляет только саму строку
    PlanItem — Exercise/Complex/ComplexItem/ProgramInclusion/
    TrainingSession/workout_snapshot/Journal history не задеты. STEP/
    program-backed и чужой PlanItem — оба 404."""
    user = await _require_user(session, init_data)
    plans = TrainingPlanRepository(session)
    deleted = await plans.delete_mutable_plan_item(plan_item_id, user.id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "PlanItem not found")


# --- Сессии ------------------------------------------------------------------------------


async def _resolve_session_titles(
    session: AsyncSession, details: list[SessionDetail], user_id: int,
) -> dict[int, str | None]:
    """Checkpoint 4C (issue #188) — единственное место, где SessionPlanItem
    читается (заполняется с Checkpoint 4A, ранее нигде не читалась).
    Батч на всю страницу — 4 запроса суммарно (было 3 до Phase B1), не по
    N на сессию: SessionPlanItem -> PlanItem -> (ProgramInclusion |
    Complex | Exercise).

    Program-backed: если хотя бы один source PlanItem имеет
    program_inclusion_id — заголовок это ProgramInclusion.program_name
    ("Подтягивания"), не имя отдельного блока ("Блок A"/"Блок Б" никогда
    не должны стать пользовательской карточкой верхнего уровня).
    Complex-backed (Phase B1, issue #215) — PlanItem.complex_id, но не
    program_inclusion_id (system/user Workout, не курс) — заголовок это
    Complex.name ("3 минуты подтягиваний"), НЕ Exercise.name отдельного
    упражнения внутри Workout — проверяется раньше exercise_id-ветки,
    иначе несвязанный/decoy exercise_id на complex-based PlanItem дал бы
    неверное имя.
    Manual: все source PlanItem имеют program_inclusion_id=NULL и
    complex_id=NULL — заголовок это имя Exercise (единственного, по факту
    4B: одна manual-группа = одна TrainingSession).
    Отсутствует совсем — сессия создана мимо create_live_session
    (до Checkpoint 4A) или связанный PlanItem с тех пор удалён — честный
    None, не выдуманное имя."""
    plans = TrainingPlanRepository(session)
    sessions_repo = TrainingSessionRepository(session)

    session_ids = [detail.id for detail in details]
    plan_item_ids_by_session = await sessions_repo.list_plan_item_ids_by_session(session_ids)

    all_plan_item_ids = sorted({pid for ids in plan_item_ids_by_session.values() for pid in ids})
    plan_items = await plans.list_plan_items_by_ids_for_user(all_plan_item_ids, user_id)
    plan_items_by_id = {item.id: item for item in plan_items}

    inclusion_ids = sorted({item.program_inclusion_id for item in plan_items if item.program_inclusion_id is not None})
    inclusions = await plans.list_inclusions_by_ids(inclusion_ids)
    program_name_by_inclusion = {
        inclusion.id: inclusion.snapshot.get("program_name", "") for inclusion in inclusions
    }

    manual_exercise_ids = sorted({
        item.exercise_id for item in plan_items
        if item.program_inclusion_id is None and item.complex_id is None and item.exercise_id is not None
    })
    exercises = await ProgramRepository(session).list_exercises_by_ids(manual_exercise_ids)
    exercise_name_by_id = {exercise.id: exercise.name for exercise in exercises}

    # Phase B1 gate fix (issue #215) — Workout title (Complex.name), не
    # Exercise.name. До этого фикса функция вообще не проверяла
    # item.complex_id — для complex-based PlanItem (Checkpoint A1/B1
    # interval workouts) title резолвился бы через exercise_id ветку
    # ниже, что для decoy/несвязанного exercise_id дало бы неверное имя.
    workout_complex_ids = sorted({
        item.complex_id for item in plan_items
        if item.program_inclusion_id is None and item.complex_id is not None
    })
    complexes = await ProgramRepository(session).list_complexes_by_ids(workout_complex_ids)
    workout_title_by_complex_id = {complex_.id: complex_.name for complex_ in complexes}

    titles: dict[int, str | None] = {}
    for detail in details:
        source_items = [
            plan_items_by_id[pid] for pid in plan_item_ids_by_session.get(detail.id, []) if pid in plan_items_by_id
        ]
        program_backed = next((item for item in source_items if item.program_inclusion_id is not None), None)
        complex_backed = next((item for item in source_items if item.complex_id is not None), None)
        if program_backed is not None:
            titles[detail.id] = program_name_by_inclusion.get(program_backed.program_inclusion_id)
        elif complex_backed is not None:
            titles[detail.id] = workout_title_by_complex_id.get(complex_backed.complex_id)
        elif source_items and source_items[0].exercise_id is not None:
            titles[detail.id] = exercise_name_by_id.get(source_items[0].exercise_id)
        elif detail.source == SessionSource.FREEFORM and detail.workout_snapshot is not None:
            # «Начать» с Workout Detail: без PlanItem, заголовок — из замороженного снимка.
            titles[detail.id] = detail.workout_snapshot.get("title")
        else:
            titles[detail.id] = None
    return titles


@router_v2.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status_filter: Literal["started", "completed"] | None = Query(default=None, alias="status"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    exclude_backfilled: bool = Query(default=False),
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> SessionListResponse:
    """status (Checkpoint 4C) — опциональный фильтр, без параметра ведёт
    себя как раньше (и STARTED, и COMPLETED) — SessionV2Lab.tsx/
    SessionJournalScreen.tsx его не передают, их поведение не меняется.

    date_from/date_to (#256) — включительно, ЛОКАЛЬНЫЕ дни пользователя (его
    часовой пояс, как в Analytics v2); Журнал грузит месяц за запрос.

    exclude_backfilled (#284) — только для Журнала: скрыть v2-сессии, созданные backfill-ом legacy
    Workout (#163; отпечаток — TrainingSessionRepository._backfilled_fingerprint). Старая схема —
    источник правды для перенесённой истории, её карточки показаны отдельно (GET /api/history) и
    только у них есть «Изменить»/«Удалить». Электив (#279, source=elective) и живые/Builder-сессии
    не скрываются. has_more считается после скрытия. Без флага — прежний ответ."""
    user = await _require_user(session, init_data)
    performed_from = performed_to = None
    if date_from is not None or date_to is not None:
        tz = resolve_timezone(user.timezone)
        if date_from is not None:
            performed_from = local_range_bounds_utc(date_from, date_from, tz)[0]
        if date_to is not None:
            performed_to = local_range_bounds_utc(date_to, date_to, tz)[1]
    status_value = SessionStatus(status_filter) if status_filter is not None else None
    # Phase B1 (issue #215, раздел 4) — второй call site lazy finalization:
    # пользователь мог не заходить в /sessions/live/active вообще (например
    # сразу открыл Журнал со status=completed после deadline) — expired
    # interval должен материализоваться и здесь. Проверяем STARTED-строки
    # ЭТОГО пользователя НЕЗАВИСИМО от запрошенного status_value — если
    # финализировать только среди уже отфильтрованных по completed строк,
    # ни одна STARTED-сессия никогда бы не попала в эту проверку вообще.
    # Только user.id — не сканирует чужие сессии и не всю таблицу.
    live_sessions = LiveSessionService(session)
    started_details = await TrainingSessionRepository(session).list_for_user(
        user.id, limit=200, offset=0, status=SessionStatus.STARTED,
    )
    for detail in started_details:
        await live_sessions.finalize_expired_interval_if_needed(detail.id, user.id)

    # limit+1 — только чтобы честно ответить has_more без отдельного запроса.
    fetched = await TrainingSessionRepository(session).list_for_user(
        user.id, limit=limit + 1, offset=offset, status=status_value,
        performed_from=performed_from, performed_to=performed_to, exclude_backfilled=exclude_backfilled,
    )
    has_more = len(fetched) > limit
    details = fetched[:limit]
    titles = await _resolve_session_titles(session, details, user.id)
    names = await _catalog_exercise_names(session, details)
    verdicts = await SessionDeletionService(session).evaluate(details, user.id)
    workout_ids = await _openable_workout_ids(session, details, user.id)
    return SessionListResponse(
        sessions=[
            _session_response(
                detail, progression=None, skipped_reason=None, title=titles.get(detail.id),
                exercise_names=names, can_delete=verdicts[detail.id].can_delete,
                workout_id=workout_ids.get(detail.id),
            )
            for detail in details
        ],
        has_more=has_more,
    )


@router_v2.get("/journal/days", response_model=JournalDaysResponse)
async def journal_days(
    month: str = Query(..., description="YYYY-MM"),
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> JournalDaysResponse:
    """Календарь Журнала (#256): сколько завершённых тренировок в каждый день
    месяца. v2-сессии — по локальному дню пользователя (timezone, дефолт проекта
    — Europe/Moscow, как в Analytics v2); legacy Workout — по дате, которую
    показывает карточка Истории (UTC-дата performed_at). Только агрегаты по
    границам месяца, без сканирования всей истории."""
    try:
        year, month_number = parse_month(month)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    user = await _require_user(session, init_data)
    tz = resolve_timezone(user.timezone)
    first_day, last_day = month_date_range(year, month_number)
    sessions_repo = TrainingSessionRepository(session)
    workouts_repo = WorkoutRepository(session)

    start, end = local_range_bounds_utc(first_day, last_day, tz)
    # v2-сессии, созданные backfill-ом (#284), не считаются: их показывает legacy-карточка ниже —
    # те же правила, что у списка Журнала (GET /sessions?exclude_backfilled=true).
    counts = local_day_counts(await sessions_repo.completed_performed_at(user.id, start, end, exclude_backfilled=True), tz)
    legacy_start, legacy_end = local_range_bounds_utc(first_day, last_day, UTC)
    for day, count in local_day_counts(
        await workouts_repo.completed_performed_at(user.id, legacy_start, legacy_end), UTC,
    ).items():
        counts[day] = counts.get(day, 0) + count

    latest_days: list[date] = []
    latest_session = await sessions_repo.latest_completed_performed_at(user.id, exclude_backfilled=True)
    if latest_session is not None:
        latest_days.append(latest_session.astimezone(tz).date())
    latest_workout = await workouts_repo.latest_completed_performed_at(user.id)
    if latest_workout is not None:
        latest_days.append(latest_workout.astimezone(UTC).date())
    latest = max(latest_days) if latest_days else None
    return JournalDaysResponse(
        month=f"{year:04d}-{month_number:02d}",
        timezone=str(tz),
        days=[JournalDayResponse(date=day.isoformat(), count=counts[day]) for day in sorted(counts)],
        latest_month=f"{latest.year:04d}-{latest.month:02d}" if latest is not None else None,
    )


@router_v2.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: int,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> None:
    """R2 — консервативное удаление завершённой Builder-сессии. Чужая/
    несуществующая — 404 (не раскрывает существование); небезопасная или
    недоказуемо безопасная — 409 с человекочитаемой причиной, ничего не
    удаляется. Удаляется только дерево TrainingSession."""
    user = await _require_user(session, init_data)
    found, verdict = await SessionDeletionService(session).delete(session_id, user.id)
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    if not verdict.can_delete:
        raise HTTPException(status.HTTP_409_CONFLICT, verdict.reason)


def _raise_for_edit_failure(outcome: EditOutcome) -> None:
    if outcome.status == EditStatus.NOT_FOUND:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    if outcome.status == EditStatus.DENIED:
        raise HTTPException(status.HTTP_409_CONFLICT, outcome.detail)
    if outcome.status == EditStatus.INVALID:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, outcome.detail)


async def _single_session_response(session: AsyncSession, session_id: int, user_id: int) -> SessionResponse:
    detail = await TrainingSessionRepository(session).get_for_user(session_id, user_id)
    titles = await _resolve_session_titles(session, [detail], user_id)
    names = await _catalog_exercise_names(session, [detail])
    verdict = (await SessionDeletionService(session).evaluate([detail], user_id))[detail.id]
    workout_ids = await _openable_workout_ids(session, [detail], user_id)
    return _session_response(
        detail, progression=None, skipped_reason=None, title=titles.get(detail.id),
        exercise_names=names, can_delete=verdict.can_delete, workout_id=workout_ids.get(detail.id),
    )


@router_v2.patch("/sessions/{session_id}", response_model=SessionResponse)
async def edit_session(
    session_id: int,
    body: SessionEditRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> SessionResponse:
    """#262 — правка завершённой Builder-сессии (значения/усилие/заметки
    подходов, усилие и комментарий тренировки, дата). Предикат безопасности —
    тот же, что у удаления: чужая — 404, небезопасная (курс/STEP/недоказанная)
    — 409 с причиной. Прогрессия не пересчитывается."""
    user = await _require_user(session, init_data)
    fields = body.model_fields_set
    outcome = await SessionEditingService(session).edit(
        session_id, user.id, resolve_timezone(user.timezone),
        performed_on=body.performed_on,
        effort=(body.effort,) if "effort" in fields else None,
        comment=(body.comment,) if "comment" in fields else None,
        sets=[SetEdit(s.block_index, s.set_number, s.value, s.effort, s.note) for s in body.sets],
        now=datetime.now(UTC),
    )
    _raise_for_edit_failure(outcome)
    return await _single_session_response(session, session_id, user.id)


@router_v2.post("/sessions/{session_id}/clone", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def clone_session(
    session_id: int,
    body: SessionCloneRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> SessionResponse:
    """#262 — «Повторить»: новая завершённая сессия (source=backdated) с теми же
    блоками/целями/фактом. Те же 404/409, что у правки; без прогрессии."""
    user = await _require_user(session, init_data)
    outcome = await SessionEditingService(session).clone(
        session_id, user.id, resolve_timezone(user.timezone), performed_on=body.performed_on, now=datetime.now(UTC),
    )
    _raise_for_edit_failure(outcome)
    return await _single_session_response(session, outcome.session_id, user.id)


def _block_input(block: SessionBlockInputSchema) -> SessionBlockInput:
    return SessionBlockInput(
        exercise_id=block.exercise_id, complex_id=block.complex_id,
        sets=[
            SetLogInput(
                set_number=s.set_number, metric_type=MetricType(s.metric_type), value=s.value, unit=s.unit,
                is_max_set=s.is_max_set, effort=s.effort, note=s.note,
            )
            for s in block.sets
        ],
    )


@router_v2.post("/sessions", response_model=SessionResponse)
async def create_session(
    body: SessionCreateRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> SessionResponse:
    user = await _require_user(session, init_data)
    # #263: Журнал пишет прошедшие события — будущая дата отклоняется (небольшой
    # допуск на расхождение часов клиента и сервера).
    is_journal_entry = body.source == "backdated" or body.activity_type is not None
    if is_journal_entry and body.performed_at > datetime.now(UTC) + timedelta(minutes=5):
        raise HTTPException(422, "Дата не может быть в будущем")
    # Владение: упражнения — системные или свои, тренировки — видимые пользователю
    # (чужое/несуществующее = 404, как во всех публичных эндпоинтах).
    program_repo = ProgramRepository(session)
    for block in body.blocks:
        if block.exercise_id is not None:
            if await program_repo.get_visible_exercise_for_user(block.exercise_id, user.id) is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Exercise not found")
            # #285: внутренняя STEP-роль (block_a/block_b) — не для записей Журнала/свободных/элективных:
            # такая сессия совпала бы с отпечатком backfill-копии (_backfilled_fingerprint) и пропала из
            # Журнала. STEP-блоки допустимы только у сессии программы (program_inclusion_id) — по ним
            # считается прогрессия; публичный клиент их так не шлёт.
            if body.program_inclusion_id is None and await program_repo.get_publicly_attachable_exercise_for_user(
                block.exercise_id, user.id,
            ) is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY, "Внутреннее упражнение программы нельзя записать вне программы",
                )
        if block.complex_id is not None and await program_repo.get_visible_workout_for_user(
            block.complex_id, user.id,
        ) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Workout not found")
    # Запись задним числом/свободная активность завершена в момент performed_at:
    # длительность не выводится из «сейчас» (иначе минуты Analytics были бы вымышлены).
    completed_at = body.performed_at if is_journal_entry else None
    result, inclusion_not_found = await TrainingSessionLogService(session).record_session(
        user_id=user.id, source=SessionSource(body.source), performed_at=body.performed_at,
        effort=body.effort, comment=body.comment, blocks=[_block_input(b) for b in body.blocks],
        program_inclusion_id=body.program_inclusion_id, completed_at=completed_at,
        activity_type=body.activity_type, duration_seconds=body.duration_seconds,
    )
    if inclusion_not_found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ProgramInclusion not found")

    progression = None
    if result.progression_result is not None:
        progression = SessionProgressionResponse(
            block_a=BlockProgressionResponse(
                target_before=result.progression_result.block_a.target_before,
                target_after=result.progression_result.block_a.target_after,
                equipment_changed=result.progression_result.block_a.equipment_changed,
            ),
            block_b=BlockProgressionResponse(
                target_before=result.progression_result.block_b.target_before,
                target_after=result.progression_result.block_b.target_after,
                equipment_changed=result.progression_result.block_b.equipment_changed,
            ),
        )
    # Коммит до ответа: Журнал перечитывает список сразу после записи (#263), а коммит
    # зависимости get_session выполняется уже после отправки ответа.
    await session.commit()
    return _session_response(
        result.session, progression=progression, skipped_reason=result.progression_skipped_reason,
    )


# --- Живая (server-driven) сессия -------------------------------------------------------
#
# Раздел 12 docs/plan-and-specs.md буквально называет эти пути "POST
# /sessions", "POST /sessions/{id}/phase/next" и т.д. — БЕЗ "/live". Это
# УЖЕ занято выше: POST /api/v2/sessions (волна 3, issue #165) — другой
# сценарий ("записать целиком уже выполненную тренировку" — источник plan/
# freeform/backdated/elective одним запросом), не сервер-управляемая
# пошаговая сессия из этого раздела. Чтобы не переиспользовать один путь
# для двух разных контрактов (разная форма тела, разный смысл), все новые
# эндпоинты этого раздела живут под /sessions/live — намеренное отклонение
# от буквального текста спеки, не недосмотр.
#
# GET /sessions/live/active объявлен ПЕРВЫМ среди /sessions/live/{id}/...
# роутов — порядок регистрации важен для FastAPI: конкретный литеральный
# путь должен идти раньше параметризованного {session_id}, иначе "active"
# рискует быть склеен как значение session_id (см. план задачи).


def _live_session_response_fields(detail: SessionDetail, *, title: str | None = None) -> dict:
    """Построение LiveSessionResponse из SessionDetail. interval — состояние
    ТЕКУЩЕГО начатого interval-блока (вычисляется на лету, не персистится);
    не начатый interval-блок как активный не проецируется. Идентичность
    протокола каждого блока — из замороженного workout_snapshot по позиции.

    Намеренно без try/except вокруг парсинга снимка: он пишется только
    системой при старте, сбой парсинга — реальная порча данных."""
    now = datetime.now(UTC)
    snapshot_items = positional_snapshot_items(detail.workout_snapshot, len(detail.blocks))

    interval_state: IntervalStateResponse | None = None
    timing = current_interval_timing(detail, now)
    if timing is not None:
        interval_state = IntervalStateResponse(
            execution_started_at=timing.execution_started_at,
            total_end_at=timing.total_end_at,
            phase=timing.phase.value,
            phase_ends_at=timing.phase_ends_at,
            total_duration_seconds=timing.total_duration_seconds,
            work_seconds=timing.work_seconds,
            rest_seconds=timing.rest_seconds,
            completed_cycles=timing.completed_cycles,
        )

    def _interval_config(item) -> IntervalConfigResponse | None:
        protocol = interval_protocol(item.protocol) if item is not None else None
        if protocol is None:
            return None
        return IntervalConfigResponse(
            total_duration_seconds=protocol.total_duration_seconds,
            work_seconds=protocol.work_seconds, rest_seconds=protocol.rest_seconds,
        )

    return {
        "id": detail.id, "client_session_id": detail.client_session_id, "status": detail.status.value,
        "phase": LiveSessionPhaseResponse(name=detail.phase_name.value, ends_at=detail.phase_ends_at),
        "phase_index": detail.phase_index, "current_block_index": detail.current_block_index,
        "current_set_number": detail.current_set_number,
        "blocks": [
            LiveSessionBlockResponse(
                order_index=block.order_index, exercise_id=block.exercise_id, complex_id=block.complex_id,
                result=block.result,
                protocol_type=item.protocol.type.value if item is not None else None,
                exercise_name=item.exercise_name if item is not None else None,
                rest_seconds=rest_seconds_for_protocol(item.protocol) if item is not None else None,
                started_at=block_started_at(detail, block.order_index),
                interval_config=_interval_config(item),
                targets=[
                    LiveSetTargetResponse(
                        set_number=target.set_number, metric_type=target.metric_type.value,
                        value=str(target.value), unit=target.unit,
                    )
                    for target in block.set_targets
                ],
                set_logs=[
                    SetLogResponse(
                        set_number=log.set_number, is_max_set=log.is_max_set, metric_type=log.metric_type.value,
                        value=str(log.value), unit=log.unit,
                        effort=str(log.effort) if log.effort is not None else None, note=log.note,
                        is_extra=log.is_extra,
                    )
                    for log in block.set_logs
                ],
            )
            for block, item in zip(detail.blocks, snapshot_items, strict=True)
        ],
        "server_time": now,
        "interval": interval_state,
        "awaiting_block_start": awaiting_block_start(detail),
        "title": title,
    }


def _live_session_response(detail: SessionDetail, *, title: str | None = None) -> LiveSessionResponse:
    return LiveSessionResponse(**_live_session_response_fields(detail, title=title))


def _live_session_complete_response(result: CompleteResult) -> LiveSessionCompleteResponse:
    progression = None
    if result.progression_result is not None:
        progression = SessionProgressionResponse(
            block_a=BlockProgressionResponse(
                target_before=result.progression_result.block_a.target_before,
                target_after=result.progression_result.block_a.target_after,
                equipment_changed=result.progression_result.block_a.equipment_changed,
            ),
            block_b=BlockProgressionResponse(
                target_before=result.progression_result.block_b.target_before,
                target_after=result.progression_result.block_b.target_after,
                equipment_changed=result.progression_result.block_b.equipment_changed,
            ),
        )
    return LiveSessionCompleteResponse(
        **_live_session_response_fields(result.session),
        progression_result=progression, progression_skipped_reason=result.progression_skipped_reason,
    )


@router_v2.post("/sessions/live", response_model=LiveSessionResponse)
async def start_live_session(
    body: LiveSessionStartRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> LiveSessionResponse:
    user = await _require_user(session, init_data)
    try:
        result = await LiveSessionService(session).start_session(
            user_id=user.id, client_session_id=body.client_session_id, plan_item_ids=body.plan_item_ids,
            workout_id=body.workout_id,
        )
    except ActiveSessionConflictError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "active_session_exists", "active_session_id": exc.active_session_id},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    if result is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Workout not found" if body.workout_id is not None else "PlanItem not found",
        )
    titles = await _resolve_session_titles(session, [result.session], user.id)
    return _live_session_response(result.session, title=titles.get(result.session.id))


@router_v2.get("/sessions/live/active", response_model=LiveSessionActiveResponse)
async def get_active_live_session(
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> LiveSessionActiveResponse:
    user = await _require_user(session, init_data)
    result = await LiveSessionService(session).get_active(user_id=user.id)
    if result is None:
        return LiveSessionActiveResponse(session=None)
    # Phase B2 gate fix (issue #215) — тот же batch-резолвер, что Журнал
    # уже использует (_resolve_session_titles), с единственной сессией —
    # без него reload посреди тренировки терял заголовок вовсе (найдено
    # живым прогоном).
    titles = await _resolve_session_titles(session, [result.session], user.id)
    return LiveSessionActiveResponse(session=_live_session_response(result.session, title=titles.get(result.session.id)))


@router_v2.post("/sessions/live/{session_id}/phase/next", response_model=LiveSessionResponse)
async def advance_live_session_phase(
    session_id: int,
    body: LiveSessionPhaseNextRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> LiveSessionResponse:
    user = await _require_user(session, init_data)
    result = await LiveSessionService(session).advance_phase(
        session_id=session_id, user_id=user.id, expected_phase_index=body.expected_phase_index,
    )
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Live session not found")
    return _live_session_response(result.session)


@router_v2.post("/sessions/live/{session_id}/blocks/start", response_model=LiveSessionResponse)
async def start_live_session_block(
    session_id: int,
    body: LiveSessionBlockRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> LiveSessionResponse:
    """R1 — явный "Начать" следующего блока после interstitial. Идемпотентен
    (двойной клик стартует блок один раз)."""
    user = await _require_user(session, init_data)
    result = await LiveSessionService(session).start_block(
        session_id=session_id, user_id=user.id, expected_block_index=body.expected_block_index,
    )
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Live session not found")
    return _live_session_response(result.session)


@router_v2.post("/sessions/live/{session_id}/blocks/finish", response_model=LiveSessionCompleteResponse)
async def finish_live_session_interval_block(
    session_id: int,
    body: LiveSessionBlockRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> LiveSessionCompleteResponse:
    """R1 — клиент дошёл до дедлайна interval-блока. Середина тренировки —
    сессия остаётся STARTED и ждёт следующий блок; последний блок —
    завершает сессию."""
    user = await _require_user(session, init_data)
    result, not_found = await LiveSessionService(session).finish_interval_block(
        session_id=session_id, user_id=user.id, expected_block_index=body.expected_block_index,
    )
    if not_found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Live session not found")
    return _live_session_complete_response(result)


@router_v2.post("/sessions/live/{session_id}/sets:batch", response_model=LiveSessionResponse)
async def batch_live_session_sets(
    session_id: int,
    body: LiveSetBatchRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> LiveSessionResponse:
    user = await _require_user(session, init_data)
    entries = [
        BatchSetLogInput(
            set_index=entry.set_index, exercise_id=entry.exercise_id, value=entry.value,
            effort=entry.effort, note=entry.note, block_index=entry.block_index,
            is_extra=entry.is_extra,
        )
        for entry in body.sets
    ]
    try:
        result = await LiveSessionService(session).batch_sets(
            session_id=session_id, user_id=user.id, entries=entries,
        )
    except ValueError as exc:
        # Exercise из батча не найден среди блоков сессии — см. докстринг
        # TrainingSessionRepository.upsert_set_logs_batch: репозиторий сам
        # не знает про HTTPException, роут переводит ValueError в 404.
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Live session not found")
    return _live_session_response(result.session)


@router_v2.post("/sessions/live/{session_id}/complete", response_model=LiveSessionCompleteResponse)
async def complete_live_session(
    session_id: int,
    body: LiveSessionCompleteRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> LiveSessionCompleteResponse:
    user = await _require_user(session, init_data)
    result, not_found = await LiveSessionService(session).complete_session(
        session_id=session_id, user_id=user.id, abandoned=body.abandoned,
        effort=body.effort, comment=body.comment,
    )
    if not_found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Live session not found")
    return _live_session_complete_response(result)


# --- Каскад прогрессии (правка исторической сессии) -------------------------------------


def _set_log_inputs(sets: list[SetLogInputSchema] | None) -> list[SetLogInput] | None:
    if sets is None:
        return None
    return [
        SetLogInput(
            set_number=s.set_number, metric_type=MetricType(s.metric_type), value=s.value, unit=s.unit,
            is_max_set=s.is_max_set, effort=s.effort, note=s.note,
        )
        for s in sets
    ]


def _progression_preview_response(deltas) -> ProgressionPreviewResponse:
    return ProgressionPreviewResponse(
        deltas=[
            PlanItemDeltaResponse(plan_item_id=d.plan_item_id, exercise=d.exercise, before=d.before, after=d.after)
            for d in deltas
        ],
    )


@router_v2.post("/program-inclusions/{inclusion_id}/progression/preview", response_model=ProgressionPreviewResponse)
async def preview_progression_cascade(
    inclusion_id: int,
    body: ProgressionPreviewRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> ProgressionPreviewResponse:
    user = await _require_user(session, init_data)
    deltas, not_applicable = await ProgressionCascadeService(session).preview(
        inclusion_id=inclusion_id, user_id=user.id, edited_session_id=body.edited_session_id,
        edited_block_a_sets=_set_log_inputs(body.block_a), edited_block_b_sets=_set_log_inputs(body.block_b),
    )
    if deltas is None:
        if not_applicable:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "ProgramInclusion is not a step-strategy inclusion",
            )
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ProgramInclusion or session not found")
    return _progression_preview_response(deltas)


@router_v2.post("/program-inclusions/{inclusion_id}/progression/apply", response_model=ProgressionPreviewResponse)
async def apply_progression_cascade(
    inclusion_id: int,
    body: ProgressionPreviewRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> ProgressionPreviewResponse:
    user = await _require_user(session, init_data)
    deltas, not_applicable = await ProgressionCascadeService(session).apply(
        inclusion_id=inclusion_id, user_id=user.id, edited_session_id=body.edited_session_id,
        edited_block_a_sets=_set_log_inputs(body.block_a), edited_block_b_sets=_set_log_inputs(body.block_b),
    )
    if deltas is None:
        if not_applicable:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "ProgramInclusion is not a step-strategy inclusion",
            )
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ProgramInclusion or session not found")
    return _progression_preview_response(deltas)
