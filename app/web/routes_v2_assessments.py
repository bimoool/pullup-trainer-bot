"""/api/v2/assessments — хаб «Тесты» (CRIMPD, #260): протоколы с последним результатом и
история замеров пользователя. Результаты замеров НЕ входят в каскад прогрессии и не меняют
baseline онбординга (см. докстринг AssessmentProtocol): здесь только своя история и тренд.
Протоколы — общий справочник; результаты — только свои, чужой id = 404."""

from datetime import UTC, date, datetime, time
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from init_data_py import InitData
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.models_program import AssessmentProtocol, AssessmentResult
from app.db.repositories.assessments import AssessmentRepository
from app.db.repositories.users import UserRepository
from app.domain.multi_program import MetricType
from app.services.training_analytics import resolve_timezone
from app.web.auth import get_validated_init_data
from app.web.db import get_session
from app.web.schemas_v2_assessments import (
    AssessmentDetailResponse,
    AssessmentProtocolResponse,
    AssessmentResultCreate,
    AssessmentResultResponse,
    AssessmentResultUpdate,
    AssessmentsListResponse,
)

router_v2_assessments = APIRouter(prefix="/api/v2/assessments")

TREND_POINTS = 12
_UNITS = {
    MetricType.REPS: "повт.",
    MetricType.TIME: "сек",
    MetricType.WEIGHT: "кг",
    MetricType.ANGLE: "°",
    MetricType.DISTANCE: "м",
}


def _dec(value: Decimal) -> str:
    return str(value.quantize(Decimal(1))) if value == value.to_integral_value() else str(value.normalize())


def _unit(protocol: AssessmentProtocol) -> str:
    return _UNITS.get(protocol.metric_type, "")


def _local_date(user: User, moment: datetime) -> date:
    return moment.astimezone(resolve_timezone(user.timezone)).date()


def _to_moment(user: User, day: date) -> datetime:
    """Дата замера хранится полднем локального дня пользователя (одна дата — один момент)."""
    return datetime.combine(day, time(12, 0), tzinfo=resolve_timezone(user.timezone)).astimezone(UTC)


def _result(user: User, row: AssessmentResult) -> AssessmentResultResponse:
    return AssessmentResultResponse(
        id=row.id, protocol_id=row.protocol_id, performed_on=_local_date(user, row.performed_at),
        value=_dec(row.value), unit=row.unit, note=row.note,
    )


def _protocol(user: User, protocol: AssessmentProtocol, newest_first: list[AssessmentResult]) -> AssessmentProtocolResponse:
    return AssessmentProtocolResponse(
        id=protocol.id, name=protocol.name, description=protocol.description,
        metric_type=protocol.metric_type.value, unit=_unit(protocol),
        last_result=_result(user, newest_first[0]) if newest_first else None,
        results_count=len(newest_first),
        trend=[_dec(r.value) for r in reversed(newest_first[:TREND_POINTS])],
    )


async def _current_user(init_data: InitData, session: AsyncSession) -> User:
    user = await UserRepository(session).get_by_telegram_id(init_data.user.id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


def _validate_day(user: User, day: date) -> None:
    if day > _local_date(user, datetime.now(UTC)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Дата не может быть в будущем")


def _validate_value(protocol: AssessmentProtocol, value: Decimal) -> None:
    if protocol.metric_type == MetricType.REPS and value != value.to_integral_value():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Повторения — целое число")


@router_v2_assessments.get("", response_model=AssessmentsListResponse)
async def list_assessments(
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> AssessmentsListResponse:
    user = await _current_user(init_data, session)
    repo = AssessmentRepository(session)
    by_protocol: dict[int, list[AssessmentResult]] = {}
    for row in await repo.list_results_for_user(user.id):
        by_protocol.setdefault(row.protocol_id, []).append(row)
    return AssessmentsListResponse(
        protocols=[_protocol(user, p, by_protocol.get(p.id, [])) for p in await repo.list_protocols()],
    )


@router_v2_assessments.get("/{protocol_id}/results", response_model=AssessmentDetailResponse)
async def get_assessment(
    protocol_id: int,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> AssessmentDetailResponse:
    user = await _current_user(init_data, session)
    repo = AssessmentRepository(session)
    protocol = await repo.get_protocol(protocol_id)
    if protocol is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assessment not found")
    rows = await repo.list_results_for_user(user.id, protocol_id)
    return AssessmentDetailResponse(protocol=_protocol(user, protocol, rows), results=[_result(user, r) for r in rows])


@router_v2_assessments.post(
    "/{protocol_id}/results", response_model=AssessmentResultResponse, status_code=status.HTTP_201_CREATED,
)
async def create_assessment_result(
    protocol_id: int,
    payload: AssessmentResultCreate,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> AssessmentResultResponse:
    user = await _current_user(init_data, session)
    repo = AssessmentRepository(session)
    protocol = await repo.get_protocol(protocol_id)
    if protocol is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assessment not found")
    _validate_day(user, payload.performed_on)
    _validate_value(protocol, payload.value)
    note = (payload.note or "").strip() or None
    row = await repo.create_result(
        user.id, protocol.id, _to_moment(user, payload.performed_on), payload.value, _unit(protocol), note,
    )
    await session.commit()
    return _result(user, row)


@router_v2_assessments.patch("/results/{result_id}", response_model=AssessmentResultResponse)
async def update_assessment_result(
    result_id: int,
    payload: AssessmentResultUpdate,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> AssessmentResultResponse:
    user = await _current_user(init_data, session)
    repo = AssessmentRepository(session)
    row = await repo.get_result(user.id, result_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Result not found")
    protocol = await repo.get_protocol(row.protocol_id)
    fields = payload.model_fields_set
    if "performed_on" in fields:
        if payload.performed_on is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Дата обязательна")
        _validate_day(user, payload.performed_on)
        row.performed_at = _to_moment(user, payload.performed_on)
    if "value" in fields:
        if payload.value is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Значение обязательно")
        if protocol is not None:
            _validate_value(protocol, payload.value)
        row.value = payload.value
    if "note" in fields:
        row.note = (payload.note or "").strip() or None
    await session.commit()
    return _result(user, row)


@router_v2_assessments.delete("/results/{result_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_assessment_result(
    result_id: int,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> None:
    user = await _current_user(init_data, session)
    if not await AssessmentRepository(session).delete_result(user.id, result_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Result not found")
    await session.commit()
