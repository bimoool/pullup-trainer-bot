"""Программа «Подтягивания» V5.6 (issue #305): состояние, ввод входов и тест 1RM.

Тонкий слой над app.services.course_v5 / app.domain.pullups_v5 (docs/domain/PULLUPS_V5_6.md):

* ``GET  /api/v2/program-inclusions/{id}/course`` — версия, уровень, роль следующего занятия, рецепт
  следующего занятия (или список недостающих входов);
* ``PUT  /api/v2/program-inclusions/{id}/course/inputs`` — входы §3 (R, резины, шаг веса, заявленные
  пользователем 5×5/5×3, выбор следующей резины, снятие паузы §9). Только вперёд. E1RM здесь НЕ
  принимается (422): он — только результат теста;
* ``POST /api/v2/program-inclusions/{id}/course/one-rep-max/next-set`` — следующий подход лестницы 1RM;
* ``POST /api/v2/program-inclusions/{id}/course/one-rep-max`` — записать тест 1RM: оконченный по правилу
  лестницы (неудача или восьмой подход) или явно остановленный пользователем (``stopped: true``).

Оба эндпоинта теста на КАЖДОМ запросе проверяют: тест применим (сила с весом, иначе 409
``one_rep_max_not_applicable``), есть BW и шаг (409 ``course_setup_required``), ≥ 48 ч по серверному
времени после тяжёлой тяговой работы — старта MAIN и предыдущего сохранённого теста 1RM (409
``one_rep_max_too_soon``), и что присланные попытки — ровно лестница §10 (422 ``one_rep_max_invalid``).
Клиентский список попыток поэтому не даёт ни «уже идущего теста» в обход 48 ч, ни произвольного
результата. Запись сериализована advisory-локом пользователя: два одновременных запроса не запишут два
теста. Подтверждённый E1RM даёт только оконченный тест с успешным одиночным подходом; остановленный —
факт без E1RM.

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
    OneRmOutcome,
    OneRmTestError,
    PrescriptionPending,
    V5State,
    V5StateError,
    next_one_rm_set,
    one_rm_applicable,
    one_rm_missing_inputs,
    pending_inputs,
    prescribe_session,
    validate_one_rm_attempts,
)
from app.services.course_v5 import (
    OneRepMaxTooSoonError,
    inclusion_for_user,
    last_heavy_pulling_at,
    one_rep_max_day_ok,
    record_one_rep_max,
    update_inputs,
    v5_state,
)
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
    # Явная добровольная остановка до неудачи и до восьмого подхода (вместо ложной «неудачи»): попытки
    # сохраняются, но E1RM не назначается. False — оконченный по правилу лестницы стандартизированный тест.
    stopped: bool = False


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


async def _require_course_access(session: AsyncSession, user, inclusion) -> None:
    """Решения 2026-10-07 / 2026-10-17: запись входов/теста курса — по тому же единому правилу, что старт: программа
    «Подтягивания» (V5.6) бесплатна, платная — только с подпиской (402). Чтение состояния курса не гейтится."""
    from app.services.program_access import ProgramAccessService
    from app.web.routes_v2 import _subscription_required

    if not await ProgramAccessService(session).inclusions_training_allowed(user, [inclusion.id], now=datetime.now(UTC)):
        raise _subscription_required()


def _too_soon() -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        {
            "code": "one_rep_max_too_soon",
            "message": "Тест 1RM — не раньше чем через 48 часов после тяжёлой тяговой работы или предыдущего теста 1RM.",
        },
    )


async def _require_one_rep_max_day(session: AsyncSession, inclusion, user_id: int) -> None:
    if not one_rep_max_day_ok(await last_heavy_pulling_at(session, inclusion, user_id), now=datetime.now(UTC)):
        raise _too_soon()


def _require_one_rep_max_eligible(state: V5State) -> None:
    if not one_rm_applicable(state):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "one_rep_max_not_applicable", "message": "Тест 1RM нужен только силе с весом."},
        )
    missing = one_rm_missing_inputs(state)
    if missing:
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "course_setup_required", "missing": [m.value for m in missing]})


def _invalid_test(exc: OneRmTestError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": "one_rep_max_invalid", "message": str(exc)})


@router_v2_course.get("/{inclusion_id}/course", response_model=CourseStateResponse)
async def get_course_state(
    inclusion_id: int,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> CourseStateResponse:
    _user, inclusion = await _require_course(session, init_data, inclusion_id)
    return _course_response(v5_state(inclusion))


@router_v2_course.put("/{inclusion_id}/course/inputs", response_model=CourseStateResponse)
async def put_course_inputs(
    inclusion_id: int,
    body: CourseInputsRequest,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> CourseStateResponse:
    user, inclusion = await _require_course(session, init_data, inclusion_id)
    await _require_course_access(session, user, inclusion)
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
    session: AsyncSession = Depends(get_session, scope="function"),
) -> OneRmNextSetResponse:
    user, inclusion = await _require_course(session, init_data, inclusion_id)
    await _require_course_access(session, user, inclusion)
    state = v5_state(inclusion)
    _require_one_rep_max_eligible(state)
    # «Отдельный свежий день, ≥ 48 ч после тяжёлой тяговой работы» (§10) — на КАЖДОМ шаге по серверному
    # времени, а не только на пустом списке: присланные попытки не делают тест «уже идущим». Настоящий
    # тест это не ломает: время только растёт, а новая тяжёлая работа и так делает тест недействительным.
    await _require_one_rep_max_day(session, inclusion, user.id)
    attempts = [a.to_domain() for a in body.attempts]
    try:
        validate_one_rm_attempts(
            attempts, body_mass=state.inputs.body_mass_kg, load_step=state.inputs.load_step_kg,
        )
    except OneRmTestError as exc:
        raise _invalid_test(exc) from exc
    nxt = next_one_rm_set(attempts, body_mass=state.inputs.body_mass_kg, load_step=state.inputs.load_step_kg)
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
    session: AsyncSession = Depends(get_session, scope="function"),
) -> CourseStateResponse:
    user, inclusion = await _require_course(session, init_data, inclusion_id)
    await _require_course_access(session, user, inclusion)
    _require_one_rep_max_eligible(v5_state(inclusion))
    try:
        state, result = await record_one_rep_max(
            session, inclusion, [a.to_domain() for a in body.attempts], user_id=user.id,
            performed_at=datetime.now(UTC), outcome=OneRmOutcome.STOPPED if body.stopped else OneRmOutcome.COMPLETED,
        )
    except OneRepMaxTooSoonError as exc:
        raise _too_soon() from exc
    except OneRmTestError as exc:
        raise _invalid_test(exc) from exc
    await session.commit()
    return _course_response(state, one_rep_max={
        "e1rm_kg": _kg(result.e1rm_kg), "conservative": result.conservative, "sets_used": result.sets_used,
        "outcome": result.outcome.value, "confirmed": result.confirmed,
        "last_successful_single_kg": _kg(result.last_successful_single_kg),
    })


def _kg(value: Decimal | None) -> str | None:
    return format(value.normalize(), "f") if value is not None else None
