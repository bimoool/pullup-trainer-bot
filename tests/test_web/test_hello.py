"""GET /api/hello — единственный эндпойнт Этапа 0 Mini App (issue #15), не
содержательная фича, а доказательство, что вся цепочка (initData → HTTPS →
FastAPI → repositories/domain) работает целиком, на тех же
repositories/domain, что и бот.

Реальную подпись initData (HMAC от init-data-py) здесь не строим — она
проверяется в app/web/auth.py, тестируется отдельно (test_auth.py) фейковой
валидной/невалидной строкой. Здесь get_validated_init_data подменяется
через dependency_overrides на фейковый объект с нужными полями (тот же
приём, что FakeGitHubClient/FakeRobokassaClient в остальном проекте —
реальная Telegram-подпись не участвует в тесте бизнес-логики эндпойнта)."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from httpx import ASGITransport, AsyncClient

from app.db.models import User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.session import BlockLog
from app.web.auth import get_validated_init_data
from app.web.db import get_session
from app.web.main import app


@dataclass
class _FakeWebAppUser:
    id: int
    first_name: str


@dataclass
class _FakeInitData:
    user: _FakeWebAppUser


def _override_dependencies(session, telegram_id: int, first_name: str) -> None:
    app.dependency_overrides[get_validated_init_data] = (
        lambda: _FakeInitData(user=_FakeWebAppUser(id=telegram_id, first_name=first_name))
    )

    async def _override_session():
        yield session

    app.dependency_overrides[get_session] = _override_session


async def test_health_endpoint_requires_no_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_hello_for_unknown_telegram_id_reports_not_registered(session):
    _override_dependencies(session, telegram_id=9001, first_name="Настя")
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/hello")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "name": "Настя", "onboarding_step": "not_registered", "readiness_status": None,
        "days_since_last_workout": None, "is_admin": False,
    }


async def test_hello_for_registered_user_without_baseline_reports_baseline_step(session):
    await UserRepository(session).create(telegram_id=9002, username="fresh")

    _override_dependencies(session, telegram_id=9002, first_name="Олег")
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/hello")
    finally:
        app.dependency_overrides.clear()

    body = response.json()
    assert body == {
        "name": "Олег", "onboarding_step": "baseline", "readiness_status": None, "days_since_last_workout": None,
        "is_admin": False,
    }


async def test_hello_for_user_with_baseline_but_no_questionnaire_reports_questionnaire_step(session):
    user: User = await UserRepository(session).create(telegram_id=9004, username="mid-onboarding")
    await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=5)

    _override_dependencies(session, telegram_id=9004, first_name="Лена")
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/hello")
    finally:
        app.dependency_overrides.clear()

    body = response.json()
    assert body == {
        "name": "Лена", "onboarding_step": "questionnaire", "readiness_status": None,
        "days_since_last_workout": None, "is_admin": False,
    }


async def test_hello_for_onboarded_user_without_workouts_reports_done(session):
    user: User = await UserRepository(session).create(telegram_id=9003, username="done")
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))

    _override_dependencies(session, telegram_id=9003, first_name="Олег")
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/hello")
    finally:
        app.dependency_overrides.clear()

    body = response.json()
    assert body == {
        "name": "Олег", "onboarding_step": "done", "readiness_status": None, "days_since_last_workout": None,
        "is_admin": False,
    }


async def test_hello_reports_readiness_from_last_workout(session):
    user: User = await UserRepository(session).create(telegram_id=9005, username="active")
    performed_at = datetime.now(UTC) - timedelta(days=1)
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=performed_at, reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=performed_at,
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=Decimal("20.0"),
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=Decimal("20.0"),
    )
    await UserRepository(session).complete_onboarding(user.id, performed_at)

    _override_dependencies(session, telegram_id=9005, first_name="Марина")
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/hello")
    finally:
        app.dependency_overrides.clear()

    body = response.json()
    assert body["name"] == "Марина"
    assert body["onboarding_step"] == "done"
    assert body["readiness_status"] == "too_early"
    assert body["days_since_last_workout"] == 1
