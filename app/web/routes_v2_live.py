"""Живая (server-driven) сессия — /api/v2/sessions/live/* (issue #306: вынесено из routes_v2.py
механически, без изменения поведения; Live Engine v2 строится поверх этого роутера)."""


from fastapi import APIRouter, Depends, HTTPException, status
from init_data_py import InitData
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.repositories.training_sessions import BatchSetLogInput, SessionDetail
from app.domain.block_execution import interval_protocol, rest_seconds_for_protocol
from app.domain.workout_snapshot import positional_snapshot_items
from app.services.live_engine import (
    ClientEvent,
    ClientEventConflictError,
    EngineVersionMismatchError,
    LiveEngineService,
    engine_now,
    engine_view,
)
from app.services.live_session import (
    ActiveSessionConflictError,
    CompleteResult,
    EngineV1OnlyError,
    LiveSessionService,
    PhaseBackConflictError,
    awaiting_block_start,
    block_started_at,
    current_interval_timing,
    is_engine_v2,
)
from app.services.plan_spacing import TooEarlyError
from app.services.program_access import SubscriptionRequiredError
from app.web.auth import get_validated_init_data
from app.web.db import get_session
from app.web.routes_v2 import _require_user, _resolve_session_titles, _subscription_required
from app.web.routes_v2_plan import too_early_http_error
from app.web.schemas_v2 import BlockProgressionResponse, SessionProgressionResponse
from app.web.schemas_v2_session import (
    IntervalConfigResponse,
    IntervalStateResponse,
    LiveEngineEventResult,
    LiveEngineEventsRequest,
    LiveEngineEventsResponse,
    LiveEngineView,
    LiveSessionActiveResponse,
    LiveSessionBlockRequest,
    LiveSessionBlockResponse,
    LiveSessionCompleteRequest,
    LiveSessionCompleteResponse,
    LiveSessionPhaseBackRequest,
    LiveSessionPhaseNextRequest,
    LiveSessionPhaseResponse,
    LiveSessionResponse,
    LiveSessionStartRequest,
    LiveSetBatchRequest,
    LiveSetLogResponse,
    LiveSetTargetResponse,
)

router_v2_live = APIRouter(prefix="/api/v2")


def _engine_mismatch() -> HTTPException:
    """issue #306: эндпоинт движка v1 для сессии движка v2 (и наоборот) — состояние не меняется."""
    return HTTPException(
        status.HTTP_409_CONFLICT,
        {"code": "engine_version_mismatch", "message": "Сессия исполняется другой версией движка."},
    )


def _snapshot_names(detail: SessionDetail) -> list[str | None]:
    blocks = (detail.prescription_snapshot or {}).get("blocks") or []
    names = [block.get("exercise_display_name") for block in blocks]
    return names if len(names) == len(detail.blocks) else [None] * len(detail.blocks)


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
    now = engine_now()
    snapshot_items = positional_snapshot_items(detail.workout_snapshot, len(detail.blocks))
    snapshot_names = _snapshot_names(detail)
    view = engine_view(detail, now)

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
                exercise_name=item.exercise_name if item is not None else snapshot_names[block.order_index],
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
                    LiveSetLogResponse(
                        set_number=log.set_number, is_max_set=log.is_max_set, metric_type=log.metric_type.value,
                        value=str(log.value), unit=log.unit,
                        effort=str(log.effort) if log.effort is not None else None, note=log.note,
                        is_extra=log.is_extra, set_index=log.set_index,
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
        "engine_version": detail.engine_version,
        "engine": LiveEngineView(**view) if view is not None else None,
        "engine_status": detail.engine_status,
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


@router_v2_live.post("/sessions/live", response_model=LiveSessionResponse)
async def start_live_session(
    body: LiveSessionStartRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> LiveSessionResponse:
    user = await _require_user(session, init_data)
    try:
        result = await LiveSessionService(session).start_session(
            user_id=user.id, client_session_id=body.client_session_id, plan_item_ids=body.plan_item_ids,
            workout_id=body.workout_id, bypass_spacing=settings.is_admin(init_data.user.id),
            engine_version=body.engine_version,
        )
    except TooEarlyError as exc:
        raise too_early_http_error(exc) from exc
    except ActiveSessionConflictError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "active_session_exists", "active_session_id": exc.active_session_id},
        ) from exc
    except SubscriptionRequiredError as exc:
        raise _subscription_required() from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    if result is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Workout not found" if body.workout_id is not None else "PlanItem not found",
        )
    titles = await _resolve_session_titles(session, [result.session], user.id)
    return _live_session_response(result.session, title=titles.get(result.session.id))


@router_v2_live.get("/sessions/live/active", response_model=LiveSessionActiveResponse)
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


@router_v2_live.post("/sessions/live/{session_id}/phase/next", response_model=LiveSessionResponse)
async def advance_live_session_phase(
    session_id: int,
    body: LiveSessionPhaseNextRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> LiveSessionResponse:
    user = await _require_user(session, init_data)
    try:
        result = await LiveSessionService(session).advance_phase(
            session_id=session_id, user_id=user.id, expected_phase_index=body.expected_phase_index,
        )
    except EngineV1OnlyError as exc:
        raise _engine_mismatch() from exc
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Live session not found")
    return _live_session_response(result.session)


@router_v2_live.post("/sessions/live/{session_id}/phase/back", response_model=LiveSessionResponse)
async def back_live_session_phase(
    session_id: int,
    body: LiveSessionPhaseBackRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> LiveSessionResponse:
    """#292 — «Предыдущий подход»: фаза переоткрывает предыдущий подход
    (SetLog не удаляется). 409 — нет предыдущего подхода / сессия не
    активна / устаревший expected_phase_index."""
    user = await _require_user(session, init_data)
    try:
        result = await LiveSessionService(session).back_phase(
            session_id=session_id, user_id=user.id, expected_phase_index=body.expected_phase_index,
        )
    except PhaseBackConflictError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, error.code) from error
    except EngineV1OnlyError as exc:
        raise _engine_mismatch() from exc
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Live session not found")
    return _live_session_response(result.session)


@router_v2_live.post("/sessions/live/{session_id}/blocks/start", response_model=LiveSessionResponse)
async def start_live_session_block(
    session_id: int,
    body: LiveSessionBlockRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> LiveSessionResponse:
    """R1 — явный "Начать" следующего блока после interstitial. Идемпотентен
    (двойной клик стартует блок один раз)."""
    user = await _require_user(session, init_data)
    try:
        result = await LiveSessionService(session).start_block(
            session_id=session_id, user_id=user.id, expected_block_index=body.expected_block_index,
        )
    except EngineV1OnlyError as exc:
        raise _engine_mismatch() from exc
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Live session not found")
    return _live_session_response(result.session)


@router_v2_live.post("/sessions/live/{session_id}/blocks/finish", response_model=LiveSessionCompleteResponse)
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
    try:
        result, not_found = await LiveSessionService(session).finish_interval_block(
            session_id=session_id, user_id=user.id, expected_block_index=body.expected_block_index,
        )
    except EngineV1OnlyError as exc:
        raise _engine_mismatch() from exc
    if not_found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Live session not found")
    return _live_session_complete_response(result)


@router_v2_live.post("/sessions/live/{session_id}/sets:batch", response_model=LiveSessionResponse)
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
    except EngineV1OnlyError as exc:
        raise _engine_mismatch() from exc
    except ValueError as exc:
        # Exercise из батча не найден среди блоков сессии — см. докстринг
        # TrainingSessionRepository.upsert_set_logs_batch: репозиторий сам
        # не знает про HTTPException, роут переводит ValueError в 404.
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Live session not found")
    return _live_session_response(result.session)


@router_v2_live.post("/sessions/live/{session_id}/complete", response_model=LiveSessionCompleteResponse)
async def complete_live_session(
    session_id: int,
    body: LiveSessionCompleteRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> LiveSessionCompleteResponse:
    user = await _require_user(session, init_data)
    live = LiveSessionService(session)
    detail = await live.get_session(session_id=session_id, user_id=user.id)
    if detail is not None and is_engine_v2(detail):
        return await _complete_engine_v2(session, user.id, session_id, body)
    result, not_found = await live.complete_session(
        session_id=session_id, user_id=user.id, abandoned=body.abandoned,
        effort=body.effort, comment=body.comment, active_elapsed_ms=body.active_elapsed_ms,
    )
    if not_found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Live session not found")
    return _live_session_complete_response(result)


async def _complete_engine_v2(
    session: AsyncSession, user_id: int, session_id: int, body: LiveSessionCompleteRequest,
) -> LiveSessionCompleteResponse:
    """issue #306: интерфейс #307 POST …/complete сохраняется для сессии v2. Идущая сессия
    заканчивается серверным finish_early (длительность — активное время движка, а не active_elapsed_ms
    клиента: время — авторитет сервера); затем идемпотентный complete_session дописывает оценку и заметку.
    «Ноль работы» — отмена (T5): не завершается, оценка не пишется."""
    engine_service = LiveEngineService(session)
    sync = await engine_service.finish_from_complete(session_id, user_id, abandoned=body.abandoned)
    if sync is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Live session not found")
    live = LiveSessionService(session)
    detail = await live.get_session(session_id=session_id, user_id=user_id)
    if detail.engine_status == "cancelled":
        return LiveSessionCompleteResponse(
            **_live_session_response_fields(detail), progression_result=None, progression_skipped_reason="cancelled",
        )
    result, _ = await live.complete_session(
        session_id=session_id, user_id=user_id, abandoned=body.abandoned, effort=body.effort, comment=body.comment,
    )
    first = sync.completion
    if first is not None:  # завершилась этим запросом — отдаём итог первого завершения (прогрессия)
        result = CompleteResult(
            session=result.session, progression_result=first.progression_result,
            progression_skipped_reason=first.progression_skipped_reason,
        )
    return _live_session_complete_response(result)


@router_v2_live.post("/sessions/live/{session_id}/events", response_model=LiveEngineEventsResponse)
async def post_live_session_events(
    session_id: int,
    body: LiveEngineEventsRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> LiveEngineEventsResponse:
    """issue #306 (LIVE_ENGINE_V2 §2 C4): события движка v2 — по одному или офлайн-очередью в порядке
    возникновения. Повтор client_event_id — no-op (outcome=duplicate), устаревшее событие — no-op
    (outcome=noop), всегда 200 с текущим состоянием (дедлайны до «сейчас» уже применены)."""
    user = await _require_user(session, init_data)
    events = [
        ClientEvent(client_event_id=e.client_event_id, type=e.type, payload=e.payload, client_at=e.client_at)
        for e in body.events
    ]
    try:
        sync = await LiveEngineService(session).sync(session_id, user.id, events)
    except EngineVersionMismatchError as exc:
        raise _engine_mismatch() from exc
    except ClientEventConflictError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "client_event_id уже использован") from exc
    if sync is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Live session not found")
    detail = await LiveSessionService(session).get_session(session_id=session_id, user_id=user.id)
    titles = await _resolve_session_titles(session, [detail], user.id)
    completion = sync.completion
    base = _live_session_complete_response(
        CompleteResult(
            session=detail,
            progression_result=completion.progression_result if completion is not None else None,
            progression_skipped_reason=completion.progression_skipped_reason if completion is not None else None,
        ),
    )
    return LiveEngineEventsResponse(
        **{**base.model_dump(), "title": titles.get(detail.id)},
        event_results=[LiveEngineEventResult(client_event_id=r.client_event_id, outcome=r.outcome) for r in sync.events],
    )
