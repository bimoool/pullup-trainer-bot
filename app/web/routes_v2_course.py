"""Программа «Подтягивания» V5.6 (issue #305): состояние, ввод входов и тест 1RM.

Тонкий слой над app.services.course_v5 / app.domain.pullups_v5 (docs/domain/PULLUPS_V5_6.md):

* ``GET  /api/v2/program-inclusions/{id}/course`` — версия, уровень, роль следующего занятия, рецепт
  следующего занятия (или список недостающих входов);
* ``PUT  /api/v2/program-inclusions/{id}/course/inputs`` — входы §3 (R, резины, E1RM, шаг веса,
  подтверждённые результаты, выбор следующей резины, снятие паузы §9). Только вперёд;
* ``POST /api/v2/program-inclusions/{id}/course/one-rep-max/next-set`` — следующий подход лестницы 1RM;
* ``POST /api/v2/program-inclusions/{id}/course/one-rep-max`` — записать тест 1RM (не раньше 48 ч после
  тяжёлой тяговой работы).

Инклюзия устаревшей версии программы (без program_version) здесь — 404: её не переводим в V5.6.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from init_data_py import InitData
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.users import UserRepository
from app.domain.pullups_v5 import (
    ONE_RM_REST_SECONDS,
    PROGRAM_VERSION,
    AttemptSpeed,
    OneRmAttempt,
    PrescriptionPending,
    V5State,
    V5StateError,
    next_one_rm_set,
    pending_inputs,
    prescribe_session,
)
from app.services.course_v5 import (
    OneRepMaxTooSoonError,
    inclusion_for_user,
    record_one_rep_max,
    update_inputs,
    v5_state,
)
from app.services.plan_spacing import MainSpacingService
from app.web.auth import get_validated_init_data
from app.web.db import get_session
from app.web.schemas_v2_course import CourseInputsRequest

router_v2_course = APIRouter(prefix="/api/v2/program-inclusions")


class OneRmAttemptSchema(BaseModel):
    load_kg: Decimal = Field(ge=0, le=300)
    reps: int = Field(ge=1, le=10)
    success: bool
    speed: Literal["fast", "normal", "slow"] | None = None

    def to_domain(self) -> OneRmAttempt:
        return OneRmAttempt(
            load_kg=self.load_kg, reps=self.reps, success=self.success,
            speed=AttemptSpeed(self.speed) if self.speed is not None else None,
        )


class OneRmNextSetRequest(BaseModel):
    attempts: list[OneRmAttemptSchema] = Field(default_factory=list, max_length=8)


class OneRmRecordRequest(BaseModel):
    attempts: list[OneRmAttemptSchema] = Field(min_length=1, max_length=8)


class OneRmNextSetResponse(BaseModel):
    next_set: dict | None
    rest_seconds: int = ONE_RM_REST_SECONDS


class CourseStateResponse(BaseModel):
    program_version: str
    level: str | None
    next_workout_role: str
    pending_inputs: list[str]
    next_workout: dict | None
    # Смены помощи, ждущие подтверждения полной записи резины: [{block, intent, proposed}].
    assistance_pending: list[dict]
    recovery_check_required: bool
    state: dict
    one_rep_max: dict | None = None


def _course_response(state: V5State, *, one_rep_max: dict | None = None) -> CourseStateResponse:
    prescription = prescribe_session(state)
    return CourseStateResponse(
        program_version=PROGRAM_VERSION, level=state.level.value if state.level is not None else None,
        next_workout_role=state.next_role.value, pending_inputs=[item.value for item in pending_inputs(state)],
        next_workout=None if isinstance(prescription, PrescriptionPending) else prescription.to_dict(),
        assistance_pending=list(state.assistance_pending),
        recovery_check_required=state.recovery_check_required, state=state.to_dict(), one_rep_max=one_rep_max,
    )


async def _require_course(session: AsyncSession, init_data: InitData, inclusion_id: int):
    user = await UserRepository(session).get_by_telegram_id(init_data.user.id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    inclusion = await inclusion_for_user(session, inclusion_id, user.id)
    if inclusion is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course program V5.6 inclusion not found")
    return user, inclusion


@router_v2_course.get("/{inclusion_id}/course", response_model=CourseStateResponse)
async def get_course_state(
    inclusion_id: int,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> CourseStateResponse:
    _user, inclusion = await _require_course(session, init_data, inclusion_id)
    return _course_response(v5_state(inclusion))


@router_v2_course.put("/{inclusion_id}/course/inputs", response_model=CourseStateResponse)
async def put_course_inputs(
    inclusion_id: int,
    body: CourseInputsRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> CourseStateResponse:
    _user, inclusion = await _require_course(session, init_data, inclusion_id)
    try:
        state = await update_inputs(
            session, inclusion, body.to_domain(), clear_recovery=body.clear_recovery_check,
            confirmations=[(c.block, c.setup.to_domain()) for c in body.assistance_confirmations],
        )
    except V5StateError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await session.commit()
    return _course_response(state)


@router_v2_course.post("/{inclusion_id}/course/one-rep-max/next-set", response_model=OneRmNextSetResponse)
async def one_rep_max_next_set(
    inclusion_id: int,
    body: OneRmNextSetRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> OneRmNextSetResponse:
    _user, inclusion = await _require_course(session, init_data, inclusion_id)
    state = v5_state(inclusion)
    if state.inputs.body_mass_kg is None or state.inputs.load_step_kg is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "course_setup_required", "missing": [
                name for name, value in (("body_mass", state.inputs.body_mass_kg), ("load_step", state.inputs.load_step_kg))
                if value is None
            ]},
        )
    nxt = next_one_rm_set(
        [a.to_domain() for a in body.attempts], body_mass=state.inputs.body_mass_kg, load_step=state.inputs.load_step_kg,
    )
    return OneRmNextSetResponse(
        next_set=None if nxt is None else {
            "set_number": nxt.set_number, "load_kg": format(nxt.load_kg.normalize(), "f"), "reps": nxt.reps,
        },
    )


@router_v2_course.post("/{inclusion_id}/course/one-rep-max", response_model=CourseStateResponse)
async def record_course_one_rep_max(
    inclusion_id: int,
    body: OneRmRecordRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> CourseStateResponse:
    user, inclusion = await _require_course(session, init_data, inclusion_id)
    last_heavy = await MainSpacingService(session).last_main_start_at(user.id)
    try:
        state, result = await record_one_rep_max(
            session, inclusion, [a.to_domain() for a in body.attempts], performed_at=datetime.now(UTC),
            last_heavy_pulling_at=last_heavy,
        )
    except OneRepMaxTooSoonError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "one_rep_max_too_soon", "message": "Тест 1RM — не раньше чем через 48 часов после тяжёлой тяговой работы."},
        ) from exc
    await session.commit()
    return _course_response(state, one_rep_max={
        "e1rm_kg": format(result.e1rm_kg.normalize(), "f") if result.e1rm_kg is not None else None,
        "conservative": result.conservative, "sets_used": result.sets_used,
    })
